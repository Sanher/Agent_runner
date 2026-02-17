import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agents.issue_agent.service import IssueAgentService


logger = logging.getLogger("agent_runner.issue_router")


class GenerateIssueRequest(BaseModel):
    user_input: str
    include_comment: bool = False


class SubmitIssueRequest(BaseModel):
    issue: Dict[str, Any]
    selectors: Dict[str, str] = Field(
        default_factory=dict,
        description="Selectors CSS/XPath para title, description, comment, dropdown, dropdown_option, submit",
    )
    non_headless: bool = True


class ReportRequest(BaseModel):
    reason: str
    details: Optional[Dict[str, Any]] = None


def create_issue_router(
    service: IssueAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    router = APIRouter(prefix="/issue-agent", tags=["issue-agent"])

    def _extract_secret(request: Request) -> tuple[str, str]:
        header_secret = request.headers.get("x-job-secret", "").strip()
        if header_secret:
            return header_secret, "header"
        query_secret = request.query_params.get("secret", "").strip()
        if query_secret:
            return query_secret, "query"
        return "", "missing"

    def _is_ingress_request(request: Request) -> bool:
        # Home Assistant Ingress ya autentica; no forzar secreto duplicado.
        return bool(request.headers.get("x-ingress-path", "").strip())

    def ensure_auth(request: Request) -> None:
        if not job_secret:
            return
        if _is_ingress_request(request):
            logger.debug("Auth bypass issue-agent por ingress en %s", request.url.path)
            return

        provided, source = _extract_secret(request)
        if provided != job_secret:
            logger.warning(
                "Unauthorized issue-agent en %s (source=%s, client=%s)",
                request.url.path,
                source,
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=401, detail="Unauthorized")

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            logger.error("Config issue-agent inválida. Faltan: %s", ",".join(sorted(missing)))
            raise HTTPException(
                status_code=400,
                detail=f"Issue agent config inválida. Faltan: {', '.join(sorted(missing))}",
            )

    @router.get("/status")
    def status(request: Request):
        ensure_auth(request)
        return service.get_status()

    @router.get("/events")
    def events(request: Request, limit: int = 200):
        ensure_auth(request)
        return service.get_events(limit=limit)

    @router.post("/generate")
    def generate(req: GenerateIssueRequest, request: Request):
        ensure_auth(request)
        ensure_config()
        try:
            item = service.generate_issue(req.user_input, req.include_comment)
            logger.info("Issue generado via API (issue_id=%s)", item.get("issue_id", ""))
            return {"ok": True, "item": item}
        except Exception as err:
            logger.exception("Fallo en /issue-agent/generate")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/submit")
    def submit(req: SubmitIssueRequest, request: Request):
        ensure_auth(request)
        ensure_config()
        mandatory = ["title", "description"]
        for key in mandatory:
            if key not in req.selectors or not str(req.selectors[key]).strip():
                raise HTTPException(status_code=400, detail=f"Missing selector: {key}")
        try:
            result = service.submit_issue_via_playwright(
                issue=req.issue,
                selectors=req.selectors,
                non_headless=req.non_headless,
            )
            logger.info("Issue enviado via API (issue_id=%s)", req.issue.get("issue_id", ""))
            return {"ok": True, "result": result}
        except Exception as err:
            # Este error también activará trazas útiles en logs del add-on.
            logger.exception("Fallo en /issue-agent/submit")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/report")
    def report(req: ReportRequest, request: Request):
        ensure_auth(request)
        try:
            return service.send_webhook_report(reason=req.reason, details=req.details)
        except Exception as err:
            logger.exception("Fallo en /issue-agent/report")
            raise HTTPException(status_code=500, detail=str(err)) from err

    return router
