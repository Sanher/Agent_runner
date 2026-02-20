import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from agents.answers_agent.service import AnswersAgentService
from agents.email_agent.service import EmailAgentService
from agents.issue_agent.service import IssueAgentService
from agents.support_guidance import (
    DEFAULT_SUPPORT_MARKETING_URL,
    DEFAULT_SUPPORT_TELEGRAM_URL,
    DEFAULT_SUPPORT_USER_URL_PREFIX,
)
from agents.workday_agent.service import WorkdayAgentService
from routers.answers_agent import create_answers_router
from routers.email_agent import create_email_router
from routers.issue_agent import create_issue_router
from routers.ui import create_ui_router
from routers.workday_agent import create_workday_router


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("agent_runner")

APP = FastAPI(title="Agent Runner")

def _resolve_data_dir() -> Path:
    """Resuelve directorio de datos persistente con override por ENV."""
    requested = Path(os.getenv("AGENT_RUNNER_DATA_DIR", "/data")).expanduser()
    try:
        requested.mkdir(parents=True, exist_ok=True)
        return requested.resolve()
    except OSError:
        # Fallback local para entornos donde /data no es escribible.
        fallback = (Path.cwd() / ".data").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "No se pudo usar DATA_DIR=%s; usando fallback local %s",
            requested,
            fallback,
        )
        return fallback


# Directorio persistente para runtime.
DATA_DIR = _resolve_data_dir()


def _load_addon_options() -> Dict[str, Any]:
    """Carga opciones desde DATA_DIR/options.json cuando existe."""
    options_path = DATA_DIR / "options.json"
    if not options_path.exists():
        logger.info("No existe options.json; se usarán variables de entorno o valores por defecto")
        return {}
    try:
        options = json.loads(options_path.read_text(encoding="utf-8"))
        logger.info("Opciones cargadas desde %s", options_path)
        return options
    except json.JSONDecodeError:
        logger.warning("options.json inválido; se usarán valores por defecto")
        return {}
    except Exception:
        logger.exception("No se pudo leer %s; se usarán valores por defecto", options_path)
        return {}


ADDON_OPTIONS = _load_addon_options()


def _setting(name: str, default: str = "") -> str:
    """Resuelve configuración priorizando ENV y luego options.json."""
    env_name = name.upper()
    if env_name in os.environ:
        return os.getenv(env_name, default)
    return str(ADDON_OPTIONS.get(name.lower(), default))


def _setting_with_aliases(name: str, aliases: list[str], default: str = "") -> str:
    """Resuelve setting por clave principal y aliases (retrocompatibilidad)."""
    value = _setting(name, "")
    if value:
        return value
    for alias in aliases:
        value = _setting(alias, "")
        if value:
            return value
    return default


def _setting_values_with_aliases(name: str, aliases: list[str]) -> List[str]:
    """Resuelve todos los valores no vacíos para clave principal + aliases."""
    keys = [name, *aliases]
    values: List[str] = []
    for key in keys:
        env_name = key.upper()
        if env_name in os.environ:
            value = str(os.getenv(env_name, "")).strip()
        else:
            value = str(ADDON_OPTIONS.get(key.lower(), "")).strip()
        if value and value not in values:
            values.append(value)
    return values


