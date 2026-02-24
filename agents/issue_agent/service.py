import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


AGENT_NAME = "issue_agent"
ISSUE_TYPES = {"bug", "feature", "task", "enhacement", "enhancement", "blockchain exchange", "blockchain", "exchange"}
REPO_KEYS = ("frontend", "backend", "management")
REPOS = set(REPO_KEYS)
REPO_ALIASES = {
    "front": "frontend",
    "frontend": "frontend",
    "back": "backend",
    "backend": "backend",
    "management": "management",
}
UNITS = {"core", "customer", "custome", "custom", "bot", "integrations", "marketing", "it"}
REPO_SLUGS = {"frontend": "frontend", "backend": "backend", "management": "management"}
ISSUE_TEMPLATE_BY_REPO_AND_TYPE = {
    ("frontend", "bug"): "bug_report.yml",
    ("frontend", "feature"): "feature_request.yml",
    ("frontend", "enhancement"): "enhancement_request.yml",
    ("frontend", "task"): "enhancement_request.yml",
    ("backend", "bug"): "bug_report.md",
    ("backend", "feature"): "feature_request.md",
    ("backend", "task"): "task_request.md",
    ("backend", "enhancement"): "task_request.md",
    ("backend", "blockchain"): "blockchain-template.md",
    ("backend", "exchange"): "exchange-template.md",
}
DEFAULT_BUG_PARENT_REPO_BY_REPO = {repo: "" for repo in REPO_KEYS}
DEFAULT_BUG_PARENT_ISSUE_NUMBER_BY_REPO = {repo: "" for repo in REPO_KEYS}
NEW_FEATURE_TEMPLATE = """FASE 1 - SOLICITUD DE NUEVA FEATURE
¿En que consiste?
{info}

¿Lo tiene la competencia?
Esto lo pasare yo

Beneficios para la compañía ¿visitas? ¿nuevos ingresos?
Atraera usuarios

¿Riesgos?
Coste de desarrollo

¿Porque la nuestra va a ser mejor que la competencia?
Este dato lo pasare yo

FASE 2 - PRESENTACIÓN A MANAGERS
¿Por qué lo va a usar el usuario?

¿Le funciona a la competencia? ¿Cuánto le aporta?

¿Tenemos ya esa información o habría que generarla?

¿Hay que integrarse con un tercero?

¿Le va a costar una inversión a la compañía (aparte del coste en horas del equipo)?

Tamaño??? M, L, XL
(Semana, mes, varios meses)

¿Favorece o perjudica a alguna otra feature del negocio?

¿Cuál sería el objetivo medible marcado?

¿Es escalable?

¿Cuál es el coste de mantenimiento?

FASE 3 - PASO AL EQUIPO DE DESARROLLO
¿Qué equipos se ven involucrados?

Casos de uso / historias de usuario
*******************"""


