import unittest

try:
    from fastapi.testclient import TestClient

    from answers_agent import server as answers_server

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class AnswersWebhookSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(answers_server.APP)
        self.original_secret = answers_server.SETTINGS.telegram_webhook_secret
        answers_server.SETTINGS.telegram_webhook_secret = "my-webhook-secret"

    def tearDown(self) -> None:
        answers_server.SETTINGS.telegram_webhook_secret = self.original_secret

    def test_webhook_rejects_missing_secret_header(self) -> None:
        response = self.client.post("/answers_agent/webhook/telegram", json={"update_id": 1})
        self.assertEqual(response.status_code, 401)

    def test_webhook_rejects_invalid_secret_header(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={"update_id": 1},
            headers={"x-telegram-bot-api-secret-token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_webhook_accepts_valid_secret_header(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={"update_id": 1},
            headers={"x-telegram-bot-api-secret-token": "my-webhook-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ignored"], "non-text-message")

    def test_webhook_ignores_low_context_greeting(self) -> None:
        response = self.client.post(
            "/answers_agent/webhook/telegram",
            json={
                "update_id": 2,
                "message": {
                    "text": "hello",
                    "chat": {"id": 1234},
                    "from": {"id": 999},
                },
            },
            headers={"x-telegram-bot-api-secret-token": "my-webhook-secret"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ignored"], "low-context-greeting")


if __name__ == "__main__":
    unittest.main()
