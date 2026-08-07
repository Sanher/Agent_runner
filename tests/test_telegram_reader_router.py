import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.telegram_reader import create_telegram_reader_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on the local environment
    DEPS_AVAILABLE = False


class _FakeTelegramReaderService:
    def __init__(self) -> None:
        self.process_calls = 0
        self.baseline_calls = 0
        self.list_limits = []
        self.dismiss_calls = []
        self.restore_calls = []
        self.raise_on = ""
        self.summaries = {
            "summary-1": {
                "summary_id": "summary-1",
                "summary": "Private chat summary",
                "suggested_tasks": [{"task_key": "task-1", "title": "Review test issue"}],
            },
            "summary-2": {
                "summary_id": "summary-2",
                "summary": "Another chat summary",
                "suggested_tasks": [],
            },
        }

    def _raise_if_requested(self, operation: str) -> None:
        if self.raise_on == operation:
            raise RuntimeError(f"{operation} failed")

    def get_status(self):
        self._raise_if_requested("status")
        return {"ok": True, "enabled": True}

    def process_pending_summaries(self):
        self._raise_if_requested("process")
        self.process_calls += 1
        return {"summary_count": 1, "summaries_created": 1}

    def baseline_from_now(self):
        self._raise_if_requested("baseline")
        self.baseline_calls += 1
        return {"status": "baseline_set"}

    def list_summaries(self, limit=50):
        self._raise_if_requested("list")
        self.list_limits.append(limit)
        return list(self.summaries.values())[:limit]

    def get_summary(self, summary_id):
        self._raise_if_requested("get")
        return self.summaries.get(summary_id)

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


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class TelegramReaderRouterTests(unittest.TestCase):
    def _build_client(self, *, service=None, missing_config=None, job_secret="top-secret"):
        app = FastAPI()
        service = service or _FakeTelegramReaderService()
        app.include_router(
            create_telegram_reader_router(
                service=service,
                job_secret=job_secret,
                missing_config_fn=missing_config or (lambda: []),
            )
        )
        return TestClient(app), service

    def test_status_returns_service_status_with_complete_configuration(self) -> None:
        client, _ = self._build_client()

        response = client.get("/telegram-reader/status?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "enabled": True,
                "missing_required_config": [],
                "configured": True,
                "configuration_complete": True,
                "config_valid": True,
            },
        )

    def test_status_includes_shared_answers_delivery_requirements(self) -> None:
        client, _ = self._build_client(
            missing_config=lambda: ["answers_telegram_bot_token", "answers_webhook_secret"]
        )

        response = client.get("/telegram-reader/status?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["missing_required_config"],
            ["answers_telegram_bot_token", "answers_webhook_secret"],
        )
        self.assertFalse(payload["configured"])
        self.assertFalse(payload["configuration_complete"])
        self.assertFalse(payload["config_valid"])

    def test_process_returns_service_result(self) -> None:
        client, service = self._build_client()

        response = client.post("/telegram-reader/process?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "result": {"summary_count": 1, "summaries_created": 1},
            },
        )
        self.assertEqual(service.process_calls, 1)

    def test_process_requires_complete_config_without_running_service(self) -> None:
        client, service = self._build_client(
            missing_config=lambda: ["telegram_reader_enabled", "answers_telegram_bot_token"]
        )

        response = client.post("/telegram-reader/process?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertIn("telegram_reader_enabled", response.json()["detail"])
        self.assertEqual(service.process_calls, 0)

    def test_baseline_starts_from_now(self) -> None:
        client, service = self._build_client()

        response = client.post("/telegram-reader/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "result": {"status": "baseline_set"}})
        self.assertEqual(service.baseline_calls, 1)

    def test_baseline_requires_complete_config_without_running_service(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["answers_telegram_bot_token"])

        response = client.post("/telegram-reader/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertIn("answers_telegram_bot_token", response.json()["detail"])
        self.assertEqual(service.baseline_calls, 0)

    def test_read_endpoints_remain_available_when_config_is_incomplete(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["telegram_reader_enabled"])

        response = client.get("/telegram-reader/summaries?limit=1&secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(service.list_limits, [1])

    def test_get_summary_returns_requested_item(self) -> None:
        client, _ = self._build_client()

        response = client.get("/telegram-reader/summaries/summary-1?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["summary_id"], "summary-1")

    def test_get_summary_returns_404_when_missing(self) -> None:
        client, _ = self._build_client()

        response = client.get("/telegram-reader/summaries/missing?secret=top-secret")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Summary not found", response.json()["detail"])

    def test_dismiss_persists_human_reason_when_config_is_incomplete(self) -> None:
        client, service = self._build_client(missing_config=lambda: ["telegram_reader_enabled"])

        response = client.post(
            "/telegram-reader/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret",
            json={"reason": "duplicate"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"]["dismissed"])
        self.assertEqual(service.dismiss_calls, [("summary-1", "task-1", "duplicate")])

    def test_dismiss_rejects_invalid_reason_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post(
            "/telegram-reader/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret",
            json={"reason": "invalid"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason must be one of", response.json()["detail"])
        self.assertEqual(service.dismiss_calls, [])

    def test_restore_reverts_a_dismissed_task(self) -> None:
        client, service = self._build_client()

        response = client.delete(
            "/telegram-reader/summaries/summary-1/tasks/task-1/dismiss?secret=top-secret"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"]["dismissed"])
        self.assertEqual(service.restore_calls, [("summary-1", "task-1")])

    def test_task_review_rejects_invalid_path_without_calling_service(self) -> None:
        client, service = self._build_client()

        response = client.post(
            "/telegram-reader/summaries/summary-1/tasks/invalid%20task/dismiss?secret=top-secret",
            json={"reason": "other"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid task_key")
        self.assertEqual(service.dismiss_calls, [])

    def test_endpoints_require_secret(self) -> None:
        client, service = self._build_client()

        status_response = client.get("/telegram-reader/status")
        process_response = client.post("/telegram-reader/process")
        baseline_response = client.post("/telegram-reader/baseline")
        summaries_response = client.get("/telegram-reader/summaries")
        dismiss_response = client.post(
            "/telegram-reader/summaries/summary-1/tasks/task-1/dismiss",
            json={"reason": "other"},
        )

        self.assertEqual(status_response.status_code, 401)
        self.assertEqual(process_response.status_code, 401)
        self.assertEqual(baseline_response.status_code, 401)
        self.assertEqual(summaries_response.status_code, 401)
        self.assertEqual(dismiss_response.status_code, 401)
        self.assertEqual(service.process_calls, 0)
        self.assertEqual(service.baseline_calls, 0)
        self.assertEqual(service.list_limits, [])
        self.assertEqual(service.dismiss_calls, [])

    def test_router_has_no_telegram_write_endpoint(self) -> None:
        client, _ = self._build_client()

        response = client.post("/telegram-reader/send?secret=top-secret")

        self.assertEqual(response.status_code, 404)

    def test_router_has_no_poll_endpoint(self) -> None:
        client, service = self._build_client()

        response = client.post("/telegram-reader/poll?secret=top-secret")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(service.process_calls, 0)

    def test_unexpected_service_error_returns_500(self) -> None:
        service = _FakeTelegramReaderService()

        def raise_token_bearing_error():
            raise RuntimeError(
                "Client error for url "
                "https://api.telegram.org/botBOT_TOKEN_SHOULD_NOT_APPEAR/getUpdates"
            )

        service.process_pending_summaries = raise_token_bearing_error
        client, _ = self._build_client(service=service)

        response = client.post("/telegram-reader/process?secret=top-secret")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Telegram reader operation failed")
        self.assertNotIn("BOT_TOKEN_SHOULD_NOT_APPEAR", response.text)


if __name__ == "__main__":
    unittest.main()
