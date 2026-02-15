from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
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

    @router.get("/jobs")
    def list_jobs():
        """Lista jobs disponibles en el agente web."""
        return {"jobs": sorted(runners.keys())}

    @router.get("/status")
    def status():
        """Devuelve estado en tiempo real del flujo workday."""
        return service.get_status()

    return router
