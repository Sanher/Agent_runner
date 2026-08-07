"""Factory and localhost-only launcher for the local chat intake console.

This module never imports :mod:`main`.  It constructs the local Discord
reader only; Telegram delivery remains owned by the authenticated Answers
webhook in Agent Runner.  The standalone console therefore never takes over
the shared Telegram Business bot or starts any unrelated service.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, List, Optional

from fastapi import FastAPI

from routers.intake_local_ui import IntakeSourceBinding, create_intake_local_ui_router


LOCAL_INTAKE_BIND_HOST = "127.0.0.1"
DEFAULT_LOCAL_INTAKE_PORT = 8098
DEFAULT_LOCAL_INTAKE_DATA_DIR = Path(".data/intake_local")
HOME_ASSISTANT_PROTECTED_ROOTS = tuple(
    Path(path) for path in ("/data", "/config", "/share", "/media", "/ssl", "/backup")
)
_UNCONFIGURED_SECRET_VALUES = frozenset({"", "false", "none", "null"})

logger = logging.getLogger("agent_runner.intake_local")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


def _env_string_list(name: str) -> List[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _is_within_protected_home_assistant_path(candidate: Path) -> bool:
    """Return whether a local-console path overlaps a common HA runtime root."""
    resolved = candidate.resolve()
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in HOME_ASSISTANT_PROTECTED_ROOTS)


def _fallback_local_data_dir() -> Path:
    """Resolve the local fallback and fail closed if the working tree is mounted in HA."""
    fallback = DEFAULT_LOCAL_INTAKE_DATA_DIR.resolve()
    if _is_within_protected_home_assistant_path(fallback):
        raise RuntimeError("Refusing a local intake fallback inside a Home Assistant runtime directory")
    return fallback


def _has_configured_job_secret(value: object) -> bool:
    """Reject empty and template placeholder secrets for the local console."""
    return str(value or "").strip().lower() not in _UNCONFIGURED_SECRET_VALUES


def intake_local_data_dir() -> Path:
    """Resolve the dedicated local-console data root without touching add-on data."""
    requested = Path(os.getenv("INTAKE_LOCAL_DATA_DIR", str(DEFAULT_LOCAL_INTAKE_DATA_DIR))).expanduser()
    resolved = requested.resolve()
    if _is_within_protected_home_assistant_path(resolved):
        fallback = _fallback_local_data_dir()
        logger.warning(
            "Refusing INTAKE_LOCAL_DATA_DIR inside a Home Assistant runtime directory; using %s",
            fallback,
        )
        return fallback
    return resolved


def intake_local_host() -> str:
    """Return an explicitly loopback-only host even when ENV is misconfigured."""
    requested = str(os.getenv("INTAKE_LOCAL_HOST", LOCAL_INTAKE_BIND_HOST)).strip().lower()
    if requested == "localhost":
        # Uvicorn may resolve localhost to an externally configured address or
        # prefer IPv6 unexpectedly.  Bind the concrete IPv4 loopback instead.
        return LOCAL_INTAKE_BIND_HOST
    if requested in {LOCAL_INTAKE_BIND_HOST, "::1"}:
        return requested
    logger.warning("Refusing non-loopback INTAKE_LOCAL_HOST; using 127.0.0.1")
    return LOCAL_INTAKE_BIND_HOST


def intake_local_port() -> int:
    """Read a valid unprivileged local port from the dedicated environment key."""
    return _env_int(
        "INTAKE_LOCAL_PORT",
        DEFAULT_LOCAL_INTAKE_PORT,
        minimum=1024,
        maximum=65535,
    )


def _missing_configuration_for(service: Any) -> List[str]:
    """Reuse each reader's public status validation without exposing secrets."""
    status = service.get_status()
    if not isinstance(status, dict):
        return ["service_status_invalid"]
    return [str(value) for value in status.get("missing_required_config", []) if str(value).strip()]


