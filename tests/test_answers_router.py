import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.answers_agent import create_answers_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


class _FakeAnswersService:
    def __init__(self) -> None:
        self.chats = [
            {
                "chat_id": 1001,
                "user_id": "55",
                "name": "Alice",
                "status": "pending",
                "updated_at": "2026-02-18T11:10:00",
                "last_received_ts": 1739873400,
                "received_count": 2,
                "received_messages": [
                    {"content": "Hola", "timestamp": 1739873000, "chat_id": 1001, "user_id": "55", "name": "Alice"},
                    {"content": "¿Hay update?", "timestamp": 1739873400, "chat_id": 1001, "user_id": "55", "name": "Alice"},
                ],
                "suggested_reply": "Estamos revisándolo y te avisamos en breve.",
                "context_messages": [],
            }
        ]
        self.archived_chats = [
            {
                "archive_id": "arch-1",
                "chat_id": 1001,
                "user_id": "55",
                "name": "Alice",
                "status": "reviewed",
                "received_count": 2,
                "last_received_ts": 1739873400,
                "received_messages": [
                    {"content": "Hello", "timestamp": 1739873000, "chat_id": 1001, "user_id": "55", "name": "Alice"},
                    {"content": "Any update?", "timestamp": 1739873400, "chat_id": 1001, "user_id": "55", "name": "Alice"},
                ],
                "suggested_reply": "We are checking this.",
                "archived_reason": "reviewed",
                "archived_at": 1739873500,
            }
        ]

    def list_chats_grouped(self):
        return self.chats

    def list_archived_chats(self):
        return self.archived_chats

    def suggest_changes(self, chat_id: int, instruction: str):
        if int(chat_id) != 1001:
            raise RuntimeError(f"Chat not found: {chat_id}")
        self.chats[0]["suggested_reply"] = f"{self.chats[0]['suggested_reply']} ({instruction})"
        self.chats[0]["status"] = "draft"
        return {
            "chat_id": 1001,
            "suggested_reply": self.chats[0]["suggested_reply"],
            "status": "draft",
            "updated_at": "2026-02-18T11:12:00",
        }

    def suggest_ai(self, chat_id: int):
        if int(chat_id) != 1001:
            raise RuntimeError(f"Chat not found: {chat_id}")
        self.chats[0]["suggested_reply"] = "Sugerencia IA manual"
        self.chats[0]["status"] = "draft"
        return {
            "chat_id": 1001,
            "suggested_reply": self.chats[0]["suggested_reply"],
            "status": "draft",
            "updated_at": "2026-02-18T11:12:30",
        }

    def send_reply(self, chat_id: int, text: str):
        if int(chat_id) != 1001:
            raise RuntimeError(f"Chat not found: {chat_id}")
        if not str(text).strip():
            raise RuntimeError("text is required")
        self.chats[0]["status"] = "sent"
        self.chats[0]["suggested_reply"] = text
        return {
            "chat_id": 1001,
            "message_id": 777,
            "status": "sent",
            "suggested_reply": text,
            "updated_at": "2026-02-18T11:13:00",
        }

    def mark_chat_status(self, chat_id: int, status: str):
        if int(chat_id) != 1001:
            raise RuntimeError(f"Chat not found: {chat_id}")
        self.chats[0]["status"] = status
        return {"chat_id": 1001, "status": status, "updated_at": "2026-02-18T11:14:00"}

    openai_api_key = ""
    telegram_bot_token = ""
    data_dir = "/tmp/answers-agent-tests"


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class AnswersRouterTests(unittest.TestCase):
    def _build_client(self):
        service = _FakeAnswersService()
        app = FastAPI()
        app.include_router(create_answers_router(service=service, job_secret="top-secret"))
        return TestClient(app), service

    def test_list_chats_grouped(self) -> None:
        client, _ = self._build_client()
        response = client.get("/answers-agent/chats?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["chat_id"], 1001)
        self.assertEqual(payload["items"][0]["received_count"], 2)

    def test_mark_chat_status_reviewed(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/answers-agent/chats/1001/status?secret=top-secret",
            json={"status": "reviewed"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["status"], "reviewed")
        self.assertEqual(service.chats[0]["status"], "reviewed")

    def test_list_archived_chats(self) -> None:
        client, _ = self._build_client()
        response = client.get("/answers-agent/chats/archived?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["chat_id"], 1001)
        self.assertEqual(payload["items"][0]["archived_reason"], "reviewed")

    def test_suggest_changes_not_found_returns_404(self) -> None:
        client, _ = self._build_client()
        response = client.post(
            "/answers-agent/chats/9999/suggest?secret=top-secret",
            json={"instruction": "Hazla más breve"},
        )
        self.assertEqual(response.status_code, 404)

    def test_suggest_ai_endpoint(self) -> None:
        client, service = self._build_client()
        response = client.post("/answers-agent/chats/1001/suggest-ai?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["status"], "draft")
        self.assertEqual(service.chats[0]["suggested_reply"], "Sugerencia IA manual")

    def test_requires_secret_when_configured(self) -> None:
        client, _ = self._build_client()
        response = client.get("/answers-agent/chats")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
