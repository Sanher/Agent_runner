import unittest
from copy import deepcopy

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.email_agent import create_email_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


class _FakeEmailService:
    def __init__(self) -> None:
        self._items = [
            {
                "suggestion_id": "s-1",
                "email_id": "m-1",
                "from": "alerts@example.com",
                "subject": "Subject 1",
                "date": "2026-02-17T20:00:00",
                "original_body": "Body 1",
                "suggested_reply": "Reply 1",
                "status": "draft",
                "created_at": "2026-02-17T20:00:00",
                "updated_at": "2026-02-17T20:00:00",
            },
            {
                "suggestion_id": "s-2",
                "email_id": "m-2",
                "from": "alerts@example.com",
                "subject": "Subject 2",
                "date": "2026-02-17T20:01:00",
                "original_body": "Body 2",
                "suggested_reply": "Reply 2",
                "status": "draft",
                "created_at": "2026-02-17T20:01:00",
                "updated_at": "2026-02-17T20:01:00",
            },
        ]

    def check_new_and_suggest(self, **kwargs):
        return []

    def load_suggestions(self):
        return deepcopy(self._items)

    def save_suggestions(self, suggestions):
        self._items = deepcopy(suggestions)

    def regenerate_suggestion(self, suggestion_id: str, instruction: str):
        raise RuntimeError("Not used in this test")

    def create_suggestion_from_text(self, **kwargs):
        raise RuntimeError("Not used in this test")

    def get_settings(self):
        return {"allowed_from_whitelist": []}

    def update_settings(self, items):
        return {"allowed_from_whitelist": items}


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class EmailMarkReviewedTests(unittest.TestCase):
    def _build_client(self):
        service = _FakeEmailService()
        app = FastAPI()
        app.include_router(
            create_email_router(
                service=service,
                job_secret="top-secret",
                missing_config_fn=lambda: [],
            )
        )
        return TestClient(app), service

    def test_mark_reviewed_removes_suggestion_from_active_list(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/email-agent/suggestions/s-1/status?secret=top-secret",
            json={"status": "reviewed"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["removed"])
        self.assertEqual(payload["item"]["status"], "reviewed")
        remaining_ids = {item["suggestion_id"] for item in service._items}
        self.assertNotIn("s-1", remaining_ids)
        self.assertIn("s-2", remaining_ids)

    def test_mark_copied_keeps_suggestion(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/email-agent/suggestions/s-2/status?secret=top-secret",
            json={"status": "copied"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["removed"])
        updated = [item for item in service._items if item["suggestion_id"] == "s-2"][0]
        self.assertEqual(updated["status"], "copied")


if __name__ == "__main__":
    unittest.main()
