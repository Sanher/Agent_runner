import logging
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from agents.support_guidance import (
    DEFAULT_SUPPORT_MARKETING_URL,
    DEFAULT_SUPPORT_TELEGRAM_URL,
    DEFAULT_SUPPORT_USER_URL_PREFIX,
    SupportGuidanceConfig,
    build_prompt_policy_lines,
    contains_sensitive_material,
    is_low_context_greeting,
    is_spam_like_message,
)


class AnswersAgentService:
    """Service to review and respond to answers_agent conversations grouped by chat."""
    # Retain archived conversations for one week, then purge automatically.
    ARCHIVE_RETENTION_SECONDS = 7 * 24 * 60 * 60

    def __init__(
        self,
        data_dir: Path,
        telegram_bot_token: str,
        openai_api_key: str,
        openai_model: str,
        request_timeout_seconds: int = 30,
        telegram_webhook_secret: str = "",
        support_telegram_url: str = DEFAULT_SUPPORT_TELEGRAM_URL,
        support_marketing_url: str = DEFAULT_SUPPORT_MARKETING_URL,
        support_user_url_prefix: str = DEFAULT_SUPPORT_USER_URL_PREFIX,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("agent_runner.answers_agent")
        self.data_dir = data_dir
        self.telegram_bot_token = str(telegram_bot_token or "").strip()
        self.openai_api_key = str(openai_api_key or "").strip()
        self.openai_model = str(openai_model or "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.request_timeout_seconds = max(5, int(request_timeout_seconds or 30))
        self.telegram_webhook_secret = str(telegram_webhook_secret or "").strip()
        self.support_guidance = SupportGuidanceConfig(
            telegram_support_url=str(support_telegram_url or DEFAULT_SUPPORT_TELEGRAM_URL).strip()
            or DEFAULT_SUPPORT_TELEGRAM_URL,
            marketing_url=str(support_marketing_url or DEFAULT_SUPPORT_MARKETING_URL).strip()
            or DEFAULT_SUPPORT_MARKETING_URL,
            user_url_prefix=str(support_user_url_prefix or DEFAULT_SUPPORT_USER_URL_PREFIX).strip()
            or DEFAULT_SUPPORT_USER_URL_PREFIX,
        )
        self._lock = threading.Lock()

        self.conversations_path = self.data_dir / "conversations.json"
        self.review_state_path = self.data_dir / "review_state.json"
        self.archived_chats_path = self.data_dir / "archived_chats.json"
        self.pending_issues_path = self.data_dir / "pending_issues.json"
        self.blocked_users_path = self.data_dir / "blocked_users.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_file(self.conversations_path, {"users": {}})
        self._ensure_file(self.review_state_path, {"chats": {}})
        self._ensure_file(self.archived_chats_path, {"items": []})
        self._ensure_file(self.pending_issues_path, {"issues": []})
        self._ensure_file(self.blocked_users_path, {"blocked": []})
        self._debug(
            "Answers service initialized",
            data_dir=str(self.data_dir),
            has_telegram_token=bool(self.telegram_bot_token),
            has_webhook_secret=bool(self.telegram_webhook_secret),
            has_openai_api_key=bool(self.openai_api_key),
            openai_model=self.openai_model,
            request_timeout_seconds=self.request_timeout_seconds,
        )

    @staticmethod
    def _ensure_file(path: Path, default_payload: Any) -> None:
        if path.exists():
            return
        path.write_text(json.dumps(default_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _load_json(path: Path, default_payload: Any) -> Any:
        if not path.exists():
            return default_payload
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default_payload

    @staticmethod
    def _save_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _now_ts() -> int:
        return int(time.time())

    def _debug(self, message: str, **meta: Any) -> None:
        # Extra diagnostic traces when LOG_LEVEL=DEBUG.
        suffix = " | " + ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        self.logger.debug("[DEBUG][answers_agent] %s%s", message, suffix)

    @staticmethod
    def _display_name_from_message(message: Dict[str, Any]) -> str:
        candidates = [
            message.get("name"),
            message.get("display_name"),
            message.get("user_name"),
            message.get("username"),
        ]
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _default_display_name(user_entry: Dict[str, Any], user_id: str) -> str:
        for key in ("display_name", "name", "username"):
            raw = str(user_entry.get(key, "")).strip()
            if raw:
                return raw
        return f"user_{user_id}"

    @staticmethod
    def _default_suggested_reply(received_messages: List[Dict[str, Any]]) -> str:
        if not received_messages:
            return "Give me a second to check this."
        return "Give me a second to check this."

    @staticmethod
    def _safe_chat_id(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").lower().strip())
        return re.sub(r"[^\w\sáéíóúüñ¿?¡!]", "", cleaned)

    @staticmethod
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

    def validate_telegram_webhook_secret(self, provided_secret: str) -> bool:
        expected = str(self.telegram_webhook_secret or "").strip()
        provided = str(provided_secret or "").strip()
        if not expected:
            return False
        return provided == expected

    def _append_pending_issue(
        self,
        user_id: int,
        chat_id: int,
        summary: str,
        conversation: List[Dict[str, Any]],
    ) -> None:
        with self._lock:
            data = self._load_json(self.pending_issues_path, {"issues": []})
            issues = data.setdefault("issues", [])
            if not isinstance(issues, list):
                issues = []
                data["issues"] = issues
            issues.append(
                {
                    "id": f"issue-{self._now_ts()}-{chat_id}",
                    "user_id": int(user_id),
                    "chat_id": int(chat_id),
                    "summary": str(summary or "").strip() or "User issue pending follow-up",
                    "conversation": conversation[-12:],
                    "status": "pending_review",
                    "created_at": self._now_ts(),
                }
            )
            self._save_json(self.pending_issues_path, data)

    def _mark_user_blocked(self, user_id: int) -> None:
        with self._lock:
            data = self._load_json(self.blocked_users_path, {"blocked": []})
            blocked = data.setdefault("blocked", [])
            if not isinstance(blocked, list):
                blocked = []
                data["blocked"] = blocked
            if int(user_id) not in blocked:
                blocked.append(int(user_id))
                self._save_json(self.blocked_users_path, data)

    def _is_user_blocked(self, user_id: int) -> bool:
        with self._lock:
            data = self._load_json(self.blocked_users_path, {"blocked": []})
        blocked = data.get("blocked", [])
        if not isinstance(blocked, list):
            return False
        return int(user_id) in blocked

    def _openai_support_reply(self, model_messages: List[Dict[str, str]]) -> Optional[str]:
        if not self.openai_api_key:
            return None

        policy_lines = build_prompt_policy_lines(self.support_guidance)
        system_prompt = (
            "You are a Telegram support assistant. "
            "Reply in English. "
            "If you are unsure, reply exactly: 'Give me a second to check this.' "
            "Be brief and helpful.\n\n"
            "Mandatory policies:\n"
            + "\n".join(f"- {line}" for line in policy_lines)
        )
        payload = {
            "model": self.openai_model,
            "input": [
                {"role": "system", "content": system_prompt},
                *[
                    {"role": item.get("role", "user"), "content": item.get("content", "")}
                    for item in model_messages
                ],
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        try:
            self._debug(
                "Requesting suggestion from OpenAI",
                model=self.openai_model,
                messages_count=len(model_messages),
            )
            response = httpx.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
            output_text = self._extract_responses_text(raw)
            if not output_text:
                diagnostics = self._responses_diagnostics(raw)
                self.logger.warning(
                    "OpenAI returned 200 but no usable text (diagnostics=%s)",
                    diagnostics,
                )
            else:
                self._debug(
                    "AI suggestion generated",
                    status=str(raw.get("status") or ""),
                    chars=len(output_text),
                )
            return output_text or None
        except httpx.HTTPStatusError as err:
            body_excerpt = ""
            try:
                body_excerpt = err.response.text[:500]
            except Exception:
                body_excerpt = ""
            self.logger.error(
                "HTTP error calling OpenAI responses (status=%s, body_excerpt=%s)",
                getattr(err.response, "status_code", "unknown"),
                body_excerpt,
            )
            return None
        except Exception:
            self.logger.exception("Failed to generate support response with OpenAI")
            return None

    @staticmethod
    def _extract_responses_text(payload: Dict[str, Any]) -> str:
        direct = str(payload.get("output_text") or "").strip()
        if direct:
            return direct

        # Some Responses API payloads provide text only inside output[].content[].
        output = payload.get("output")
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for chunk in content:
                    if not isinstance(chunk, dict):
                        continue
                    text = str(chunk.get("text") or "").strip()
                    if text:
                        parts.append(text)
            if parts:
                return "\n".join(parts).strip()

        return ""

    @staticmethod
    def _responses_diagnostics(payload: Dict[str, Any]) -> Dict[str, Any]:
        output = payload.get("output")
        output_types: List[str] = []
        content_types: List[str] = []
        content_items = 0
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                output_types.append(str(item.get("type") or ""))
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for chunk in content:
                    if not isinstance(chunk, dict):
                        continue
                    content_items += 1
                    content_types.append(str(chunk.get("type") or ""))

        error_obj = payload.get("error")
        error_type = ""
        error_code = ""
        if isinstance(error_obj, dict):
            error_type = str(error_obj.get("type") or "")
            error_code = str(error_obj.get("code") or "")

        return {
            "id": str(payload.get("id") or ""),
            "model": str(payload.get("model") or ""),
            "status": str(payload.get("status") or ""),
            "incomplete_details": payload.get("incomplete_details"),
            "error_type": error_type,
            "error_code": error_code,
            "output_items": len(output) if isinstance(output, list) else 0,
            "content_items": content_items,
            "output_types": sorted(set(filter(None, output_types))),
            "content_types": sorted(set(filter(None, content_types))),
        }

    def _chat_business_connection_id(self, chat_id: int) -> Optional[str]:
        with self._lock:
            review_state = self._load_review_state()
        chat_state = review_state.get("chats", {}).get(str(chat_id), {})
        if not isinstance(chat_state, dict):
            return None
        value = str(chat_state.get("business_connection_id") or "").strip()
        return value or None

    def process_telegram_update(self, update_payload: Dict[str, Any]) -> Dict[str, Any]:
        update = update_payload or {}
        message_kind = ""
        message: Dict[str, Any] = {}
        for candidate_key in ("message", "business_message", "edited_business_message"):
            candidate = update.get(candidate_key)
            if isinstance(candidate, dict):
                message_kind = candidate_key
                message = candidate
                break

        text = str(message.get("text") or "").strip()
        if not text:
            self._debug("Ignoring non-text Telegram update", source=message_kind or "unknown")
            return {"ok": True, "ignored": "non-text-message"}
        if is_low_context_greeting(text):
            self._debug("Ignoring low-context greeting", source=message_kind or "message")
            return {"ok": True, "ignored": "low-context-greeting"}

        chat = message.get("chat", {})
        from_user = message.get("from", {})
        try:
            chat_id = int(chat.get("id"))
            user_id = int(from_user.get("id"))
        except Exception as err:
            raise RuntimeError(f"Invalid Telegram payload: {err}") from err
        business_connection_id = str(
            message.get("business_connection_id")
            or update.get("business_connection_id")
            or ""
        ).strip()

        if self._is_user_blocked(user_id):
            self._debug("Ignoring message from blocked user", chat_id=chat_id, source=message_kind or "message")
            return {"ok": True, "ignored": "blocked-user"}

        user_name = self._resolve_user_display_name(from_user)
        normalized = self._normalize_text(text)

        with self._lock:
            conversations = self._load_json(self.conversations_path, {"users": {}})
            users = conversations.setdefault("users", {})
            user_entry = users.setdefault(
                str(user_id),
                {"messages": [], "last_bot_message_id": None, "display_name": user_name},
            )
            user_entry["display_name"] = user_name
            messages = user_entry.setdefault("messages", [])
            if not isinstance(messages, list):
                messages = []
                user_entry["messages"] = messages
            user_record = {
                "role": "user",
                "content": text,
                "normalized": normalized,
                "chat_id": int(chat_id),
                "timestamp": self._now_ts(),
                "name": user_name,
            }
            if business_connection_id:
                user_record["business_connection_id"] = business_connection_id
            messages.append(user_record)
            self._save_json(self.conversations_path, conversations)

        if is_spam_like_message(text):
            self._mark_user_blocked(user_id)
            self._persist_chat_review_state(
                chat_id,
                suggested_reply="",
                status="reviewed",
                extra={"blocked": True, "blocked_reason": "spam"},
            )
            self.logger.warning("Spam-like message detected and blocked (chat_id=%s, user_id=%s)", chat_id, user_id)
            return {"ok": True, "action": "spam-detected"}

        # Manual mode: do not auto-generate AI/workflow suggestions on webhook intake.
        # Suggested text is generated only via "AI suggest" or manual edit actions.
        reply = "Give me a second to check this."

        if contains_sensitive_material(reply):
            reply = ""

        self._persist_chat_review_state(
            chat_id,
            suggested_reply=reply,
            status="pending",
            extra={
                "last_received_ts": self._now_ts(),
                "business_connection_id": business_connection_id or "",
                "source": message_kind or "message",
                "manual_review_required": True,
            },
        )
        self._debug(
            "Message queued for manual review",
            chat_id=chat_id,
            source=message_kind or "message",
            has_suggested_reply=bool(str(reply or "").strip()),
        )

        return {
            "ok": True,
            "queued_for_review": True,
            "status": "pending",
            "has_suggested_reply": bool(str(reply or "").strip()),
        }

    def _load_review_state(self) -> Dict[str, Any]:
        raw = self._load_json(self.review_state_path, {"chats": {}})
        if not isinstance(raw, dict):
            return {"chats": {}}
        chats = raw.get("chats", {})
        if not isinstance(chats, dict):
            chats = {}
        return {"chats": chats}

    def _save_review_state(self, review_state: Dict[str, Any]) -> None:
        self._save_json(self.review_state_path, review_state)

    def _load_archived_chats(self) -> Dict[str, Any]:
        raw = self._load_json(self.archived_chats_path, {"items": []})
        if not isinstance(raw, dict):
            return {"items": []}
        items = raw.get("items", [])
        if not isinstance(items, list):
            items = []
        return {"items": items}

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _prune_archived_items(self, items: List[Dict[str, Any]], now_ts: int) -> List[Dict[str, Any]]:
        threshold = max(0, int(now_ts) - self.ARCHIVE_RETENTION_SECONDS)
        kept: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            archived_at = self._as_int(item.get("archived_at"), 0)
            if archived_at <= 0:
                continue
            if archived_at >= threshold:
                kept.append(item)
        return kept

    def _archive_chat_snapshot(self, chat: Dict[str, Any], archived_reason: str = "reviewed") -> Dict[str, Any]:
        now_ts = self._now_ts()
        chat_id = self._as_int(chat.get("chat_id"), 0)
        snapshot = {
            "archive_id": f"arch-{now_ts}-{chat_id}",
            "chat_id": chat_id,
            "user_id": str(chat.get("user_id") or ""),
            "name": str(chat.get("name") or ""),
            "status": str(chat.get("status") or "reviewed"),
            "received_count": self._as_int(chat.get("received_count"), 0),
            "last_received_ts": self._as_int(chat.get("last_received_ts"), 0),
            "received_messages": list(chat.get("received_messages") or [])[-50:],
            "suggested_reply": str(chat.get("suggested_reply") or ""),
            "updated_at": str(chat.get("updated_at") or ""),
            "archived_reason": str(archived_reason or "reviewed"),
            "archived_at": now_ts,
        }
        with self._lock:
            data = self._load_archived_chats()
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            before_prune = len(items)
            items = self._prune_archived_items(items, now_ts)
            pruned_count = max(0, before_prune - len(items))
            if pruned_count:
                self._debug("Archived retention cleanup applied", removed=pruned_count)

            replaced = False
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                # If we archive the same chat snapshot again, overwrite it in place.
                if (
                    self._as_int(item.get("chat_id"), -1) == chat_id
                    and self._as_int(item.get("last_received_ts"), -1) == snapshot["last_received_ts"]
                ):
                    archive_id = str(item.get("archive_id") or "").strip()
                    if archive_id:
                        snapshot["archive_id"] = archive_id
                    items[idx] = snapshot
                    replaced = True
                    break

            if not replaced:
                items.append(snapshot)

            data["items"] = items
            self._save_json(self.archived_chats_path, data)
        self._debug(
            "Chat archived",
            chat_id=chat_id,
            archived_total=len(items),
            archived_reason=snapshot["archived_reason"],
        )
        return snapshot

    def list_archived_chats(self) -> List[Dict[str, Any]]:
        now_ts = self._now_ts()
        with self._lock:
            data = self._load_archived_chats()
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            before_prune = len(items)
            filtered = self._prune_archived_items(items, now_ts)
            pruned_count = max(0, before_prune - len(filtered))
            if len(filtered) != len(items):
                data["items"] = filtered
                self._save_json(self.archived_chats_path, data)
            if pruned_count:
                self._debug("Archived retention cleanup applied", removed=pruned_count)
        filtered.sort(key=lambda item: self._as_int(item.get("archived_at"), 0), reverse=True)
        self._debug("Archived chats loaded", archived_count=len(filtered))
        return filtered

    def _chat_context(self, chat_id: int) -> Dict[str, Any]:
        for chat in self.list_chats_grouped():
            if int(chat["chat_id"]) == int(chat_id):
                return chat
        self.logger.warning("Chat not found in answers_agent (chat_id=%s)", chat_id)
        raise RuntimeError(f"Chat not found: {chat_id}")

    def _chat_context_including_reviewed(self, chat_id: int) -> Dict[str, Any]:
        for chat in self._build_grouped_chats(include_reviewed=True):
            if int(chat["chat_id"]) == int(chat_id):
                return chat
        self.logger.warning("Chat not found in answers_agent (chat_id=%s)", chat_id)
        raise RuntimeError(f"Chat not found: {chat_id}")

    def _build_grouped_chats(self, include_reviewed: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            conversations = self._load_json(self.conversations_path, {"users": {}})
            review_state = self._load_review_state()

        users = conversations.get("users", {})
        if not isinstance(users, dict):
            users = {}

        grouped: Dict[str, Dict[str, Any]] = {}
        for user_id, user_entry in users.items():
            if not isinstance(user_entry, dict):
                continue
            messages = user_entry.get("messages", [])
            if not isinstance(messages, list):
                continue
            fallback_name = self._default_display_name(user_entry, str(user_id))
            for message in messages:
                if not isinstance(message, dict):
                    continue
                chat_id = message.get("chat_id")
                if chat_id is None:
                    continue
                numeric_chat_id = self._safe_chat_id(chat_id)
                if numeric_chat_id is None:
                    continue
                chat_key = str(numeric_chat_id)
                role = str(message.get("role", "")).strip().lower()
                content = str(message.get("content", "")).strip()
                timestamp = int(message.get("timestamp") or 0)
                grouped_chat = grouped.setdefault(
                    chat_key,
                    {
                        "chat_id": numeric_chat_id,
                        "user_id": str(user_id),
                        "name": fallback_name,
                        "received_messages": [],
                        "context_messages": [],
                        "last_received_ts": 0,
                        "last_assistant_reply": "",
                    },
                )

                if role in {"user", "assistant"} and content:
                    grouped_chat["context_messages"].append(
                        {
                            "role": role,
                            "content": content,
                            "timestamp": timestamp,
                        }
                    )

                if role == "user":
                    name = self._display_name_from_message(message) or grouped_chat["name"] or fallback_name
                    grouped_chat["name"] = name
                    grouped_chat["received_messages"].append(
                        {
                            "content": content,
                            "timestamp": timestamp,
                            "chat_id": numeric_chat_id,
                            "user_id": str(user_id),
                            "name": name,
                        }
                    )
                    grouped_chat["last_received_ts"] = max(grouped_chat["last_received_ts"], timestamp)
                elif role == "assistant" and content:
                    grouped_chat["last_assistant_reply"] = content

        items: List[Dict[str, Any]] = []
        review_chats = review_state.get("chats", {})
        if not isinstance(review_chats, dict):
            review_chats = {}

        hidden_reviewed = 0
        for chat_key, chat in grouped.items():
            received = sorted(chat["received_messages"], key=lambda item: int(item.get("timestamp") or 0))
            context = sorted(chat["context_messages"], key=lambda item: int(item.get("timestamp") or 0))
            state = review_chats.get(chat_key, {})
            if not isinstance(state, dict):
                state = {}
            status = str(state.get("status") or "pending").strip() or "pending"
            reviewed_snapshot_ts = int(state.get("reviewed_last_received_ts") or 0)
            current_last_received_ts = int(chat.get("last_received_ts") or 0)
            if (
                not include_reviewed
                and status == "reviewed"
                and reviewed_snapshot_ts > 0
                and current_last_received_ts <= reviewed_snapshot_ts
            ):
                # Hide reviewed chats until a new incoming message arrives.
                hidden_reviewed += 1
                continue

            suggested_reply = str(
                state.get("suggested_reply")
                or chat.get("last_assistant_reply")
                or self._default_suggested_reply(received)
            ).strip()
            updated_at = str(state.get("updated_at") or "")

            items.append(
                {
                    "chat_id": int(chat["chat_id"]),
                    "user_id": str(chat["user_id"]),
                    "name": str(chat["name"] or f"user_{chat['user_id']}"),
                    "status": status,
                    "updated_at": updated_at,
                    "last_received_ts": int(chat.get("last_received_ts") or 0),
                    "received_count": len(received),
                    "received_messages": received[-50:],
                    "suggested_reply": suggested_reply,
                    "context_messages": context[-16:],
                }
            )

        items.sort(key=lambda item: int(item.get("last_received_ts") or 0), reverse=True)
        self._debug(
            "Grouped chats loaded",
            chats=len(items),
            users=len(users),
            review_chats=len(review_chats),
            hidden_reviewed=hidden_reviewed,
        )
        return items

    def list_chats_grouped(self) -> List[Dict[str, Any]]:
        return self._build_grouped_chats(include_reviewed=False)

    def _persist_chat_review_state(
        self,
        chat_id: int,
        *,
        suggested_reply: Optional[str] = None,
        status: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            review_state = self._load_review_state()
            chats = review_state.setdefault("chats", {})
            chat_key = str(chat_id)
            current = chats.get(chat_key, {}) if isinstance(chats.get(chat_key), dict) else {}
            if suggested_reply is not None:
                current["suggested_reply"] = str(suggested_reply)
            if status is not None:
                current["status"] = str(status)
            if extra:
                for key, value in extra.items():
                    current[key] = value
            current["updated_at"] = datetime.now().isoformat()
            chats[chat_key] = current
            self._save_review_state(review_state)
            self._debug(
                "Review state updated",
                chat_id=chat_id,
                status=current.get("status", ""),
                has_suggested_reply=bool(str(current.get("suggested_reply", "")).strip()),
            )
            return dict(current)

    def _rewrite_reply_with_openai(
        self,
        context_messages: List[Dict[str, Any]],
        current_reply: str,
        instruction: str,
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("answers_openai_api_key is not configured")

        context_lines: List[str] = []
        for item in context_messages[-12:]:
            role = str(item.get("role", "user")).strip().lower()
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            prefix = "User" if role == "user" else "Agent"
            context_lines.append(f"{prefix}: {content}")

        prompt = (
            "Rewrite the suggested reply for Telegram.\n"
            "Rules: keep it short, clear, avoid sensitive data requests, and use English.\n"
            "Return only the final reply text.\n\n"
            f"Context:\n{chr(10).join(context_lines) or '(no context)'}\n\n"
            f"Current reply:\n{current_reply}\n\n"
            f"Reviewer instruction:\n{instruction}"
        )
        self._debug(
            "Requesting rewrite from OpenAI",
            context_messages=min(len(context_messages), 12),
            instruction_chars=len(instruction),
        )

        try:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.openai_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a Telegram support reviewer. "
                                "Do not request sensitive information. "
                                "Keep responses short and actionable."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
        except Exception:
            self.logger.exception("Failed to rewrite response with OpenAI")
            raise
        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        rewritten = str(content or "").strip()
        if not rewritten:
            raise RuntimeError("OpenAI returned empty reply")
        self._debug("Response rewritten", reply_chars=len(rewritten))
        return rewritten

    def suggest_changes(self, chat_id: int, instruction: str) -> Dict[str, Any]:
        clean_instruction = str(instruction or "").strip()
        if not clean_instruction:
            raise RuntimeError("instruction is required")

        chat = self._chat_context(chat_id)
        current_reply = str(chat.get("suggested_reply", "")).strip() or "Give me a second to check this."
        rewritten = self._rewrite_reply_with_openai(
            context_messages=chat.get("context_messages", []),
            current_reply=current_reply,
            instruction=clean_instruction,
        )
        state = self._persist_chat_review_state(
            chat_id,
            suggested_reply=rewritten,
            status="draft",
        )
        self.logger.info("Suggestion updated for chat_id=%s", chat_id)
        return {
            "chat_id": int(chat_id),
            "suggested_reply": rewritten,
            "status": state.get("status", "draft"),
            "updated_at": state.get("updated_at", ""),
        }

    def suggest_ai(self, chat_id: int) -> Dict[str, Any]:
        chat = self._chat_context_including_reviewed(chat_id)
        context_messages = [
            {"role": str(item.get("role", "")), "content": str(item.get("content", "")).strip()}
            for item in chat.get("context_messages", [])
            if str(item.get("role", "")) in {"user", "assistant"} and str(item.get("content", "")).strip()
        ]
        if not context_messages:
            raise RuntimeError("chat has no context")

        suggested = self._openai_support_reply(context_messages)
        if not suggested:
            self.logger.warning(
                "Manual AI suggestion returned no usable text (chat_id=%s, context_messages=%s)",
                chat_id,
                len(context_messages),
            )
            raise RuntimeError("openai suggestion unavailable")
        if contains_sensitive_material(suggested):
            self.logger.warning("Manual AI suggestion blocked by sensitive policy (chat_id=%s)", chat_id)
            raise RuntimeError("openai suggestion blocked by sensitive policy")

        state = self._persist_chat_review_state(
            chat_id,
            suggested_reply=suggested,
            status="draft",
            extra={"manual_review_required": True, "suggested_by": "manual_ai"},
        )
        self.logger.info("Manual AI suggestion generated for chat_id=%s", chat_id)
        return {
            "chat_id": int(chat_id),
            "suggested_reply": suggested,
            "status": state.get("status", "draft"),
            "updated_at": state.get("updated_at", ""),
        }

    def _append_sent_reply_to_conversation(self, chat_id: int, text: str, message_id: Optional[int]) -> None:
        with self._lock:
            conversations = self._load_json(self.conversations_path, {"users": {}})
            users = conversations.setdefault("users", {})
            target_user_entry: Optional[Dict[str, Any]] = None
            for _, entry in users.items():
                if not isinstance(entry, dict):
                    continue
                messages = entry.get("messages", [])
                if not isinstance(messages, list):
                    continue
                if any(
                    self._safe_chat_id(msg.get("chat_id")) == int(chat_id)
                    for msg in messages
                    if isinstance(msg, dict)
                ):
                    target_user_entry = entry
                    break

            if target_user_entry is None:
                synthetic_user_id = f"chat_{chat_id}"
                target_user_entry = users.setdefault(
                    synthetic_user_id,
                    {"messages": [], "last_bot_message_id": None, "display_name": synthetic_user_id},
                )

            target_user_entry.setdefault("messages", [])
            target_user_entry["messages"].append(
                {
                    "role": "assistant",
                    "content": text,
                    "chat_id": int(chat_id),
                    "message_id": message_id,
                    "timestamp": self._now_ts(),
                    "manual": True,
                }
            )
            target_user_entry["last_bot_message_id"] = message_id
            self._save_json(self.conversations_path, conversations)
            self._debug(
                "Manual reply appended to conversation",
                chat_id=chat_id,
                message_id=message_id,
            )

    def _send_telegram_message(
        self,
        chat_id: int,
        text: str,
        business_connection_id: Optional[str] = None,
    ) -> Optional[int]:
        if not self.telegram_bot_token:
            raise RuntimeError("answers_telegram_bot_token is not configured")
        payload: Dict[str, Any] = {"chat_id": int(chat_id), "text": text}
        if business_connection_id:
            payload["business_connection_id"] = str(business_connection_id).strip()
        self._debug(
            "Sending message to Telegram",
            chat_id=chat_id,
            text_chars=len(text),
            has_business_connection_id=bool(payload.get("business_connection_id")),
        )
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                json=payload,
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self.logger.exception("Failed sending reply to Telegram (chat_id=%s)", chat_id)
            raise
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        try:
            message_id = int(result.get("message_id")) if result.get("message_id") is not None else None
            self._debug("Message sent to Telegram", chat_id=chat_id, message_id=message_id)
            return message_id
        except Exception:
            return None

    def send_reply(self, chat_id: int, text: str) -> Dict[str, Any]:
        body = str(text or "").strip()
        if not body:
            raise RuntimeError("text is required")
        self._chat_context_including_reviewed(chat_id)
        business_connection_id = self._chat_business_connection_id(chat_id)
        message_id = self._send_telegram_message(
            chat_id,
            body,
            business_connection_id=business_connection_id,
        )
        self._append_sent_reply_to_conversation(chat_id, body, message_id)
        state = self._persist_chat_review_state(
            chat_id,
            suggested_reply=body,
            status="sent",
            extra={
                "last_sent_ts": self._now_ts(),
                "last_message_id": message_id,
                "business_connection_id": business_connection_id or "",
                "manual_review_required": False,
            },
        )
        self.logger.info("Reply sent for chat_id=%s (message_id=%s)", chat_id, message_id)
        return {
            "chat_id": int(chat_id),
            "message_id": message_id,
            "status": state.get("status", "sent"),
            "suggested_reply": body,
            "updated_at": state.get("updated_at", ""),
        }

    def mark_chat_status(self, chat_id: int, status: str) -> Dict[str, Any]:
        normalized = str(status or "").strip().lower()
        valid = {"pending", "draft", "reviewed", "sent"}
        if normalized not in valid:
            raise RuntimeError(f"status must be one of {sorted(valid)}")
        chat = self._chat_context_including_reviewed(chat_id)
        extra: Dict[str, Any] = {}
        if normalized == "reviewed":
            extra["reviewed_last_received_ts"] = int(chat.get("last_received_ts") or 0)
            extra["manual_review_required"] = False
            self._archive_chat_snapshot(chat, archived_reason="reviewed")
        state = self._persist_chat_review_state(
            chat_id,
            suggested_reply=str(chat.get("suggested_reply", "")),
            status=normalized,
            extra=extra,
        )
        self.logger.info("Chat status updated (chat_id=%s, status=%s)", chat_id, normalized)
        return {
            "chat_id": int(chat_id),
            "status": state.get("status", normalized),
            "updated_at": state.get("updated_at", ""),
        }

    def get_debug_status(self) -> Dict[str, Any]:
        # Quick diagnostic summary for HA without manual file inspection.
        items = self.list_chats_grouped()
        archived_items = self.list_archived_chats()
        return {
            "ok": True,
            "data_dir": str(self.data_dir),
            "conversations_path": str(self.conversations_path),
            "review_state_path": str(self.review_state_path),
            "archived_chats_path": str(self.archived_chats_path),
            "pending_issues_path": str(self.pending_issues_path),
            "blocked_users_path": str(self.blocked_users_path),
            "has_openai_api_key": bool(self.openai_api_key),
            "has_telegram_token": bool(self.telegram_bot_token),
            "has_webhook_secret": bool(self.telegram_webhook_secret),
            "chats_count": len(items),
            "archived_count": len(archived_items),
            "pending_count": sum(1 for item in items if str(item.get("status", "")) == "pending"),
            "draft_count": sum(1 for item in items if str(item.get("status", "")) == "draft"),
            "reviewed_count": sum(1 for item in items if str(item.get("status", "")) == "reviewed"),
            "sent_count": sum(1 for item in items if str(item.get("status", "")) == "sent"),
        }
