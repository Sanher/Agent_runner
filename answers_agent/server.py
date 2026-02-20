import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel
from agents.support_guidance import (
    DEFAULT_SUPPORT_MARKETING_URL,
    DEFAULT_SUPPORT_TELEGRAM_URL,
    DEFAULT_SUPPORT_USER_URL_PREFIX,
    SupportGuidanceConfig,
    build_prompt_policy_lines,
    contains_sensitive_material,
    is_low_context_greeting,
    is_spam_like_message,
    match_support_workflow_reply,
)

logger = logging.getLogger("agent_runner.answers_server")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GUIDELINES_DIR = BASE_DIR / "guidelines"

DATA_DIR.mkdir(parents=True, exist_ok=True)
GUIDELINES_DIR.mkdir(parents=True, exist_ok=True)

CONVERSATIONS_PATH = DATA_DIR / "conversations.json"
PENDING_ISSUES_PATH = DATA_DIR / "pending_issues.json"
MANUAL_ACTIONS_PATH = DATA_DIR / "manual_actions.json"
BLOCKED_USERS_PATH = DATA_DIR / "blocked_users.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not read JSON at %s; using fallback", path)
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


for file_path, fallback in [
    (CONVERSATIONS_PATH, {"users": {}}),
    (PENDING_ISSUES_PATH, {"issues": []}),
    (MANUAL_ACTIONS_PATH, {"actions": []}),
    (BLOCKED_USERS_PATH, {"blocked": []}),
]:
    if not file_path.exists():
        _save_json(file_path, fallback)


