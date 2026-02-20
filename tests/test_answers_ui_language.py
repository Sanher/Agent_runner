import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.ui import create_ui_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class AnswersUiLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(create_ui_router(job_secret="top-secret"))
        self.client = TestClient(app)

    def test_answers_ui_strings_are_english(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Answers Agent", html)
        self.assertIn("No chats with received messages yet.", html)
        self.assertIn("Received messages", html)
        self.assertIn("Suggested reply", html)
        self.assertIn("Status:", html)
        self.assertIn("View archived", html)
        self.assertIn("Unarchive", html)
        self.assertIn("Archived conversations are auto-deleted after 7 days.", html)
        self.assertNotIn("No hay chats con mensajes recibidos todavía.", html)
        self.assertNotIn("Mensajes recibidos", html)
        self.assertNotIn("Mensaje sugerido", html)


if __name__ == "__main__":
    unittest.main()
