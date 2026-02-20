import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.email_agent import create_email_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


class _FakeEmailService:
    def __init__(self) -> None:
        self.last_call = None

    def send_suggestion_email(self, suggestion_id: str, to_email: str, body: str, cc_email: str = None):
        self.last_call = {
            "suggestion_id": suggestion_id,
            "to_email": to_email,
            "body": body,
            "cc_email": cc_email,
        }
        if suggestion_id == "missing":
            raise RuntimeError("Suggestion not found: missing")
        if to_email == "bad-email":
            raise RuntimeError("Invalid recipient email")
        return {
            "suggestion_id": suggestion_id,
            "status": "sent",
            "sent_to": to_email,
        }


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class EmailSendTests(unittest.TestCase):
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

    def test_send_suggestion_success(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/email-agent/suggestions/s-1/send?secret=top-secret",
            json={"to_email": "user@example.com", "cc_email": "cc@example.com", "body": "hello"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["status"], "sent")
        self.assertEqual(service.last_call["to_email"], "user@example.com")
        self.assertEqual(service.last_call["cc_email"], "cc@example.com")

    def test_send_suggestion_not_found_returns_404(self) -> None:
        client, _ = self._build_client()
        response = client.post(
            "/email-agent/suggestions/missing/send?secret=top-secret",
            json={"to_email": "user@example.com", "body": "hello"},
        )
        self.assertEqual(response.status_code, 404)

    def test_send_suggestion_validation_returns_400(self) -> None:
        client, _ = self._build_client()
        response = client.post(
            "/email-agent/suggestions/s-1/send?secret=top-secret",
            json={"to_email": "bad-email", "body": "hello"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
