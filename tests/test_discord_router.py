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
        self.baseline_calls = []
        self.dismiss_calls = []
        self.restore_calls = []
        self.raise_on = ""
        self.summaries = {
            "summary-1": {
                "summary_id": "summary-1",
                "summary": "Discussion summary",
                "suggested_tasks": [{"task_key": "task-1", "title": "Review integration"}],
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

    def baseline_channel_from_now(self, channel_id):
        self._raise_if_requested("baseline")
        self.baseline_calls.append(channel_id)
        if channel_id == "404":
            raise LookupError(f"Channel not found: {channel_id}")
        return {"channel_id": channel_id, "status": "baseline_set"}

    def dismiss_suggested_task(self, summary_id, task_key, reason):
        self._raise_if_requested("dismiss")
        self.dismiss_calls.append((summary_id, task_key, reason))
        if summary_id not in self.summaries:
            raise LookupError(f"Summary not found: {summary_id}")
        if task_key != "task-1":
            raise LookupError(f"Suggested task not found: {task_key}")
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": True,
            "dismissed_reason": reason,
        }

    def restore_suggested_task(self, summary_id, task_key):
        self._raise_if_requested("restore")
        self.restore_calls.append((summary_id, task_key))
        if summary_id not in self.summaries:
            raise LookupError(f"Summary not found: {summary_id}")
        if task_key != "task-1":
            raise LookupError(f"Suggested task not found: {task_key}")
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": False,
            "dismissed_reason": "",
        }


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

    def test_baseline_starts_an_allowed_channel_from_now(self) -> None:
        client, service = self._build_client()

        response = client.post("/discord-agent/channels/123456789012345678/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "result": {
                    "channel_id": "123456789012345678",
                    "status": "baseline_set",
                },
            },
        )
        self.assertEqual(service.baseline_calls, ["123456789012345678"])

    def test_baseline_rejects_invalid_channel_id_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post("/discord-agent/channels/not-a-channel/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid channel_id")
        self.assertEqual(service.baseline_calls, [])

    def test_baseline_requires_complete_config_without_calling_service(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["discord_bot_token"])

        response = client.post("/discord-agent/channels/123/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertIn("discord_bot_token", response.json()["detail"])
        self.assertEqual(service.baseline_calls, [])

    def test_baseline_requires_secret_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post("/discord-agent/channels/123/baseline")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(service.baseline_calls, [])

    def test_baseline_returns_404_for_a_service_lookup_failure(self) -> None:
        client, _ = self._build_client()

        response = client.post("/discord-agent/channels/404/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Channel not found", response.json()["detail"])

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

    def test_dismiss_suggested_task_persists_human_reason(self) -> None:
        client, service = self._build_client()

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret",
            json={"reason": "duplicate"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(response.json()["result"]["dismissed"])
        self.assertEqual(response.json()["result"]["dismissed_reason"], "duplicate")
        self.assertEqual(service.dismiss_calls, [("summary-1", "task-1", "duplicate")])

    def test_dismiss_suggested_task_rejects_unknown_reason_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret",
            json={"reason": "invalid"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason must be one of", response.json()["detail"])
        self.assertEqual(service.dismiss_calls, [])

    def test_dismiss_suggested_task_remains_available_when_config_is_incomplete(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["discord_enabled"])

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret",
            json={"reason": "other"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"]["dismissed"])
        self.assertEqual(service.dismiss_calls, [("summary-1", "task-1", "other")])

    def test_dismiss_suggested_task_rejects_an_invalid_path_id_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/invalid%20task/dismiss?secret=top-secret",
            json={"reason": "other"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid task_key")
        self.assertEqual(service.dismiss_calls, [])

    def test_dismiss_suggested_task_returns_404_when_service_cannot_find_task(self) -> None:
        client, _ = self._build_client()

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/missing/dismiss?secret=top-secret",
            json={"reason": "not_actionable"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Suggested task not found", response.json()["detail"])

    def test_restore_suggested_task_restores_a_dismissed_item(self) -> None:
        client, service = self._build_client()

        response = client.delete(
            "/discord-agent/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(response.json()["result"]["dismissed"])
        self.assertEqual(service.restore_calls, [("summary-1", "task-1")])

    def test_task_review_routes_require_secret(self) -> None:
        client, _ = self._build_client()

        response = client.post(
            "/discord-agent/summaries/summary-1/tasks/task-1/dismiss",
            json={"reason": "other"},
        )

        self.assertEqual(response.status_code, 401)

    def test_task_restore_route_requires_secret(self) -> None:
        client, service = self._build_client()

        response = client.delete("/discord-agent/summaries/summary-1/tasks/task-1/dismiss")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(service.restore_calls, [])

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
