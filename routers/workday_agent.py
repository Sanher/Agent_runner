import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agents.workday_agent.service import WorkdayAgentService
from routers.auth import ensure_request_authorized

logger = logging.getLogger("agent_runner.workday_router")


class RunRequest(BaseModel):
    """Payload to run web-agent jobs."""
    supervision: bool = True
    run_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class WorkdaySettingsRequest(BaseModel):
    blocked_start_date: str = ""
    blocked_end_date: str = ""


def create_workday_router(
    service: WorkdayAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Creates the web-agent HTTP router and delegates execution to the service."""
    router = APIRouter(tags=["workday-agent"])

    runners: Dict[str, Callable[[str, bool, str], Dict[str, Any]]] = service.list_jobs()

    @router.post("/run/{job_name}")
    def run_job(job_name: str, req: RunRequest, request: Request):
        """Runs a registered job (for example workday_flow)."""
        missing = missing_config_fn()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid workday config. Missing: {', '.join(sorted(missing))}",
            )

        body_secret = str((req.payload or {}).get("secret", "")).strip()
        ensure_request_authorized(
            request,
            job_secret,
            logger,
            body_secret=body_secret,
            context_path=f"/run/{job_name}",
        )

        runner = runners.get(job_name)
        if not runner:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")

        run_id = req.run_id or service.now_id()
        return runner(job_name=job_name, supervision=req.supervision, run_id=run_id)

    def ensure_auth(request: Request) -> None:
        """Validates auth for the router GET/POST endpoints."""
        ensure_request_authorized(request, job_secret, logger)

    @router.get("/jobs")
    def list_jobs(request: Request):
        """Lists available jobs in the web agent."""
        ensure_auth(request)
        return {"jobs": sorted(runners.keys())}

    @router.get("/status")
    def status(request: Request):
        """Returns real-time status for the workday flow."""
        ensure_auth(request)
        return service.get_status()

    @router.get("/settings")
    def get_settings(request: Request):
        """Returns editable configuration for the workday scheduler."""
        ensure_auth(request)
        return {"ok": True, "settings": service.get_settings()}

    @router.post("/settings")
    def update_settings(req: WorkdaySettingsRequest, request: Request):
        """Updates blocked date range for automatic start."""
        ensure_auth(request)
        try:
            updated = service.update_settings(req.blocked_start_date, req.blocked_end_date)
        except RuntimeError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        return {"ok": True, "settings": updated}

    @router.get("/events")
    def events(request: Request, limit: int = 200, day: str = ""):
        """Returns runtime events for the workday agent (persisted jsonl)."""
        ensure_auth(request)
        return service.get_runtime_events(limit=limit, day=day)

    @router.get("/history")
    def history(request: Request, day: str = ""):
        """Returns daily click history for the workday agent."""
        ensure_auth(request)
        return service.get_daily_click_history(day=day)

    @router.post("/retry-failed")
    def retry_failed(request: Request):
        """Automatically retries the most recent failed action (if applicable)."""
        ensure_auth(request)
        try:
            logger.info("Manual retry requested at %s", request.url.path)
            return service.retry_failed_action()
        except RuntimeError as err:
            logger.warning("Manual retry rejected: %s", err)
            raise HTTPException(status_code=400, detail=str(err)) from err

    return router
