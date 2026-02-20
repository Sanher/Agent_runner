import email
import imaplib
import json
import logging
import mimetypes
import re
import smtplib
import threading
from datetime import datetime, timedelta
from email import utils as email_utils
from email.header import decode_header
from email.message import EmailMessage, Message
from email.utils import parseaddr
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from agents.support_guidance import (
    DEFAULT_MARKETPLACE_ORDERS_URL,
    DEFAULT_SUPPORT_MARKETING_URL,
    DEFAULT_SUPPORT_TELEGRAM_URL,
    DEFAULT_SUPPORT_USER_URL_PREFIX,
    SupportGuidanceConfig,
    build_email_support_guidance,
)


logger = logging.getLogger("agent_runner.email_agent")
AGENT_NAME = "email_agent"
TELEGRAM_SUPPORT_URL = DEFAULT_SUPPORT_TELEGRAM_URL
MARKETPLACE_ORDERS_URL = DEFAULT_MARKETPLACE_ORDERS_URL
SIGNATURE_ASSET_KEYS = (
    "logo",
    "linkedin",
    "tiktok",
    "instagram",
    "twitter",
    "youtube",
    "telegram",
)
REVIEWED_RETENTION_DAYS = 7


class EmailAgentService:
    """Service to detect new emails and generate suggested replies."""

    def __init__(
        self,
        data_dir: Path,
        openai_api_key: str,
        openai_model: str,
        gmail_email: str,
        gmail_app_password: str,
        gmail_imap_host: str,
        webhook_notify_url: str,
        smtp_email: str,
        smtp_password: str,
        smtp_host: str,
        smtp_port: int,
        default_from_email: str,
        default_cc_email: str,
        default_signature_assets_dir: str,
        allowed_from_whitelist: List[str],
        support_telegram_url: str = DEFAULT_SUPPORT_TELEGRAM_URL,
        support_marketing_url: str = DEFAULT_SUPPORT_MARKETING_URL,
        support_user_url_prefix: str = DEFAULT_SUPPORT_USER_URL_PREFIX,
    ) -> None:
        self.data_dir = data_dir
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.gmail_email = gmail_email
        self.gmail_app_password = gmail_app_password
        self.gmail_imap_host = gmail_imap_host
        self.webhook_notify_url = webhook_notify_url
        self.smtp_email = smtp_email or gmail_email
        self.smtp_password = smtp_password or gmail_app_password
        self.smtp_host = smtp_host
        self.smtp_port = max(1, int(smtp_port))
        self.default_from_email = (default_from_email or self.smtp_email or "").strip()
        self.default_cc_email = (default_cc_email or "").strip()
        self.default_signature_assets_dir = (
            str(default_signature_assets_dir or "/config/media/signature").strip()
        )
        self.allowed_from_whitelist = sorted(
            {
                str(item).strip().lower()
                for item in allowed_from_whitelist
                if str(item).strip()
            }
        )
        self.support_guidance = SupportGuidanceConfig(
            telegram_support_url=str(support_telegram_url or DEFAULT_SUPPORT_TELEGRAM_URL).strip(),
            marketing_url=str(support_marketing_url or DEFAULT_SUPPORT_MARKETING_URL).strip(),
            user_url_prefix=str(support_user_url_prefix or DEFAULT_SUPPORT_USER_URL_PREFIX).strip(),
        )
        self._check_lock = threading.Lock()

        self.config_path = self.data_dir / "email_agent_config.json"
        self.memory_path = self.data_dir / "email_agent_memory.jsonl"
        self.suggestions_path = self.data_dir / "email_agent_suggestions.json"

        self._debug("Service initialized")

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _debug(self, message: str, **meta: Any) -> None:
        suffix = " | " + ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        logger.debug(f"[DEBUG][{AGENT_NAME}] {message} | timestamp_text={self._now_text()}{suffix}")

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
    def _normalize_email(value: str) -> str:
        return parseaddr(value or "")[1].strip().lower()

    @staticmethod
    def _parse_email_list(raw: str) -> tuple[List[str], bool]:
        # Accept flexible CSV-like lists: comma, semicolon, or newline.
        items: List[str] = []
        invalid = False
        for piece in str(raw or "").replace(";", ",").replace("\n", ",").split(","):
            token = piece.strip()
            if not token:
                continue
            normalized = parseaddr(token)[1].strip().lower()
            if not normalized:
                invalid = True
                continue
            if normalized not in items:
                items.append(normalized)
        return items, invalid

    @classmethod
    def _normalize_email_csv(cls, raw: str) -> str:
        items, _ = cls._parse_email_list(raw)
        return ", ".join(items)

    @classmethod
    def _validate_email_csv(cls, raw: str) -> bool:
        items, invalid = cls._parse_email_list(raw)
        if invalid:
            return False
        return all(cls._is_valid_email(item) for item in items)

    @classmethod
    def _normalize_validated_email_csv(cls, raw: str) -> str:
        if not str(raw or "").strip():
            return ""
        if not cls._validate_email_csv(raw):
            raise RuntimeError("Invalid CC email list")
        return cls._normalize_email_csv(raw)

    @staticmethod
    def _is_valid_email(value: str) -> bool:
        normalized = parseaddr(value or "")[1].strip()
        if "@" not in normalized:
            return False
        local, _, domain = normalized.partition("@")
        return bool(local and "." in domain)

    @staticmethod
    def _reply_subject(subject: str) -> str:
        clean_subject = str(subject or "").strip()
        if not clean_subject:
            return "RE: (no subject)"
        if clean_subject.lower().startswith("re:"):
            return clean_subject
        return f"RE: {clean_subject}"

    @staticmethod
    def _strip_html(value: str) -> str:
        return re.sub(r"<[^>]+>", "", str(value or ""))

    @classmethod
    def _signature_asset_style(cls, key: str) -> str:
        if key == "logo":
            return "display:block; height:56px; width:auto; margin:0 0 8px 0;"
        return (
            "display:inline-block; height:14px; width:auto; max-width:14px; "
            "vertical-align:middle; image-rendering:auto;"
        )

    @classmethod
    def _render_signature_with_assets(
        cls,
        signature_template: str,
        signature_assets_dir: str,
    ) -> tuple[str, str, list[tuple[Path, str, str]]]:
        """Build plain-text and HTML signature by resolving asset placeholders."""
        template = str(signature_template or "").strip()
        if not template:
            return "", "", []

        used_keys = [key for key in SIGNATURE_ASSET_KEYS if f"{{{{{key}}}}}" in template]
        attachments: list[tuple[Path, str, str]] = []
        cid_by_key: Dict[str, str] = {}
        assets_dir = Path(str(signature_assets_dir or "").strip())

        for key in used_keys:
            file_path = assets_dir / f"{key}.png"
            if not file_path.exists():
                logger.warning(
                    "[%s] Signature asset not found | key=%s | path=%s",
                    AGENT_NAME,
                    key,
                    str(file_path),
                )
                continue
            cid = email_utils.make_msgid(domain="agent-runner.local")[1:-1]
            cid_by_key[key] = cid
            attachments.append((file_path, cid, key))

        html_signature = template
        plain_signature = template
        for key in SIGNATURE_ASSET_KEYS:
            token = f"{{{{{key}}}}}"
            cid = cid_by_key.get(key)
            replacement = (
                f'<img src="cid:{cid}" alt="{html_escape(key)}" style="{cls._signature_asset_style(key)}" />'
                if cid
                else ""
            )
            html_signature = html_signature.replace(token, replacement)
            plain_signature = plain_signature.replace(token, "")

        html_signature = html_signature.replace("\n", "<br>")
        plain_signature = cls._strip_html(plain_signature)
        plain_signature = "\n".join(line.rstrip() for line in plain_signature.splitlines()).strip()
        return plain_signature, html_signature, attachments

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

        # IMAP OR is binary: OR A B. Chain expressions to support N senders.
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
            "default_from_email": self.default_from_email,
            "default_cc_email": self.default_cc_email,
            "signature_assets_dir": self.default_signature_assets_dir,
            "common_replies": [],
        }
        if not self.config_path.exists():
            return default_config
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("email_agent_config.json is not a JSON object; using defaults")
                return default_config
            return {**default_config, **data}
        except json.JSONDecodeError:
            logger.warning("email_agent_config.json is invalid; using defaults")
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
                logger.warning("email_agent_suggestions.json is not a list; using []")
                return []
            filtered, purged_count = self._purge_expired_reviewed_suggestions(data)
            if purged_count:
                self.save_suggestions(filtered)
                self._debug(
                    "Expired reviewed suggestions purged",
                    purged=purged_count,
                    retention_days=REVIEWED_RETENTION_DAYS,
                )
            return filtered
        except json.JSONDecodeError:
            logger.warning("email_agent_suggestions.json is invalid; using []")
            return []

    def save_suggestions(self, suggestions: List[Dict[str, Any]]) -> None:
        self.suggestions_path.parent.mkdir(parents=True, exist_ok=True)
        self.suggestions_path.write_text(
            json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _parse_iso_datetime(raw: Any) -> Optional[datetime]:
        value = str(raw or "").strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    @classmethod
    def _purge_expired_reviewed_suggestions(
        cls, suggestions: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], int]:
        now = datetime.now()
        filtered: List[Dict[str, Any]] = []
        purged_count = 0
        retention = timedelta(days=REVIEWED_RETENTION_DAYS)

        for item in suggestions:
            status = str(item.get("status", "")).strip().lower()
            if status != "reviewed":
                filtered.append(item)
                continue

            reviewed_at = cls._parse_iso_datetime(
                item.get("reviewed_at") or item.get("updated_at") or item.get("created_at")
            )
            if reviewed_at is None or (now - reviewed_at) <= retention:
                filtered.append(item)
                continue

            purged_count += 1

        return filtered, purged_count

    def _fetch_gmail_messages(
        self,
        max_emails: int,
        unread_only: bool,
        mailbox: str,
        allowed_whitelist: List[str],
    ) -> List[Dict[str, Any]]:
        self._debug(
            "Fetching emails via IMAP",
            mailbox=mailbox,
            unread_only=unread_only,
            max_emails=max_emails,
            whitelist=len(allowed_whitelist),
        )
        if not self.gmail_email or not self.gmail_app_password:
            raise RuntimeError("Missing IMAP credentials")

        criteria: List[str] = ["UNSEEN"] if unread_only else ["ALL"]
        criteria += self._build_from_criteria(allowed_whitelist)
        self._debug("IMAP criteria prepared", criteria_terms=len(criteria))
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

        self._debug("Emails fetched via IMAP", count=len(messages), mailbox=mailbox)
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

    @classmethod
    def _special_support_guidance(cls, subject: str, body: str) -> List[str]:
        return build_email_support_guidance(
            subject=subject,
            body=body,
            config=SupportGuidanceConfig(),
        )

    def _special_support_guidance_for_item(self, subject: str, body: str) -> List[str]:
        return build_email_support_guidance(
            subject=subject,
            body=body,
            config=self.support_guidance,
        )

    def _generate_draft(
        self,
        email_item: Dict[str, Any],
        config: Dict[str, Any],
        additional_instruction: str = "",
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("Missing openai_api_key")

        special_guidance = self._special_support_guidance(
            str(email_item.get("subject", "")),
            str(email_item.get("body", "")),
        )
        if self.support_guidance != SupportGuidanceConfig():
            special_guidance = self._special_support_guidance_for_item(
                str(email_item.get("subject", "")),
                str(email_item.get("body", "")),
            )
        matched_context = self._select_context(config, email_item["subject"], email_item["body"])
        self._debug(
            "Guidance context resolved",
            matched_context_count=len(matched_context),
            special_guidance_count=len(special_guidance),
        )

        payload = {
            "global_context": config.get("global_context", ""),
            "reply_language": config.get("reply_language", "English") or "English",
            "matched_context": [*matched_context, *special_guidance],
            "special_guidance": special_guidance,
            "memory_examples": self.load_memory_examples(),
            "email": email_item,
            "extra_instruction": additional_instruction,
            "instructions": [
                "Write only the final email body as plain text.",
                "Use English by default unless the incoming email clearly requires a different language.",
                "Never pretend the email was sent; this is only a draft suggestion.",
                "If special guidance is present, follow it strictly and include referenced URLs exactly.",
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
            logger.exception(
                f"[{AGENT_NAME}] Failed to send email suggestion webhook | timestamp_text={self._now_text()}"
            )

    def check_new_and_suggest(self, max_emails: int, unread_only: bool, mailbox: str) -> List[Dict[str, Any]]:
        if not self._check_lock.acquire(blocking=False):
            self._debug("Detection skipped: another run is already in progress")
            return []

        self._debug("Starting new email detection", mailbox=mailbox)
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
                            "Email skipped due to sender whitelist",
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
                    # Save incrementally to avoid losing already created suggestions
                    # if a later email in the same batch fails.
                    self.save_suggestions(known)
                    self._debug("Suggestion created", suggestion_id=suggestion["suggestion_id"], email_id=msg["id"])

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
                            "[%s] Failed to store suggestion memory | timestamp_text=%s",
                            AGENT_NAME,
                            self._now_text(),
                        )
                    self._notify_new_suggestion(suggestion)
                except Exception:
                    logger.exception(
                        "[%s] Error processing individual email | timestamp_text=%s | email_id=%s",
                        AGENT_NAME,
                        self._now_text(),
                        msg.get("id", ""),
                    )
                    continue

            self._debug("Detection completed", created=len(created), total_saved=len(known))
            return created
        finally:
            self._check_lock.release()

    def create_suggestion_from_text(self, from_text: str, subject: str, body: str) -> Dict[str, Any]:
        """Create a manual suggestion from user-provided text."""
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
        self._debug("Manual suggestion created", suggestion_id=suggestion["suggestion_id"])
        return suggestion

    def send_suggestion_email(
        self,
        suggestion_id: str,
        to_email: str,
        body: Optional[str] = None,
        cc_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a specific suggestion draft via SMTP."""
        self._debug(
            "Sending suggestion email",
            suggestion_id=suggestion_id,
            has_custom_cc=cc_email is not None,
        )
        if not self.smtp_email or not self.smtp_password:
            raise RuntimeError("Missing SMTP credentials")

        config = self.load_config()
        from_email = self._normalize_email(str(config.get("default_from_email", "")))
        if not from_email:
            from_email = self._normalize_email(self.default_from_email) or self._normalize_email(self.smtp_email)

        if not from_email or not self._is_valid_email(from_email):
            raise RuntimeError("Invalid sender email")

        raw_cc = cc_email if cc_email is not None else str(config.get("default_cc_email", "")).strip()
        if cc_email is None and not raw_cc:
            raw_cc = self.default_cc_email
        cc_csv = self._normalize_validated_email_csv(raw_cc)
        cc_items, _ = self._parse_email_list(cc_csv)
        self._debug(
            "Resolved recipients for delivery",
            suggestion_id=suggestion_id,
            to_email=to_email,
            cc_count=len(cc_items),
        )

        recipient = self._normalize_email(to_email)
        if not recipient or not self._is_valid_email(recipient):
            raise RuntimeError("Invalid recipient email")
        if recipient == from_email:
            raise RuntimeError("Recipient must be different from sender")

        suggestions = self.load_suggestions()
        for item in suggestions:
            if item["suggestion_id"] != suggestion_id:
                continue

            subject = self._reply_subject(str(item.get("subject", "")))
            source_body = str(body if body is not None else item.get("suggested_reply", "")).strip()
            if not source_body:
                raise RuntimeError("Reply body is required")

            signature_template = str(config.get("signature", "")).strip()
            signature_assets_dir = str(
                config.get("signature_assets_dir", self.default_signature_assets_dir)
            ).strip()
            plain_signature, html_signature, signature_attachments = self._render_signature_with_assets(
                signature_template,
                signature_assets_dir,
            )

            core_body = source_body
            if signature_template and core_body.rstrip().endswith(signature_template):
                core_body = core_body.rstrip()[: -len(signature_template)].rstrip()

            draft_body = core_body
            if plain_signature:
                draft_body = f"{core_body}\n\n{plain_signature}" if core_body else plain_signature
            draft_body = draft_body.strip()

            message = EmailMessage()
            message["From"] = from_email
            message["To"] = recipient
            if cc_csv:
                message["Cc"] = cc_csv
            message["Subject"] = subject
            message.set_content(draft_body)
            if html_signature:
                html_core = html_escape(core_body).replace("\n", "<br>")
                html_body = html_core
                if html_signature.strip():
                    html_body = f"{html_core}<br><br>{html_signature}" if html_core else html_signature
                message.add_alternative(f"<html><body>{html_body}</body></html>", subtype="html")
                html_part = message.get_payload()[-1]
                for file_path, cid, key in signature_attachments:
                    guessed = mimetypes.guess_type(str(file_path))[0] or "image/png"
                    maintype, subtype = guessed.split("/", 1)
                    with file_path.open("rb") as fh:
                        html_part.add_related(
                            fh.read(),
                            maintype=maintype,
                            subtype=subtype,
                            cid=f"<{cid}>",
                            filename=file_path.name,
                        )
                self._debug(
                    "HTML signature applied",
                    suggestion_id=suggestion_id,
                    assets_dir=signature_assets_dir,
                    assets_attached=len(signature_attachments),
                )

            recipients = [recipient]
            recipients.extend(cc_items)

            try:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30) as smtp:
                    smtp.login(self.smtp_email, self.smtp_password)
                    smtp.send_message(message, from_addr=from_email, to_addrs=recipients)
            except Exception as err:
                raise RuntimeError(f"SMTP send failed: {err}") from err

            now = datetime.now().isoformat()
            item["suggested_reply"] = draft_body
            item["status"] = "sent"
            item["updated_at"] = now
            item["sent_at"] = now
            item["sent_to"] = recipient
            item["sent_cc"] = cc_csv
            item["sent_subject"] = subject
            self.save_suggestions(suggestions)
            self._debug(
                "Suggestion email sent",
                suggestion_id=suggestion_id,
                to_email=recipient,
                cc_count=len(cc_items),
            )
            return item

        raise RuntimeError(f"Suggestion not found: {suggestion_id}")

    def get_settings(self) -> Dict[str, Any]:
        config = self.load_config()
        whitelist = self._normalize_whitelist(config.get("allowed_from_whitelist"))
        if not whitelist:
            whitelist = self.allowed_from_whitelist
        default_from_email = self._normalize_email(str(config.get("default_from_email", "")))
        if not default_from_email:
            default_from_email = self._normalize_email(self.default_from_email) or self._normalize_email(
                self.smtp_email
            )
        default_cc_email = self._normalize_email_csv(str(config.get("default_cc_email", "")).strip())
        if not default_cc_email:
            default_cc_email = self._normalize_email_csv(self.default_cc_email)
        signature_assets_dir = str(
            config.get("signature_assets_dir", self.default_signature_assets_dir)
        ).strip() or self.default_signature_assets_dir
        return {
            "allowed_from_whitelist": whitelist,
            "signature": str(config.get("signature", "")),
            "default_from_email": default_from_email,
            "default_cc_email": default_cc_email,
            "signature_assets_dir": signature_assets_dir,
        }

    def update_settings(
        self,
        allowed_from_whitelist: Optional[List[str]] = None,
        signature: Optional[str] = None,
        default_from_email: Optional[str] = None,
        default_cc_email: Optional[str] = None,
        signature_assets_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = self.load_config()
        if allowed_from_whitelist is not None:
            config["allowed_from_whitelist"] = self._normalize_whitelist(allowed_from_whitelist)
        if signature is not None:
            config["signature"] = str(signature).strip()
        if default_from_email is not None:
            normalized_from = self._normalize_email(default_from_email)
            if default_from_email and not normalized_from:
                raise RuntimeError("Invalid default_from_email")
            config["default_from_email"] = normalized_from or self.default_from_email
        if default_cc_email is not None:
            config["default_cc_email"] = self._normalize_validated_email_csv(default_cc_email)
        if signature_assets_dir is not None:
            config["signature_assets_dir"] = str(signature_assets_dir).strip() or self.default_signature_assets_dir

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        settings = self.get_settings()
        self._debug(
            "Email settings updated",
            whitelist_count=len(settings.get("allowed_from_whitelist", [])),
            has_signature=bool(settings.get("signature", "")),
            has_default_cc=bool(settings.get("default_cc_email", "")),
            signature_assets_dir=settings.get("signature_assets_dir", ""),
        )
        return settings

    def regenerate_suggestion(self, suggestion_id: str, user_instruction: str) -> Dict[str, Any]:
        self._debug("Regenerating suggestion", suggestion_id=suggestion_id)
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
            self._debug("Suggestion regenerated", suggestion_id=suggestion_id)
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