class IssueAgentService:
    """Agent to generate and complete web issues with OpenAI + Playwright."""

    def __init__(
        self,
        data_dir: Path,
        repo_base_url: str,
        project_name: str,
        storage_state_path: str,
        openai_api_key: str,
        openai_model: str,
        openai_style_law: str,
        webhook_url: str,
        logger,
        bug_parent_repo_by_repo: Optional[Dict[str, str]] = None,
        bug_parent_issue_number_by_repo: Optional[Dict[str, str]] = None,
    ) -> None:
        self.data_dir = data_dir
        self.repo_base_url = repo_base_url
        self.project_name = str(project_name or "").strip()
        self.storage_state_path = (
            Path(str(storage_state_path).strip()).expanduser()
            if str(storage_state_path or "").strip()
            else (self.data_dir / "storage" / "issue_agent.json")
        )
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_style_law = openai_style_law
        self.webhook_url = webhook_url
        self.bug_parent_repo_by_repo = {
            repo: str((bug_parent_repo_by_repo or {}).get(repo, "")).strip()
            or DEFAULT_BUG_PARENT_REPO_BY_REPO[repo]
            for repo in REPO_KEYS
        }
        self.bug_parent_issue_number_by_repo = {
            repo: str((bug_parent_issue_number_by_repo or {}).get(repo, "")).strip()
            or DEFAULT_BUG_PARENT_ISSUE_NUMBER_BY_REPO[repo]
            for repo in REPO_KEYS
        }
        self.logger = logger

        # Rutas persistentes de runtime.
        self.memory_path = self.data_dir / "issue_agent_memory.jsonl"
        self.events_path = self.data_dir / "issue_agent_events.jsonl"
        self.status_path = self.data_dir / "issue_agent_status.json"
        self._run_lock = threading.Lock()

        self._persist_status(
            {
                "ok": True,
                "message": "Issue agent ready",
                "updated_at": datetime.now().isoformat(),
            }
        )
        self._debug(
            "Service initialized",
            has_repo_base=bool(self.repo_base_url.strip()),
            has_project_name=bool(self.project_name),
            storage_state_path=str(self.storage_state_path),
            has_openai_key=bool(self.openai_api_key.strip()),
            has_webhook=bool(self.webhook_url.strip()),
            bug_parent_mapping_configured=any(bool(value) for value in self.bug_parent_repo_by_repo.values()),
        )

    @staticmethod
    def now_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    def _artifact_dir(self, job: str, run_id: str) -> Path:
        run_dir = self.data_dir / "runs" / str(job).strip() / str(run_id).strip()
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _capture_artifact(self, page, run_dir: Path, tag: str) -> Dict[str, str]:
        png_path = run_dir / f"{tag}.png"
        html_path = run_dir / f"{tag}.html"
        page.screenshot(path=str(png_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        self._debug(
            "Issue artifact captured",
            tag=tag,
            png=str(png_path),
            html=str(html_path),
        )
        return {"png": str(png_path), "html": str(html_path)}

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
        self.logger.debug("[DEBUG][%s] %s | timestamp_text=%s%s", AGENT_NAME, message, self._now_text(), suffix)

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
            return {"ok": True, "message": "Issue agent ready"}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:
            self.logger.exception("Failed to read issue_agent status")
            return {"ok": False, "message": "Failed to read status"}

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

    @staticmethod
    def _extract_json_content(raw_content: str) -> Dict[str, Any]:
        content = raw_content.strip()
        if content.startswith("```"):
            lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
            content = "\n".join(lines).strip()
        return json.loads(content)

    def _normalize_issue_type(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "enhacement":
            return "enhancement"
        if normalized == "blockchain exchange":
            return "exchange"
        if normalized in ISSUE_TYPES:
            return normalized
        return "bug"

    def _normalize_repo(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        return REPO_ALIASES.get(normalized, "backend")

    def _normalize_unit(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"custom", "custome"}:
            return "customer"
        return normalized if normalized in UNITS else "core"

    @staticmethod
    def _build_new_feature_description(user_input: str) -> str:
        return NEW_FEATURE_TEMPLATE.format(info=str(user_input or "").strip())

    @staticmethod
    def _repo_slug(repo: str) -> str:
        return REPO_SLUGS.get(REPO_ALIASES.get(str(repo or "").strip().lower(), ""), "")

    def _repo_owner(self) -> str:
        base = str(self.repo_base_url or "").strip()
        if base:
            try:
                path = urlsplit(base).path.strip("/")
                if path:
                    return path.split("/")[0].strip()
            except Exception:
                pass
        for configured in self.bug_parent_repo_by_repo.values():
            value = str(configured or "").strip()
            if "/" in value:
                return value.split("/", 1)[0].strip()
        return ""

    def _repo_issues_base_url(self, repo: str) -> str:
        base = str(self.repo_base_url or "").strip().rstrip("/")
        slug = self._repo_slug(repo)
        if not base or not slug:
            return ""
        return f"{base}/{slug}/issues"

    def _repo_new_issue_url(self, repo: str, issue_type: str) -> str:
        issues_base = self._repo_issues_base_url(repo)
        if not issues_base:
            return ""
        new_url = f"{issues_base}/new"
        template = ISSUE_TEMPLATE_BY_REPO_AND_TYPE.get(
            (str(repo or "").strip().lower(), str(issue_type or "").strip().lower()),
            "",
        )
        if template:
            return f"{new_url}?template={template}"
        return new_url

    def _repo_issue_url(self, repo: str, issue_number: str) -> str:
        issues_base = self._repo_issues_base_url(repo)
        number = str(issue_number or "").strip()
        if not issues_base or not number:
            return ""
        return f"{issues_base}/{number}"

    @staticmethod
    def _requires_web_browsing(issue_type: str) -> bool:
        normalized = str(issue_type or "").strip().lower()
        return "exchange" in normalized or "blockchain" in normalized

    @staticmethod
    def _infer_is_evm_from_text(text: str) -> Optional[bool]:
        value = str(text or "").strip().lower()
        if not value:
            return None
        if "non-evm" in value or "not evm" in value:
            return False
        yes_match = re.search(r"is\s*evm\??\s*[:=]\s*(yes|true|1|si|sí)", value)
        if yes_match:
            return True
        no_match = re.search(r"is\s*evm\??\s*[:=]\s*(no|false|0)", value)
        if no_match:
            return False
        return None

    @staticmethod
    def _infer_close_issue_from_text(text: str) -> bool:
        value = str(text or "").strip().lower()
        if not value:
            return False
        close_hints = [
            "close issue",
            "close it",
            "please close",
            "cerrar issue",
            "cerrar incidencia",
            "cierra la issue",
            "resuelto",
            "solucionado",
            "resolved",
            "fixed, close",
        ]
        return any(hint in value for hint in close_hints)

    @staticmethod
    def _extract_cc_mentions(text: str) -> List[str]:
        matches = re.findall(r"@[\w.-]+", str(text or ""))
        seen = set()
        ordered: List[str] = []
        for item in matches:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    @staticmethod
    def _strip_comment_prefixes(text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(r"^\s*(#+|\*+)\s*", "", value).strip()
        value = re.sub(r"^(context|proposal|resolution)\s*[:\-]\s*", "", value, flags=re.IGNORECASE).strip()
        return value

    def _format_issue_comment(self, comment: str, close_issue: bool, user_input: str) -> str:
        raw_lines = [self._strip_comment_prefixes(line) for line in str(comment or "").splitlines()]
        lines = [line for line in raw_lines if line]

        if close_issue:
            single_line = " ".join(lines).strip()
            return self._strip_comment_prefixes(single_line)

        if not lines:
            lines = ["Pending context", "Pending proposal"]
        elif len(lines) == 1:
            lines = [lines[0], "Proposal pending confirmation."]

        two_lines = lines[:2]
        mentions = self._extract_cc_mentions(user_input)
        cc_line = f"CC: {' '.join(mentions)}" if mentions else ""

        parts = two_lines + ([cc_line] if cc_line else [])
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_responses_output_text(payload: Dict[str, Any]) -> str:
        output_text = str(payload.get("output_text", "") or "").strip()
        if output_text:
            return output_text

        chunks: List[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                ctype = str(content.get("type", "")).strip().lower()
                if ctype not in {"output_text", "text"}:
                    continue
                text_value: Any = content.get("text", "")
                if isinstance(text_value, dict):
                    text_value = text_value.get("value", "")
                text = str(text_value or "").strip()
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def _call_openai_issue_writer(
        self,
        user_input: str,
        include_comment: bool,
        issue_type: str,
        repo: str,
        unit: str,
        comment_issue_number: str,
        is_new_feature: bool,
    ) -> Dict[str, str]:
        if not self.openai_api_key:
            raise RuntimeError("Missing issue_openai_api_key")

        memory = self.load_memory_examples()
        payload = {
            "task": "generate_issue_fields",
            "user_input": user_input,
            "issue_type": issue_type,
            "repo": repo,
            "unit": unit,
            "include_comment": include_comment,
            "comment_issue_number": comment_issue_number,
            "is_new_feature": is_new_feature,
            "memory_examples": memory,
            "required_output": {
                "title": "string",
                "description": "string",
                "steps_to_reproduce": "string",
                "comment": "string",
                "close_issue": "boolean",
            },
        }
        if is_new_feature:
            payload["required_output"]["description"] = "string (must follow the provided feature template)"

        self._debug(
            "Requesting issue draft from OpenAI",
            include_comment=include_comment,
            memory=len(memory),
            issue_type=issue_type,
            repo=repo,
            unit=unit,
            is_new_feature=is_new_feature,
            use_browsing=self._requires_web_browsing(issue_type),
        )
        language_law = (
            "Write all fields in English."
            if repo == "backend"
            else "Write all fields in Spanish from Spain."
        )
        markdown_links_law = "Use Markdown links for URLs unless explicitly asked to provide plain URLs."
        use_browsing = self._requires_web_browsing(issue_type)
        verification_law = (
            "Mandatory verification mode for blockchain/exchange: browse the web and verify every factual claim before writing it. "
            "Do not invent, assume, or hallucinate names, metrics, incidents, chains, exchanges, or timelines. "
            "If a fact cannot be verified, write 'Not verified'. "
            "Include source links in Markdown for all verified facts."
            if use_browsing
            else ""
        )
        backend_bug_title_law = (
            "For backend bug issues, title format must be: "
            "AFFECTED CHAIN(S), AFFECTED AREA(S) - short problem description. "
            "Chains and affected areas must be uppercase and comma-separated. "
            "If there is no affected chain, omit it."
            if repo == "backend" and issue_type == "bug"
            else ""
        )
        backend_blockchain_law = (
            "For backend blockchain issues: title must be only the chain name in lowercase. "
            "Description must be Markdown and follow this exact structure: "
            "**Blockchain relevant info** with fields Name, TVL, Website, id, Token, Block Explorer, Is EVM?, Main Exchange; "
            "**Blockchain other relevant exchanges**; "
            "**Blockchain testnet relevant info**; "
            "**Blockchain relevant links**; "
            "and **Additional context** only when user provided it. "
            "Set TVL to '?' when it cannot be verified. "
            "For EVM id, prioritize chainlist as source and only include id if the chain is EVM."
            if repo == "backend" and issue_type == "blockchain"
            else ""
        )
        backend_exchange_law = (
            "For backend exchange issues: title must be only the exchange name. "
            "Description must be Markdown and follow this exact structure: "
            "**Exchange relevant info** with fields Name, Blockchain, Website (URL), Logo (URL), Swap (URL), Factory, Router, Docs, Contact info (email, telegram..); "
            "and **Additional context** only when user provided it. "
            "For EVM exchanges, prioritize official docs for Factory/Router. "
            "If not EVM, provide the equivalent main contract if verified."
            if repo == "backend" and issue_type == "exchange"
            else ""
        )
        comment_style_law = (
            "Comment style rules: "
            "if include_comment=true and close_issue=false, return plain text with exactly two short lines "
            "(line 1 = context, line 2 = proposal), without labels/headings. "
            "If user provided @mentions, append one final line starting with 'CC:' and those mentions. "
            "If include_comment=true and close_issue=true, return a single plain resolution sentence only, "
            "without labels/headings and without the word 'Resolution'."
        )

        system_prompt = (
            "You are an issue writing assistant. "
            "Mimic the style from memory examples. "
            "Return ONLY valid JSON with keys: title, description, steps_to_reproduce, comment. "
            "If comment_issue_number is provided, reference it in the comment as a response number. "
            "When include_comment is true, set close_issue=true only if the user clearly asks to close the issue. "
            "For bug issues, provide clear, numbered reproduction steps in steps_to_reproduce. "
            "For feature issues, provide implementation guidance in steps_to_reproduce. "
            f"{language_law} "
            f"{markdown_links_law} "
            f"{verification_law} "
            f"{backend_bug_title_law} "
            f"{backend_blockchain_law} "
            f"{backend_exchange_law} "
            f"{comment_style_law} "
            f"Writing law/style: {self.openai_style_law.strip() or 'Keep it concise and actionable.'}"
        )
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        if use_browsing:
            response = httpx.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json={
                    "model": self.openai_model,
                    "instructions": system_prompt,
                    "input": json.dumps(payload, ensure_ascii=False),
                    "tools": [{"type": "web_search_preview"}],
                    "temperature": 0.2,
                },
                timeout=90,
            )
            response.raise_for_status()
            content = self._extract_responses_output_text(response.json())
            if not content:
                raise RuntimeError("OpenAI Responses API returned no text output")
        else:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json={
                    "model": self.openai_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt + " No internet browsing is allowed.",
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
        close_issue_raw = parsed.get("close_issue", False)
        close_issue = bool(close_issue_raw)
        if isinstance(close_issue_raw, str):
            close_issue = close_issue_raw.strip().lower() in {"true", "1", "yes", "y", "si", "sí"}
        formatted_comment = str(parsed.get("comment", "")).strip() if include_comment else ""
        if include_comment:
            formatted_comment = self._format_issue_comment(
                comment=formatted_comment,
                close_issue=close_issue,
                user_input=user_input,
            )
        return {
            "title": str(parsed.get("title", "")).strip(),
            "description": str(parsed.get("description", "")).strip(),
            "steps_to_reproduce": str(parsed.get("steps_to_reproduce", "")).strip(),
            "comment": formatted_comment,
            "close_issue": close_issue,
        }

    def generate_issue(
        self,
        user_input: str,
        issue_type: str,
        repo: str,
        unit: str,
        include_comment: bool,
        comment_issue_number: str = "",
        as_new_feature: bool = False,
        as_third_party: bool = False,
    ) -> Dict[str, Any]:
        issue_type = self._normalize_issue_type(issue_type)
        repo = self._normalize_repo(repo)
        unit = self._normalize_unit(unit)
        comment_issue_number = str(comment_issue_number or "").strip()
        self._debug(
            "Generating issue draft",
            issue_type=issue_type,
            repo=repo,
            unit=unit,
            include_comment=bool(include_comment),
            as_new_feature=bool(as_new_feature),
            as_third_party=bool(as_third_party),
            comment_issue_number=comment_issue_number or "-",
        )

        management_special_flow = as_new_feature or as_third_party
        if management_special_flow:
            repo = "management"
        if as_new_feature:
            issue_type = "feature"

        mode = "comment" if include_comment and comment_issue_number else "create"
        template_name = ISSUE_TEMPLATE_BY_REPO_AND_TYPE.get((repo, issue_type), "")
        if management_special_flow:
            template_name = ""
        self.logger.info(
            "Issue flow start: repo=%s issue_type=%s template=%s mode=%s browsing_enabled=%s",
            repo,
            issue_type,
            template_name or "none",
            mode,
            self._requires_web_browsing(issue_type),
        )

        generated_input = user_input
        if as_new_feature:
            generated_input = self._build_new_feature_description(user_input)

        generated = self._call_openai_issue_writer(
            user_input=generated_input,
            include_comment=include_comment,
            issue_type=issue_type,
            repo=repo,
            unit=unit,
            comment_issue_number=comment_issue_number,
            is_new_feature=as_new_feature,
        )
        if as_new_feature:
            generated["description"] = generated_input
        if as_new_feature:
            title_text = generated["title"].strip()
            generated["title"] = title_text if title_text.upper().startswith("[NEW]") else f"[NEW] {title_text}"
        if as_third_party:
            label = str(issue_type or "").strip().upper()
            title_text = generated["title"].strip()
            generated["title"] = title_text if title_text.upper().startswith(f"[{label}]") else f"[{label}] {title_text}"
        if repo == "frontend" and issue_type == "bug":
            title_text = generated["title"].strip()
            generated["title"] = title_text if title_text.upper().startswith("[BUG]") else f"[BUG] {title_text}"
            if not generated.get("steps_to_reproduce", "").strip():
                generated["steps_to_reproduce"] = (
                    "1. Go to the affected screen.\n"
                    "2. Perform the action that triggers the issue.\n"
                    "3. Verify the current result and the expected result."
                )
        if repo == "frontend" and issue_type == "feature":
            title_text = generated["title"].strip()
            generated["title"] = (
                title_text if title_text.upper().startswith("[FEATURE]") else f"[FEATURE] {title_text}"
            )
            if not generated.get("steps_to_reproduce", "").strip():
                generated["steps_to_reproduce"] = (
                    "- Define the involved components and states.\n"
                    "- Implement the interaction in the main view.\n"
                    "- Validate use cases, errors, and metrics."
                )
        if repo == "frontend" and issue_type == "enhancement":
            title_text = generated["title"].strip()
            generated["title"] = (
                title_text if title_text.upper().startswith("[ENHACEMENT]") else f"[ENHACEMENT] {title_text}"
            )
        if repo == "frontend" and issue_type == "task":
            title_text = generated["title"].strip()
            generated["title"] = title_text if title_text.upper().startswith("[TASK]") else f"[TASK] {title_text}"
        if repo == "backend" and issue_type in {"bug", "feature", "task", "enhancement"}:
            title_text = generated["title"].strip()
            if "-" in title_text:
                left, right = title_text.split("-", 1)
                left_text = left.strip().upper()
                right_text = right.strip()
                generated["title"] = f"{left_text} - {right_text}" if right_text else f"{left_text} - Bug details"
            else:
                generated["title"] = f"BACKEND - {title_text}"
        if repo == "backend" and issue_type == "blockchain":
            title_text = generated["title"].strip().splitlines()[0] if generated["title"].strip() else ""
            title_text = title_text.replace("[", "").replace("]", "").strip()
            if " - " in title_text:
                title_text = title_text.split(" - ", 1)[0].strip()
            if "," in title_text:
                title_text = title_text.split(",", 1)[0].strip()
            generated["title"] = title_text.lower()
            unit = "core"
        if repo == "backend" and issue_type == "exchange":
            title_text = generated["title"].strip().splitlines()[0] if generated["title"].strip() else ""
            generated["title"] = title_text.replace("[", "").replace("]", "").strip()
            unit = "core"

        target_link = (
            self._repo_issue_url(repo, comment_issue_number)
            if include_comment and comment_issue_number
            else self._repo_new_issue_url(repo, issue_type)
        )
        should_close_comment = bool(generated.get("close_issue")) or self._infer_close_issue_from_text(user_input)
        self._debug(
            "Issue draft generation completed",
            resolved_issue_type=issue_type,
            resolved_repo=repo,
            resolved_unit=unit,
            include_comment=bool(include_comment),
            close_issue_on_comment=bool(should_close_comment),
            generated_link=self._sanitize_url_for_log(target_link),
        )

        issue = {
            "issue_id": f"issue-{self.now_id()}",
            "title": generated["title"],
            "description": generated["description"],
            "steps_to_reproduce": generated.get("steps_to_reproduce", ""),
            "comment": generated["comment"],
            "issue_type": issue_type,
            "repo": repo,
            "unit": unit,
            "include_comment": bool(include_comment),
            "close_issue_on_comment": bool(should_close_comment),
            "comment_issue_number": comment_issue_number,
            "generated_link": target_link,
            "created_at": datetime.now().isoformat(),
            "is_evm": self._infer_is_evm_from_text(user_input) if issue_type == "blockchain" else None,
            "as_new_feature": bool(as_new_feature),
            "as_third_party": bool(as_third_party),
        }
        self._append_event("issue_generated", issue_id=issue["issue_id"])
        self._persist_status({"ok": True, "message": "Issue generated", "updated_at": datetime.now().isoformat()})
        self.logger.info("Issue generated (issue_id=%s)", issue["issue_id"])
        return issue

    def submit_issue_via_playwright(
        self,
        issue: Dict[str, Any],
        selectors: Dict[str, str],
        non_headless: bool,
    ) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Issue flow already running")

        run_id_raw = str(issue.get("issue_id", "")).strip() or f"issue-{self.now_id()}"
        run_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id_raw).strip("-") or f"issue-{self.now_id()}"
        run_dir = self._artifact_dir("issue_flow", run_id)
        artifacts: Dict[str, Dict[str, str]] = {}
        page = None

        try:
            # `non_headless=True` allows manual login in the browser session.
            self.logger.info(
                "Starting issue submission via Playwright (issue_id=%s, run_id=%s, non_headless=%s, target=%s, artifacts=%s)",
                issue.get("issue_id", ""),
                run_id,
                non_headless,
                self._sanitize_url_for_log(issue.get("generated_link", "")),
                run_dir,
            )
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=not non_headless)
                context_kwargs: Dict[str, Any] = {}
                if self.storage_state_path.exists():
                    context_kwargs["storage_state"] = str(self.storage_state_path)
                    self.logger.info("Issue flow: reusing storage_state from %s", self.storage_state_path)
                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                repo = self._normalize_repo(str(issue.get("repo", "")))
                issue_type = str(issue.get("issue_type", "")).strip().lower()
                target_url = str(issue.get("generated_link", "")).strip() or self._repo_new_issue_url(repo, issue_type)
                page.goto(target_url, wait_until="domcontentloaded")
                artifacts["start_loaded"] = self._capture_artifact(page, run_dir, "start_loaded")
                self._debug(
                    "Playwright target loaded",
                    repo=repo,
                    issue_type=issue_type,
                    include_comment=bool(issue.get("include_comment")),
                    target=self._sanitize_url_for_log(target_url),
                )

                try:
                    if issue.get("include_comment") and str(issue.get("comment_issue_number", "")).strip():
                        self._debug(
                            "Executing comment mode flow",
                            repo=repo,
                            issue_number=str(issue.get("comment_issue_number", "")).strip(),
                            close_issue=bool(issue.get("close_issue_on_comment")),
                        )
                        self._submit_issue_comment(page, issue)
                    elif repo == "management" and issue.get("as_third_party"):
                        self._debug("Executing management third-party flow")
                        self._submit_management_third_party_issue(page, issue)
                    elif repo == "management" and issue.get("as_new_feature"):
                        self._debug("Executing management new-feature flow")
                        self._submit_management_feature_issue(page, issue)
                    elif repo == "frontend":
                        self._debug("Executing frontend issue flow", issue_type=issue_type)
                        self._submit_frontend_issue(page, issue)
                    elif repo == "backend" and issue_type in {"bug", "feature", "task", "enhancement", "blockchain", "exchange"}:
                        self._debug("Executing backend issue flow", issue_type=issue_type)
                        self._submit_backend_issue(page, issue)
                    else:
                        self._debug("Executing generic selector-based issue flow")
                        self._fill_text_or_select(page, selectors["title"], issue["title"])
                        self._fill_text_or_select(page, selectors["description"], issue["description"])
                        self._fill_text_or_select(page, selectors.get("issue_type", ""), issue.get("issue_type", ""))
                        self._fill_text_or_select(page, selectors.get("repo", ""), issue.get("repo", ""))
                        self._fill_text_or_select(page, selectors.get("unit", ""), issue.get("unit", ""))
                        self._fill_text_or_select(
                            page,
                            selectors.get("comment_issue_number", ""),
                            issue.get("comment_issue_number", ""),
                        )

                        dropdown = selectors.get("dropdown", "").strip()
                        dropdown_option = selectors.get("dropdown_option", "").strip()
                        if dropdown and dropdown_option:
                            page.click(dropdown)
                            page.click(dropdown_option)

                        if issue.get("comment") and selectors.get("comment", "").strip():
                            self._fill_text_or_select(page, selectors["comment"], issue["comment"])

                        if selectors.get("submit", "").strip():
                            page.click(selectors["submit"])

                    # Short pause to confirm actions and allow immediate manual interaction when needed.
                    page.wait_for_timeout(1200)
                    artifacts["final_click"] = self._capture_artifact(page, run_dir, "final_click")
                except Exception:
                    try:
                        artifacts["failed"] = self._capture_artifact(page, run_dir, "failed")
                    except Exception as capture_err:
                        self.logger.warning("Issue flow: failure artifact capture failed: %s", capture_err)
                    raise
                try:
                    self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state_path))
                    self.logger.info("Issue flow: storage_state updated at %s", self.storage_state_path)
                except Exception as storage_err:
                    self.logger.warning("Issue flow: failed to persist storage_state: %s", storage_err)
                context.close()
                browser.close()

            self.append_memory(
                {
                    "ts": datetime.now().isoformat(),
                    "title": issue.get("title", ""),
                    "description": issue.get("description", ""),
                    "steps_to_reproduce": issue.get("steps_to_reproduce", ""),
                    "comment": issue.get("comment", ""),
                }
            )
            self._append_event(
                "issue_submitted",
                issue_id=issue.get("issue_id", ""),
                run_id=run_id,
                artifacts_dir=str(run_dir),
            )
            self._persist_status({"ok": True, "message": "Issue submitted", "updated_at": datetime.now().isoformat()})
            self.logger.info("Issue submission completed (issue_id=%s)", issue.get("issue_id", ""))
            final_url = page.url if "page" in locals() else str(issue.get("generated_link", "")).strip()
            non_blocking_warnings = issue.get("_warnings", []) if isinstance(issue.get("_warnings", []), list) else []
            summary_text = (
                f"Playwright summary: issue_id={issue.get('issue_id', '')} "
                f"repo={self._normalize_repo(str(issue.get('repo', '')))} "
                f"url={self._sanitize_url_for_log(final_url)} "
                f"warnings={len(non_blocking_warnings)} "
                f"run_id={run_id} "
                f"artifacts={run_dir}"
            )
            if non_blocking_warnings:
                self.logger.warning(
                    "Issue flow completed with non-blocking warnings (issue_id=%s, count=%s)",
                    issue.get("issue_id", ""),
                    len(non_blocking_warnings),
                )
                for warning in non_blocking_warnings:
                    self.logger.warning("Issue flow warning: %s", warning)
            self.logger.info(summary_text)
            self.logger.info(
                "Issue flow finish: issue_id=%s run_id=%s issue_url=%s project=%s unit=%s team=%s status=%s sprint=%s creation_date=%s parent=%s artifacts=%s",
                issue.get("issue_id", ""),
                run_id,
                self._sanitize_url_for_log(final_url),
                self.project_name or "-",
                issue.get("unit", "") or "-",
                self._frontend_team_label(str(issue.get("repo", ""))) if not issue.get("as_third_party") else "-",
                "Backlog" if issue.get("as_new_feature") or issue.get("as_third_party") else "Todo",
                "Current",
                "Today",
                "true" if str(issue.get("issue_type", "")).strip().lower() == "bug" or issue.get("as_third_party") else "false",
                run_dir,
            )
            return {
                "ok": True,
                "submitted": True,
                "issue_id": issue.get("issue_id"),
                "final_url": final_url,
                "run_id": run_id,
                "artifacts_dir": str(run_dir),
                "artifacts": artifacts,
                "warnings": non_blocking_warnings,
                "summary": summary_text,
            }
        except PlaywrightTimeoutError as err:
            self._persist_status({"ok": False, "message": f"Timeout Playwright: {err}", "updated_at": datetime.now().isoformat()})
            self._append_event("issue_submit_failed", reason="timeout", run_id=run_id, artifacts_dir=str(run_dir))
            self.logger.exception("Playwright timeout during issue submission (run_id=%s)", run_id)
            raise
        except Exception as err:
            self._persist_status({"ok": False, "message": f"Playwright failure: {err}", "updated_at": datetime.now().isoformat()})
            self._append_event("issue_submit_failed", reason=str(err), run_id=run_id, artifacts_dir=str(run_dir))
            self.logger.exception("Issue submission failed via Playwright (run_id=%s)", run_id)
            raise
        finally:
            self._run_lock.release()

    def _fill_text_or_select(self, page, selector: str, value: Any) -> None:
        if not selector or not str(value).strip():
            return

        value_text = str(value).strip()
        try:
            page.wait_for_selector(selector, timeout=800, state="attached")
            try:
                tag_name = page.eval_on_selector(selector, "el => el.tagName.toLowerCase()")
            except Exception:
                tag_name = ""
            if tag_name == "select":
                try:
                    page.select_option(selector, value_text)
                except Exception:
                    page.fill(selector, value_text)
            else:
                page.fill(selector, value_text)
        except Exception as err:
            self.logger.warning(
                "Issue flow: selector fallback/unavailable (selector=%s, value=%s, error=%s)",
                selector,
                value_text[:150],
                err,
            )

    def _ensure_project_selected(self, page) -> None:
        if not self.project_name:
            self.logger.warning("Issue flow: project selection skipped (missing issue_project_name)")
            return
        try:
            self._click_option_by_text(page, self.project_name)
        except Exception as err:
            self.logger.warning("Issue flow: failed to select project '%s': %s", self.project_name, err)

    @staticmethod
    def _frontend_unit_label(unit: str) -> str:
        mapping = {
            "core": "Core",
            "customer": "Customer",
            "custome": "Customer",
            "custom": "Customer",
            "bot": "Bot",
            "integrations": "Integrations",
            "marketing": "Marketing",
            "it": "IT",
        }
        return mapping.get(str(unit or "").strip().lower(), "Core")

    @staticmethod
    def _frontend_team_label(repo: str) -> str:
        mapping = {
            "frontend": "Frontend",
            "backend": "Backend",
            "management": "Management",
        }
        key = REPO_ALIASES.get(str(repo or "").strip().lower(), "frontend")
        return mapping.get(key, "Frontend")

    def _click_option_by_text(self, page, text: str, always_click: bool = False, timeout_ms: int = 6000) -> None:
        option = page.locator("li[role='option']").filter(has_text=text).first
        option.wait_for(state="visible", timeout=timeout_ms)
        selected = option.get_attribute("aria-selected")
        if always_click or selected != "true":
            option.click(timeout=timeout_ms)

    @staticmethod
    def _append_issue_warning(issue: Dict[str, Any], message: str) -> None:
        warnings = issue.setdefault("_warnings", [])
        if isinstance(warnings, list):
            warnings.append(message)

    def _open_projects_editor(self, page) -> None:
        button = page.locator("button#create-issue-sidebar-projects-section-heading").first
        if button.count() == 0:
            button = page.get_by_role("button", name=re.compile("Edit Projects", re.I)).first
        button.wait_for(state="visible", timeout=8000)
        try:
            button.click(timeout=8000)
        except Exception:
            button.click(timeout=8000, force=True)

    def _click_create_and_wait_created(self, page, repo: str, issue_type: str, issue_id: str) -> None:
        create_button = page.locator('[data-testid="create-issue-button"]').first
        if create_button.count() == 0:
            create_button = page.get_by_role("button", name=re.compile(r"^Create$", re.I)).first

        create_button.wait_for(state="visible", timeout=10000)
        self.logger.info(
            "Issue flow: clicking Create (repo=%s, issue_type=%s, issue_id=%s)",
            repo,
            issue_type,
            issue_id,
        )
        try:
            create_button.click(timeout=10000)
        except Exception:
            create_button.click(timeout=10000, force=True)

        created_regex = re.compile(r".*/issues/\d+(?:[?#].*)?$")
        created = False
        for shortcut in ("Meta+Enter", "Control+Enter"):
            try:
                page.wait_for_url(created_regex, timeout=9000)
                created = True
                break
            except Exception:
                try:
                    page.keyboard.press(shortcut)
                except Exception:
                    pass
                page.wait_for_timeout(350)

        if not created:
            try:
                page.wait_for_url(created_regex, timeout=4000)
                created = True
            except Exception:
                created = False

        self.logger.info(
            "Issue flow: create submitted, entering post-create fields (repo=%s, issue_type=%s, url=%s)",
            repo,
            issue_type,
            self._sanitize_url_for_log(page.url),
        )
        if not created:
            raise RuntimeError(
                f"Create did not navigate to created issue (repo={repo}, issue_type={issue_type}, url={page.url})"
            )

    def _apply_bug_parent_relationship(
        self,
        page,
        repo: str,
        parent_repo_override: str = "",
        parent_issue_number_override: str = "",
    ) -> Optional[str]:
        repo_key = str(repo or "").strip().lower()
        parent_repo = str(parent_repo_override or "").strip() or self.bug_parent_repo_by_repo.get(repo_key, "")
        parent_issue_number = str(parent_issue_number_override or "").strip() or self.bug_parent_issue_number_by_repo.get(
            repo_key, ""
        )
        configured_parent_issues = {
            str(value).strip()
            for value in self.bug_parent_issue_number_by_repo.values()
            if str(value).strip()
        }
        if parent_issue_number in configured_parent_issues:
            management_parent_repo = str(self.bug_parent_repo_by_repo.get("management", "")).strip()
            if management_parent_repo:
                parent_repo = management_parent_repo
        if not parent_repo or not parent_issue_number:
            self.logger.warning("Issue flow: parent relationship skipped (missing target for repo=%s)", repo_key)
            return f"Parent relationship skipped: missing target for repo '{repo_key}'"
        self._debug(
            "Applying parent relationship",
            repo=repo_key,
            parent_repo=parent_repo,
            parent_issue=parent_issue_number,
        )
        try:
            edit_relationships_btn = page.locator("button").filter(has_text="Edit Relationships").first
            edit_relationships_btn.scroll_into_view_if_needed(timeout=3000)
            try:
                edit_relationships_btn.click(timeout=7000)
            except Exception:
                edit_relationships_btn.click(timeout=7000, force=True)
            page.wait_for_timeout(2000)
            add_parent_item = page.locator("li[role='menuitem']").filter(has_text="Add parent").first
            add_parent_item.wait_for(state="visible", timeout=7000)
            add_parent_item.click(timeout=7000)
            page.locator('[data-testid="back-to-repo-selection-button"]').first.click(timeout=7000)

            repo_search = page.locator(
                'input[aria-label*="repository" i], input[placeholder*="repository" i], input[aria-label*="Select repository" i]'
            ).first
            if repo_search.count() > 0:
                repo_search.fill(parent_repo, timeout=7000)
                page.wait_for_timeout(700)

            try:
                self._click_option_by_text(page, parent_repo, always_click=True, timeout_ms=7000)
            except Exception:
                parent_repo_short = parent_repo.split("/")[-1].strip()
                if parent_repo_short:
                    self._click_option_by_text(page, parent_repo_short, always_click=True, timeout_ms=7000)
                else:
                    raise

            page.wait_for_timeout(2500)
            issue_search = page.locator('input[aria-label="Search issues"], input[placeholder*="Search issues"]').first
            issue_search.wait_for(state="visible", timeout=12000)
            issue_search.fill(parent_issue_number, timeout=7000)
            page.wait_for_timeout(5000)
            parent_issue = page.locator("li[role='option']").filter(has_text=f"#{parent_issue_number}").first
            parent_issue.wait_for(state="visible", timeout=7000)
            parent_issue.click(timeout=7000)
            self._debug("Parent relationship selected", parent_issue=parent_issue_number)
            return None
        except Exception as err:
            self.logger.warning(
                "Issue flow: failed to apply parent relationship (repo=%s, parent_repo=%s, parent_issue=%s, error=%s)",
                repo_key,
                parent_repo,
                parent_issue_number,
                err,
            )
            return (
                f"Parent relationship failed (repo={repo_key}, parent_repo={parent_repo}, "
                f"parent_issue={parent_issue_number}): {err}"
            )

    def _ensure_project_post_fields_visible(self, page) -> bool:
        # GitHub project metadata can be collapsed right after create.
        # Open the chevron container before trying Status/Unit/Team/Sprint/Date.
        business_unit_btn = page.locator("button").filter(has_text="Business Unit")
        if business_unit_btn.count() > 0:
            return True

        candidate_groups = []
        project_name = str(self.project_name or "").strip()
        if project_name:
            project_pattern = re.compile(rf"\b{re.escape(project_name)}\b", re.I)
            candidate_groups.append(
                page.locator("div,section,aside")
                .filter(has_text=project_pattern)
                .locator("button[data-component='IconButton'][aria-expanded='false']")
            )
        candidate_groups.append(page.locator("button[data-component='IconButton'][aria-expanded='false']"))

        for group in candidate_groups:
            try:
                total = min(group.count(), 8)
            except Exception:
                total = 0
            for idx in range(total):
                button = group.nth(idx)
                try:
                    button.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                try:
                    button.click(timeout=3000)
                except Exception:
                    try:
                        button.click(timeout=3000, force=True)
                    except Exception:
                        continue
                page.wait_for_timeout(350)
                if business_unit_btn.count() > 0:
                    return True
        return business_unit_btn.count() > 0

    def _apply_post_creation_fields(
        self, page, unit_label: str, team_label: str = "", status_label: str = "Todo"
    ) -> List[str]:
        # Shared post-create metadata flow used across frontend/backend/management issue variants.
        self._debug("Applying post-create fields", status=status_label, unit=unit_label, team=team_label or "-")
        warnings: List[str] = []
        if not self._ensure_project_post_fields_visible(page):
            message = "Post-create project fields are still collapsed (Business Unit not visible)"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)

        status_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                if attempt == 0:
                    self._ensure_project_post_fields_visible(page)
                    page.wait_for_timeout(500)
                elif attempt == 1:
                    page.locator("button").filter(has_text=re.compile(r"Status|Todo|Backlog", re.I)).first.click(
                        timeout=4000
                    )
                    page.wait_for_timeout(500)
                else:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(250)
                    self._ensure_project_post_fields_visible(page)
                    page.wait_for_timeout(500)

                try:
                    self._click_option_by_text(page, status_label)
                except Exception:
                    if status_label != "Todo":
                        self._click_option_by_text(page, "Todo")
                    else:
                        raise
                status_error = None
                break
            except Exception as err:
                status_error = err
                continue

        if status_error is not None:
            message = f"Post-create status selection failed after retries: {status_error}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)

        try:
            page.locator("button").filter(has_text="Business Unit").first.click(timeout=5000)
            self._click_option_by_text(page, unit_label)
        except Exception as err:
            message = f"Post-create business unit failed (unit={unit_label}): {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)

        if team_label:
            try:
                page.wait_for_timeout(300)
                page.locator("button").filter(has_text="Team").first.click(timeout=5000)
                self._click_option_by_text(page, team_label)
            except Exception as err:
                message = f"Post-create team failed (team={team_label}): {err}"
                warnings.append(message)
                self.logger.warning("Issue flow: %s", message)

        try:
            page.wait_for_timeout(300)
            page.locator("button").filter(has_text="Sprint").first.click(timeout=5000)
            current_option = page.locator("li[role='option']").filter(has_text="Current").first
            current_option.wait_for(state="visible", timeout=5000)
            current_option.click(timeout=5000)
        except Exception as err:
            message = f"Post-create sprint failed (Current): {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)

        try:
            page.wait_for_timeout(300)
            page.locator("button").filter(has_text="Creation Date").first.click(timeout=5000)
            target_date = datetime.now().strftime("%m/%d/%Y")
            day_cell = page.locator(f'div[role="gridcell"][data-date="{target_date}"]').first
            if day_cell.count() > 0:
                day_cell.click(timeout=5000)
            else:
                page.locator('div[role="gridcell"][aria-selected="true"]').first.click(timeout=5000)
        except Exception as err:
            message = f"Post-create creation date failed: {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)

        return warnings

    @staticmethod
    def _backend_bug_markdown_body(description: str, steps: str) -> str:
        return f"**Describe the bug**\n{description}\n\n**To Reproduce**\n{steps}"

    @staticmethod
    def _backend_feature_markdown_body(description: str) -> str:
        return f"**Is your feature request related to a problem? Please describe.**\n{description}"

    @staticmethod
    def _backend_task_markdown_body(description: str) -> str:
        return f"**Describe the request**\n{description}"

    @staticmethod
    def _backend_blockchain_markdown_body(description: str, chain_name: str, is_evm: Optional[bool]) -> str:
        if "**Blockchain relevant info**" in str(description or ""):
            return str(description or "").strip()
        evm_value = "Yes" if is_evm is True else "No" if is_evm is False else "?"
        return (
            "**Blockchain relevant info**\n\n"
            f"- Name: {chain_name}\n"
            "- TVL: ?\n"
            "- Website:\n"
            "- id:\n"
            "- Token:\n"
            "- Block Explorer:\n"
            f"- Is EVM? {evm_value}\n"
            "- Main Exchange:\n\n"
            "**Blockchain other relevant exchanges**\n"
            "Not verified\n\n"
            "**Blockchain testnet relevant info**\n"
            "Not verified\n\n"
            "**Blockchain relevant links**\n"
            "Not verified"
        )

    @staticmethod
    def _backend_exchange_markdown_body(description: str, exchange_name: str) -> str:
        if "**Exchange relevant info**" in str(description or ""):
            return str(description or "").strip()
        return (
            "**Exchange relevant info**\n"
            f"- Name: {exchange_name}\n"
            "- Blockchain:\n"
            "- Website (URL):\n"
            "- Logo (URL):\n"
            "- Swap (URL):\n"
            "- Factory:\n"
            "- Router:\n"
            "- Docs:\n"
            "- Contact info (email,telegram..):\n\n"
            "**Additional context**\n"
            f"{description.strip() or 'Not provided'}"
        )

    def _apply_blockchain_labels_and_type(self, page, is_evm: Optional[bool]) -> None:
        if is_evm is True:
            self._debug("Applying blockchain label", label="evm")
            page.locator("button").filter(has_text="Edit Labels").first.click()
            page.wait_for_timeout(2000)
            labels_filter = page.locator('input[aria-label="Filter labels"]').first
            labels_filter.fill("EVM")
            page.wait_for_timeout(1200)
            self._click_option_by_text(page, "evm")
        else:
            self._debug("Skipping blockchain EVM label", is_evm=is_evm)

    def _apply_issue_type(self, page, issue_type: str) -> None:
        # Force GitHub issue type to match the requested workflow semantics.
        page.locator("button").filter(has_text="Edit Type").first.click()
        mapping = {
            "bug": "Bug",
            "feature": "Feature",
            "task": "Task",
            "enhancement": "Task",
        }
        resolved_type = mapping.get(str(issue_type or "").strip().lower(), "Feature")
        self._debug("Applying issue type", requested=issue_type, resolved=resolved_type)
        self._click_option_by_text(page, resolved_type)

    def _apply_management_epic_new_feature(self, page) -> None:
        self._debug("Applying management epic", epic="NEW FEATURES REQUEST")
        try:
            page.locator("button").filter(has_text="Epic").first.click()
            epic_search = page.locator('input[aria-label="Choose an option"]').first
            epic_search.fill("NEW FEATURE")
            page.wait_for_timeout(1200)
            self._click_option_by_text(page, "NEW FEATURES REQUEST")
        except Exception as err:
            self.logger.warning("Issue flow: failed to set epic 'NEW FEATURES REQUEST': %s", err)

    def _submit_management_feature_issue(self, page, issue: Dict[str, Any]) -> None:
        # Management "new feature" flow: blank issue + template body + backlog metadata + epic selection.
        self._debug("Starting management new-feature submit flow")
        title = str(issue.get("title", "")).strip()
        if issue.get("as_new_feature") and not title.upper().startswith("[NEW]"):
            title = f"[NEW] {title}"
        description = str(issue.get("description", "")).strip()

        page.locator('input[aria-label="Add a title"]').first.fill(title)
        markdown_area = page.locator('textarea[aria-label="Markdown value"]').first
        markdown_area.fill("")
        markdown_area.fill(description)

        self._open_projects_editor(page)
        self._ensure_project_selected(page)

        self._click_create_and_wait_created(
            page,
            repo="management",
            issue_type="feature",
            issue_id=str(issue.get("issue_id", "")),
        )

        self._apply_issue_type(page, "feature")
        field_warnings = self._apply_post_creation_fields(
            page,
            unit_label=self._frontend_unit_label(str(issue.get("unit", ""))),
            team_label=self._frontend_team_label("management"),
            status_label="Backlog",
        )
        for warning in field_warnings:
            self._append_issue_warning(issue, warning)
        self._apply_management_epic_new_feature(page)

    def _submit_management_third_party_issue(self, page, issue: Dict[str, Any]) -> None:
        issue_type = str(issue.get("issue_type", "")).strip().lower()
        self._debug("Starting management third-party submit flow", issue_type=issue_type)
        title = str(issue.get("title", "")).strip()
        label = issue_type.upper() if issue_type else "TASK"
        if not title.upper().startswith(f"[{label}]"):
            title = f"[{label}] {title}"
        description = str(issue.get("description", "")).strip()

        page.locator('input[aria-label="Add a title"]').first.fill(title)
        markdown_area = page.locator('textarea[aria-label="Markdown value"]').first
        markdown_area.fill("")
        markdown_area.fill(description)

        self._open_projects_editor(page)
        self._ensure_project_selected(page)

        self._click_create_and_wait_created(
            page,
            repo="management",
            issue_type=issue_type or "task",
            issue_id=str(issue.get("issue_id", "")),
        )

        self._apply_issue_type(page, issue_type)
        field_warnings = self._apply_post_creation_fields(
            page,
            unit_label=self._frontend_unit_label(str(issue.get("unit", ""))),
            team_label="",
            status_label="Backlog",
        )
        for warning in field_warnings:
            self._append_issue_warning(issue, warning)
        parent_warning = self._apply_bug_parent_relationship(page, repo="management")
        if parent_warning:
            self._append_issue_warning(issue, parent_warning)

    def _submit_issue_comment(self, page, issue: Dict[str, Any]) -> None:
        # Comment-only flow for existing issues: write comment and optionally close in a single action.
        self._debug(
            "Starting comment submit flow",
            issue_number=str(issue.get("comment_issue_number", "")).strip(),
            close_issue=bool(issue.get("close_issue_on_comment")),
        )
        comment_text = str(issue.get("comment", "")).strip() or str(issue.get("description", "")).strip()
        if not comment_text:
            comment_text = str(issue.get("title", "")).strip()

        comment_box = page.locator(
            'textarea[aria-label="Markdown value"], textarea[placeholder*="Use Markdown to format your comment"]'
        ).first
        comment_box.fill(comment_text)
        page.wait_for_timeout(300)

        if issue.get("close_issue_on_comment"):
            close_button = page.locator("button").filter(has_text="Close issue").first
            if close_button.count() > 0:
                close_button.click()
                self._debug("Comment flow action executed", action="close_issue")
                return

        comment_button = page.locator("button").filter(has_text="Comment").first
        comment_button.click()
        self._debug("Comment flow action executed", action="comment")

    def _submit_backend_issue(self, page, issue: Dict[str, Any]) -> None:
        issue_type = str(issue.get("issue_type", "")).strip().lower()
        self._debug("Starting backend submit flow", issue_type=issue_type)
        title = str(issue.get("title", "")).strip()
        description = str(issue.get("description", "")).strip()
        steps = str(issue.get("steps_to_reproduce", "")).strip()
        if issue_type == "bug":
            if not steps:
                steps = (
                    "1. Go to the affected page.\n"
                    "2. Perform the action that triggers the bug.\n"
                    "3. Verify current behavior vs expected behavior."
                )
            markdown_body = self._backend_bug_markdown_body(description, steps)
        elif issue_type == "feature":
            markdown_body = self._backend_feature_markdown_body(description)
        elif issue_type == "blockchain":
            title = title.lower()
            markdown_body = self._backend_blockchain_markdown_body(
                description=description,
                chain_name=title,
                is_evm=issue.get("is_evm"),
            )
        elif issue_type == "exchange":
            markdown_body = self._backend_exchange_markdown_body(
                description=description,
                exchange_name=title,
            )
        else:
            markdown_body = self._backend_task_markdown_body(description)

        page.locator('input[aria-label="Add a title"]').first.fill(title)
        markdown_area = page.locator('textarea[aria-label="Markdown value"]').first
        markdown_area.fill("")
        markdown_area.fill(markdown_body)

        if issue_type == "blockchain":
            self._apply_blockchain_labels_and_type(page, issue.get("is_evm"))

        self._open_projects_editor(page)
        self._ensure_project_selected(page)

        self._click_create_and_wait_created(
            page,
            repo="backend",
            issue_type=issue_type or "task",
            issue_id=str(issue.get("issue_id", "")),
        )

        field_warnings = self._apply_post_creation_fields(
            page,
            unit_label="Core"
            if issue_type in {"blockchain", "exchange"}
            else self._frontend_unit_label(str(issue.get("unit", ""))),
            team_label="Backend",
        )
        for warning in field_warnings:
            self._append_issue_warning(issue, warning)
        if issue_type == "bug":
            parent_warning = self._apply_bug_parent_relationship(page, str(issue.get("repo", "")))
            if parent_warning:
                self._append_issue_warning(issue, parent_warning)

    def _submit_frontend_issue(self, page, issue: Dict[str, Any]) -> None:
        issue_type = str(issue.get("issue_type", "")).strip().lower()
        self._debug("Starting frontend submit flow", issue_type=issue_type)
        title = str(issue.get("title", "")).strip()
        if issue_type == "bug" and not title.upper().startswith("[BUG]"):
            title = f"[BUG] {title}"
        if issue_type == "feature" and not title.upper().startswith("[FEATURE]"):
            title = f"[FEATURE] {title}"
        if issue_type == "enhancement" and not title.upper().startswith("[ENHACEMENT]"):
            title = f"[ENHACEMENT] {title}"
        if issue_type == "task" and not title.upper().startswith("[TASK]"):
            title = f"[TASK] {title}"

        description = str(issue.get("description", "")).strip()
        steps = str(issue.get("steps_to_reproduce", "")).strip()
        if not steps:
            if issue_type == "feature":
                steps = (
                    "- Define the involved components and states.\n"
                    "- Implement the interaction in the main view.\n"
                    "- Validate use cases, errors, and metrics."
                )
            else:
                steps = (
                    "1. Go to the affected screen.\n"
                    "2. Perform the action that triggers the issue.\n"
                    "3. Verify the current result and the expected result."
                )

        page.locator('input[aria-label="Add a title"]').first.fill(title)
        if issue_type == "feature":
            page.locator('textarea[placeholder*="Show the favorites list in a side panel"]').first.fill(description)
            page.locator('textarea[placeholder*="User opens the pair explorer"]').first.fill(steps)
        elif issue_type in {"enhancement", "task"}:
            page.locator('textarea[placeholder*="Saved wallets should support more color options."]').first.fill(
                description
            )
        else:
            page.locator("textarea[placeholder*=\"I can't save a wallet\"]").first.fill(description)
            page.locator('textarea[placeholder^="1. Go to Wallet page"]').first.fill(steps)

        # Projects field: ensure the configured project is selected.
        self._open_projects_editor(page)
        self._ensure_project_selected(page)

        self._click_create_and_wait_created(
            page,
            repo="frontend",
            issue_type=issue_type or "task",
            issue_id=str(issue.get("issue_id", "")),
        )

        field_warnings = self._apply_post_creation_fields(
            page,
            unit_label=self._frontend_unit_label(str(issue.get("unit", ""))),
            team_label=self._frontend_team_label(str(issue.get("repo", ""))),
        )
        for warning in field_warnings:
            self._append_issue_warning(issue, warning)
        if issue_type == "bug":
            parent_warning = self._apply_bug_parent_relationship(page, str(issue.get("repo", "")))
            if parent_warning:
                self._append_issue_warning(issue, parent_warning)

    def send_webhook_report(self, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.webhook_url.strip():
            self.logger.warning("Issue-agent webhook skipped: missing issue_webhook_url")
            return {"ok": False, "skipped": True, "reason": "missing issue_webhook_url"}

        payload = {
            "ok": True,
            "agent": AGENT_NAME,
            "reason": reason,
            "details": details or {},
            "status": self.get_status(),
            "ts": datetime.now().isoformat(),
        }
        self._debug("Sending issue-agent webhook", reason=reason)
        httpx.post(self.webhook_url, json=payload, timeout=20).raise_for_status()
        self._append_event("webhook_sent", reason=reason)
        self.logger.info("Issue-agent webhook sent (reason=%s)", reason)
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
