import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from agents.email_agent.service import EmailAgentService
from agents.workday_agent.service import WorkdayAgentService
from routers.email_agent import create_email_router
from routers.workday_agent import create_workday_router


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("agent_runner")

APP = FastAPI(title="Agent Runner")

def _resolve_data_dir() -> Path:
    """Resuelve directorio de datos; en local permite override por ENV."""
    requested = Path(os.getenv("AGENT_RUNNER_DATA_DIR", "/data")).expanduser()
    try:
        requested.mkdir(parents=True, exist_ok=True)
        return requested.resolve()
    except OSError:
        # Fallback local para entornos donde /data es de solo lectura (p.ej. macOS host).
        fallback = (Path.cwd() / ".data").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "No se pudo usar DATA_DIR=%s; usando fallback local %s",
            requested,
            fallback,
        )
        return fallback


# Directorio persistente (Home Assistant add-on monta /data).
DATA_DIR = _resolve_data_dir()


def _load_addon_options() -> Dict[str, Any]:
    """Carga opciones desde /data/options.json cuando existe."""
    options_path = DATA_DIR / "options.json"
    if not options_path.exists():
        logger.info("No existe options.json; se usarán variables de entorno o valores por defecto")
        return {}
    try:
        options = json.loads(options_path.read_text(encoding="utf-8"))
        logger.info("Opciones del add-on cargadas desde %s", options_path)
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
WORKDAY_TIMEZONE = _setting_with_aliases("workday_timezone", ["timezone"], "Europe/Madrid")
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

# Agente correo (email + IMAP Gmail)
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
    allowed_from_whitelist=EMAIL_ALLOWED_FROM_WHITELIST,
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
            state = _load_scheduler_state()
            last_run_date = str(state.get("last_run_date", ""))
            today = now.strftime("%Y-%m-%d")
            should_start_today = (
                last_run_date != today
                and (now.hour > 6 or (now.hour == 6 and now.minute >= 57))
                and (now.hour < 8 or (now.hour == 8 and now.minute <= 31))
            )
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
        "Scheduler interno email iniciado (cada %s horas, whitelist=%s)",
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
                logger.error("Config email inválida. Faltan: %s", signature)
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
            logger.info("Email scheduler ejecutado. Nuevas sugerencias=%s", len(created))
        except Exception:
            logger.exception("Fallo no controlado en ejecución automática email")

        time.sleep(interval_seconds)


@APP.on_event("startup")
def _on_startup() -> None:
    recovery_thread = threading.Thread(
        target=_workday_recovery_loop,
        name="workday-recovery",
        daemon=True,
    )
    recovery_thread.start()
    thread = threading.Thread(
        target=_workday_scheduler_loop,
        name="workday-scheduler",
        daemon=True,
    )
    thread.start()
    email_thread = threading.Thread(
        target=_email_scheduler_loop,
        name="email-scheduler",
        daemon=True,
    )
    email_thread.start()


APP.include_router(create_workday_router(workday_service, JOB_SECRET, _workday_missing_required_config))
APP.include_router(create_email_router(email_service, JOB_SECRET, _email_missing_required_config))


@APP.get("/")
def root(request: Request):
    """Redirige la raíz al UI del agente de correo (útil en Ingress)."""
    target = "email-agent/ui"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=307)


@APP.get("/health")
def health():
    """Expone estado básico y disponibilidad de configuración por agente."""
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "has_job_secret": bool(JOB_SECRET),
        "workday_agent": {
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
        },
        "email_agent": {
            "config_valid": len(_email_missing_required_config()) == 0,
            "missing_required_config": _email_missing_required_config(),
            "has_openai_api_key": bool(EMAIL_OPENAI_API_KEY),
            "has_openai_model": bool(EMAIL_OPENAI_MODEL),
            "has_imap_email": bool(EMAIL_IMAP_EMAIL),
            "has_imap_password": bool(EMAIL_IMAP_PASSWORD),
            "has_imap_credentials": bool(EMAIL_IMAP_EMAIL and EMAIL_IMAP_PASSWORD),
            "imap_host": EMAIL_IMAP_HOST,
            "has_webhook_notify": bool(EMAIL_WEBHOOK_NOTIFY_URL),
            "allowed_from_whitelist": EMAIL_ALLOWED_FROM_WHITELIST,
            "background_interval_hours": EMAIL_BACKGROUND_INTERVAL_HOURS,
        },
        "agents": ["workday_agent", "email_agent"],
    }
