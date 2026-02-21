import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agents.issue_agent.service import IssueAgentService
from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.issue_router")


class GenerateIssueRequest(BaseModel):
    user_input: str
    issue_type: str = "bug"
    repo: str = "backend"
    unit: str = "core"
    include_comment: bool = False
    comment_issue_number: str = ""
    as_new_feature: bool = False
    as_third_party: bool = False


class SubmitIssueRequest(BaseModel):
    issue: Dict[str, Any]
    selectors: Dict[str, str] = Field(
        default_factory=dict,
        description="CSS/XPath selectors for title, description, comment, issue_type, repo, unit, comment_issue_number, dropdown, dropdown_option, submit",
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
    repo_aliases = {
        "front": "frontend",
        "frontend": "frontend",
        "back": "backend",
        "backend": "backend",
        "management": "management",
    }

    def ensure_auth(request: Request) -> None:
        ensure_request_authorized(request, job_secret, logger)

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            logger.error("Invalid issue-agent config. Missing: %s", ",".join(sorted(missing)))
            raise HTTPException(
                status_code=400,
                detail=f"Invalid issue-agent config. Missing: {', '.join(sorted(missing))}",
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
            normalized_issue_type = str(req.issue_type or "").strip().lower()
            issue_type = normalized_issue_type
            repo = req.repo
            as_new_feature = bool(req.as_new_feature)
            as_third_party = bool(req.as_third_party)

            # Priority rule:
            # - comment mode is always neutral (task) and keeps user-selected repo
            # - special UI aliases (new feature / third party *) only apply in create mode
            if req.include_comment:
                # Comment mode is neutral and should not trigger special management workflows.
                issue_type = "task"
                as_new_feature = False
                as_third_party = False
                logger.info(
                    "Issue generate mapping: comment mode -> neutral task (repo=%s, original_type=%s)",
                    repo,
                    normalized_issue_type or "-",
                )
            elif normalized_issue_type == "new feature":
                as_new_feature = True
                issue_type = "feature"
                repo = "management"
                logger.info("Issue generate mapping: 'new feature' -> management feature flow")
            elif normalized_issue_type == "third party bug":
                as_third_party = True
                issue_type = "bug"
                repo = "management"
                logger.info("Issue generate mapping: 'third party bug' -> management third-party flow")
            elif normalized_issue_type == "third party feature":
                as_third_party = True
                issue_type = "feature"
                repo = "management"
                logger.info("Issue generate mapping: 'third party feature' -> management third-party flow")
            elif normalized_issue_type == "third party task":
                as_third_party = True
                issue_type = "task"
                repo = "management"
                logger.info("Issue generate mapping: 'third party task' -> management third-party flow")

            item = service.generate_issue(
                req.user_input,
                issue_type,
                repo,
                req.unit,
                req.include_comment,
                comment_issue_number=req.comment_issue_number,
                as_new_feature=as_new_feature,
                as_third_party=as_third_party,
            )
            logger.info("Issue generated via API (issue_id=%s)", item.get("issue_id", ""))
            return {"ok": True, "item": item}
        except Exception as err:
            logger.exception("Failure in /issue-agent/generate")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/submit")
    def submit(req: SubmitIssueRequest, request: Request):
        ensure_auth(request)
        ensure_config()
        repo = repo_aliases.get(str(req.issue.get("repo", "")).strip().lower(), "backend")
        issue_type = str(req.issue.get("issue_type", "")).strip().lower()
        is_front_repo = repo == "frontend"
        is_backend_automated = repo == "backend" and issue_type in {
            "bug",
            "feature",
            "task",
            "enhancement",
            "blockchain",
            "exchange",
        }
        is_management_automated = repo == "management" and (
            bool(req.issue.get("as_new_feature")) or bool(req.issue.get("as_third_party"))
        )
        if not (is_front_repo or is_backend_automated or is_management_automated):
            mandatory = ["title", "description"]
            for key in mandatory:
                if key not in req.selectors or not str(req.selectors[key]).strip():
                    raise HTTPException(status_code=400, detail=f"Missing selector: {key}")
        required_issue_fields = ["issue_id", "title", "description", "generated_link"]
        for key in required_issue_fields:
            if not str(req.issue.get(key, "")).strip():
                raise HTTPException(status_code=400, detail=f"Missing issue field: {key}")
        try:
            result = service.submit_issue_via_playwright(
                issue=req.issue,
                selectors=req.selectors,
                non_headless=req.non_headless,
            )
            logger.info("Issue submitted via API (issue_id=%s)", req.issue.get("issue_id", ""))
            return {"ok": True, "result": result}
        except Exception as err:
            # This error also emits useful traces in add-on logs.
            logger.exception("Failure in /issue-agent/submit")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @router.post("/report")
    def report(req: ReportRequest, request: Request):
        ensure_auth(request)
        try:
            return service.send_webhook_report(reason=req.reason, details=req.details)
        except Exception as err:
            logger.exception("Failure in /issue-agent/report")
            raise HTTPException(status_code=500, detail=str(err)) from err

    return router
