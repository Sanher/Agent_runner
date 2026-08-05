"""HTTP endpoints for the read-only Discord summary agent."""

import logging
from typing import Any, Callable, Dict, List, Optional, Protocol

from fastapi import APIRouter, HTTPException, Query, Request

from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.discord_router")


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

    return router
