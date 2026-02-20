import logging
from typing import Any, Dict, Sequence

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agents.answers_agent.service import AnswersAgentService
from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.answers_router")


class SuggestChangesRequest(BaseModel):
    instruction: str


class SendReplyRequest(BaseModel):
    text: str


class MarkChatStatusRequest(BaseModel):
    status: str


class TelegramWebhookPayload(BaseModel):
    update_id: int | None = None
    message: Dict[str, Any] | None = None
    business_message: Dict[str, Any] | None = None
    edited_business_message: Dict[str, Any] | None = None


def create_answers_router(
    service: AnswersAgentService,
    job_secret: str,
    telegram_webhook_secrets: Sequence[str] = (),
) -> APIRouter:
    """Build HTTP router for manual moderation of answers_agent conversations."""
    router = APIRouter(tags=["answers-agent"])
    manual_router = APIRouter(prefix="/answers-agent", tags=["answers-agent"])

    def ensure_auth(request: Request) -> str:
        # Auth source is useful for HA diagnostics (query/header/ingress).
        return ensure_request_authorized(request, job_secret, logger)

    def ensure_telegram_webhook_auth(request: Request) -> None:
        provided = request.headers.get("x-telegram-bot-api-secret-token", "").strip()
        accepted = [str(item or "").strip() for item in telegram_webhook_secrets if str(item or "").strip()]
        if not accepted and getattr(service, "telegram_webhook_secret", "").strip():
            accepted = [str(service.telegram_webhook_secret).strip()]

        if not accepted:
            logger.error("Telegram webhook rejected: no configured secret")
            raise HTTPException(status_code=401, detail="Unauthorized webhook")
        if not provided or provided not in accepted:
            logger.warning("Telegram webhook rejected due to invalid secret")
            raise HTTPException(status_code=401, detail="Unauthorized webhook")

    @router.post("/answers_agent/webhook/telegram")
    def telegram_webhook(payload: TelegramWebhookPayload, request: Request):
        ensure_telegram_webhook_auth(request)
        try:
            return service.process_telegram_update(payload.model_dump(exclude_none=True))
        except RuntimeError as err:
            logger.warning("Invalid Telegram webhook payload (detail=%s)", err)
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.exception("Failure in /answers_agent/webhook/telegram")
            raise HTTPException(status_code=500, detail=str(err)) from err

    @manual_router.get("/chats")
    def list_chats(request: Request):
        auth_source = ensure_auth(request)
        items = service.list_chats_grouped()
        logger.debug("Answers chat list requested (count=%s, auth=%s)", len(items), auth_source)
        return {"ok": True, "count": len(items), "items": items}

    @manual_router.get("/chats/archived")
    def list_archived_chats(request: Request):
        auth_source = ensure_auth(request)
        items = service.list_archived_chats()
        logger.debug("Answers archived chat list requested (count=%s, auth=%s)", len(items), auth_source)
        return {"ok": True, "count": len(items), "items": items}

    @manual_router.post("/chats/{chat_id}/suggest")
    def suggest_changes(chat_id: int, req: SuggestChangesRequest, request: Request):
        auth_source = ensure_auth(request)
        try:
            item = service.suggest_changes(chat_id=chat_id, instruction=req.instruction)
            logger.info("Suggestion regenerated in answers (chat_id=%s, auth=%s)", chat_id, auth_source)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Chat not found:") else 400
            logger.warning("Invalid suggestion request in answers (chat_id=%s, detail=%s)", chat_id, detail)
            raise HTTPException(status_code=status_code, detail=detail) from err
        except Exception as err:
            logger.exception("Failure in /answers-agent/chats/%s/suggest", chat_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

    @manual_router.post("/chats/{chat_id}/suggest-ai")
    def suggest_ai(chat_id: int, request: Request):
        auth_source = ensure_auth(request)
        try:
            item = service.suggest_ai(chat_id=chat_id)
            logger.info("Manual AI suggestion in answers (chat_id=%s, auth=%s)", chat_id, auth_source)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Chat not found:") else 400
            logger.warning("Invalid manual AI suggestion request in answers (chat_id=%s, detail=%s)", chat_id, detail)
            raise HTTPException(status_code=status_code, detail=detail) from err
        except Exception as err:
            logger.exception("Failure in /answers-agent/chats/%s/suggest-ai", chat_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

    @manual_router.post("/chats/{chat_id}/send")
    def send_reply(chat_id: int, req: SendReplyRequest, request: Request):
        auth_source = ensure_auth(request)
        try:
            item = service.send_reply(chat_id=chat_id, text=req.text)
            logger.info("Reply sent in answers (chat_id=%s, auth=%s)", chat_id, auth_source)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Chat not found:") else 400
            logger.warning("Invalid send request in answers (chat_id=%s, detail=%s)", chat_id, detail)
            raise HTTPException(status_code=status_code, detail=detail) from err
        except Exception as err:
            logger.exception("Failure in /answers-agent/chats/%s/send", chat_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

    @manual_router.post("/chats/{chat_id}/status")
    def mark_status(chat_id: int, req: MarkChatStatusRequest, request: Request):
        auth_source = ensure_auth(request)
        try:
            item = service.mark_chat_status(chat_id=chat_id, status=req.status)
            logger.info(
                "Answers chat status updated (chat_id=%s, status=%s, auth=%s)",
                chat_id,
                req.status,
                auth_source,
            )
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Chat not found:") else 400
            logger.warning("Invalid status change in answers (chat_id=%s, detail=%s)", chat_id, detail)
            raise HTTPException(status_code=status_code, detail=detail) from err
        except Exception as err:
            logger.exception("Failure in /answers-agent/chats/%s/status", chat_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

    @manual_router.get("/status")
    def status(request: Request):
        auth_source = ensure_auth(request)
        payload = service.get_debug_status()
        logger.debug("Answers status requested (auth=%s)", auth_source)
        return payload

    router.include_router(manual_router)
    return router
