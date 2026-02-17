import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlsplit, urlunsplit

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


AGENT_NAME = "issue_agent"


class IssueAgentService:
    """Agente para generar y completar issues web con OpenAI + Playwright."""

    def __init__(
        self,
        data_dir: Path,
        target_web_url: str,
        openai_api_key: str,
        openai_model: str,
        openai_style_law: str,
        webhook_url: str,
        logger,
    ) -> None:
        self.data_dir = data_dir
        self.target_web_url = target_web_url
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_style_law = openai_style_law
        self.webhook_url = webhook_url
        self.logger = logger

        # Rutas persistentes en /data (Home Assistant add-on).
        self.memory_path = self.data_dir / "issue_agent_memory.jsonl"
        self.events_path = self.data_dir / "issue_agent_events.jsonl"
        self.status_path = self.data_dir / "issue_agent_status.json"
        self._run_lock = threading.Lock()

        self._persist_status(
            {
                "ok": True,
                "message": "Issue agent listo",
                "updated_at": datetime.now().isoformat(),
            }
        )
        self._debug(
            "Servicio inicializado",
            has_target=bool(self.target_web_url.strip()),
            has_openai_key=bool(self.openai_api_key.strip()),
            has_webhook=bool(self.webhook_url.strip()),
        )

    @staticmethod
    def now_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    @staticmethod
    def _sanitize_url_for_log(raw_url: str) -> str:
        if not raw_url:
            return ""
        try:
            parts = urlsplit(raw_url)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except Exception:
            return raw_url

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _debug(self, message: str, **meta: Any) -> None:
        suffix = " | " + ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        self.logger.debug("[DEBUG][%s] %s | hora_texto=%s%s", AGENT_NAME, message, self._now_text(), suffix)

    def _append_event(self, event: str, **meta: Any) -> None:
        payload = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "meta": meta,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _persist_status(self, data: Dict[str, Any]) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_status(self) -> Dict[str, Any]:
        if not self.status_path.exists():
            return {"ok": True, "message": "Issue agent listo"}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:
            self.logger.exception("No se pudo leer estado de issue_agent")
            return {"ok": False, "message": "No se pudo leer estado"}

    def load_memory_examples(self, max_items: int = 12) -> List[Dict[str, Any]]:
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

    def build_generated_link(self, user_input: str) -> str:
        if not self.target_web_url.strip():
            raise RuntimeError("Missing issue_target_web_url")
        suffix = quote_plus(user_input.strip())
        if not suffix:
            return self.target_web_url
        joiner = "&" if "?" in self.target_web_url else "?"
        return f"{self.target_web_url}{joiner}q={suffix}"

    @staticmethod
    def _extract_json_content(raw_content: str) -> Dict[str, Any]:
        content = raw_content.strip()
        if content.startswith("```"):
            lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
            content = "\n".join(lines).strip()
        return json.loads(content)

    def _call_openai_issue_writer(self, user_input: str, include_comment: bool) -> Dict[str, str]:
        if not self.openai_api_key:
            raise RuntimeError("Missing issue_openai_api_key")

        memory = self.load_memory_examples()
        payload = {
            "task": "generate_issue_fields",
            "user_input": user_input,
            "include_comment": include_comment,
            "memory_examples": memory,
            "required_output": {
                "title": "string",
                "description": "string",
                "comment": "string",
            },
        }
        self._debug("Solicitando borrador de issue a OpenAI", include_comment=include_comment, memory=len(memory))

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
                        "content": (
                            "You are an issue writing assistant. "
                            "Mimic the style from memory examples. "
                            "No internet browsing is allowed. "
                            "Return ONLY valid JSON with keys: title, description, comment. "
                            f"Writing law/style: {self.openai_style_law.strip() or 'Keep it concise and actionable.'}"
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.2,
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = self._extract_json_content(content)
        return {
            "title": str(parsed.get("title", "")).strip(),
            "description": str(parsed.get("description", "")).strip(),
            "comment": str(parsed.get("comment", "")).strip() if include_comment else "",
        }

    def generate_issue(self, user_input: str, include_comment: bool) -> Dict[str, Any]:
        generated = self._call_openai_issue_writer(user_input=user_input, include_comment=include_comment)
        issue = {
            "issue_id": f"issue-{self.now_id()}",
            "title": generated["title"],
            "description": generated["description"],
            "comment": generated["comment"],
            "generated_link": self.build_generated_link(user_input),
            "created_at": datetime.now().isoformat(),
        }
        self._append_event("issue_generated", issue_id=issue["issue_id"])
        self._persist_status({"ok": True, "message": "Issue generado", "updated_at": datetime.now().isoformat()})
        self.logger.info("Issue generado (issue_id=%s)", issue["issue_id"])
        return issue

    def submit_issue_via_playwright(
        self,
        issue: Dict[str, Any],
        selectors: Dict[str, str],
        non_headless: bool,
    ) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Issue flow already running")

        try:
            # Para HA add-on: non-headless=true permite login manual en la sesión del navegador.
            self.logger.info(
                "Inicio submit issue via Playwright (issue_id=%s, non_headless=%s, target=%s)",
                issue.get("issue_id", ""),
                non_headless,
                self._sanitize_url_for_log(issue.get("generated_link", "")),
            )
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=not non_headless)
                page = browser.new_page()
                page.goto(issue["generated_link"], wait_until="domcontentloaded")

                page.fill(selectors["title"], issue["title"])
                page.fill(selectors["description"], issue["description"])

                dropdown = selectors.get("dropdown", "").strip()
                dropdown_option = selectors.get("dropdown_option", "").strip()
                if dropdown and dropdown_option:
                    page.click(dropdown)
                    page.click(dropdown_option)

                if issue.get("comment") and selectors.get("comment", "").strip():
                    page.fill(selectors["comment"], issue["comment"])

                if selectors.get("submit", "").strip():
                    page.click(selectors["submit"])

                # Pausa breve para confirmar acciones y permitir interacción manual inmediata si aplica.
                page.wait_for_timeout(1200)
                browser.close()

            self.append_memory(
                {
                    "ts": datetime.now().isoformat(),
                    "title": issue.get("title", ""),
                    "description": issue.get("description", ""),
                    "comment": issue.get("comment", ""),
                }
            )
            self._append_event("issue_submitted", issue_id=issue.get("issue_id", ""))
            self._persist_status({"ok": True, "message": "Issue enviado", "updated_at": datetime.now().isoformat()})
            self.logger.info("Submit issue completado (issue_id=%s)", issue.get("issue_id", ""))
            return {"ok": True, "submitted": True, "issue_id": issue.get("issue_id")}
        except PlaywrightTimeoutError as err:
            self._persist_status({"ok": False, "message": f"Timeout Playwright: {err}", "updated_at": datetime.now().isoformat()})
            self._append_event("issue_submit_failed", reason="timeout")
            self.logger.exception("Timeout en Playwright durante submit issue")
            raise
        except Exception as err:
            self._persist_status({"ok": False, "message": f"Fallo Playwright: {err}", "updated_at": datetime.now().isoformat()})
            self._append_event("issue_submit_failed", reason=str(err))
            self.logger.exception("Fallo en submit issue via Playwright")
            raise
        finally:
            self._run_lock.release()

    def send_webhook_report(self, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.webhook_url.strip():
            self.logger.warning("Webhook issue-agent omitido: falta issue_webhook_url")
            return {"ok": False, "skipped": True, "reason": "missing issue_webhook_url"}

        payload = {
            "ok": True,
            "agent": AGENT_NAME,
            "reason": reason,
            "details": details or {},
            "status": self.get_status(),
            "ts": datetime.now().isoformat(),
        }
        self._debug("Enviando webhook issue-agent", reason=reason)
        httpx.post(self.webhook_url, json=payload, timeout=20).raise_for_status()
        self._append_event("webhook_sent", reason=reason)
        self.logger.info("Webhook issue-agent enviado (reason=%s)", reason)
        return {"ok": True, "sent": True}

    def get_events(self, limit: int = 200) -> Dict[str, Any]:
        if not self.events_path.exists():
            return {"events": []}
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        items: List[Dict[str, Any]] = []
        for line in lines[-max(1, min(limit, 2000)) :]:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"events": items}