def _setting_int(name: str, default: int) -> int:
    raw = _setting(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning("Valor inválido para %s=%s; usando %s", name, raw, default)
        return default


def _normalize_email_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [item.strip().lower() for item in raw.split(",") if item.strip()]
    return []


def _setting_email_whitelist(name: str, aliases: list[str]) -> List[str]:
    env_name = name.upper()
    if env_name in os.environ:
        return _normalize_email_list(os.getenv(env_name, ""))

    value = ADDON_OPTIONS.get(name.lower())
    if value is not None:
        return _normalize_email_list(value)

    for alias in aliases:
        alias_env = alias.upper()
        if alias_env in os.environ:
            return _normalize_email_list(os.getenv(alias_env, ""))
        value = ADDON_OPTIONS.get(alias.lower())
        if value is not None:
            return _normalize_email_list(value)

    return []


# Compartido
JOB_SECRET = _setting("job_secret", "")

# Agente web (workday)
WORKDAY_TARGET_URL = _setting_with_aliases("workday_target_url", ["target_url"], "")
WORKDAY_SSO_EMAIL = _setting_with_aliases("workday_sso_email", ["sso_email"], "")
WORKDAY_TIMEZONE = _setting_with_aliases(
    "workday_timezone",
    ["timezone", "tz"],
    str(os.getenv("TZ", "")).strip() or "UTC",
)
WORKDAY_WEBHOOK_START_URL = _setting_with_aliases(
    "workday_webhook_start_url",
    ["workday_webhook_status_url", "hass_webhook_url_status"],
    "",
)
WORKDAY_WEBHOOK_FINAL_URL = _setting_with_aliases(
    "workday_webhook_final_url", ["hass_webhook_url_final"], ""
)
WORKDAY_WEBHOOK_START_BREAK_URL = _setting("workday_webhook_start_break_url", "")
WORKDAY_WEBHOOK_STOP_BREAK_URL = _setting("workday_webhook_stop_break_url", "")

# Email agent (email + IMAP)
EMAIL_OPENAI_API_KEY = _setting_with_aliases("email_openai_api_key", ["openai_api_key"], "")
EMAIL_OPENAI_MODEL = _setting_with_aliases("email_openai_model", ["openai_model"], "gpt-4o-mini")
EMAIL_IMAP_EMAIL = _setting_with_aliases("email_imap_email", ["gmail_email"], "")
EMAIL_IMAP_PASSWORD = _setting_with_aliases("email_imap_password", ["gmail_app_password"], "")
EMAIL_IMAP_HOST = _setting_with_aliases("email_imap_host", ["gmail_imap_host"], "imap.gmail.com")
EMAIL_WEBHOOK_NOTIFY_URL = _setting_with_aliases(
    "email_webhook_notify_url",
    ["email_agent_webhook_notify"],
    WORKDAY_WEBHOOK_START_URL,
)
EMAIL_ALLOWED_FROM_WHITELIST = _setting_email_whitelist(
    "email_allowed_from_whitelist",
    ["email_allowed_from"],
)
EMAIL_BACKGROUND_INTERVAL_HOURS = max(1, _setting_int("email_background_interval_hours", 4))
EMAIL_SMTP_EMAIL = _setting_with_aliases(
    "email_smtp_email",
    ["email_imap_email", "gmail_email"],
    EMAIL_IMAP_EMAIL,
)
EMAIL_SMTP_PASSWORD = _setting_with_aliases(
    "email_smtp_password",
    ["email_imap_password", "gmail_app_password"],
    EMAIL_IMAP_PASSWORD,
)
EMAIL_SMTP_HOST = _setting_with_aliases("email_smtp_host", ["gmail_smtp_host"], "smtp.gmail.com")
EMAIL_SMTP_PORT = max(1, _setting_int("email_smtp_port", 465))
EMAIL_DEFAULT_FROM = _setting_with_aliases(
    "email_default_from",
    ["email_sender", "email_smtp_email", "email_imap_email", "gmail_email"],
    EMAIL_SMTP_EMAIL,
)
EMAIL_DEFAULT_CC = _setting_with_aliases("email_default_cc", ["email_cc"], "")
EMAIL_SIGNATURE_ASSETS_DIR = _setting("email_signature_assets_dir", "/config/media/signature")
SUPPORT_TELEGRAM_URL = _setting_with_aliases(
    "support_telegram_url",
    ["telegram_support_url"],
    DEFAULT_SUPPORT_TELEGRAM_URL,
)
SUPPORT_MARKETING_URL = _setting_with_aliases(
    "support_marketing_url",
    ["marketing_url"],
    DEFAULT_SUPPORT_MARKETING_URL,
)
SUPPORT_USER_URL_PREFIX = _setting_with_aliases(
    "support_user_url_prefix",
    ["user_url_prefix"],
    DEFAULT_SUPPORT_USER_URL_PREFIX,
)

# Issue agent (OpenAI + Playwright)
ISSUE_REPO_BASE_URL = _setting("issue_repo_base_url", "")
ISSUE_PROJECT_NAME = _setting("issue_project_name", "")
ISSUE_STORAGE_STATE_PATH = _setting("issue_storage_state_path", "")
ISSUE_OPENAI_API_KEY = _setting_with_aliases("issue_openai_api_key", ["openai_api_key"], "")
ISSUE_OPENAI_MODEL = _setting_with_aliases("issue_openai_model", ["openai_model"], "gpt-4o-mini")
ISSUE_OPENAI_STYLE_LAW = _setting(
    "issue_openai_style_law",
    "Write clear, actionable issues with enough technical context.",
)
ISSUE_WEBHOOK_URL = _setting_with_aliases(
    "issue_webhook_url",
    ["hass_webhook_url_issue"],
    WORKDAY_WEBHOOK_START_URL,
)
ISSUE_REPO_FRONTEND = _setting_with_aliases(
    "issue_repo_frontend",
    ["issue_bug_parent_repo_frontend", "issue_bug_parent_repo_front"],
    "",
)
ISSUE_REPO_BACKEND = _setting_with_aliases(
    "issue_repo_backend",
    ["issue_bug_parent_repo_backend", "issue_bug_parent_repo_back"],
    "",
)
ISSUE_REPO_MANAGEMENT = _setting_with_aliases(
    "issue_repo_management",
    ["issue_bug_parent_repo_management"],
    "",
)
ISSUE_BUG_PARENT_ISSUE_FRONTEND = _setting_with_aliases(
    "issue_bug_parent_issue_frontend",
    ["issue_bug_parent_issue_front"],
    "",
)
ISSUE_BUG_PARENT_ISSUE_BACKEND = _setting_with_aliases(
    "issue_bug_parent_issue_backend",
    ["issue_bug_parent_issue_back"],
    "",
)
ISSUE_BUG_PARENT_ISSUE_MANAGEMENT = _setting("issue_bug_parent_issue_management", "")

# Agente respuestas (Telegram)
DEFAULT_ANSWERS_DATA_DIR = (Path(__file__).resolve().parent / "answers_agent" / "data").resolve()
ANSWERS_DATA_DIR = Path(
    _setting("answers_data_dir", str(DEFAULT_ANSWERS_DATA_DIR))
).expanduser()
ANSWERS_TELEGRAM_BOT_TOKEN = _setting_with_aliases(
    "answers_telegram_bot_token",
    ["telegram_bot_token"],
    "",
)
ANSWERS_OPENAI_API_KEY = _setting_with_aliases(
    "answers_openai_api_key",
    ["openai_api_key"],
    "",
)
ANSWERS_OPENAI_MODEL = _setting_with_aliases(
    "answers_openai_model",
    ["openai_model"],
    "gpt-4o-mini",
)
ANSWERS_REQUEST_TIMEOUT_SECONDS = max(5, _setting_int("answers_request_timeout_seconds", 30))
ANSWERS_TELEGRAM_WEBHOOK_SECRETS = _setting_values_with_aliases(
    "telegram_wehbook_secret",
    ["telegram_webhook_secret", "answers_webhook_secret"],
)
ANSWERS_TELEGRAM_WEBHOOK_SECRET = ANSWERS_TELEGRAM_WEBHOOK_SECRETS[0] if ANSWERS_TELEGRAM_WEBHOOK_SECRETS else ""


def _apply_timezone() -> None:
    """Aplica TZ de proceso para que fechas/ventanas usen hora local."""
    os.environ["TZ"] = WORKDAY_TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()
    logger.info("Timezone aplicada: %s", WORKDAY_TIMEZONE)


_apply_timezone()

workday_service = WorkdayAgentService(
    data_dir=DATA_DIR,
    target_url=WORKDAY_TARGET_URL,
    sso_email=WORKDAY_SSO_EMAIL,
    webhook_start_url=WORKDAY_WEBHOOK_START_URL,
    webhook_final_url=WORKDAY_WEBHOOK_FINAL_URL,
    webhook_start_break_url=WORKDAY_WEBHOOK_START_BREAK_URL,
    webhook_stop_break_url=WORKDAY_WEBHOOK_STOP_BREAK_URL,
    logger=logger.getChild("workday_agent"),
)

email_service = EmailAgentService(
    data_dir=DATA_DIR,
    openai_api_key=EMAIL_OPENAI_API_KEY,
    openai_model=EMAIL_OPENAI_MODEL,
    gmail_email=EMAIL_IMAP_EMAIL,
    gmail_app_password=EMAIL_IMAP_PASSWORD,
    gmail_imap_host=EMAIL_IMAP_HOST,
    webhook_notify_url=EMAIL_WEBHOOK_NOTIFY_URL,
    smtp_email=EMAIL_SMTP_EMAIL,
    smtp_password=EMAIL_SMTP_PASSWORD,
    smtp_host=EMAIL_SMTP_HOST,
    smtp_port=EMAIL_SMTP_PORT,
    default_from_email=EMAIL_DEFAULT_FROM,
    default_cc_email=EMAIL_DEFAULT_CC,
    default_signature_assets_dir=EMAIL_SIGNATURE_ASSETS_DIR,
    allowed_from_whitelist=EMAIL_ALLOWED_FROM_WHITELIST,
    support_telegram_url=SUPPORT_TELEGRAM_URL,
    support_marketing_url=SUPPORT_MARKETING_URL,
    support_user_url_prefix=SUPPORT_USER_URL_PREFIX,
)

@dataclass(frozen=True)
class AgentModule:
    name: str
    router_factory: Callable[[], Any]
    health_factory: Callable[[], Dict[str, Any]]
    startup_tasks: Tuple[Tuple[str, Callable[[], None]], ...] = ()


issue_service = IssueAgentService(
    data_dir=DATA_DIR,
    repo_base_url=ISSUE_REPO_BASE_URL,
    project_name=ISSUE_PROJECT_NAME,
    storage_state_path=ISSUE_STORAGE_STATE_PATH,
    openai_api_key=ISSUE_OPENAI_API_KEY,
    openai_model=ISSUE_OPENAI_MODEL,
    openai_style_law=ISSUE_OPENAI_STYLE_LAW,
    webhook_url=ISSUE_WEBHOOK_URL,
    bug_parent_repo_by_repo={
        "frontend": ISSUE_REPO_FRONTEND,
        "backend": ISSUE_REPO_BACKEND,
        "management": ISSUE_REPO_MANAGEMENT,
    },
    bug_parent_issue_number_by_repo={
        "frontend": ISSUE_BUG_PARENT_ISSUE_FRONTEND,
        "backend": ISSUE_BUG_PARENT_ISSUE_BACKEND,
        "management": ISSUE_BUG_PARENT_ISSUE_MANAGEMENT,
    },
    logger=logger.getChild("issue_agent"),
)

answers_service = AnswersAgentService(
    data_dir=ANSWERS_DATA_DIR,
    telegram_bot_token=ANSWERS_TELEGRAM_BOT_TOKEN,
    openai_api_key=ANSWERS_OPENAI_API_KEY,
    openai_model=ANSWERS_OPENAI_MODEL,
    request_timeout_seconds=ANSWERS_REQUEST_TIMEOUT_SECONDS,
    telegram_webhook_secret=ANSWERS_TELEGRAM_WEBHOOK_SECRET,
    support_telegram_url=SUPPORT_TELEGRAM_URL,
    support_marketing_url=SUPPORT_MARKETING_URL,
    support_user_url_prefix=SUPPORT_USER_URL_PREFIX,
    logger=logger.getChild("answers_agent"),
)

def _workday_missing_required_config() -> List[str]:
    missing: List[str] = []
    required = {
        "job_secret": JOB_SECRET,
        "workday_target_url": WORKDAY_TARGET_URL,
        "workday_webhook_start_url": WORKDAY_WEBHOOK_START_URL,
        "workday_webhook_final_url": WORKDAY_WEBHOOK_FINAL_URL,
        "workday_webhook_start_break_url": WORKDAY_WEBHOOK_START_BREAK_URL,
        "workday_webhook_stop_break_url": WORKDAY_WEBHOOK_STOP_BREAK_URL,
    }
    for key, value in required.items():
        if not str(value).strip():
            missing.append(key)
    return missing


def _email_missing_required_config() -> List[str]:
    missing: List[str] = []
    required = {
        "email_openai_api_key": EMAIL_OPENAI_API_KEY,
        "email_imap_email": EMAIL_IMAP_EMAIL,
        "email_imap_password": EMAIL_IMAP_PASSWORD,
    }
    for key, value in required.items():
        if not str(value).strip():
            missing.append(key)
    return missing


def _workday_health_payload() -> Dict[str, Any]:
    return {
        "config_valid": len(_workday_missing_required_config()) == 0,
        "missing_required_config": _workday_missing_required_config(),
        "has_target_url": bool(WORKDAY_TARGET_URL),
        "has_sso_email": bool(WORKDAY_SSO_EMAIL),
        "has_webhook_start": bool(WORKDAY_WEBHOOK_START_URL),
        "has_webhook_final": bool(WORKDAY_WEBHOOK_FINAL_URL),
        "has_webhook_start_break": bool(WORKDAY_WEBHOOK_START_BREAK_URL),
        "has_webhook_stop_break": bool(WORKDAY_WEBHOOK_STOP_BREAK_URL),
        "timezone": WORKDAY_TIMEZONE,
        "runtime_phase": workday_service.get_status().get("phase"),
        "runtime_state_file": str(workday_service.runtime_state_path),
        "runtime_events_file": str(workday_service.runtime_events_path),
    }


def _email_health_payload() -> Dict[str, Any]:
    return {
        "config_valid": len(_email_missing_required_config()) == 0,
        "missing_required_config": _email_missing_required_config(),
        "has_openai_api_key": bool(EMAIL_OPENAI_API_KEY),
        "has_openai_model": bool(EMAIL_OPENAI_MODEL),
        "has_imap_email": bool(EMAIL_IMAP_EMAIL),
        "has_imap_password": bool(EMAIL_IMAP_PASSWORD),
        "has_imap_credentials": bool(EMAIL_IMAP_EMAIL and EMAIL_IMAP_PASSWORD),
        "imap_host": EMAIL_IMAP_HOST,
        "has_smtp_email": bool(EMAIL_SMTP_EMAIL),
        "has_smtp_password": bool(EMAIL_SMTP_PASSWORD),
        "has_smtp_credentials": bool(EMAIL_SMTP_EMAIL and EMAIL_SMTP_PASSWORD),
        "smtp_host": EMAIL_SMTP_HOST,
        "smtp_port": EMAIL_SMTP_PORT,
        "default_from_email": EMAIL_DEFAULT_FROM,
        "default_cc_email": EMAIL_DEFAULT_CC,
        "signature_assets_dir": EMAIL_SIGNATURE_ASSETS_DIR,
        "support_telegram_url": SUPPORT_TELEGRAM_URL,
        "support_marketing_url": SUPPORT_MARKETING_URL,
        "support_user_url_prefix": SUPPORT_USER_URL_PREFIX,
        "has_webhook_notify": bool(EMAIL_WEBHOOK_NOTIFY_URL),
        "allowed_from_whitelist": EMAIL_ALLOWED_FROM_WHITELIST,
        "background_interval_hours": EMAIL_BACKGROUND_INTERVAL_HOURS,
    }


def _issue_missing_required_config() -> List[str]:
    missing: List[str] = []
    required = {
        "issue_repo_base_url": ISSUE_REPO_BASE_URL,
        "issue_openai_api_key": ISSUE_OPENAI_API_KEY,
    }
    for key, value in required.items():
        if not str(value).strip():
            missing.append(key)
    return missing


def _issue_health_payload() -> Dict[str, Any]:
    return {
        "config_valid": len(_issue_missing_required_config()) == 0,
        "missing_required_config": _issue_missing_required_config(),
        "has_repo_base_url": bool(ISSUE_REPO_BASE_URL),
        "has_project_name": bool(ISSUE_PROJECT_NAME),
        "has_storage_state_path_config": bool(str(ISSUE_STORAGE_STATE_PATH).strip()),
        "storage_state_path": str(issue_service.storage_state_path),
        "has_openai_api_key": bool(ISSUE_OPENAI_API_KEY),
        "has_openai_model": bool(ISSUE_OPENAI_MODEL),
        "has_webhook_url": bool(ISSUE_WEBHOOK_URL),
        "bug_parent_repo_by_repo": issue_service.bug_parent_repo_by_repo,
        "bug_parent_issue_number_by_repo": issue_service.bug_parent_issue_number_by_repo,
    }


def _answers_health_payload() -> Dict[str, Any]:
    return {
        "config_valid": True,
        "missing_required_config": [],
        "has_telegram_token": bool(ANSWERS_TELEGRAM_BOT_TOKEN),
        "has_webhook_secret": bool(ANSWERS_TELEGRAM_WEBHOOK_SECRET),
        "has_openai_api_key": bool(ANSWERS_OPENAI_API_KEY),
        "has_openai_model": bool(ANSWERS_OPENAI_MODEL),
        "data_dir": str(ANSWERS_DATA_DIR),
    }


WORKDAY_SCHEDULER_STATE_PATH = DATA_DIR / "workday_agent_scheduler_state.json"


def _load_scheduler_state() -> Dict[str, Any]:
    if not WORKDAY_SCHEDULER_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(WORKDAY_SCHEDULER_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        logger.exception("No se pudo leer estado del scheduler de workday")
    return {}


def _save_scheduler_state(state: Dict[str, Any]) -> None:
    try:
        WORKDAY_SCHEDULER_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("No se pudo guardar estado del scheduler de workday")


def _workday_scheduler_loop() -> None:
    logger.info("Scheduler interno workday iniciado")
    last_invalid_signature = ""
    last_active_phase = ""
    last_blocked_day = ""
    while True:
        missing = _workday_missing_required_config()
        if missing:
            signature = ",".join(sorted(missing))
            if signature != last_invalid_signature:
                logger.error("Config workday inválida. Faltan: %s", signature)
                last_invalid_signature = signature
            time.sleep(60)
            continue

        last_invalid_signature = ""
        if workday_service.has_active_run():
            active_phase = str(workday_service.get_status().get("phase", ""))
            if active_phase != last_active_phase:
                logger.info(
                    "Scheduler workday en espera por ejecución activa (phase=%s)",
                    active_phase,
                )
                last_active_phase = active_phase
            time.sleep(30)
            continue

        last_active_phase = ""
        now = datetime.now()
        # Weekdays: lunes(0) a viernes(4)
        if now.weekday() <= 4:
            today = now.strftime("%Y-%m-%d")
            if workday_service.is_automatic_start_blocked_for_day(today):
                settings = workday_service.get_settings()
                if last_blocked_day != today:
                    logger.info(
                        "Scheduler workday omitido por rango bloqueado (%s - %s) para fecha %s",
                        settings.get("blocked_start_date", ""),
                        settings.get("blocked_end_date", ""),
                        today,
                    )
                    last_blocked_day = today
                time.sleep(30)
                continue

            last_blocked_day = ""
            state = _load_scheduler_state()
            last_run_date = str(state.get("last_run_date", ""))
            in_start_window = (
                (now.hour > 6 or (now.hour == 6 and now.minute >= 57))
                and (now.hour < 9 or (now.hour == 9 and now.minute <= 30))
            )
            should_start_today = last_run_date != today and in_start_window
            if should_start_today:
                run_id = f"auto-{workday_service.now_id()}"
                logger.info("Lanzando workday_flow automático run_id=%s", run_id)
                _save_scheduler_state({"last_run_date": today, "last_run_id": run_id})
                try:
                    workday_service.run_workday_flow(
                        job_name="workday_flow",
                        supervision=False,
                        run_id=run_id,
                    )
                except Exception:
                    logger.exception("Fallo no controlado en ejecución automática workday")
        else:
            last_blocked_day = ""
        time.sleep(30)


def _workday_recovery_loop() -> None:
    logger.info("Recovery workday iniciado")
    last_invalid_signature = ""
    while True:
        if not workday_service.has_active_run():
            logger.info("Recovery workday: no hay ejecución pendiente de reanudar")
            return

        missing = _workday_missing_required_config()
        if missing:
            signature = ",".join(sorted(missing))
            if signature != last_invalid_signature:
                logger.error("Recovery workday bloqueado. Faltan: %s", signature)
                last_invalid_signature = signature
            time.sleep(60)
            continue

        last_invalid_signature = ""
        result = workday_service.resume_pending_flow()
        logger.info("Recovery workday resultado: %s", result)
        if result.get("reason") == "busy":
            time.sleep(15)
            continue
        return


def _email_scheduler_loop() -> None:
    logger.info(
        "Internal email scheduler started (every %s hours, whitelist=%s)",
        EMAIL_BACKGROUND_INTERVAL_HOURS,
        ",".join(EMAIL_ALLOWED_FROM_WHITELIST) if EMAIL_ALLOWED_FROM_WHITELIST else "*",
    )
    interval_seconds = EMAIL_BACKGROUND_INTERVAL_HOURS * 3600
    last_invalid_signature = ""
    while True:
        missing = _email_missing_required_config()
        if missing:
            signature = ",".join(sorted(missing))
            if signature != last_invalid_signature:
                logger.error("Invalid email config. Missing: %s", signature)
                last_invalid_signature = signature
            time.sleep(60)
            continue

        last_invalid_signature = ""
        try:
            created = email_service.check_new_and_suggest(
                max_emails=10,
                unread_only=True,
                mailbox="INBOX",
            )
            logger.info("Email scheduler executed. New suggestions=%s", len(created))
        except Exception:
            logger.exception("Unhandled failure in automatic email execution")

        time.sleep(interval_seconds)


def _issue_daily_report_loop() -> None:
    # HA add-on scheduler: sends a daily heartbeat to the configured webhook.
    logger.info("Issue-agent daily scheduler started")
    last_report_date = ""
    last_invalid_signature = ""
    while True:
        missing = _issue_missing_required_config()
        if missing:
            signature = ",".join(sorted(missing))
            if signature != last_invalid_signature:
                logger.error("Invalid issue-agent config. Missing: %s", signature)
                last_invalid_signature = signature
            time.sleep(60)
            continue

        last_invalid_signature = ""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != last_report_date:
            try:
                issue_service.send_webhook_report(reason="daily_status", details={"date": today})
                logger.info("Issue-agent daily report sent (date=%s)", today)
                last_report_date = today
            except Exception:
                logger.exception("Could not send issue-agent daily report")
        time.sleep(300)


def _build_agent_modules() -> List[AgentModule]:
    return [
        AgentModule(
            name="workday_agent",
            router_factory=lambda: create_workday_router(
                workday_service,
                JOB_SECRET,
                _workday_missing_required_config,
            ),
            health_factory=_workday_health_payload,
            startup_tasks=(
                ("recovery", _workday_recovery_loop),
                ("scheduler", _workday_scheduler_loop),
            ),
        ),
        AgentModule(
            name="email_agent",
            router_factory=lambda: create_email_router(
                email_service,
                JOB_SECRET,
                _email_missing_required_config,
            ),
            health_factory=_email_health_payload,
            startup_tasks=(
                ("scheduler", _email_scheduler_loop),
            ),
        ),
        AgentModule(
            name="issue_agent",
            router_factory=lambda: create_issue_router(
                issue_service,
                JOB_SECRET,
                _issue_missing_required_config,
            ),
            health_factory=_issue_health_payload,
            startup_tasks=(
                ("daily_report", _issue_daily_report_loop),
            ),
        ),
        AgentModule(
            name="answers_agent",
            router_factory=lambda: create_answers_router(
                answers_service,
                JOB_SECRET,
                telegram_webhook_secrets=ANSWERS_TELEGRAM_WEBHOOK_SECRETS,
            ),
            health_factory=_answers_health_payload,
        ),
    ]


AGENT_MODULES = _build_agent_modules()


@APP.on_event("startup")
def _on_startup() -> None:
    for module in AGENT_MODULES:
        for task_name, task_target in module.startup_tasks:
            thread = threading.Thread(
                target=task_target,
                name=f"{module.name}-{task_name}",
                daemon=True,
            )
            thread.start()


for module in AGENT_MODULES:
    APP.include_router(module.router_factory())
APP.include_router(create_ui_router(JOB_SECRET))


@APP.get("/")
def root(request: Request):
    """Redirige la raíz al UI integrado de la aplicación."""
    target = "ui"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=307)


@APP.get("/health")
def health():
    """Expone estado básico y disponibilidad de configuración por agente."""
    per_agent = {module.name: module.health_factory() for module in AGENT_MODULES}
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "has_job_secret": bool(JOB_SECRET),
        **per_agent,
        "agents": [module.name for module in AGENT_MODULES],
        "ui_path": "/ui",
    }
