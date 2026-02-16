from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agents.workday_agent.service import WorkdayAgentService


class RunRequest(BaseModel):
    """Payload para ejecutar jobs del agente web/workday."""
    supervision: bool = True
    run_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


def create_workday_router(
    service: WorkdayAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Crea router HTTP del agente web y delega ejecución al servicio."""
    router = APIRouter(tags=["workday-agent"])

    runners: Dict[str, Callable[[str, bool, str], Dict[str, Any]]] = service.list_jobs()

    @router.post("/run/{job_name}")
    def run_job(job_name: str, req: RunRequest):
        """Ejecuta un job registrado (por ejemplo workday_flow)."""
        missing = missing_config_fn()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Workday config inválida. Faltan: {', '.join(sorted(missing))}",
            )

        if job_secret:
            provided = (req.payload or {}).get("secret", "")
            if provided != job_secret:
                raise HTTPException(status_code=401, detail="Unauthorized")

        runner = runners.get(job_name)
        if not runner:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")

        run_id = req.run_id or service.now_id()
        return runner(job_name=job_name, supervision=req.supervision, run_id=run_id)

    def ensure_auth(request: Request) -> None:
        if not job_secret:
            return
        provided = (
            request.headers.get("x-job-secret", "").strip()
            or request.query_params.get("secret", "").strip()
        )
        if provided != job_secret:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @router.get("/jobs")
    def list_jobs(request: Request):
        """Lista jobs disponibles en el agente web."""
        ensure_auth(request)
        return {"jobs": sorted(runners.keys())}

    @router.get("/status")
    def status(request: Request):
        """Devuelve estado en tiempo real del flujo workday."""
        ensure_auth(request)
        return service.get_status()

    @router.get("/events")
    def events(request: Request, limit: int = 200, day: str = ""):
        """Devuelve eventos runtime del agente workday (jsonl persistido)."""
        ensure_auth(request)
        return service.get_runtime_events(limit=limit, day=day)

    @router.get("/history")
    def history(request: Request, day: str = ""):
        """Devuelve historial diario de pulsaciones/clicks del agente workday."""
        ensure_auth(request)
        return service.get_daily_click_history(day=day)

    @router.post("/retry-failed")
    def retry_failed(request: Request):
        """Reintenta automáticamente la acción fallida más reciente (si aplica)."""
        ensure_auth(request)
        try:
            return service.retry_failed_action()
        except RuntimeError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    return router
