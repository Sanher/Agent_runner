import ast
import json
import ipaddress
import re
import shutil
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
WEEKLY_RETENTION_SECONDS = 7 * 24 * 60 * 60
NEW_FEATURE_TEMPLATE = """FASE 1 - SOLICITUD DE NUEVA FEATURE
¿En que consiste?
{info}

¿Lo tiene la competencia?
{competition}

Beneficios para la compañía ¿visitas? ¿nuevos ingresos?
{benefits}

¿Riesgos?
{risks}

¿Porque la nuestra va a ser mejor que la competencia?
{why_better}

FASE 2 - PRESENTACIÓN A MANAGERS
¿Por qué lo va a usar el usuario?
{user_why_use}

¿Le funciona a la competencia? ¿Cuánto le aporta?
{competitor_value}

¿Tenemos ya esa información o habría que generarla?
{info_availability}

¿Hay que integrarse con un tercero?
{third_party_integration}

¿Le va a costar una inversión a la compañía (aparte del coste en horas del equipo)?
{investment}

Tamaño??? M, L, XL
(Semana, mes, varios meses)
{size}

¿Favorece o perjudica a alguna otra feature del negocio?
{feature_impact}

¿Cuál sería el objetivo medible marcado?
{measurable_goal}

¿Es escalable?
{scalable}

¿Cuál es el coste de mantenimiento?
{maintenance_cost}

FASE 3 - PASO AL EQUIPO DE DESARROLLO
¿Qué equipos se ven involucrados?
{teams}

Casos de uso / historias de usuario
{use_cases}
*******************"""
NEW_FEATURE_DEFAULT_FIELDS = {
    "competition": "Esto lo pasare yo",
    "benefits": "Atraera usuarios",
    "risks": "Coste de desarrollo",
    "why_better": "Este dato lo pasare yo",
    "user_why_use": "",
    "competitor_value": "",
    "info_availability": "",
    "third_party_integration": "",
    "investment": "",
    "size": "",
    "feature_impact": "",
    "measurable_goal": "",
    "scalable": "",
    "maintenance_cost": "",
    "teams": "",
    "use_cases": "",
}
NEW_FEATURE_ENRICHABLE_FIELDS = tuple(key for key in NEW_FEATURE_DEFAULT_FIELDS if key != "risks")
DRAFT_WARNING_MESSAGES = {
    "source": {
        "no_valid_external_links": "No se han detectado enlaces externos válidos para enriquecer la solicitud.",
        "source_not_verifiable": "Hay información de fuentes que no se ha podido verificar o completar.",
        "url_missing_pricing": "No se ha podido verificar pricing desde las URLs aportadas.",
        "url_missing_auth_details": "No se han encontrado detalles suficientes de autenticación en las URLs aportadas.",
        "url_missing_capabilities": "No se han encontrado suficientes capacidades o endpoints documentados en las URLs aportadas.",
        "source_missing_tvl": "No se ha podido verificar el TVL desde las fuentes aportadas.",
        "source_missing_chain_id": "No se ha podido verificar el chain id desde las fuentes aportadas.",
        "source_missing_explorer": "No se ha podido verificar un block explorer desde las fuentes aportadas.",
        "source_missing_exchange_confirmation": "No se ha podido confirmar el exchange principal desde las fuentes aportadas.",
        "source_missing_factory": "No se ha podido verificar el contrato factory desde las fuentes aportadas.",
        "source_missing_router": "No se ha podido verificar el contrato router desde las fuentes aportadas.",
        "source_missing_contact_info": "No se ha podido verificar información de contacto suficiente desde las fuentes aportadas.",
    },
    "user": {
        "missing_expected_behavior": "Falta describir el comportamiento esperado.",
        "missing_current_behavior": "Falta describir el comportamiento actual.",
        "missing_reproduction_steps": "Faltan pasos de reproducción suficientemente concretos.",
        "missing_environment_context": "Falta contexto de entorno o plataforma afectada.",
        "missing_affected_area": "Falta concretar el área afectada.",
        "missing_user_value": "Falta explicar el valor para el usuario.",
        "missing_scope_detail": "Falta concretar el alcance de la solicitud.",
        "missing_success_metric": "Falta definir una métrica de éxito.",
        "missing_dependency_context": "Falta contexto sobre dependencias o integraciones implicadas.",
        "missing_acceptance_criteria": "Faltan criterios de aceptación.",
        "missing_current_limitation": "Falta explicar la limitación actual.",
        "missing_proposed_improvement": "Falta concretar la mejora propuesta.",
    },
}
DEFAULT_DRAFT_WARNING_GROUPS = ("source", "user")


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
        self.cleanup_state_path = self.data_dir / "issue_agent_cleanup_state.json"
        self._run_lock = threading.Lock()
        self._active_run_id = ""

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
        self._maybe_weekly_cleanup()

    @staticmethod
    def now_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    def _resolve_submit_run_id(self, issue: Dict[str, Any]) -> str:
        explicit_run_id = str(issue.get("submit_run_id", "") or issue.get("run_id", "")).strip()
        if explicit_run_id:
            run_id_raw = explicit_run_id
        else:
            issue_id = str(issue.get("issue_id", "")).strip() or f"issue-{self.now_id()}"
            run_id_raw = f"{issue_id}-submit-{self.now_id()}-{time.time_ns() % 1_000_000:06d}"
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id_raw).strip("-") or f"issue-{self.now_id()}"

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

    def _playwright_step(self, message: str, **meta: Any) -> None:
        # Short live step events consumed by the UI Playwright panel during submit.
        run_id = str(getattr(self, "_active_run_id", "") or "").strip()
        compact_meta_parts: List[str] = []
        payload: Dict[str, Any] = {"run_id": run_id, "message": str(message or "").strip()}
        for key, value in meta.items():
            text = str(value or "").strip()
            if text:
                trimmed = text[:120]
                payload[key] = trimmed
                compact_meta_parts.append(f"{key}={trimmed[:48]}")
        if compact_meta_parts:
            payload["message"] = f"{payload['message']} | {'; '.join(compact_meta_parts[:3])}"
        self._append_event("issue_playwright_step", **payload)

    # Weekly cleanup state is tracked in a small sidecar file to avoid running cleanup
    # on every request. This keeps runtime overhead low in HA while still enforcing retention.
    def _load_cleanup_state(self) -> Dict[str, Any]:
        if not self.cleanup_state_path.exists():
            return {}
        try:
            return json.loads(self.cleanup_state_path.read_text(encoding="utf-8"))
        except Exception:
            self.logger.warning("Issue flow: failed to read cleanup state, recreating it")
            return {}

    def _save_cleanup_state(self, data: Dict[str, Any]) -> None:
        self.cleanup_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.cleanup_state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _parse_iso_ts(raw: str) -> Optional[datetime]:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None

    def _purge_old_issue_runs(self, cutoff_ts: float) -> int:
        # Removes old Playwright artifacts only (screenshots/html).
        # It does not touch memory, storage_state, or status files.
        runs_root = self.data_dir / "runs" / "issue_flow"
        if not runs_root.exists():
            return 0
        removed = 0
        for entry in runs_root.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff_ts:
                    shutil.rmtree(entry)
                    removed += 1
            except Exception as err:
                self.logger.warning("Issue flow: failed to remove old artifacts dir %s: %s", entry, err)
        return removed

    def _prune_old_events(self, cutoff_ts: float) -> int:
        # Prunes old telemetry rows from issue_agent_events.jsonl.
        if not self.events_path.exists():
            return 0
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        kept: List[str] = []
        removed = 0
        for line in lines:
            try:
                payload = json.loads(line)
            except Exception:
                kept.append(line)
                continue
            ts = self._parse_iso_ts(str(payload.get("ts", "")))
            if ts is None:
                kept.append(line)
                continue
            if ts.timestamp() < cutoff_ts:
                removed += 1
                continue
            kept.append(line)
        if removed > 0:
            body = "\n".join(kept)
            if body:
                body += "\n"
            self.events_path.write_text(body, encoding="utf-8")
        return removed

    def _maybe_weekly_cleanup(self) -> None:
        # Weekly retention guard:
        # - delete issue_flow run dirs older than 7 days
        # - delete telemetry events older than 7 days
        # - keep memory/status/storage_state untouched
        now = datetime.now()
        now_ts = time.time()
        state = self._load_cleanup_state()
        last_cleanup = self._parse_iso_ts(str(state.get("last_weekly_cleanup", "")))
        if last_cleanup is not None:
            try:
                if (now_ts - last_cleanup.timestamp()) < WEEKLY_RETENTION_SECONDS:
                    return
            except Exception:
                pass

        cutoff_ts = now_ts - WEEKLY_RETENTION_SECONDS
        removed_runs = self._purge_old_issue_runs(cutoff_ts=cutoff_ts)
        removed_events = self._prune_old_events(cutoff_ts=cutoff_ts)
        self._save_cleanup_state({"last_weekly_cleanup": now.isoformat()})
        cleanup_at = now.strftime("%Y-%m-%d %H:%M:%S")
        self.logger.info(
            "Issue flow: weekly cleanup completed at %s (removed_runs=%s, removed_events=%s, retention_days=7)",
            cleanup_at,
            removed_runs,
            removed_events,
        )

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

    @staticmethod
    def _coerce_multiline_text(raw: Any) -> str:
        if isinstance(raw, (list, tuple)):
            return "\n".join(str(item).strip() for item in raw if str(item).strip()).strip()

        text = str(raw or "").strip()
        if text.startswith("[") and text.endswith("]"):
            parsed_value: Any = None
            for parser in (json.loads, ast.literal_eval):
                try:
                    parsed_value = parser(text)
                    break
                except Exception:
                    continue
            if isinstance(parsed_value, (list, tuple)):
                return "\n".join(
                    str(item).strip() for item in parsed_value if str(item).strip()
                ).strip()
        return text

    @staticmethod
    def _empty_draft_warnings() -> Dict[str, List[str]]:
        return {group: [] for group in DEFAULT_DRAFT_WARNING_GROUPS}

    @staticmethod
    def _append_draft_warning_message(warnings: Dict[str, List[str]], group: str, message: str) -> None:
        group_name = str(group or "").strip().lower()
        text = str(message or "").strip()
        if group_name not in warnings or not text:
            return
        if text not in warnings[group_name]:
            warnings[group_name].append(text)

    def _normalize_warning_group(self, raw: Any, group: str) -> List[str]:
        normalized_group = str(group or "").strip().lower()
        allowed = DRAFT_WARNING_MESSAGES.get(normalized_group, {})
        result: List[str] = []
        if isinstance(raw, list):
            values = raw
        elif str(raw or "").strip():
            values = [raw]
        else:
            values = []
        for item in values:
            code = str(item or "").strip()
            if not code:
                continue
            message = allowed.get(code)
            if not message:
                message = allowed.get("source_not_verifiable") if normalized_group == "source" else "Falta contexto del usuario para completar correctamente la solicitud."
            if message not in result:
                result.append(message)
        return result

    def _normalize_draft_warnings(self, raw: Any) -> Dict[str, List[str]]:
        normalized = self._empty_draft_warnings()
        if isinstance(raw, dict):
            for group in DEFAULT_DRAFT_WARNING_GROUPS:
                for message in self._normalize_warning_group(raw.get(group, []), group):
                    self._append_draft_warning_message(normalized, group, message)
            return normalized
        for message in self._normalize_warning_group(raw, "source"):
            self._append_draft_warning_message(normalized, "source", message)
        return normalized

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
    def _build_new_feature_description(user_input: str, enrichment: Optional[Dict[str, str]] = None) -> str:
        values = dict(NEW_FEATURE_DEFAULT_FIELDS)
        values["info"] = str(user_input or "").strip()
        for key in NEW_FEATURE_DEFAULT_FIELDS:
            candidate = str((enrichment or {}).get(key, "")).strip()
            if candidate:
                values[key] = candidate
        return NEW_FEATURE_TEMPLATE.format(**values)

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
    def _extract_urls(text: str) -> List[str]:
        raw_matches = re.findall(r"https?://[^\s<>()\"']+", str(text or ""), flags=re.I)
        urls: List[str] = []
        seen = set()
        for raw in raw_matches:
            candidate = str(raw or "").strip().rstrip(".,);:]")
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)
        return urls

    @staticmethod
    def _is_local_or_private_host(hostname: str) -> bool:
        host = str(hostname or "").strip().lower()
        if not host:
            return True
        if host in {"localhost", "::1"} or host.endswith(".local"):
            return True
        if host.startswith("127."):
            return True
        try:
            ip = ipaddress.ip_address(host)
            return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
        except ValueError:
            return False

    def _issue_enrichment_blacklist_prefixes(self) -> List[str]:
        prefixes: List[str] = []
        for raw in [self.repo_base_url] + [self._repo_issues_base_url(repo) for repo in REPO_KEYS]:
            value = self._sanitize_url_for_log(str(raw or "").strip()).rstrip("/")
            if value:
                prefixes.append(value.lower())
        return prefixes

    def _extract_enrichment_urls(self, text: str) -> List[str]:
        candidates: List[str] = []
        blocked_prefixes = self._issue_enrichment_blacklist_prefixes()
        for raw_url in self._extract_urls(text):
            safe_url = self._sanitize_url_for_log(raw_url).rstrip("/")
            if not safe_url:
                continue
            lowered = safe_url.lower()
            try:
                host = urlsplit(safe_url).hostname or ""
            except Exception:
                continue
            if self._is_local_or_private_host(host):
                continue
            if any(lowered.startswith(prefix) for prefix in blocked_prefixes):
                continue
            candidates.append(safe_url)
        return candidates[:3]

    def _enrich_new_feature_from_links(self, user_input: str, repo: str, urls: List[str]) -> Dict[str, Any]:
        if not self.openai_api_key:
            raise RuntimeError("Missing issue_openai_api_key")

        normalized_urls = [self._sanitize_url_for_log(url) for url in urls if str(url or "").strip()]
        payload = {
            "task": "enrich_new_feature_from_links",
            "user_input": str(user_input or "").strip(),
            "urls": normalized_urls,
            "required_output": {
                "info": "string",
                "competition": "string",
                "benefits": "string",
                "why_better": "string",
                "user_why_use": "string",
                "competitor_value": "string",
                "info_availability": "string",
                "third_party_integration": "string",
                "investment": "string",
                "size": "string",
                "feature_impact": "string",
                "measurable_goal": "string",
                "scalable": "string",
                "maintenance_cost": "string",
                "teams": "string",
                "use_cases": "string",
                "warnings": ["string"],
            },
        }
        language_law = "Write all returned fields in English." if repo == "backend" else "Write all returned fields in Spanish from Spain."
        system_prompt = (
            "You enrich a product/API feature request from user-provided links. "
            "Use browsing only to inspect the provided URLs and clearly linked official docs/pricing pages from those URLs. "
            "Do not perform general competitor research. "
            "Never invent facts, plans, pricing, quotas, or capabilities. "
            "If a field cannot be verified from the provided sources, return an empty string for that field and add a short warning. "
            "Keep the text concise and practical for an internal feature request template. "
            f"{language_law} "
            "Return ONLY valid JSON."
        )
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json={
                "model": self.openai_model,
                "instructions": system_prompt,
                "input": json.dumps(payload, ensure_ascii=False),
                "tools": [{"type": "web_search_preview"}],
                "temperature": 0.1,
            },
            timeout=90,
        )
        response.raise_for_status()
        content = self._extract_responses_output_text(response.json())
        if not content:
            raise RuntimeError("OpenAI Responses API returned no text output for link enrichment")
        parsed = self._extract_json_content(content)
        fields = {}
        for key in ("info",) + NEW_FEATURE_ENRICHABLE_FIELDS:
            fields[key] = str(parsed.get(key, "")).strip()
        raw_warnings = parsed.get("warnings", [])
        warnings: List[str] = []
        if isinstance(raw_warnings, list):
            warnings = [str(item).strip() for item in raw_warnings if str(item).strip()]
        elif str(raw_warnings or "").strip():
            warnings = [str(raw_warnings).strip()]
        return {"fields": fields, "warnings": warnings, "urls": normalized_urls}

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
                "warnings": {
                    "source": ["code"],
                    "user": ["code"],
                },
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
        warning_codes_law = (
            "Warnings output law: "
            f"source warning codes allowed={','.join(sorted(DRAFT_WARNING_MESSAGES['source'].keys()))}; "
            f"user warning codes allowed={','.join(sorted(DRAFT_WARNING_MESSAGES['user'].keys()))}. "
            "Return only codes from those lists. "
            "Never include names, URLs, brands, or free-form explanations in warnings."
        )

        system_prompt = (
            "You are an issue writing assistant. "
            "Mimic the style from memory examples. "
            "Return ONLY valid JSON with keys: title, description, steps_to_reproduce, comment, warnings. "
            "If comment_issue_number is provided, reference it in the comment as a response number. "
            "When include_comment is true, set close_issue=true only if the user clearly asks to close the issue. "
            "For bug issues, provide clear, numbered reproduction steps in steps_to_reproduce. "
            "For feature issues, provide implementation guidance in steps_to_reproduce. "
            "Use warnings for missing, weak, ambiguous, or non-verified information that the user should review before submitting. "
            "If there are no warnings, return both warning groups as empty arrays. "
            f"{language_law} "
            f"{markdown_links_law} "
            f"{verification_law} "
            f"{backend_bug_title_law} "
            f"{backend_blockchain_law} "
            f"{backend_exchange_law} "
            f"{comment_style_law} "
            f"{warning_codes_law} "
            f"Writing law/style: {self.openai_style_law.strip() or 'Keep it concise and actionable.'}"
        )
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        request_json: Dict[str, Any] = {
            "model": self.openai_model,
            "instructions": system_prompt if use_browsing else system_prompt + " No internet browsing is allowed.",
            "input": json.dumps(payload, ensure_ascii=False),
            "temperature": 0.2,
        }
        if use_browsing:
            request_json["tools"] = [{"type": "web_search_preview"}]
        if str(self.openai_model or "").strip().lower().startswith("gpt-5"):
            request_json["reasoning"] = {"effort": "low"}

        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=request_json,
            timeout=90 if use_browsing else 60,
        )
        response.raise_for_status()
        content = self._extract_responses_output_text(response.json())
        if not content:
            raise RuntimeError("OpenAI Responses API returned no text output")
        parsed = self._extract_json_content(content)
        close_issue_raw = parsed.get("close_issue", False)
        close_issue = bool(close_issue_raw)
        if isinstance(close_issue_raw, str):
            close_issue = close_issue_raw.strip().lower() in {"true", "1", "yes", "y", "si", "sí"}
        formatted_comment = str(parsed.get("comment", "")).strip() if include_comment else ""
        warnings = self._normalize_draft_warnings(parsed.get("warnings", {}))
        if include_comment:
            formatted_comment = self._format_issue_comment(
                comment=formatted_comment,
                close_issue=close_issue,
                user_input=user_input,
            )
        return {
            "title": str(parsed.get("title", "")).strip(),
            "description": str(parsed.get("description", "")).strip(),
            "steps_to_reproduce": self._coerce_multiline_text(
                parsed.get("steps_to_reproduce", "")
            ),
            "comment": formatted_comment,
            "close_issue": close_issue,
            "warnings": warnings,
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
        enrich_links: bool = False,
    ) -> Dict[str, Any]:
        self._maybe_weekly_cleanup()
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
            enrich_links=bool(enrich_links),
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
        draft_warnings = self._empty_draft_warnings()
        if as_new_feature:
            enrichment: Dict[str, str] = {}
            if enrich_links:
                enrichment_urls = self._extract_enrichment_urls(user_input)
                self._debug(
                    "New feature link enrichment evaluated",
                    requested=bool(enrich_links),
                    candidate_urls=len(enrichment_urls),
                    repo=repo,
                )
                if enrichment_urls:
                    try:
                        enriched = self._enrich_new_feature_from_links(user_input=user_input, repo=repo, urls=enrichment_urls)
                        enrichment = {
                            key: value
                            for key, value in dict(enriched.get("fields", {})).items()
                            if str(value or "").strip()
                        }
                        for warning in enriched.get("warnings", []) if isinstance(enriched.get("warnings", []), list) else []:
                            text = str(warning or "").strip()
                            if text:
                                self._append_draft_warning_message(draft_warnings, "source", text)
                    except Exception as err:
                        message = "No se ha podido enriquecer la solicitud desde las URLs aportadas."
                        self._append_draft_warning_message(draft_warnings, "source", message)
                        self.logger.warning("Issue flow: %s", message)
                else:
                    self._append_draft_warning_message(
                        draft_warnings,
                        "source",
                        DRAFT_WARNING_MESSAGES["source"]["no_valid_external_links"],
                    )
            generated_input = self._build_new_feature_description(
                enrichment.pop("info", user_input) or user_input,
                enrichment=enrichment,
            )

        generated = self._call_openai_issue_writer(
            user_input=generated_input,
            include_comment=include_comment,
            issue_type=issue_type,
            repo=repo,
            unit=unit,
            comment_issue_number=comment_issue_number,
            is_new_feature=as_new_feature,
        )
        normalized_generated_warnings = self._normalize_draft_warnings(generated.get("warnings", {}))
        for group in DEFAULT_DRAFT_WARNING_GROUPS:
            for message in normalized_generated_warnings.get(group, []):
                self._append_draft_warning_message(draft_warnings, group, message)
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
            title_text = re.sub(r"^\s*\[(?:MEJORA|ENHACEMENT|ENHANCEMENT)\]\s*", "", title_text, flags=re.I).strip()
            generated["title"] = f"[ENHACEMENT] {title_text}" if title_text else "[ENHACEMENT]"
        if repo == "frontend" and issue_type == "task":
            title_text = generated["title"].strip()
            generated["title"] = title_text if title_text.upper().startswith("[TASK]") else f"[TASK] {title_text}"
        if repo == "backend" and issue_type in {"bug", "feature", "task", "enhancement"}:
            title_text = generated["title"].strip()
            title_text = re.sub(
                r"^\s*\[(?:BUG|FEATURE|TASK|ENHACEMENT|ENHANCEMENT)\]\s*",
                "",
                title_text,
                flags=re.I,
            ).strip()
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
            "draft_warnings": draft_warnings,
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
            "enrich_links": bool(enrich_links),
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
        self._maybe_weekly_cleanup()
        if not self._run_lock.acquire(blocking=False):
            active_run_id = str(self._active_run_id or "").strip()
            self.logger.warning(
                "Issue flow submit requested while another run is active (active_run_id=%s)",
                active_run_id or "unknown",
            )
            # The UI can occasionally fire a second submit while the first run is
            # already finishing. Give the lock a short grace window before failing.
            if not self._run_lock.acquire(timeout=4):
                raise RuntimeError(
                    f"Issue flow already running (active_run_id={active_run_id or 'unknown'})"
                )
            self.logger.info(
                "Issue flow: acquired run lock after short retry window (previous_active_run_id=%s)",
                active_run_id or "unknown",
            )

        run_id = self._resolve_submit_run_id(issue)
        run_dir = self._artifact_dir("issue_flow", run_id)
        artifacts: Dict[str, Dict[str, str]] = {}
        page = None
        self._active_run_id = run_id

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
                self._playwright_step("Page loaded", repo=repo, issue_type=issue_type)

                try:
                    if issue.get("include_comment") and str(issue.get("comment_issue_number", "")).strip():
                        self._playwright_step("Flow comment")
                        self._debug(
                            "Executing comment mode flow",
                            repo=repo,
                            issue_number=str(issue.get("comment_issue_number", "")).strip(),
                            close_issue=bool(issue.get("close_issue_on_comment")),
                        )
                        self._submit_issue_comment(page, issue)
                    elif repo == "management" and issue.get("as_third_party"):
                        self._playwright_step("Flow management third-party")
                        self._debug("Executing management third-party flow")
                        self._submit_management_third_party_issue(page, issue)
                    elif repo == "management" and issue.get("as_new_feature"):
                        self._playwright_step("Flow management new-feature")
                        self._debug("Executing management new-feature flow")
                        self._submit_management_feature_issue(page, issue)
                    elif repo == "frontend":
                        self._playwright_step("Flow frontend")
                        self._debug("Executing frontend issue flow", issue_type=issue_type)
                        self._submit_frontend_issue(page, issue)
                    elif repo == "backend" and issue_type in {"bug", "feature", "task", "enhancement", "blockchain", "exchange"}:
                        self._playwright_step("Flow backend", issue_type=issue_type)
                        self._debug("Executing backend issue flow", issue_type=issue_type)
                        self._submit_backend_issue(page, issue)
                    else:
                        self._playwright_step("Flow generic")
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
            self._active_run_id = ""
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
        target_text = str(text or "").strip()
        exact_match = re.compile(rf"^{re.escape(target_text)}$", re.IGNORECASE)
        partial_match = re.compile(re.escape(target_text), re.IGNORECASE)
        candidates = [
            page.locator("li[role='option']").filter(has_text=exact_match).first,
            page.locator("li[role='menuitem']").filter(has_text=exact_match).first,
            page.locator("button[role='option']").filter(has_text=exact_match).first,
            page.locator("li[role='option']").filter(has_text=partial_match).first,
            page.locator("li[role='menuitem']").filter(has_text=partial_match).first,
            page.locator("button[role='option']").filter(has_text=partial_match).first,
        ]

        last_error: Optional[Exception] = None
        for option in candidates:
            try:
                option.wait_for(state="visible", timeout=timeout_ms)
                selected = option.get_attribute("aria-selected")
                if always_click or selected != "true":
                    try:
                        option.click(timeout=timeout_ms)
                    except Exception:
                        option.click(timeout=timeout_ms, force=True)
                return
            except Exception as err:
                last_error = err
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Option not found: {text}")

    def _click_single_visible_option(self, page, timeout_ms: int = 6000) -> bool:
        selectors = [
            "li[role='option']",
            "li[role='menuitem']",
            "button[role='option']",
        ]
        visible_candidates = []
        seen_keys = set()

        for selector in selectors:
            locator = page.locator(selector)
            try:
                total = min(locator.count(), 12)
            except Exception:
                total = 0
            for idx in range(total):
                option = locator.nth(idx)
                try:
                    if not option.is_visible():
                        continue
                    text = str(option.inner_text() or "").strip()
                    if not text:
                        continue
                    key = (selector, text.lower())
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    visible_candidates.append(option)
                except Exception:
                    continue

        if len(visible_candidates) != 1:
            return False

        try:
            visible_candidates[0].click(timeout=timeout_ms)
        except Exception:
            visible_candidates[0].click(timeout=timeout_ms, force=True)
        return True

    @staticmethod
    def _dismiss_open_overlays(page) -> None:
        # Primer portal overlays can stay open and intercept pointer events in following clicks.
        # Send Escape a couple of times to reliably close active dropdown/picker panels.
        for _ in range(2):
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            try:
                page.wait_for_timeout(150)
            except Exception:
                pass

    @staticmethod
    def _click_locator_resilient(locator, timeout_ms: int = 5000) -> None:
        locator.wait_for(state="visible", timeout=timeout_ms)
        try:
            locator.click(timeout=timeout_ms)
        except Exception:
            locator.click(timeout=timeout_ms, force=True)

    def _fill_issue_title(self, page, title: str) -> None:
        title_text = str(title or "").strip()
        if not title_text or title_text == "[NEW]":
            raise RuntimeError("Generated issue title is empty")
        title_input = page.locator('input[aria-label="Add a title"], input[placeholder="Title"]').first
        title_input.wait_for(state="visible", timeout=8000)
        title_input.fill("")
        title_input.fill(title_text)
        try:
            current_value = str(title_input.input_value(timeout=1200) or "").strip()
        except Exception:
            return
        if current_value != title_text:
            self.logger.warning(
                "Issue flow: title fill verification mismatch; retrying (expected_length=%s, actual_length=%s)",
                len(title_text),
                len(current_value),
            )
            title_input.fill("")
            title_input.fill(title_text)
            try:
                current_value = str(title_input.input_value(timeout=1200) or "").strip()
            except Exception:
                current_value = title_text
        if current_value != title_text:
            raise RuntimeError("Issue title remained empty after fill")

    def _open_project_field_button(self, page, label: str, timeout_ms: int = 5000) -> None:
        last_error: Optional[Exception] = None
        for _ in range(3):
            attempt = _ + 1
            self._playwright_step(f"Open {label} ({attempt}/3)")
            self._dismiss_open_overlays(page)
            try:
                # Re-expand project metadata if it got collapsed after previous interactions.
                self._ensure_project_post_fields_visible(page)
            except Exception:
                pass
            button = page.locator("button").filter(has_text=label).first
            try:
                button.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                self._debug("Opening project field", field=label, attempt=attempt, forced_click="false")
                self._click_locator_resilient(button, timeout_ms=timeout_ms)
                page.wait_for_timeout(220)
                self._playwright_step(f"{label} opened")
                return
            except Exception as err:
                self._debug("Retry opening project field", field=label, attempt=attempt, forced_click="true")
                last_error = err
                page.wait_for_timeout(180)
                continue
        if last_error is not None:
            self._playwright_step(f"{label} failed")
            raise last_error

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
        self._playwright_step("Click Create", repo=repo, issue_type=issue_type)
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
                self._playwright_step("Retry create", key=shortcut)
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
        self._playwright_step("Create done", url=self._sanitize_url_for_log(page.url))
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
            page.wait_for_timeout(1200)

            repo_search_term, selection_targets = self._parent_repo_search_strategy(parent_repo)
            repo_search = page.locator(
                'input[aria-label*="repository" i], input[placeholder*="repository" i], input[aria-label*="Select repository" i]'
            ).first
            if repo_search.count() > 0:
                repo_search.wait_for(state="visible", timeout=7000)
                try:
                    repo_search.click(timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(250)
                try:
                    repo_search.fill("", timeout=3000)
                except Exception:
                    pass
                repo_search.fill(repo_search_term, timeout=7000)
                page.wait_for_timeout(2200)

            selection_error: Optional[Exception] = None
            selected_parent_repo = False
            for selection_target in selection_targets:
                for attempt in range(2):
                    try:
                        self._click_option_by_text(
                            page,
                            selection_target,
                            always_click=True,
                            timeout_ms=9000,
                        )
                        selected_parent_repo = True
                        break
                    except Exception as err:
                        selection_error = err
                        if attempt == 0 and repo_search.count() > 0:
                            try:
                                repo_search.fill("", timeout=3000)
                            except Exception:
                                pass
                            repo_search.fill(repo_search_term, timeout=7000)
                            page.wait_for_timeout(2200)
                        continue
                if selected_parent_repo:
                    break

            if not selected_parent_repo and repo_search.count() > 0:
                try:
                    selected_parent_repo = self._click_single_visible_option(
                        page,
                        timeout_ms=9000,
                    )
                except Exception as err:
                    selection_error = err

            if not selected_parent_repo:
                if selection_error is not None:
                    raise selection_error
                raise RuntimeError(f"Unable to select parent repository: {parent_repo}")

            page.wait_for_timeout(3500)
            issue_search = page.locator('input[aria-label="Search issues"], input[placeholder*="Search issues"]').first
            issue_search.wait_for(state="visible", timeout=15000)
            try:
                issue_search.click(timeout=3000)
            except Exception:
                pass
            issue_search.fill(parent_issue_number, timeout=9000)
            page.wait_for_timeout(5500)
            self._click_option_by_text(
                page,
                f"#{parent_issue_number}",
                always_click=True,
                timeout_ms=9000,
            )
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

    @staticmethod
    def _parent_repo_search_strategy(parent_repo: str) -> tuple[str, List[str]]:
        parent_repo_text = str(parent_repo or "").strip()
        parent_repo_short = parent_repo_text.split("/")[-1].strip()
        repo_search_term = (
            "mana"
            if parent_repo_short.lower() == "management"
            else (parent_repo_short or parent_repo_text)
        )
        selection_targets = (
            [parent_repo_short, parent_repo_text]
            if parent_repo_short.lower() == "management"
            else [parent_repo_text, parent_repo_short]
        )
        deduped_targets: List[str] = []
        for value in selection_targets:
            text = str(value or "").strip()
            if text and text not in deduped_targets:
                deduped_targets.append(text)
        return repo_search_term, deduped_targets

    def _ensure_project_post_fields_visible(self, page) -> bool:
        # GitHub project metadata can be collapsed right after create.
        # Open the chevron container before trying Status/Unit/Team/Sprint/Date.
        business_unit_btn = page.locator("button").filter(has_text=re.compile(r"Business Unit", re.I))
        toggle_icons = page.locator("svg.octicon-chevron-down, svg.octicon-triangle-down")

        def _business_unit_is_visible() -> bool:
            if business_unit_btn.count() == 0:
                return False
            try:
                return bool(business_unit_btn.first.is_visible())
            except Exception:
                return False

        if _business_unit_is_visible():
            return True

        candidate_groups = []
        project_name = str(self.project_name or "").strip()
        if project_name:
            project_pattern = re.compile(rf"\b{re.escape(project_name)}\b", re.I)
            projects_section = (
                page.locator("div,section,aside")
                .filter(has_text=re.compile(r"\bProjects\b", re.I))
                .filter(has_text=project_pattern)
            )
            candidate_groups.append(
                projects_section
                .locator("button[data-component='IconButton'][aria-expanded='false']")
                .filter(has=toggle_icons)
            )
            candidate_groups.append(
                projects_section.locator("button[data-component='IconButton']").filter(has=toggle_icons)
            )
            # Focus first on the project status row itself (most stable anchor after issue creation).
            candidate_groups.append(
                page.locator(
                    "xpath=//span[normalize-space()='Status']/ancestor::*[self::div or self::section or self::aside][1]"
                )
                .locator("button[data-component='IconButton'][aria-expanded='false']")
                .filter(has=toggle_icons)
            )
            candidate_groups.append(
                page.locator(
                    "xpath=//span[normalize-space()='Status']/ancestor::*[self::div or self::section or self::aside][1]"
                )
                .locator("button[data-component='IconButton']")
                .filter(has=toggle_icons)
            )
            candidate_groups.append(
                page.locator("div,section,aside")
                .filter(has_text=project_pattern)
                .filter(has_text=re.compile(r"\bStatus\b", re.I))
                .locator("button[data-component='IconButton'][aria-expanded='false']")
                .filter(has=toggle_icons)
            )
            candidate_groups.append(
                page.locator("div,section,aside")
                .filter(has_text=project_pattern)
                .filter(has_text=re.compile(r"\bStatus\b", re.I))
                .locator("button[data-component='IconButton']")
                .filter(has=toggle_icons)
            )
        else:
            # Front-like explicit expansion step as fallback when project name is unavailable.
            # Click project chevrons (down arrows) after Create to reveal hidden project fields.
            candidate_groups.append(
                page.locator("button[data-component='IconButton'][aria-expanded='false']").filter(has=toggle_icons)
            )
            candidate_groups.append(
                page.locator("button[data-component='IconButton']").filter(has=toggle_icons)
            )
        candidate_groups.append(page.locator("button[data-component='IconButton'][aria-expanded='false']").filter(has=toggle_icons))
        candidate_groups.append(page.locator("button[data-component='IconButton']").filter(has=toggle_icons))

        for group in candidate_groups:
            try:
                total = min(group.count(), 20)
            except Exception:
                total = 0
            # Prefer lower DOM nodes (sidebar issue fields) before top header controls.
            for idx in range(total - 1, -1, -1):
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
                if _business_unit_is_visible():
                    self._debug("Project post-create fields expanded via fallback chevron group")
                    return True
        return _business_unit_is_visible()

    def _apply_post_creation_fields(
        self, page, unit_label: str, team_label: str = "", status_label: str = "Todo"
    ) -> List[str]:
        # Shared post-create metadata flow used across frontend/backend/management issue variants.
        self._debug("Applying post-create fields", status=status_label, unit=unit_label, team=team_label or "-")
        self._playwright_step("Post-create start")
        warnings: List[str] = []
        field_results: Dict[str, bool] = {
            "status": False,
            "business_unit": False,
            "team": not bool(team_label),
            "sprint": False,
            "creation_date": False,
        }
        project_fields_collapsed_initially = not self._ensure_project_post_fields_visible(page)
        if project_fields_collapsed_initially:
            self._debug("Post-create project fields initially collapsed; running retries before warning")

        status_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                self._playwright_step(f"Set status ({attempt + 1}/3)", status=status_label)
                if attempt == 0:
                    self._ensure_project_post_fields_visible(page)
                    page.wait_for_timeout(500)
                elif attempt == 1:
                    self._dismiss_open_overlays(page)
                    status_button = page.locator("button").filter(has_text=re.compile(r"Status|Todo|Backlog", re.I)).first
                    self._click_locator_resilient(status_button, timeout_ms=4000)
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
                field_results["status"] = True
                self._playwright_step("Status ok", status=status_label)
                self._dismiss_open_overlays(page)
                break
            except Exception as err:
                status_error = err
                self._dismiss_open_overlays(page)
                continue

        if status_error is not None:
            message = f"Post-create status selection failed after retries: {status_error}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)
        self._dismiss_open_overlays(page)

        try:
            self._playwright_step("Set business unit", unit=unit_label)
            self._open_project_field_button(page, "Business Unit", timeout_ms=5000)
            self._click_option_by_text(page, unit_label)
            field_results["business_unit"] = True
            self._playwright_step("Business unit ok", unit=unit_label)
            self._dismiss_open_overlays(page)
        except Exception as err:
            message = f"Post-create business unit failed (unit={unit_label}): {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)
            self._playwright_step("Business unit failed", unit=unit_label)
            self._dismiss_open_overlays(page)

        if team_label:
            try:
                page.wait_for_timeout(300)
                self._playwright_step("Set team", team=team_label)
                self._open_project_field_button(page, "Team", timeout_ms=5000)
                self._click_option_by_text(page, team_label)
                field_results["team"] = True
                self._playwright_step("Team ok", team=team_label)
                self._dismiss_open_overlays(page)
            except Exception as err:
                message = f"Post-create team failed (team={team_label}): {err}"
                warnings.append(message)
                self.logger.warning("Issue flow: %s", message)
                self._playwright_step("Team failed", team=team_label)
                self._dismiss_open_overlays(page)

        try:
            page.wait_for_timeout(300)
            self._playwright_step("Set sprint", sprint="Current")
            self._open_project_field_button(page, "Sprint", timeout_ms=5000)
            current_option = page.locator("li[role='option']").filter(has_text="Current").first
            current_option.wait_for(state="visible", timeout=5000)
            current_option.click(timeout=5000)
            field_results["sprint"] = True
            self._playwright_step("Sprint ok", sprint="Current")
            self._dismiss_open_overlays(page)
        except Exception as err:
            message = f"Post-create sprint failed (Current): {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)
            self._playwright_step("Sprint failed", sprint="Current")
            self._dismiss_open_overlays(page)

        try:
            page.wait_for_timeout(300)
            self._playwright_step("Set creation date", date="Today")
            self._open_project_field_button(page, "Creation Date", timeout_ms=5000)
            target_date = datetime.now().strftime("%m/%d/%Y")
            day_cell = page.locator(f'div[role="gridcell"][data-date="{target_date}"]').first
            if day_cell.count() > 0:
                day_cell.click(timeout=5000)
            else:
                page.locator('div[role="gridcell"][aria-selected="true"]').first.click(timeout=5000)
            field_results["creation_date"] = True
            self._playwright_step("Creation date ok", date=target_date)
            self._dismiss_open_overlays(page)
        except Exception as err:
            message = f"Post-create creation date failed: {err}"
            warnings.append(message)
            self.logger.warning("Issue flow: %s", message)
            self._playwright_step("Creation date failed", date="Today")
            self._dismiss_open_overlays(page)

        if project_fields_collapsed_initially:
            if warnings:
                message = "Post-create project fields are still collapsed (Business Unit not visible)"
                warnings.append(message)
                self.logger.warning("Issue flow: %s", message)
            else:
                self._debug("Post-create project fields recovered; no warning emitted")

        self.logger.info(
            "Issue flow: post-create fields result (status=%s, business_unit=%s, team=%s, sprint=%s, creation_date=%s)",
            "ok" if field_results["status"] else "fail",
            "ok" if field_results["business_unit"] else "fail",
            "ok" if field_results["team"] else "fail",
            "ok" if field_results["sprint"] else "fail",
            "ok" if field_results["creation_date"] else "fail",
        )

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

    def _remove_frontend_task_template_label(self, page) -> Optional[str]:
        try:
            self._debug("Removing frontend task template label", label="enhancement")
            self._dismiss_open_overlays(page)
            edit_labels_button = page.locator("button").filter(has_text="Edit Labels").first
            self._click_locator_resilient(edit_labels_button, timeout_ms=5000)
            page.wait_for_timeout(250)
            labels_filter = page.locator('input[aria-label="Filter labels"]').first
            if labels_filter.count() > 0:
                labels_filter.wait_for(state="visible", timeout=2000)
                labels_filter.fill("enhancement")
                page.wait_for_timeout(200)
            self._click_option_by_text(
                page,
                "enhancement",
                always_click=True,
                timeout_ms=3500,
            )
            self._dismiss_open_overlays(page)
            self._debug("Frontend task template label removed", label="enhancement")
            return None
        except Exception as err:
            warning = f"Frontend task label cleanup failed: {err}"
            self.logger.warning("Issue flow: %s", warning)
            return warning

    def _apply_issue_type(self, page, issue_type: str) -> Optional[str]:
        # Force GitHub issue type to match the requested workflow semantics.
        mapping = {
            "bug": "Bug",
            "feature": "Feature",
            "task": "Task",
            "enhancement": "Task",
        }
        resolved_type = mapping.get(str(issue_type or "").strip().lower(), "Feature")
        self._debug("Applying issue type", requested=issue_type, resolved=resolved_type)

        option_exact = re.compile(rf"^{re.escape(resolved_type)}$", re.I)
        option_loose = re.compile(re.escape(resolved_type), re.I)
        last_error: Optional[Exception] = None

        def _click_issue_type_option(timeout_ms: int = 4000) -> bool:
            candidates = [
                page.locator("li[role='option']").filter(has_text=option_exact).first,
                page.locator("li[role='menuitem']").filter(has_text=option_exact).first,
                page.locator("button[role='option']").filter(has_text=option_exact).first,
                page.locator("li[role='option']").filter(has_text=option_loose).first,
                page.locator("li[role='menuitem']").filter(has_text=option_loose).first,
                page.locator("button[role='option']").filter(has_text=option_loose).first,
            ]
            for candidate in candidates:
                try:
                    candidate.wait_for(state="visible", timeout=timeout_ms)
                    selected = candidate.get_attribute("aria-selected")
                    if selected != "true":
                        candidate.click(timeout=timeout_ms)
                    return True
                except Exception:
                    continue
            return False

        for attempt in range(3):
            try:
                self._dismiss_open_overlays(page)
                edit_type_button = page.locator("button").filter(has_text="Edit Type").first
                self._click_locator_resilient(edit_type_button, timeout_ms=5000)
                page.wait_for_timeout(250)
            except Exception as err:
                last_error = err
                continue

            try:
                if _click_issue_type_option(timeout_ms=4000):
                    self._dismiss_open_overlays(page)
                    self._debug("Issue type applied", resolved=resolved_type, attempt=attempt + 1, mode="direct")
                    return None
            except Exception as err:
                last_error = err

            try:
                filter_input = page.locator(
                    'input[aria-label="Choose an option"], input[placeholder*="Choose an option" i]'
                ).first
                if filter_input.count() > 0:
                    filter_input.wait_for(state="visible", timeout=2000)
                    filter_input.fill(resolved_type, timeout=2500)
                    page.wait_for_timeout(450)
                    if _click_issue_type_option(timeout_ms=3500):
                        self._dismiss_open_overlays(page)
                        self._debug("Issue type applied", resolved=resolved_type, attempt=attempt + 1, mode="filtered")
                        return None
                else:
                    # Some variants do not render a filter input in the type picker.
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(250)
                    if _click_issue_type_option(timeout_ms=2500):
                        self._dismiss_open_overlays(page)
                        self._debug("Issue type applied", resolved=resolved_type, attempt=attempt + 1, mode="keyboard")
                        return None
            except Exception as err:
                last_error = err

            try:
                # If the current type chip already shows the desired value, treat as success.
                type_chip = page.locator("button").filter(has_text=re.compile(rf"\bType\b.*\b{re.escape(resolved_type)}\b", re.I)).first
                if type_chip.count() > 0 and type_chip.is_visible():
                    self._dismiss_open_overlays(page)
                    self._debug("Issue type already selected", resolved=resolved_type, attempt=attempt + 1)
                    return None
            except Exception:
                pass

            self._dismiss_open_overlays(page)
            page.wait_for_timeout(220)

        warning = f"Issue type selection failed (type={resolved_type}): {last_error}"
        self.logger.warning("Issue flow: %s", warning)
        return warning

    def _apply_management_epic_new_feature(self, page) -> None:
        self._debug("Applying management epic", epic="NEW FEATURES REQUEST")
        try:
            self._playwright_step("Set epic", epic="NEW FEATURES REQUEST")
            self._dismiss_open_overlays(page)
            self._open_project_field_button(page, "Epic", timeout_ms=5000)
            epic_search = page.locator('input[aria-label="Choose an option"]').first
            epic_search.fill("NEW FEATURE")
            page.wait_for_timeout(1200)
            self._click_option_by_text(page, "NEW FEATURES REQUEST")
            self._playwright_step("Epic ok", epic="NEW FEATURES REQUEST")
            self._dismiss_open_overlays(page)
        except Exception as err:
            self._playwright_step("Epic failed", epic="NEW FEATURES REQUEST")
            self.logger.warning("Issue flow: failed to set epic 'NEW FEATURES REQUEST': %s", err)
            self._dismiss_open_overlays(page)

    def _submit_management_feature_issue(self, page, issue: Dict[str, Any]) -> None:
        # Management "new feature" flow: blank issue + template body + backlog metadata + epic selection.
        self._debug("Starting management new-feature submit flow")
        title = str(issue.get("title", "")).strip()
        if issue.get("as_new_feature") and not title.upper().startswith("[NEW]"):
            title = f"[NEW] {title}"
        description = str(issue.get("description", "")).strip()

        self._fill_issue_title(page, title)
        markdown_area = page.locator('textarea[aria-label="Markdown value"]').first
        markdown_area.fill("")
        markdown_area.fill(description)

        self._open_projects_editor(page)
        self._ensure_project_selected(page)
        self._fill_issue_title(page, title)

        self._click_create_and_wait_created(
            page,
            repo="management",
            issue_type="feature",
            issue_id=str(issue.get("issue_id", "")),
        )

        type_warning = self._apply_issue_type(page, "feature")
        if type_warning:
            self._append_issue_warning(issue, type_warning)
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

        type_warning = self._apply_issue_type(page, issue_type)
        if type_warning:
            self._append_issue_warning(issue, type_warning)
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
        if issue_type == "enhancement":
            title = re.sub(r"^\s*\[(?:MEJORA|ENHACEMENT|ENHANCEMENT)\]\s*", "", title, flags=re.I).strip()
            title = f"[ENHACEMENT] {title}" if title else "[ENHACEMENT]"
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

        if issue_type == "task":
            # Task reuses the enhancement template, so the issue type must be corrected after create.
            type_warning = self._apply_issue_type(page, "task")
            if type_warning:
                self._append_issue_warning(issue, type_warning)
            label_warning = self._remove_frontend_task_template_label(page)
            if label_warning:
                self._append_issue_warning(issue, label_warning)

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

    def mark_run_resolved(self, run_id: str) -> Dict[str, Any]:
        run_id_text = str(run_id or "").strip()
        if not run_id_text:
            return {"ok": False, "reason": "missing run_id"}
        # Keep the operator acknowledgement in the same event stream as the run.
        self._append_event("issue_run_resolved", run_id=run_id_text)
        return {"ok": True, "run_id": run_id_text}

    def get_events(self, limit: int = 200, run_id: str = "", event: str = "") -> Dict[str, Any]:
        if not self.events_path.exists():
            return {"events": []}
        run_id_text = str(run_id or "").strip()
        event_text = str(event or "").strip()
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        items: List[Dict[str, Any]] = []
        for line in lines[-max(1, min(limit, 2000)) :]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_text and str(payload.get("event", "")).strip() != event_text:
                continue
            if run_id_text and str((payload.get("meta", {}) or {}).get("run_id", "")).strip() != run_id_text:
                continue
            items.append(payload)
        return {"events": items}