def create_intake_local_app(
    *,
    job_secret: str,
    discord_service: Optional[Any] = None,
    telegram_service: Optional[Any] = None,
    discord_missing_config_fn: Optional[Callable[[], List[str]]] = None,
    telegram_missing_config_fn: Optional[Callable[[], List[str]]] = None,
) -> FastAPI:
    """Build a local console from explicitly supplied read-only services.

    The factory does not construct services, read environment values, or start
    background workers.  The integration layer must construct only the desired
    Discord and Telegram readers and pass them in here.
    """
    if not _has_configured_job_secret(job_secret):
        raise ValueError("A non-placeholder JOB_SECRET is required for the local intake console.")

    app = FastAPI(
        title="Local Intake Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(
        create_intake_local_ui_router(
            job_secret=job_secret,
            sources=(
                IntakeSourceBinding(
                    key="discord",
                    label="Discord",
                    service=discord_service,
                    missing_config_fn=discord_missing_config_fn or (lambda: []),
                    baseline_mode="channel",
                    supports_manual_poll=True,
                    delivery_mode="local_poll",
                ),
                IntakeSourceBinding(
                    key="telegram",
                    label="Telegram",
                    service=telegram_service,
                    missing_config_fn=telegram_missing_config_fn or (lambda: []),
                    baseline_mode="none",
                    supports_manual_poll=False,
                    delivery_mode="answers_webhook",
                    source_note=(
                        "Telegram updates arrive through the Answers webhook in Agent Runner. "
                        "This local console is review-only and does not connect to Telegram."
                    ),
                ),
            ),
        )
    )
    return app


def create_intake_local_app_from_environment(
    *,
    discord_service_factory: Optional[Callable[..., Any]] = None,
) -> FastAPI:
    """Construct the configured Discord reader for the localhost console.

    Telegram is deliberately not constructed here.  Its production delivery
    is a shared Answers webhook fan-out, and redirecting that webhook to a
    local console would interrupt the existing business responder.  Tests may
    inject a fake Telegram review service through :func:`create_intake_local_app`.
    """
    if discord_service_factory is None:
        from agents.discord_agent.service import DiscordAgentService

        discord_service_factory = DiscordAgentService

    job_secret = os.getenv("JOB_SECRET", "")
    if not _has_configured_job_secret(job_secret):
        raise ValueError("A non-placeholder JOB_SECRET is required for the local intake console.")

    data_dir = intake_local_data_dir()
    openai_api_key = os.getenv("DISCORD_OPENAI_API_KEY", "")
    openai_model = os.getenv("DISCORD_OPENAI_MODEL", "gpt-5-mini")
    discord_service = discord_service_factory(
        data_dir=data_dir,
        bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        channel_ids=_env_string_list("DISCORD_CHANNEL_IDS"),
        poll_interval_minutes=_env_int("DISCORD_POLL_INTERVAL_MINUTES", 15),
        summary_min_messages=_env_int("DISCORD_SUMMARY_MIN_MESSAGES", 5, maximum=100),
        retention_days=_env_int("DISCORD_RETENTION_DAYS", 14),
        logger=logger.getChild("discord"),
        enabled=_env_bool("DISCORD_ENABLED", False),
    )
    return create_intake_local_app(
        job_secret=job_secret,
        discord_service=discord_service,
        telegram_service=None,
        discord_missing_config_fn=lambda: _missing_configuration_for(discord_service),
    )


def run_intake_local_app(
    app: FastAPI,
    *,
    port: Optional[int] = None,
) -> None:
    """Run a preconfigured local console on loopback only.

    The host remains loopback-only even when ``INTAKE_LOCAL_HOST`` is set to a
    broader address.  This function is intentionally not invoked on import.
    """
    import uvicorn

    uvicorn.run(
        app,
        host=intake_local_host(),
        port=int(port or intake_local_port()),
        log_level="info",
        # A legacy query secret must never appear in the local access log.
        access_log=False,
    )


def main() -> None:
    """Construct and run the isolated local console only when invoked as a CLI."""
    if not _has_configured_job_secret(os.getenv("JOB_SECRET", "")):
        raise SystemExit("A non-placeholder JOB_SECRET is required before starting the local intake console.")
    app = create_intake_local_app_from_environment()
    run_intake_local_app(app)


if __name__ == "__main__":  # pragma: no cover - CLI guidance only
    main()