class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_webhook_secret: str = os.getenv(
        "TELEGRAM_WEHBOOK_SECRET",
        os.getenv(
            "ANSWERS_WEBHOOK_SECRET",
            os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        ),
    ).strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    bot_response_delay_seconds: int = int(os.getenv("BOT_RESPONSE_DELAY_SECONDS", "8"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    support_telegram_url: str = os.getenv("SUPPORT_TELEGRAM_URL", DEFAULT_SUPPORT_TELEGRAM_URL).strip()
    support_marketing_url: str = os.getenv("SUPPORT_MARKETING_URL", DEFAULT_SUPPORT_MARKETING_URL).strip()
    support_user_url_prefix: str = os.getenv("SUPPORT_USER_URL_PREFIX", DEFAULT_SUPPORT_USER_URL_PREFIX).strip()


SETTINGS = Settings()
APP = FastAPI(title="Answers Agent", version="0.1.0")
SUPPORT_GUIDANCE = SupportGuidanceConfig(
    telegram_support_url=SETTINGS.support_telegram_url or DEFAULT_SUPPORT_TELEGRAM_URL,
    marketing_url=SETTINGS.support_marketing_url or DEFAULT_SUPPORT_MARKETING_URL,
    user_url_prefix=SETTINGS.support_user_url_prefix or DEFAULT_SUPPORT_USER_URL_PREFIX,
)
logger.info(
    "Answers agent server initialized (has_bot_token=%s, has_webhook_secret=%s, has_openai_key=%s, support_telegram_url=%s)",
    bool(SETTINGS.telegram_bot_token),
    bool(SETTINGS.telegram_webhook_secret),
    bool(SETTINGS.openai_api_key),
    SUPPORT_GUIDANCE.telegram_support_url,
)


def _debug(message: str, **meta: Any) -> None:
    # Extra diagnostic traces when LOG_LEVEL=DEBUG.
    suffix = " | " + ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
    logger.debug("[DEBUG][answers_server] %s%s", message, suffix)


def _now_ts() -> int:
    return int(time.time())


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    return re.sub(r"[^\w\sáéíóúüñ¿?¡!]", "", cleaned)


def _looks_like_spam(text: str) -> bool:
    return is_spam_like_message(text)


def _contains_sensitive_request(text: str) -> bool:
    return contains_sensitive_material(text)


def _resolve_user_display_name(from_user: Dict[str, Any]) -> str:
    first_name = str(from_user.get("first_name") or "").strip()
    last_name = str(from_user.get("last_name") or "").strip()
    username = str(from_user.get("username") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name
    if username:
        return f"@{username}"
    user_id = str(from_user.get("id") or "").strip()
    return f"user_{user_id}" if user_id else "unknown_user"


async def _telegram_request(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not SETTINGS.telegram_bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured")
    url = f"https://api.telegram.org/bot{SETTINGS.telegram_bot_token}/{method}"
    _debug(
        "Telegram API call",
        method=method,
        chat_id=payload.get("chat_id"),
        has_message_id=bool(payload.get("message_id")),
    )
    try:
        async with httpx.AsyncClient(timeout=SETTINGS.request_timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except Exception:
        logger.exception("Telegram API request failed (method=%s, chat_id=%s)", method, payload.get("chat_id"))
        raise


async def _openai_response(messages: List[Dict[str, str]]) -> Optional[str]:
    if not SETTINGS.openai_api_key:
        _debug("OpenAI not configured; using local fallback")
        return None

    policy_lines = build_prompt_policy_lines(SUPPORT_GUIDANCE)
    system_prompt = (
        "You are a Telegram support assistant. "
        "Reply in English. "
        "If you are unsure, reply exactly: 'Give me a second to check this.' "
        "Be brief and helpful.\n\n"
        "Mandatory policies:\n"
        + "\n".join(f"- {line}" for line in policy_lines)
    )

    payload = {
        "model": SETTINGS.openai_model,
        "input": [
            {"role": "system", "content": system_prompt},
            *[{"role": m["role"], "content": m["content"]} for m in messages],
        ],
    }
    headers = {
        "Authorization": f"Bearer {SETTINGS.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        _debug("Requesting response from OpenAI", messages_count=len(messages), model=SETTINGS.openai_model)
        async with httpx.AsyncClient(timeout=SETTINGS.request_timeout_seconds) as client:
            res = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            res.raise_for_status()
            body = res.json()
            output_text = body.get("output_text", "").strip()
            if output_text:
                _debug("OpenAI responded", reply_chars=len(output_text))
                return output_text
    except Exception:
        logger.exception("OpenAI /v1/responses request failed; using fallback")

    # Defensive fallback if OpenAI fails or returns no usable text.
    return "Give me a second to check this."


def _append_manual_action(action_type: str, user_id: int, chat_id: int, context: Dict[str, Any]) -> None:
    data = _load_json(MANUAL_ACTIONS_PATH, {"actions": []})
    data["actions"].append(
        {
            "id": str(uuid.uuid4()),
            "type": action_type,
            "user_id": user_id,
            "chat_id": chat_id,
            "context": context,
            "created_at": _now_ts(),
            "status": "pending",
        }
    )
    _save_json(MANUAL_ACTIONS_PATH, data)
    logger.info("Manual action created (type=%s, user_id=%s, chat_id=%s)", action_type, user_id, chat_id)


def _append_pending_issue(user_id: int, chat_id: int, summary: str, conversation: List[Dict[str, Any]]) -> None:
    data = _load_json(PENDING_ISSUES_PATH, {"issues": []})
    data["issues"].append(
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "chat_id": chat_id,
            "summary": summary,
            "conversation": conversation,
            "status": "pending_review",
            "created_at": _now_ts(),
        }
    )
    _save_json(PENDING_ISSUES_PATH, data)
    logger.info("Pending issue recorded (user_id=%s, chat_id=%s, summary=%s)", user_id, chat_id, summary)


async def _handle_spam(user_id: int, chat_id: int) -> None:
    logger.warning("Message flagged as spam (user_id=%s, chat_id=%s)", user_id, chat_id)
    blocked = _load_json(BLOCKED_USERS_PATH, {"blocked": []})
    if user_id not in blocked["blocked"]:
        blocked["blocked"].append(user_id)
        _save_json(BLOCKED_USERS_PATH, blocked)

    try:
        await _telegram_request("banChatMember", {"chat_id": chat_id, "user_id": user_id})
    except Exception:
        logger.exception("Could not auto-block spam user (user_id=%s, chat_id=%s)", user_id, chat_id)
        _append_manual_action(
            "spam_report_required",
            user_id,
            chat_id,
            {
                "reason": "Could not auto-block/report through the API for this chat.",
                "suggested_message": "Possible spam detected at chat start. Review and report manually.",
            },
        )


async def _delayed_reply(chat_id: int, text: str, edit_message_id: Optional[int] = None) -> Optional[int]:
    _debug(
        "Scheduling delayed reply",
        chat_id=chat_id,
        delay_seconds=max(SETTINGS.bot_response_delay_seconds, 1),
        edit_message_id=edit_message_id,
    )
    await asyncio.sleep(max(SETTINGS.bot_response_delay_seconds, 1))

    if edit_message_id:
        try:
            await _telegram_request(
                "editMessageText",
                {"chat_id": chat_id, "message_id": edit_message_id, "text": text},
            )
            _debug("Message edited in Telegram", chat_id=chat_id, message_id=edit_message_id)
            return edit_message_id
        except Exception:
            logger.exception(
                "Message edit failed; sending a new message instead (chat_id=%s, message_id=%s)",
                chat_id,
                edit_message_id,
            )

    sent = await _telegram_request("sendMessage", {"chat_id": chat_id, "text": text})
    msg = sent.get("result", {})
    _debug("Message sent in Telegram", chat_id=chat_id, message_id=msg.get("message_id"))
    return msg.get("message_id")


class TelegramWebhookPayload(BaseModel):
    update_id: Optional[int] = None
    message: Optional[Dict[str, Any]] = None


class ManualResponseInput(BaseModel):
    chat_id: int
    text: str
    edit_message_id: Optional[int] = None


def _ensure_webhook_authorized(request: Request) -> None:
    """Validate Telegram secret token when configured."""
    expected = SETTINGS.telegram_webhook_secret
    if not expected:
        return

    provided = request.headers.get("x-telegram-bot-api-secret-token", "").strip()
    if provided != expected:
        logger.warning("Webhook rejected due to invalid secret (path=%s)", request.url.path)
        raise HTTPException(status_code=401, detail="Unauthorized webhook")


@APP.get("/answers_agent/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "has_telegram_bot_token": bool(SETTINGS.telegram_bot_token),
        "has_webhook_secret": bool(SETTINGS.telegram_webhook_secret),
        "has_openai_api_key": bool(SETTINGS.openai_api_key),
        "support_telegram_url": SUPPORT_GUIDANCE.telegram_support_url,
        "support_marketing_url": SUPPORT_GUIDANCE.marketing_url,
        "support_user_url_prefix": SUPPORT_GUIDANCE.user_url_prefix,
    }


@APP.get("/answers_agent/guidelines")
def get_guidelines() -> Dict[str, str]:
    files = ["behavior.md", "escalation.md", "spam_policy.md"]
    result: Dict[str, str] = {}
    for f in files:
        path = GUIDELINES_DIR / f
        result[f] = path.read_text(encoding="utf-8") if path.exists() else ""
    _debug("Guidelines requested", files=len(files))
    return result


@APP.post("/answers_agent/webhook/telegram")
async def telegram_webhook(
    payload: TelegramWebhookPayload,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Dict[str, Any]:
    _ensure_webhook_authorized(request)
    message = payload.message or {}
    text = (message.get("text") or "").strip()
    if not text:
        _debug("Webhook ignored due to non-text message")
        return {"ok": True, "ignored": "non-text-message"}
    if is_low_context_greeting(text):
        # Avoid unnecessary calls when there is no real support context.
        _debug("Webhook ignored due to low-context greeting")
        return {"ok": True, "ignored": "low-context-greeting"}

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    try:
        chat_id = int(chat.get("id"))
        user_id = int(from_user.get("id"))
    except Exception as err:
        logger.warning("Invalid webhook: missing chat_id/user_id (%s)", err)
        raise HTTPException(status_code=400, detail="Invalid Telegram payload") from err
    user_name = _resolve_user_display_name(from_user)
    _debug("Webhook received", chat_id=chat_id, user_id=user_id, user_name=user_name, text_chars=len(text))

    blocked = _load_json(BLOCKED_USERS_PATH, {"blocked": []})
    if user_id in blocked.get("blocked", []):
        _debug("Blocked user; message ignored", user_id=user_id, chat_id=chat_id)
        return {"ok": True, "ignored": "blocked-user"}

    if _looks_like_spam(text):
        background_tasks.add_task(_handle_spam, user_id, chat_id)
        _debug("Spam detected; block task queued in background", user_id=user_id, chat_id=chat_id)
        return {"ok": True, "action": "spam-detected"}

    conversations = _load_json(CONVERSATIONS_PATH, {"users": {}})
    users = conversations.setdefault("users", {})
    user_entry = users.setdefault(str(user_id), {"messages": [], "last_bot_message_id": None, "display_name": user_name})
    user_entry["display_name"] = user_name

    normalized = _normalize_text(text)
    repeated = any(m.get("normalized") == normalized and m.get("role") == "user" for m in user_entry["messages"])
    _debug("Message analyzed", repeated=repeated, history_messages=len(user_entry["messages"]))

    user_entry["messages"].append(
        {
            "role": "user",
            "content": text,
            "normalized": normalized,
            "chat_id": chat_id,
            "timestamp": _now_ts(),
            "name": user_name,
        }
    )

    if repeated:
        reply = "The dev team is checking."
        _debug("Repeat-message fallback applied", chat_id=chat_id)
    else:
        workflow_reply = match_support_workflow_reply(text, SUPPORT_GUIDANCE)
        if workflow_reply:
            reply = workflow_reply
            _debug("Support-workflow reply applied", chat_id=chat_id)
        else:
            context_window = user_entry["messages"][-8:]
            model_messages = [{"role": m["role"], "content": m["content"]} for m in context_window if m["role"] in {"user", "assistant"}]
            reply = await _openai_response(model_messages)
            if not reply:
                reply = "Give me a second to check this."
                _debug("OpenAI returned no usable response; fallback applied", chat_id=chat_id)

    if _contains_sensitive_request(reply):
        reply = "Give me a second to check this."
        logger.warning("Potentially sensitive response detected; replaced with fallback (chat_id=%s)", chat_id)

    bot_message_id = await _delayed_reply(chat_id, reply)
    user_entry["last_bot_message_id"] = bot_message_id
    user_entry["messages"].append(
        {
            "role": "assistant",
            "content": reply,
            "chat_id": chat_id,
            "message_id": bot_message_id,
            "timestamp": _now_ts(),
        }
    )

    if "dev team" in reply.lower() or "equipo" in reply.lower():
        _append_pending_issue(user_id, chat_id, "User issue pending follow-up", user_entry["messages"][-12:])

    _save_json(CONVERSATIONS_PATH, conversations)
    logger.info("Webhook processed successfully (chat_id=%s, user_id=%s, bot_message_id=%s)", chat_id, user_id, bot_message_id)
    return {"ok": True, "reply": reply}


@APP.post("/answers_agent/manual/respond")
async def manual_respond(input_data: ManualResponseInput) -> Dict[str, Any]:
    _debug("Manual response requested", chat_id=input_data.chat_id, edit_message_id=input_data.edit_message_id)
    message_id = await _delayed_reply(
        chat_id=input_data.chat_id,
        text=input_data.text,
        edit_message_id=input_data.edit_message_id,
    )

    conversations = _load_json(CONVERSATIONS_PATH, {"users": {}})
    for user_id, user_entry in conversations.get("users", {}).items():
        if user_entry.get("messages") and any(msg.get("chat_id") == input_data.chat_id for msg in user_entry["messages"]):
            user_entry["last_bot_message_id"] = message_id
            user_entry["messages"].append(
                {
                    "role": "assistant",
                    "content": input_data.text,
                    "chat_id": input_data.chat_id,
                    "message_id": message_id,
                    "timestamp": _now_ts(),
                    "manual": True,
                }
            )
            break
    _save_json(CONVERSATIONS_PATH, conversations)
    logger.info("Manual response sent (chat_id=%s, message_id=%s)", input_data.chat_id, message_id)

    return {"ok": True, "message_id": message_id}


@APP.get("/answers_agent/pending-issues")
def pending_issues() -> Dict[str, Any]:
    data = _load_json(PENDING_ISSUES_PATH, {"issues": []})
    _debug("Pending-issues queried", count=len(data.get("issues", [])))
    return data


@APP.get("/answers_agent/manual-actions")
def pending_manual_actions() -> Dict[str, Any]:
    data = _load_json(MANUAL_ACTIONS_PATH, {"actions": []})
    _debug("Manual-actions queried", count=len(data.get("actions", [])))
    return data
