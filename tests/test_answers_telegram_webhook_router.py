import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.answers_agent.service import AnswersAgentService
    from routers.answers_agent import create_answers_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class AnswersTelegramWebhookRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name)
        self.service = AnswersAgentService(
            data_dir=self.data_dir,
            telegram_bot_token="bot-token",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            telegram_webhook_secret="my-telegram-secret",
        )
        self.service._send_telegram_message = lambda chat_id, text, business_connection_id=None: 777
        app = FastAPI()
        app.include_router(
            create_answers_router(
                service=self.service,
                job_secret="top-secret",
                telegram_webhook_secrets=("my-telegram-secret",),
            )
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_webhook_rejects_invalid_secret(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 1,
                "message": {"text": "social update", "chat": {"id": 1001}, "from": {"id": 2002}},
            },
            headers={"x-telegram-bot-api-secret-token": "wrong-secret"},
        )
        self.assertEqual(response.status_code, 401)

    def test_webhook_accepts_message_when_secret_matches(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 2,
                "message": {"text": "social update", "chat": {"id": 1001}, "from": {"id": 2002}},
            },
            headers={"x-telegram-bot-api-secret-token": "my-telegram-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("queued_for_review"))
        self.assertEqual(payload.get("status"), "pending")
        self.assertTrue(payload.get("has_suggested_reply"))

        conversations = json.loads(self.service.conversations_path.read_text(encoding="utf-8"))
        user_messages = conversations.get("users", {}).get("2002", {}).get("messages", [])
        self.assertEqual(len(user_messages), 1)
        self.assertEqual(user_messages[0].get("role"), "user")

        review_state = json.loads(self.service.review_state_path.read_text(encoding="utf-8"))
        chat_state = review_state.get("chats", {}).get("1001", {})
        self.assertEqual(chat_state.get("status"), "pending")
        self.assertTrue(chat_state.get("suggested_reply"))

    def test_webhook_accepts_business_message(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 3,
                "business_message": {
                    "text": "social update",
                    "business_connection_id": "bc-123",
                    "chat": {"id": 3003},
                    "from": {"id": 4004},
                },
            },
            headers={"x-telegram-bot-api-secret-token": "my-telegram-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))

        conversations = json.loads(self.service.conversations_path.read_text(encoding="utf-8"))
        messages = conversations.get("users", {}).get("4004", {}).get("messages", [])
        self.assertTrue(any(item.get("business_connection_id") == "bc-123" for item in messages))

        review_state = json.loads(self.service.review_state_path.read_text(encoding="utf-8"))
        chat_state = review_state.get("chats", {}).get("3003", {})
        self.assertEqual(chat_state.get("business_connection_id"), "bc-123")

    def test_webhook_keeps_manual_review_mode_without_auto_openai(self) -> None:
        def _unexpected_openai_call(*args, **kwargs):
            raise AssertionError("OpenAI should not be called from webhook intake in manual mode")

        self.service._openai_support_reply = _unexpected_openai_call
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 4,
                "message": {"text": "I need help with social update", "chat": {"id": 5005}, "from": {"id": 6006}},
            },
            headers={"x-telegram-bot-api-secret-token": "my-telegram-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("queued_for_review"))
        self.assertEqual(payload.get("status"), "pending")
        self.assertTrue(payload.get("has_suggested_reply"))

        conversations = json.loads(self.service.conversations_path.read_text(encoding="utf-8"))
        user_messages = conversations.get("users", {}).get("6006", {}).get("messages", [])
        self.assertEqual([item.get("role") for item in user_messages], ["user"])

        review_state = json.loads(self.service.review_state_path.read_text(encoding="utf-8"))
        chat_state = review_state.get("chats", {}).get("5005", {})
        self.assertEqual(chat_state.get("status"), "pending")
        self.assertEqual(chat_state.get("suggested_reply"), "Give me a second to check this.")
        self.assertTrue(chat_state.get("manual_review_required"))

    def test_webhook_marks_spam_as_blocked_and_hides_from_active_list(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 5,
                "message": {"text": "QA promo for my token, buy now", "chat": {"id": 7007}, "from": {"id": 8008}},
            },
            headers={"x-telegram-bot-api-secret-token": "my-telegram-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("action"), "spam-detected")
        self.assertEqual(payload.get("status"), "spam")
        self.assertEqual(payload.get("spam_source"), "auto_rule")

        review_state = json.loads(self.service.review_state_path.read_text(encoding="utf-8"))
        chat_state = review_state.get("chats", {}).get("7007", {})
        self.assertEqual(chat_state.get("status"), "spam")
        self.assertEqual(chat_state.get("blocked_reason"), "spam")
        self.assertFalse(chat_state.get("manual_review_required"))
        self.assertGreater(int(chat_state.get("reviewed_last_received_ts") or 0), 0)

        active_chats = self.service.list_chats_grouped()
        self.assertEqual(len(active_chats), 0)

        archived = self.service.list_archived_chats()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].get("chat_id"), 7007)
        self.assertEqual(archived[0].get("archived_reason"), "spam_auto")

        spam_patterns = json.loads(self.service.spam_patterns_path.read_text(encoding="utf-8"))
        items = spam_patterns.get("items", [])
        self.assertEqual(len(items), 1)
        pattern = items[0]
        self.assertTrue(pattern.get("signature"))
        self.assertGreater(int(pattern.get("hits") or 0), 0)
        self.assertNotIn("text", pattern)
        self.assertNotIn("content", pattern)
        self.assertNotIn("message", pattern)


if __name__ == "__main__":
    unittest.main()
