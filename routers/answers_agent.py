import logging
from typing import Any, Dict, Protocol, Sequence

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agents.answers_agent.service import AnswersAgentService
from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.answers_router")
_UNCONFIGURED_WEBHOOK_SECRET_VALUES = frozenset({"", "false", "none", "null"})


class SuggestChangesRequest(BaseModel):
    instruction: str


class SendReplyRequest(BaseModel):
    text: str


class MarkChatStatusRequest(BaseModel):
    status: str


class UnarchiveChatRequest(BaseModel):
    archive_id: str | None = None


class TelegramWebhookPayload(BaseModel):
    update_id: int | None = None
    message: Dict[str, Any] | None = None
    business_message: Dict[str, Any] | None = None
    edited_business_message: Dict[str, Any] | None = None


class TelegramWebhookReaderSink(Protocol):
    """Local, atomic consumer for authenticated Telegram webhook updates.

    The Answers webhook invokes this sink directly after its own work instead
    of acknowledging an update that exists only in a lossy in-memory queue.
    Implementations must not call Telegram or a model from this method.
    """

    def ingest_webhook_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """Persist or process one normalized Telegram update without replying."""


def create_answers_router(
    service: AnswersAgentService,
    job_secret: str,
    telegram_webhook_secrets: Sequence[str] = (),
    telegram_reader_sink: TelegramWebhookReaderSink | None = None,
) -> APIRouter:
    """Build HTTP router for manual moderation of answers_agent conversations."""
    router = APIRouter(tags=["answers-agent"])
    manual_router = APIRouter(prefix="/answers-agent", tags=["answers-agent"])

    def configured_webhook_secret(value: Any) -> str:
        """Return a usable webhook secret, rejecting common config placeholders."""
        normalized = str(value or "").strip()
        return normalized if normalized.lower() not in _UNCONFIGURED_WEBHOOK_SECRET_VALUES else ""

    def ensure_auth(request: Request) -> str:
        # Auth source is useful for HA diagnostics (query/header/ingress).
        return ensure_request_authorized(request, job_secret, logger)

    def ensure_telegram_webhook_auth(request: Request) -> None:
        provided = request.headers.get("x-telegram-bot-api-secret-token", "").strip()
        accepted = [
            secret
            for secret in (configured_webhook_secret(item) for item in telegram_webhook_secrets)
            if secret
        ]
        fallback_secret = configured_webhook_secret(getattr(service, "telegram_webhook_secret", ""))
        if not accepted and fallback_secret:
            accepted = [fallback_secret]

        if not accepted:
            logger.error("Telegram webhook rejected: no configured secret")
            raise HTTPException(status_code=401, detail="Unauthorized webhook")
        if not provided or provided not in accepted:
            logger.warning("Telegram webhook rejected due to invalid secret")
            raise HTTPException(status_code=401, detail="Unauthorized webhook")

    @router.post("/answers_agent/webhook/telegram")
    def telegram_webhook(payload: TelegramWebhookPayload, request: Request):
        ensure_telegram_webhook_auth(request)
        normalized_update = payload.model_dump(exclude_none=True)
        try:
            result = service.process_telegram_update(normalized_update)
        except RuntimeError as err:
            logger.warning("Invalid Telegram webhook payload (detail=%s)", err)
            raise HTTPException(status_code=400, detail=str(err)) from err
        except Exception as err:
            logger.exception("Failure in /answers_agent/webhook/telegram")
            raise HTTPException(status_code=500, detail=str(err)) from err

        if telegram_reader_sink is not None:
            try:
                # Keep the local persistence call direct: a queued update could
                # be acknowledged to Telegram but lost on a process restart.
                telegram_reader_sink.ingest_webhook_update(normalized_update)
            except Exception as err:
                # The intake reader is strictly optional. Keep its failure private
                # and do not alter the existing Answers webhook response.
                logger.warning(
                    "Telegram reader webhook fan-out failed (error_type=%s)",
                    type(err).__name__,
                )

        return result

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

    @manual_router.post("/chats/{chat_id}/unarchive")
    def unarchive_chat(chat_id: int, req: UnarchiveChatRequest, request: Request):
        auth_source = ensure_auth(request)
        try:
            item = service.unarchive_chat(chat_id=chat_id, archive_id=req.archive_id or "")
            logger.info("Answers chat unarchived (chat_id=%s, auth=%s)", chat_id, auth_source)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            detail = str(err)
            status_code = 404 if detail.startswith("Archive not found:") else 400
            logger.warning("Invalid unarchive request in answers (chat_id=%s, detail=%s)", chat_id, detail)
            raise HTTPException(status_code=status_code, detail=detail) from err
        except Exception as err:
            logger.exception("Failure in /answers-agent/chats/%s/unarchive", chat_id)
            raise HTTPException(status_code=500, detail=str(err)) from err

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
