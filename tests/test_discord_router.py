import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.discord_agent import create_discord_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


class _FakeDiscordService:
    def __init__(self) -> None:
        self.poll_calls = 0
        self.list_limits = []
        self.raise_on = ""
        self.summaries = {
            "summary-1": {
                "summary_id": "summary-1",
                "summary": "Discussion summary",
                "suggested_tasks": [],
            },
            "summary-2": {
                "summary_id": "summary-2",
                "summary": "Another summary",
                "suggested_tasks": [],
            },
        }

    def _raise_if_requested(self, operation: str) -> None:
        if self.raise_on == operation:
            raise RuntimeError(f"{operation} failed")

    def get_status(self):
        self._raise_if_requested("status")
        return {"ok": True, "enabled": True}

    def poll_new_messages(self):
        self._raise_if_requested("poll")
        self.poll_calls += 1
        return {"channels_processed": 1, "summaries_created": 1}

    def list_summaries(self, limit=50):
        self._raise_if_requested("list")
        self.list_limits.append(limit)
        return list(self.summaries.values())[:limit]

    def get_summary(self, summary_id):
        self._raise_if_requested("get")
        return self.summaries.get(summary_id)


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class DiscordRouterTests(unittest.TestCase):
    def _build_client(self, *, service=None, missing_config=None, job_secret="top-secret"):
        app = FastAPI()
        service = service or _FakeDiscordService()
        app.include_router(
            create_discord_router(
                service=service,
                job_secret=job_secret,
                missing_config_fn=missing_config or (lambda: []),
            )
        )
        return TestClient(app), service

    def test_status_returns_service_status(self) -> None:
        client, _ = self._build_client()

        response = client.get("/discord-agent/status?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "enabled": True})

    def test_poll_returns_service_result(self) -> None:
        client, service = self._build_client()

        response = client.post("/discord-agent/poll?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "result": {"channels_processed": 1, "summaries_created": 1},
            },
        )
        self.assertEqual(service.poll_calls, 1)

    def test_poll_rejects_missing_config_without_running_service(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["discord_bot_token"])

        response = client.post("/discord-agent/poll?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertIn("discord_bot_token", response.json()["detail"])
        self.assertEqual(service.poll_calls, 0)

    def test_poll_propagates_partial_channel_failures(self) -> None:
        service = _FakeDiscordService()
        service.poll_new_messages = lambda: {
            "ok": False,
            "errors": [{"channel_id": "123", "error": "Discord request failed"}],
        }
        client, _ = self._build_client(service=service)

        response = client.post("/discord-agent/poll?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(response.json()["result"]["ok"])

    def test_list_summaries_uses_requested_limit(self) -> None:
        client, service = self._build_client()

        response = client.get("/discord-agent/summaries?limit=1&secret=top-secret")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["summary_id"], "summary-1")
        self.assertEqual(service.list_limits, [1])

    def test_get_summary_returns_requested_item(self) -> None:
        client, _ = self._build_client()

        response = client.get("/discord-agent/summaries/summary-1?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["summary_id"], "summary-1")

    def test_get_summary_returns_404_when_missing(self) -> None:
        client, _ = self._build_client()

        response = client.get("/discord-agent/summaries/missing?secret=top-secret")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Summary not found", response.json()["detail"])

    def test_endpoints_require_secret_when_configured(self) -> None:
        client, _ = self._build_client()

        response = client.get("/discord-agent/status")

        self.assertEqual(response.status_code, 401)

    def test_untrusted_ingress_header_does_not_bypass_shared_secret(self) -> None:
        client, _ = self._build_client()

        response = client.get("/discord-agent/status", headers={"x-ingress-path": "/api/hassio_ingress/test"})

        self.assertEqual(response.status_code, 401)

    def test_direct_requests_require_a_configured_secret(self) -> None:
        client, _ = self._build_client(job_secret="")

        response = client.get("/discord-agent/status")

        self.assertEqual(response.status_code, 401)

    def test_unexpected_service_error_returns_500(self) -> None:
        service = _FakeDiscordService()
        service.raise_on = "poll"
        client, _ = self._build_client(service=service)

        response = client.post("/discord-agent/poll?secret=top-secret")

        self.assertEqual(response.status_code, 500)
        self.assertIn("poll failed", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
