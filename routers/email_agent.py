import logging
from datetime import datetime
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from agents.email_agent.service import EmailAgentService
from routers.auth import ensure_request_authorized

logger = logging.getLogger("agent_runner.email_router")


class CheckNewRequest(BaseModel):
    max_emails: int = 5
    unread_only: bool = True
    mailbox: str = "INBOX"


class RegenerateRequest(BaseModel):
    instruction: str


class MarkStatusRequest(BaseModel):
    status: str


class ManualSuggestionRequest(BaseModel):
    from_text: str = ""
    subject: str = ""
    body: str


class SendSuggestionRequest(BaseModel):
    to_email: str
    body: Optional[str] = None
    cc_email: Optional[str] = None


class EmailSettingsRequest(BaseModel):
    allowed_from_whitelist: Optional[List[str]] = None
    signature: Optional[str] = None
    default_from_email: Optional[str] = None
    default_cc_email: Optional[str] = None
    signature_assets_dir: Optional[str] = None


def create_email_router(
    service: EmailAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Create HTTP router for email agent operations."""
    router = APIRouter(prefix="/email-agent", tags=["email-agent"])

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid email config. Missing: {', '.join(sorted(missing))}",
            )

    def ensure_auth(request: Request, context_path: str = "") -> None:
        ensure_request_authorized(
            request,
            job_secret,
            logger,
            context_path=context_path,
        )

    @router.post("/check-new")
    def check_new(req: CheckNewRequest, request: Request):
        """Detect new emails and generate suggestions (without sending)."""
        ensure_auth(request)
        ensure_config()
        created = service.check_new_and_suggest(
            max_emails=max(1, min(req.max_emails, 20)),
            unread_only=req.unread_only,
            mailbox=req.mailbox,
        )
        return {
            "ok": True,
            "created": len(created),
            "note": "Webhook notification was sent for each new suggestion when configured.",
            "items": created,
        }

    @router.get("/suggestions")
    def list_suggestions(request: Request, status: Optional[str] = None):
        """Return stored suggestions, optionally filtered by status."""
        ensure_auth(request)
        items = service.load_suggestions()
        if status:
            items = [item for item in items if item.get("status") == status]
        return {"ok": True, "count": len(items), "items": items}

    @router.post("/suggestions/{suggestion_id}/regenerate")
    def regenerate(suggestion_id: str, req: RegenerateRequest, request: Request):
        """Regenerate a suggestion using user instructions."""
        ensure_auth(request)
        ensure_config()
        try:
            item = service.regenerate_suggestion(suggestion_id, req.instruction)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    @router.post("/suggestions/{suggestion_id}/status")
    def mark_status(suggestion_id: str, req: MarkStatusRequest, request: Request):
        """Update suggestion status; reviewed archives it from the active list."""
        ensure_auth(request)
        valid_statuses = {"draft", "reviewed", "copied", "sent"}
        if req.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid_statuses)}")
        items = service.load_suggestions()
        for item in items:
            if item["suggestion_id"] == suggestion_id:
                updated_at = datetime.now().isoformat()
                if req.status == "reviewed":
                    item["status"] = "reviewed"
                    item["updated_at"] = updated_at
                    item["reviewed_at"] = updated_at
                    item.pop("unarchived_at", None)
                    service.save_suggestions(items)
                    return {"ok": True, "removed": True, "item": item}
                item["status"] = req.status
                item["updated_at"] = updated_at
                if req.status == "draft":
                    item.pop("reviewed_at", None)
                    item["unarchived_at"] = updated_at
                service.save_suggestions(items)
                return {"ok": True, "removed": False, "item": item}
        raise HTTPException(status_code=404, detail=f"Suggestion not found: {suggestion_id}")

    @router.post("/suggestions/{suggestion_id}/send")
    def send_suggestion(suggestion_id: str, req: SendSuggestionRequest, request: Request):
        """Send suggestion by SMTP with dynamic To and configurable CC."""
        ensure_auth(request)
        try:
            item = service.send_suggestion_email(
                suggestion_id=suggestion_id,
                to_email=req.to_email,
                body=req.body,
                cc_email=req.cc_email,
            )
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Suggestion not found:") else 400
            raise HTTPException(status_code=status_code, detail=detail) from err

    @router.post("/suggestions/manual")
    def manual_suggestion(req: ManualSuggestionRequest, request: Request):
        """Generate a new suggestion from manually pasted text."""
        ensure_auth(request)
        ensure_config()
        try:
            item = service.create_suggestion_from_text(
                from_text=req.from_text,
                subject=req.subject,
                body=req.body,
            )
            return {"ok": True, "item": item}
        except RuntimeError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @router.get("/settings")
    def get_settings(request: Request):
        """Return editable email agent settings."""
        ensure_auth(request)
        return {"ok": True, "settings": service.get_settings()}

    @router.post("/settings")
    def update_settings(req: EmailSettingsRequest, request: Request):
        """Update editable email agent settings."""
        ensure_auth(request)
        try:
            updated = service.update_settings(
                allowed_from_whitelist=req.allowed_from_whitelist,
                signature=req.signature,
                default_from_email=req.default_from_email,
                default_cc_email=req.default_cc_email,
                signature_assets_dir=req.signature_assets_dir,
            )
            return {"ok": True, "settings": updated}
        except RuntimeError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @router.get("/ui", include_in_schema=False)
    def legacy_ui_redirect(request: Request):
        """
        Compatibility: redirect /email-agent/ui to /ui.
        Preserve query string to keep existing secret links working.
        """
        ensure_auth(request, context_path="/email-agent/ui")
        path = request.url.path
        if path.endswith("/email-agent/ui"):
            target = f"{path[:-len('/email-agent/ui')]}/ui"
        else:
            target = "/ui"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=307)

    return router
