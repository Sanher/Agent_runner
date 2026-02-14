import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI

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

# Directorio persistente (Home Assistant add-on monta /data).
DATA_DIR = Path("/data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


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
    except Exception:
        logger.exception("No se pudo parsear %s; se usarán valores por defecto", options_path)
        return {}


ADDON_OPTIONS = _load_addon_options()


def _setting(name: str, default: str = "") -> str:
    """Resuelve configuración priorizando ENV y luego options.json."""
    env_name = name.upper()
    if env_name in os.environ:
        return os.getenv(env_name, default)
    return str(ADDON_OPTIONS.get(name.lower(), default))


JOB_SECRET = _setting("job_secret", "")
HASS_WEBHOOK_URL_STATUS = _setting("hass_webhook_url_status", "")
HASS_WEBHOOK_URL_FINAL = _setting("hass_webhook_url_final", "")
TARGET_URL = _setting("target_url", "")
SSO_EMAIL = _setting("sso_email", "")
TIMEZONE = _setting("timezone", "Europe/Madrid")
OPENAI_API_KEY = _setting("openai_api_key", "")
OPENAI_MODEL = _setting("openai_model", "gpt-4o-mini")
GMAIL_EMAIL = _setting("gmail_email", "")
GMAIL_APP_PASSWORD = _setting("gmail_app_password", "")
GMAIL_IMAP_HOST = _setting("gmail_imap_host", "imap.gmail.com")
EMAIL_AGENT_WEBHOOK_NOTIFY = _setting("email_agent_webhook_notify", HASS_WEBHOOK_URL_STATUS)


def _apply_timezone() -> None:
    """Aplica TZ de proceso para que fechas/ventanas usen hora local."""
    os.environ["TZ"] = TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()
    logger.info("Timezone aplicada: %s", TIMEZONE)


_apply_timezone()

workday_service = WorkdayAgentService(
    data_dir=DATA_DIR,
    target_url=TARGET_URL,
    sso_email=SSO_EMAIL,
    webhook_status_url=HASS_WEBHOOK_URL_STATUS,
    webhook_final_url=HASS_WEBHOOK_URL_FINAL,
    logger=logger.getChild("workday_agent"),
)

email_service = EmailAgentService(
    data_dir=DATA_DIR,
    openai_api_key=OPENAI_API_KEY,
    openai_model=OPENAI_MODEL,
    gmail_email=GMAIL_EMAIL,
    gmail_app_password=GMAIL_APP_PASSWORD,
    gmail_imap_host=GMAIL_IMAP_HOST,
    webhook_notify_url=EMAIL_AGENT_WEBHOOK_NOTIFY,
)

APP.include_router(create_workday_router(workday_service, JOB_SECRET))
APP.include_router(create_email_router(email_service))


@APP.get("/health")
def health():
    """Expone estado básico y disponibilidad de configuración por agente."""
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "has_job_secret": bool(JOB_SECRET),
        "has_webhook_status": bool(HASS_WEBHOOK_URL_STATUS),
        "has_webhook_final": bool(HASS_WEBHOOK_URL_FINAL),
        "has_sso_email": bool(SSO_EMAIL),
        "has_openai_api_key": bool(OPENAI_API_KEY),
        "has_gmail_credentials": bool(GMAIL_EMAIL and GMAIL_APP_PASSWORD),
        "has_email_agent_webhook_notify": bool(EMAIL_AGENT_WEBHOOK_NOTIFY),
        "timezone": TIMEZONE,
        "agents": ["workday_agent", "email_agent"],
    }
