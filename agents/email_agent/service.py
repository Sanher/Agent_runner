import email
import imaplib
import json
import logging
import threading
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


logger = logging.getLogger("agent_runner.email_agent")
AGENT_NAME = "email_agent"


class EmailAgentService:
    """Servicio para detectar correos nuevos y generar propuestas de respuesta."""

    def __init__(
        self,
        data_dir: Path,
        openai_api_key: str,
        openai_model: str,
        gmail_email: str,
        gmail_app_password: str,
        gmail_imap_host: str,
        webhook_notify_url: str,
        allowed_from_whitelist: List[str],
    ) -> None:
        self.data_dir = data_dir
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.gmail_email = gmail_email
        self.gmail_app_password = gmail_app_password
        self.gmail_imap_host = gmail_imap_host
        self.webhook_notify_url = webhook_notify_url
        self.allowed_from_whitelist = sorted(
            {
                str(item).strip().lower()
                for item in allowed_from_whitelist
                if str(item).strip()
            }
        )
        self._check_lock = threading.Lock()

        self.config_path = self.data_dir / "email_agent_config.json"
        self.memory_path = self.data_dir / "email_agent_memory.jsonl"
        self.suggestions_path = self.data_dir / "email_agent_suggestions.json"

        self._debug("Servicio inicializado")

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _debug(self, message: str, **meta: Any) -> None:
        suffix = " | "+", ".join(f"{k}={v}" for k,v in meta.items()) if meta else ""
        logger.info(f"[DEBUG][{AGENT_NAME}] {message} | hora_texto={self._now_text()}{suffix}")

    @staticmethod
    def _decode_mime_header(value: Optional[str]) -> str:
        if not value:
            return ""
        parts = decode_header(value)
        decoded: List[str] = []
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(content)
        return "".join(decoded)

    @staticmethod
    def _extract_email_address(raw_from: str) -> str:
        return parseaddr(raw_from or "")[1].strip().lower()

    @staticmethod
    def _normalize_whitelist(raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return sorted({str(item).strip().lower() for item in raw if str(item).strip()})
        if isinstance(raw, str):
            values: List[str] = []
            for piece in raw.replace("\n", ",").split(","):
                value = piece.strip().lower()
                if value:
                    values.append(value)
            return sorted(set(values))
        return []

    @staticmethod
    def _build_from_criteria(whitelist: List[str]) -> List[str]:
        if not whitelist:
            return []
        if len(whitelist) == 1:
            return ["FROM", f'"{whitelist[0]}"']

        # IMAP OR es binario: OR A B. Encadenamos para N remitentes.
        tokens: List[str] = ["OR", "FROM", f'"{whitelist[0]}"', "FROM", f'"{whitelist[1]}"']
        for sender in whitelist[2:]:
            tokens = ["OR", *tokens, "FROM", f'"{sender}"']
        return tokens

    @staticmethod
    def _extract_text_from_email(msg: Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition.lower():
                    continue
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace").strip()
            return ""

        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()

    def load_config(self) -> Dict[str, Any]:
        default_config = {
            "global_context": "",
            "reply_language": "English",
            "signature": "",
            "common_replies": [],
        }
        if not self.config_path.exists():
            return default_config
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("email_agent_config.json no es un objeto JSON; se usan defaults")
                return default_config
            return {**default_config, **data}
        except json.JSONDecodeError:
            logger.exception("email_agent_config.json inválido; se usan defaults")
            return default_config

    def load_memory_examples(self, max_items: int = 8) -> List[Dict[str, Any]]:
        if not self.memory_path.exists():
            return []
        lines = self.memory_path.read_text(encoding="utf-8").splitlines()
        parsed: List[Dict[str, Any]] = []
        for line in lines[-max_items:]:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return parsed

    def append_memory(self, entry: Dict[str, Any]) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self.memory_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def load_suggestions(self) -> List[Dict[str, Any]]:
        if not self.suggestions_path.exists():
            return []
        try:
            data = json.loads(self.suggestions_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                logger.warning("email_agent_suggestions.json no es una lista; se usa []")
                return []
            return data
        except json.JSONDecodeError:
            logger.exception("email_agent_suggestions.json inválido; se usa []")
            return []

    def save_suggestions(self, suggestions: List[Dict[str, Any]]) -> None:
        self.suggestions_path.parent.mkdir(parents=True, exist_ok=True)
        self.suggestions_path.write_text(
            json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _fetch_gmail_messages(
        self,
        max_emails: int,
        unread_only: bool,
        mailbox: str,
        allowed_whitelist: List[str],
    ) -> List[Dict[str, Any]]:
        self._debug(
            "Buscando correos en Gmail",
            mailbox=mailbox,
            unread_only=unread_only,
            max_emails=max_emails,
            whitelist=len(allowed_whitelist),
        )
        if not self.gmail_email or not self.gmail_app_password:
            raise RuntimeError("Missing gmail_email or gmail_app_password")

        criteria: List[str] = ["UNSEEN"] if unread_only else ["ALL"]
        criteria += self._build_from_criteria(allowed_whitelist)
        messages: List[Dict[str, Any]] = []

        with imaplib.IMAP4_SSL(self.gmail_imap_host) as mail:
            mail.login(self.gmail_email, self.gmail_app_password)
            status, _ = mail.select(mailbox)
            if status != "OK":
                raise RuntimeError(f"Could not open mailbox {mailbox}")

            status, data = mail.search(None, *criteria)
            if status != "OK":
                raise RuntimeError("Could not search messages")

            ids = data[0].split()
            for msg_id in ids[-max_emails:]:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue
                raw_email = msg_data[0][1]
                parsed = email.message_from_bytes(raw_email)
                messages.append(
                    {
                        "id": msg_id.decode("utf-8", errors="replace"),
                        "from": self._decode_mime_header(parsed.get("From")),
                        "subject": self._decode_mime_header(parsed.get("Subject")),
                        "date": self._decode_mime_header(parsed.get("Date")),
                        "body": self._extract_text_from_email(parsed)[:6000],
                    }
                )

        self._debug("Correos leídos de Gmail", count=len(messages), mailbox=mailbox)
        return messages

    @staticmethod
    def _select_context(config: Dict[str, Any], subject: str, body: str) -> List[str]:
        haystack = f"{subject}\n{body}".lower()
        selected: List[str] = []
        for rule in config.get("common_replies", []):
            match = str(rule.get("match", "")).lower().strip()
            guidance = str(rule.get("guidance", "")).strip()
            if match and guidance and match in haystack:
                selected.append(guidance)
        return selected

    def _generate_draft(
        self,
        email_item: Dict[str, Any],
        config: Dict[str, Any],
        additional_instruction: str = "",
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("Missing openai_api_key")

        payload = {
            "global_context": config.get("global_context", ""),
            "reply_language": config.get("reply_language", "English") or "English",
            "matched_context": self._select_context(config, email_item["subject"], email_item["body"]),
            "memory_examples": self.load_memory_examples(),
            "email": email_item,
            "extra_instruction": additional_instruction,
            "instructions": [
                "Write only the final email body as plain text.",
                "Use English by default unless the incoming email clearly requires a different language.",
                "Never pretend the email was sent; this is only a draft suggestion.",
            ],
        }

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.openai_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an assistant that drafts suggested responses for email support teams.",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.3,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        draft = data["choices"][0]["message"]["content"].strip()

        signature = config.get("signature", "")
        if signature:
            draft = f"{draft}\n\n{signature}"
        return draft

    def _notify_new_suggestion(self, suggestion: Dict[str, Any]) -> None:
        if not self.webhook_notify_url:
            return
        try:
            httpx.post(
                self.webhook_notify_url,
                json={
                    "ok": True,
                    "event": "email_suggestion_created",
                    "email_id": suggestion["email_id"],
                    "subject": suggestion["subject"],
                    "from": suggestion["from"],
                    "ts": datetime.now().isoformat(),
                },
                timeout=15,
            )
        except Exception:
            logger.exception(f"[{AGENT_NAME}] No se pudo enviar webhook de sugerencia de email | hora_texto={self._now_text()}")

    def check_new_and_suggest(self, max_emails: int, unread_only: bool, mailbox: str) -> List[Dict[str, Any]]:
        if not self._check_lock.acquire(blocking=False):
            self._debug("Detección omitida: ya hay una ejecución en curso")
            return []

        self._debug("Inicio de detección de correos nuevos", mailbox=mailbox)
        try:
            config = self.load_config()
            active_whitelist = self._normalize_whitelist(config.get("allowed_from_whitelist"))
            if not active_whitelist:
                active_whitelist = self.allowed_from_whitelist
            known = self.load_suggestions()
            known_ids = {item["email_id"] for item in known}

            created: List[Dict[str, Any]] = []
            for msg in self._fetch_gmail_messages(
                max_emails=max_emails,
                unread_only=unread_only,
                mailbox=mailbox,
                allowed_whitelist=active_whitelist,
            ):
                try:
                    if msg["id"] in known_ids:
                        continue

                    sender_email = self._extract_email_address(msg.get("from", ""))
                    if active_whitelist and sender_email not in active_whitelist:
                        self._debug(
                            "Correo ignorado por remitente",
                            email_id=msg.get("id", ""),
                            from_email=sender_email,
                        )
                        continue

                    draft = self._generate_draft(msg, config)
                    suggestion = {
                        "suggestion_id": f"s-{msg['id']}-{int(datetime.now().timestamp())}",
                        "email_id": msg["id"],
                        "from": msg["from"],
                        "subject": msg["subject"],
                        "date": msg["date"],
                        "original_body": msg["body"],
                        "suggested_reply": draft,
                        "status": "draft",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                    }
                    known.append(suggestion)
                    known_ids.add(msg["id"])
                    created.append(suggestion)
                    # Persistencia incremental para no perder sugerencias ya creadas
                    # si falla un correo posterior del lote.
                    self.save_suggestions(known)
                    self._debug("Sugerencia creada", suggestion_id=suggestion["suggestion_id"], email_id=msg["id"])

                    try:
                        self.append_memory(
                            {
                                "ts": datetime.now().isoformat(),
                                "subject": msg["subject"],
                                "from": msg["from"],
                                "suggested_reply": draft,
                            }
                        )
                    except Exception:
                        logger.exception(
                            "[%s] No se pudo guardar memoria de sugerencia | hora_texto=%s",
                            AGENT_NAME,
                            self._now_text(),
                        )
                    self._notify_new_suggestion(suggestion)
                except Exception:
                    logger.exception(
                        "[%s] Error procesando email individual | hora_texto=%s | email_id=%s",
                        AGENT_NAME,
                        self._now_text(),
                        msg.get("id", ""),
                    )
                    continue

            self._debug("Detección finalizada", created=len(created), total_guardadas=len(known))
            return created
        finally:
            self._check_lock.release()

    def create_suggestion_from_text(self, from_text: str, subject: str, body: str) -> Dict[str, Any]:
        """Crea una sugerencia manual a partir de texto introducido por el usuario."""
        if not body.strip():
            raise RuntimeError("Body is required")

        config = self.load_config()
        active_whitelist = self._normalize_whitelist(config.get("allowed_from_whitelist"))
        if not active_whitelist:
            active_whitelist = self.allowed_from_whitelist
        suggestions = self.load_suggestions()
        manual_id = f"manual-{int(datetime.now().timestamp())}"
        email_item = {
            "id": manual_id,
            "from": from_text.strip()
            or (active_whitelist[0] if active_whitelist else "manual@local"),
            "subject": subject.strip() or "Manual email",
            "date": datetime.now().isoformat(),
            "body": body.strip(),
        }
        draft = self._generate_draft(email_item, config)
        suggestion = {
            "suggestion_id": f"s-{manual_id}",
            "email_id": manual_id,
            "from": email_item["from"],
            "subject": email_item["subject"],
            "date": email_item["date"],
            "original_body": email_item["body"],
            "suggested_reply": draft,
            "status": "draft",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "source": "manual_input",
        }
        suggestions.append(suggestion)
        self.save_suggestions(suggestions)
        self.append_memory(
            {
                "ts": datetime.now().isoformat(),
                "subject": email_item["subject"],
                "from": email_item["from"],
                "suggested_reply": draft,
                "source": "manual_input",
            }
        )
        self._debug("Sugerencia manual creada", suggestion_id=suggestion["suggestion_id"])
        return suggestion

    def get_settings(self) -> Dict[str, Any]:
        config = self.load_config()
        whitelist = self._normalize_whitelist(config.get("allowed_from_whitelist"))
        if not whitelist:
            whitelist = self.allowed_from_whitelist
        return {"allowed_from_whitelist": whitelist}

    def update_settings(self, allowed_from_whitelist: List[str]) -> Dict[str, Any]:
        config = self.load_config()
        normalized = self._normalize_whitelist(allowed_from_whitelist)
        config["allowed_from_whitelist"] = normalized
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._debug("Configuración de email actualizada", whitelist_count=len(normalized))
        return {"allowed_from_whitelist": normalized}

    def regenerate_suggestion(self, suggestion_id: str, user_instruction: str) -> Dict[str, Any]:
        self._debug("Regenerando sugerencia", suggestion_id=suggestion_id)
        suggestions = self.load_suggestions()
        config = self.load_config()
        for item in suggestions:
            if item["suggestion_id"] != suggestion_id:
                continue
            draft = self._generate_draft(
                {
                    "id": item["email_id"],
                    "from": item["from"],
                    "subject": item["subject"],
                    "date": item["date"],
                    "body": item["original_body"],
                },
                config,
                additional_instruction=user_instruction,
            )
            item["suggested_reply"] = draft
            item["updated_at"] = datetime.now().isoformat()
            self.save_suggestions(suggestions)
            self._debug("Sugerencia regenerada", suggestion_id=suggestion_id)
            self.append_memory(
                {
                    "ts": datetime.now().isoformat(),
                    "subject": item["subject"],
                    "from": item["from"],
                    "suggested_reply": draft,
                    "instruction": user_instruction,
                }
            )
            return item
        raise RuntimeError(f"Suggestion not found: {suggestion_id}")
