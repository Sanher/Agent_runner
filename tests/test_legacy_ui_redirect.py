import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.email_agent import create_email_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class LegacyUiRedirectTests(unittest.TestCase):
    def _build_client(self):
        app = FastAPI()
        app.include_router(
            create_email_router(
                service=object(),  # Solo se valida auth/redirect en estos tests.
                job_secret="top-secret",
                missing_config_fn=lambda: [],
            )
        )
        return TestClient(app)

    def test_legacy_ui_redirect_preserves_query_string(self) -> None:
        client = self._build_client()
        response = client.get("/email-agent/ui?secret=top-secret", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/ui?secret=top-secret")

    def test_legacy_ui_redirect_requires_secret_when_configured(self) -> None:
        client = self._build_client()
        response = client.get("/email-agent/ui", follow_redirects=False)
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
