"""HTTP endpoints for the read-only Discord summary agent."""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Protocol

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.discord_router")


class DismissSuggestedTaskRequest(BaseModel):
    """Human review outcome for one suggested Discord task."""

    reason: str


_TASK_DISMISS_REASONS = {"created", "duplicate", "not_actionable", "other"}
_CHANNEL_ID_PATTERN = re.compile(r"[0-9]{1,30}")
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _require_channel_id(channel_id: str) -> str:
    """Validate an ASCII Discord snowflake-like channel id before delegation."""
    normalized = str(channel_id or "").strip()
    if not _CHANNEL_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Invalid channel_id")
    return normalized


def _require_opaque_id(value: str, field_name: str, maximum_length: int) -> str:
    """Keep path identifiers bounded and free from path/control characters."""
    normalized = str(value or "").strip()
    if len(normalized) > maximum_length or not _OPAQUE_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return normalized


def _require_dismiss_reason(reason: str) -> str:
    """Accept only review outcomes that have an explicit product meaning."""
    normalized = str(reason or "").strip().lower()
    if normalized not in _TASK_DISMISS_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason must be one of {sorted(_TASK_DISMISS_REASONS)}",
        )
    return normalized


class DiscordAgentService(Protocol):
    """Minimal service contract used by the Discord HTTP router."""

    def get_status(self) -> Dict[str, Any]:
        """Return the agent health and configuration status."""

    def poll_new_messages(self) -> Dict[str, Any]:
        """Read allowed Discord channels and produce any pending summaries."""

    def list_summaries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return persisted summaries, newest first."""

    def get_summary(self, summary_id: str) -> Optional[Dict[str, Any]]:
        """Return one persisted summary, or None when it does not exist."""

    def baseline_channel_from_now(self, channel_id: str) -> Dict[str, Any]:
        """Persist a current-message cursor without summarizing prior messages."""

    def dismiss_suggested_task(
        self,
        summary_id: str,
        task_key: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Persist a human dismissal decision for one suggested task."""

    def restore_suggested_task(self, summary_id: str, task_key: str) -> Dict[str, Any]:
        """Remove a previous human dismissal decision for one suggested task."""


def create_discord_router(
    service: DiscordAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Create protected manual endpoints for the Discord summary agent."""
    router = APIRouter(prefix="/discord-agent", tags=["discord-agent"])

    def ensure_auth(request: Request) -> str:
        return ensure_request_authorized(request, job_secret, logger)

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            logger.error("Invalid discord-agent config. Missing: %s", ",".join(sorted(missing)))
            raise HTTPException(
                status_code=400,
                detail=f"Invalid discord-agent config. Missing: {', '.join(sorted(missing))}",
            )

    @router.get("/status")
    def status(request: Request):
        ensure_auth(request)
        try:
            return service.get_status()
        except Exception as err:
            logger.exception("Failure in /discord-agent/status")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/poll")
    def poll(request: Request):
        ensure_auth(request)
        ensure_config()
        try:
            result = service.poll_new_messages()
            completed_without_errors = bool(result.get("ok", True))
            if completed_without_errors:
                if result.get("warnings"):
                    logger.warning("Discord agent manual poll completed with coverage warnings")
                else:
                    logger.info("Discord agent manual poll completed")
            else:
                logger.warning("Discord agent manual poll completed with channel errors")
            return {"ok": completed_without_errors, "result": result}
        except Exception as err:
            logger.exception("Failure in /discord-agent/poll")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/channels/{channel_id}/baseline")
    def baseline_channel_from_now(channel_id: str, request: Request):
        """Start watching an allowed channel from its current newest message."""
        ensure_auth(request)
        ensure_config()
        normalized_channel_id = _require_channel_id(channel_id)
        try:
            result = service.baseline_channel_from_now(normalized_channel_id)
            logger.info(
                "Discord channel baseline initialized from now (channel_id=%s)",
                normalized_channel_id,
            )
            return {"ok": True, "result": result}
        except LookupError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.exception(
                "Failure in /discord-agent/channels/%s/baseline",
                normalized_channel_id,
            )
            raise HTTPException(status_code=500, detail=str(err)) from err

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
            logger.exception("Failure in /discord-agent/summaries")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.get("/summaries/{summary_id}")
    def get_summary(summary_id: str, request: Request):
        ensure_auth(request)
        try:
            item = service.get_summary(summary_id)
        except Exception as err:
            logger.exception("Failure in /discord-agent/summaries/%s", summary_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

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
        """Record a human review decision without creating an issue or touching Discord."""
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
                "Discord suggested task dismissed (summary_id=%s, task_key=%s, reason=%s)",
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
            logger.exception(
                "Failure in /discord-agent/summaries/%s/tasks/%s/dismiss",
                normalized_summary_id,
                normalized_task_key,
            )
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.delete("/summaries/{summary_id}/tasks/{task_key}/dismiss")
    def restore_suggested_task(summary_id: str, task_key: str, request: Request):
        """Restore a previously dismissed task to the normal review list."""
        ensure_auth(request)
        normalized_summary_id = _require_opaque_id(summary_id, "summary_id", 200)
        normalized_task_key = _require_opaque_id(task_key, "task_key", 128)
        try:
            item = service.restore_suggested_task(normalized_summary_id, normalized_task_key)
            logger.info(
                "Discord suggested task restored (summary_id=%s, task_key=%s)",
                normalized_summary_id,
                normalized_task_key,
            )
            return {"ok": True, "result": item}
        except LookupError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.exception(
                "Failure in /discord-agent/summaries/%s/tasks/%s/dismiss",
                normalized_summary_id,
                normalized_task_key,
            )
            raise HTTPException(status_code=500, detail=str(err)) from err

    return router
