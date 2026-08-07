"""Protected endpoints for the read-only Telegram webhook intake agent.

Telegram delivery belongs exclusively to the authenticated Answers webhook.
This router only exposes local summary processing and review-state operations;
it never polls, writes to Telegram, or creates an Issue.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Protocol

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.telegram_reader_router")


class DismissSuggestedTaskRequest(BaseModel):
    """Human review outcome for one suggested Telegram task."""

    reason: str


_TASK_DISMISS_REASONS = {"created", "duplicate", "not_actionable", "other"}
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _require_opaque_id(value: str, field_name: str, maximum_length: int) -> str:
    """Keep path identifiers bounded and free from path/control characters."""
    normalized = str(value or "").strip()
    if len(normalized) > maximum_length or not _OPAQUE_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return normalized


def _require_dismiss_reason(reason: str) -> str:
    """Accept only review outcomes with an explicit product meaning."""
    normalized = str(reason or "").strip().lower()
    if normalized not in _TASK_DISMISS_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason must be one of {sorted(_TASK_DISMISS_REASONS)}",
        )
    return normalized


class TelegramReaderService(Protocol):
    """Minimal read-only Telegram service contract used by this router."""

    def get_status(self) -> Dict[str, Any]:
        """Return the agent health and configuration status."""

    def process_pending_summaries(self) -> Dict[str, Any]:
        """Summarize previously persisted webhook messages without Telegram I/O."""

    def baseline_from_now(self) -> Dict[str, Any]:
        """Discard queued historical updates and begin reading from now."""

    def list_summaries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return persisted summaries, newest first."""

    def get_summary(self, summary_id: str) -> Optional[Dict[str, Any]]:
        """Return one persisted summary, or None when it does not exist."""

    def dismiss_suggested_task(
        self,
        summary_id: str,
        task_key: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Persist a human dismissal decision for one suggested task."""

    def restore_suggested_task(self, summary_id: str, task_key: str) -> Dict[str, Any]:
        """Remove a previous human dismissal decision for one suggested task."""


def create_telegram_reader_router(
    service: TelegramReaderService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Create authenticated manual endpoints for the Telegram intake agent."""
    router = APIRouter(prefix="/telegram-reader", tags=["telegram-reader"])

    def ensure_auth(request: Request) -> str:
        return ensure_request_authorized(request, job_secret, logger)

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            logger.error(
                "Invalid telegram-reader config. Missing: %s",
                ",".join(sorted(missing)),
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid telegram-reader config. Missing: "
                    f"{', '.join(sorted(missing))}"
                ),
            )

    @router.get("/status")
    def status(request: Request):
        ensure_auth(request)
        try:
            payload = dict(service.get_status())
            service_missing = payload.get("missing_required_config", [])
            if not isinstance(service_missing, list):
                service_missing = []
            missing = [
                str(item).strip()
                for item in [*service_missing, *missing_config_fn()]
                if str(item or "").strip()
            ]
            missing = list(dict.fromkeys(missing))
            configuration_complete = not missing
            # The service knows its local OpenAI/chat requirements, while the
            # application adds the shared Answers webhook/token requirements.
            # Return one coherent status so ingress never reports false-ready.
            payload["missing_required_config"] = missing
            payload["configured"] = configuration_complete
            payload["configuration_complete"] = configuration_complete
            payload["config_valid"] = configuration_complete
            return payload
        except Exception as err:
            # Telegram request URLs embed the bot token. Do not log an arbitrary
            # exception or reflect it to a caller, even if a service regression
            # accidentally preserves the original HTTP client exception.
            logger.error("Failure in /telegram-reader/status (error_type=%s)", type(err).__name__)
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    @router.post("/process")
    def process_pending_summaries(request: Request):
        """Process local webhook intake without making a Telegram request."""
        ensure_auth(request)
        ensure_config()
        try:
            result = service.process_pending_summaries()
            completed_without_errors = bool(result.get("ok", True))
            if completed_without_errors:
                if result.get("warnings"):
                    logger.warning("Telegram reader manual processing completed with coverage warnings")
                else:
                    logger.info("Telegram reader manual processing completed")
            else:
                logger.warning("Telegram reader manual processing completed with errors")
            return {"ok": completed_without_errors, "result": result}
        except Exception as err:
            logger.error("Failure in /telegram-reader/process (error_type=%s)", type(err).__name__)
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    @router.post("/baseline")
    def baseline_from_now(request: Request):
        """Set the local future-only boundary for webhook-delivered intake."""
        ensure_auth(request)
        ensure_config()
        try:
            result = service.baseline_from_now()
            logger.info("Telegram reader baseline initialized from now")
            return {"ok": True, "result": result}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.error("Failure in /telegram-reader/baseline (error_type=%s)", type(err).__name__)
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    @router.get("/summaries")
    def list_summaries(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
    ):
        ensure_auth(request)
        try:
            items = service.list_summaries(limit=limit)
            return {"ok": True, "count": len(items), "items": items}
        except Exception as err:
            logger.error("Failure in /telegram-reader/summaries (error_type=%s)", type(err).__name__)
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    @router.get("/summaries/{summary_id}")
    def get_summary(summary_id: str, request: Request):
        ensure_auth(request)
        try:
            item = service.get_summary(summary_id)
        except Exception as err:
            logger.error(
                "Failure in /telegram-reader/summaries/%s (error_type=%s)",
                summary_id,
                type(err).__name__,
            )
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

        if item is None:
            raise HTTPException(status_code=404, detail=f"Summary not found: {summary_id}")
        return {"ok": True, "item": item}

    @router.post("/summaries/{summary_id}/tasks/{task_key}/dismiss")
    def dismiss_suggested_task(
        summary_id: str,
        task_key: str,
        req: DismissSuggestedTaskRequest,
        request: Request,
    ):
        """Record a human decision without sending a Telegram message or Issue."""
        ensure_auth(request)
        normalized_summary_id = _require_opaque_id(summary_id, "summary_id", 200)
        normalized_task_key = _require_opaque_id(task_key, "task_key", 128)
        reason = _require_dismiss_reason(req.reason)
        try:
            item = service.dismiss_suggested_task(
                normalized_summary_id,
                normalized_task_key,
                reason,
            )
            logger.info(
                "Telegram suggested task dismissed (summary_id=%s, task_key=%s, reason=%s)",
                normalized_summary_id,
                normalized_task_key,
                reason,
            )
            return {"ok": True, "result": item}
        except LookupError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.error(
                "Failure in /telegram-reader/summaries/%s/tasks/%s/dismiss (error_type=%s)",
                normalized_summary_id,
                normalized_task_key,
                type(err).__name__,
            )
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    @router.delete("/summaries/{summary_id}/tasks/{task_key}/dismiss")
    def restore_suggested_task(summary_id: str, task_key: str, request: Request):
        """Restore a task to review without touching Telegram or an Issue tracker."""
        ensure_auth(request)
        normalized_summary_id = _require_opaque_id(summary_id, "summary_id", 200)
        normalized_task_key = _require_opaque_id(task_key, "task_key", 128)
        try:
            item = service.restore_suggested_task(normalized_summary_id, normalized_task_key)
            logger.info(
                "Telegram suggested task restored (summary_id=%s, task_key=%s)",
                normalized_summary_id,
                normalized_task_key,
            )
            return {"ok": True, "result": item}
        except LookupError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.error(
                "Failure in /telegram-reader/summaries/%s/tasks/%s/dismiss (error_type=%s)",
                normalized_summary_id,
                normalized_task_key,
                type(err).__name__,
            )
            raise HTTPException(status_code=500, detail="Telegram reader operation failed") from None

    return router
