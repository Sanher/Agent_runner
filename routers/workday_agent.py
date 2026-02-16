import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agents.workday_agent.service import WorkdayAgentService

logger = logging.getLogger("agent_runner.workday_router")


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

    def _extract_secret(
        request: Request,
        req: Optional[RunRequest] = None,
        allow_body: bool = False,
    ) -> tuple[str, str]:
        """Extrae secret y su origen sin exponer su valor en logs."""
        header_secret = request.headers.get("x-job-secret", "").strip()
        if header_secret:
            return header_secret, "header"

        query_secret = request.query_params.get("secret", "").strip()
        if query_secret:
            return query_secret, "query"

        if allow_body and req is not None:
            body_secret = str((req.payload or {}).get("secret", "")).strip()
            if body_secret:
                return body_secret, "body"

        return "", "missing"

    @router.post("/run/{job_name}")
    def run_job(job_name: str, req: RunRequest, request: Request):
        """Ejecuta un job registrado (por ejemplo workday_flow)."""
        missing = missing_config_fn()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Workday config inválida. Faltan: {', '.join(sorted(missing))}",
            )

        if job_secret:
            provided, source = _extract_secret(request, req, allow_body=True)
            if provided != job_secret:
                logger.warning(
                    "Unauthorized en /run/%s (source=%s, client=%s)",
                    job_name,
                    source,
                    request.client.host if request.client else "unknown",
                )
                raise HTTPException(status_code=401, detail="Unauthorized")
            logger.debug("Auth OK en /run/%s (source=%s)", job_name, source)

        runner = runners.get(job_name)
        if not runner:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")

        run_id = req.run_id or service.now_id()
        return runner(job_name=job_name, supervision=req.supervision, run_id=run_id)

    def ensure_auth(request: Request) -> None:
        """Valida auth para endpoints GET/POST del router workday."""
        if not job_secret:
            # Si no hay secret global, no se exige auth en este router.
            return
        provided, source = _extract_secret(request, allow_body=False)
        if provided != job_secret:
            logger.warning(
                "Unauthorized en %s (source=%s, client=%s)",
                request.url.path,
                source,
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=401, detail="Unauthorized")
        logger.debug("Auth OK en %s (source=%s)", request.url.path, source)

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
            logger.info("Retry manual solicitado en %s", request.url.path)
            return service.retry_failed_action()
        except RuntimeError as err:
            logger.warning("Retry manual rechazado: %s", err)
            raise HTTPException(status_code=400, detail=str(err)) from err

    return router
