import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

try:
    from fastapi.testclient import TestClient

    from runners.intake_local import (
        DEFAULT_LOCAL_INTAKE_PORT,
        LOCAL_INTAKE_BIND_HOST,
        create_intake_local_app,
        create_intake_local_app_from_environment,
        intake_local_data_dir,
        intake_local_host,
        intake_local_port,
        main as intake_local_main,
        run_intake_local_app,
    )

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    DEPS_AVAILABLE = False


class _FakeDiscordService:
    def __init__(self) -> None:
        self.poll_calls = 0
        self.baseline_calls = []
        self.dismiss_calls = []
        self.restore_calls = []
        self.summary_limits = []

    def get_status(self):
        return {
            "ok": True,
            "enabled": True,
            "summary_count": 1,
            "channels": [{"channel_id": "123456789012345678", "baseline_status": "pending"}],
        }

    def list_summaries(self, limit=50):
        self.summary_limits.append(limit)
        return [
            {
                "summary_id": "discord-summary-1",
                "created_at": "2026-08-06T08:00:00+00:00",
                "message_count": 2,
                "summary": "A Discord test conversation.",
                "decisions": ["Review the local console."],
                "blockers": [],
                "suggested_tasks": [
                    {
                        "task_key": "discord-task-1",
                        "title": "Check the Discord sample",
                        "context": "A manually created test task.",
                        "issue_type": "bug",
                        "repo": "backend",
                        "unit": "chat-ingestion",
                        "evidence_message_ids": ["100", "101"],
                    }
                ],
            }
        ][:limit]

    def poll_new_messages(self):
        self.poll_calls += 1
        return {"ok": True, "summaries_created": 1}

    def baseline_channel_from_now(self, channel_id):
        self.baseline_calls.append(channel_id)
        return {"status": "baseline_initialized", "channel_id": channel_id}

    def dismiss_suggested_task(self, summary_id, task_key, reason):
        self.dismiss_calls.append((summary_id, task_key, reason))
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": True,
            "dismissed_reason": reason,
        }

    def restore_suggested_task(self, summary_id, task_key):
        self.restore_calls.append((summary_id, task_key))
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": False,
            "dismissed_reason": "",
        }


class _FakeTelegramService:
    def __init__(self) -> None:
        self.poll_calls = 0
        self.baseline_calls = 0
        self.dismiss_calls = []
        self.restore_calls = []

    def get_status(self):
        return {
            "ok": True,
            "enabled": True,
            "summary_count": 1,
            "chats": [{"chat_id": "789", "baseline_status": "pending"}],
        }

    def list_summaries(self, limit=50):
        return [
            {
                "summary_id": "telegram-summary-1",
                "created_at": "2026-08-06T09:00:00+00:00",
                "message_count": 1,
                "summary": "A Telegram test conversation.",
                "suggested_tasks": [],
            }
        ][:limit]

    def poll_new_updates(self):
        self.poll_calls += 1
        raise AssertionError("The shared-webhook Telegram source must never be polled locally")

    def baseline_from_now(self):
        self.baseline_calls += 1
        return {"status": "baseline_initialized"}

    def dismiss_suggested_task(self, summary_id, task_key, reason):
        self.dismiss_calls.append((summary_id, task_key, reason))
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": True,
            "dismissed_reason": reason,
        }

    def restore_suggested_task(self, summary_id, task_key):
        self.restore_calls.append((summary_id, task_key))
        return {
            "summary_id": summary_id,
            "task_key": task_key,
            "dismissed": False,
            "dismissed_reason": "",
        }


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class IntakeLocalConsoleTests(unittest.TestCase):
    def _build_client(self, *, discord=None, telegram=None, discord_missing=None, telegram_missing=None):
        discord = discord or _FakeDiscordService()
        telegram = telegram or _FakeTelegramService()
        app = create_intake_local_app(
            job_secret="top-secret",
            discord_service=discord,
            telegram_service=telegram,
            discord_missing_config_fn=discord_missing or (lambda: []),
            telegram_missing_config_fn=telegram_missing or (lambda: []),
        )
        return TestClient(app), discord, telegram

    def test_console_and_all_local_api_endpoints_require_job_secret(self) -> None:
        client, discord, telegram = self._build_client()

        # The static bootstrap has no data; a #fragment cannot be sent with
        # the initial HTTP request.  Every data-bearing operation is protected.
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/api/intake/discord/status").status_code, 401)
        self.assertEqual(client.get("/api/intake/discord/summaries").status_code, 401)
        self.assertEqual(client.post("/api/intake/discord/poll").status_code, 401)
        self.assertEqual(client.post("/api/intake/discord/baseline?channel_id=123").status_code, 401)
        self.assertEqual(client.post("/api/intake/telegram/poll").status_code, 401)
        self.assertEqual(client.post("/api/intake/telegram/baseline").status_code, 401)
        self.assertEqual(
            client.post(
                "/api/intake/discord/summaries/discord-summary-1/tasks/discord-task-1/dismiss",
                json={"reason": "other"},
            ).status_code,
            401,
        )
        self.assertEqual(
            client.delete(
                "/api/intake/discord/summaries/discord-summary-1/tasks/discord-task-1/dismiss",
            ).status_code,
            401,
        )
        self.assertEqual(discord.poll_calls, 0)
        self.assertEqual(telegram.poll_calls, 0)
        self.assertEqual(discord.baseline_calls, [])
        self.assertEqual(discord.dismiss_calls, [])
        self.assertEqual(discord.restore_calls, [])

    def test_console_uses_fragment_secret_and_privacy_headers_for_authenticated_endpoints(self) -> None:
        client, _, _ = self._build_client()

        response = client.get("/")
        legacy_response = client.get("/?secret=top-secret")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        html = response.text
        self.assertIn("Local Intake Console", html)
        self.assertIn('id="pollDiscordBtn"', html)
        self.assertIn('id="discordBaselineActions"', html)
        self.assertNotIn('id="pollTelegramBtn"', html)
        self.assertNotIn('id="telegramBaselineActions"', html)
        self.assertIn("Answers webhook in Agent Runner", html)
        self.assertIn("/api/intake/${encodeURIComponent(source)}${suffix}", html)
        self.assertIn('<meta name="referrer" content="no-referrer" />', html)
        self.assertIn("const fragmentSecret = window.location.hash.slice(1);", html)
        self.assertIn("new URLSearchParams(window.location.search).get('secret')", html)
        self.assertIn("window.history.replaceState(null, document.title, window.location.pathname);", html)
        self.assertIn("headers.set('X-Job-Secret', localJobSecret)", html)
        self.assertIn("{cache: 'no-store', referrerPolicy: 'no-referrer'}", html)
        self.assertNotIn("querySecret", html)
        self.assertIn("Prepare Issue draft", html)
        self.assertIn("No Issue has been created or submitted.", html)
        self.assertIn("function prepareIssueDraft(source, task, summary)", html)
        self.assertIn("function baselineSource(source, button, channelId = '')", html)
        self.assertIn("/baseline?channel_id=${encodeURIComponent(channelId)}", html)
        self.assertIn("Clear task", html)
        self.assertIn("Restore task", html)
        self.assertIn("function dismissTask(source, summaryId, taskKey, reason, button)", html)
        self.assertIn("function restoreTask(source, summaryId, taskKey, button)", html)
        self.assertIn("No chat or Issue was changed.", html)
        self.assertNotIn("/issue-agent/submit", html)
        self.assertNotIn("fetch('/issue", html)

    def test_source_status_summaries_and_discord_poll_delegate_to_injected_services(self) -> None:
        client, discord, telegram = self._build_client()
        headers = {"X-Job-Secret": "top-secret"}

        discord_status = client.get("/api/intake/discord/status", headers=headers)
        telegram_status = client.get("/api/intake/telegram/status", headers=headers)
        telegram_summaries = client.get("/api/intake/telegram/summaries?limit=1", headers=headers)
        discord_poll = client.post("/api/intake/discord/poll", headers=headers)
        telegram_poll = client.post("/api/intake/telegram/poll", headers=headers)

        self.assertEqual(discord_status.status_code, 200)
        self.assertTrue(discord_status.json()["available"])
        self.assertEqual(telegram_status.status_code, 200)
        self.assertEqual(telegram_status.json()["delivery_mode"], "answers_webhook")
        self.assertFalse(telegram_status.json()["supports_manual_poll"])
        self.assertIn("Answers webhook", telegram_status.json()["source_note"])
        self.assertEqual(telegram_summaries.status_code, 200)
        self.assertEqual(telegram_summaries.json()["items"][0]["summary_id"], "telegram-summary-1")
        self.assertEqual(discord_poll.status_code, 200)
        self.assertEqual(telegram_poll.status_code, 409)
        self.assertEqual(discord.poll_calls, 1)
        self.assertEqual(telegram.poll_calls, 0)

    def test_discord_baseline_delegates_without_polling_or_creating_an_issue(self) -> None:
        client, discord, telegram = self._build_client()
        headers = {"X-Job-Secret": "top-secret"}

        discord_baseline = client.post(
            "/api/intake/discord/baseline?channel_id=123456789012345678",
            headers=headers,
        )

        self.assertEqual(discord_baseline.status_code, 200)
        self.assertEqual(discord.baseline_calls, ["123456789012345678"])
        self.assertEqual(discord.poll_calls, 0)
        self.assertEqual(telegram.poll_calls, 0)

    def test_telegram_baseline_is_not_available_from_the_local_console(self) -> None:
        client, _, telegram = self._build_client()

        response = client.post("/api/intake/telegram/baseline?secret=top-secret")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(telegram.baseline_calls, 0)

    def test_task_clear_and_restore_are_reversible_review_operations(self) -> None:
        client, discord, telegram = self._build_client()
        headers = {"X-Job-Secret": "top-secret"}

        clear = client.post(
            "/api/intake/discord/summaries/discord-summary-1/tasks/discord-task-1/dismiss",
            headers=headers,
            json={"reason": "duplicate"},
        )
        restore = client.delete(
            "/api/intake/telegram/summaries/telegram-summary-1/tasks/telegram-task-1/dismiss",
            headers=headers,
        )

        self.assertEqual(clear.status_code, 200)
        self.assertTrue(clear.json()["result"]["dismissed"])
        self.assertEqual(discord.dismiss_calls, [("discord-summary-1", "discord-task-1", "duplicate")])
        self.assertEqual(restore.status_code, 200)
        self.assertFalse(restore.json()["result"]["dismissed"])
        self.assertEqual(telegram.restore_calls, [("telegram-summary-1", "telegram-task-1")])
        self.assertEqual(discord.poll_calls, 0)
        self.assertEqual(telegram.poll_calls, 0)

    def test_task_clear_rejects_invalid_reason_without_service_call(self) -> None:
        client, discord, _ = self._build_client()

        response = client.post(
            "/api/intake/discord/summaries/discord-summary-1/tasks/discord-task-1/dismiss?secret=top-secret",
            json={"reason": "automatic_issue_creation"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason must be one of", response.json()["detail"])
        self.assertEqual(discord.dismiss_calls, [])

    def test_task_review_remains_available_when_reader_configuration_is_incomplete(self) -> None:
        client, discord, _ = self._build_client(discord_missing=lambda: ["discord_bot_token"])

        response = client.post(
            "/api/intake/discord/summaries/discord-summary-1/tasks/discord-task-1/dismiss?secret=top-secret",
            json={"reason": "created"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(discord.dismiss_calls, [("discord-summary-1", "discord-task-1", "created")])

    def test_discord_baseline_requires_a_numeric_channel_id_without_service_call(self) -> None:
        client, discord, _ = self._build_client()

        response = client.post("/api/intake/discord/baseline?secret=top-secret&channel_id=not-a-channel")

        self.assertEqual(response.status_code, 400)
        self.assertIn("numeric channel_id", response.json()["detail"])
        self.assertEqual(discord.baseline_calls, [])

    def test_poll_rejects_missing_source_configuration_without_reading_chat(self) -> None:
        client, discord, _ = self._build_client(discord_missing=lambda: ["discord_bot_token"])

        response = client.post("/api/intake/discord/poll?secret=top-secret")

        self.assertEqual(response.status_code, 400)
        self.assertIn("discord_bot_token", response.json()["detail"])
        self.assertEqual(discord.poll_calls, 0)

    def test_unwired_shared_webhook_source_is_visible_but_cannot_poll(self) -> None:
        discord = _FakeDiscordService()
        app = create_intake_local_app(
            job_secret="top-secret",
            discord_service=discord,
            telegram_service=None,
        )
        client = TestClient(app)

        status = client.get("/api/intake/telegram/status?secret=top-secret")
        summaries = client.get("/api/intake/telegram/summaries?secret=top-secret")
        poll = client.post("/api/intake/telegram/poll?secret=top-secret")

        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["available"])
        self.assertEqual(summaries.status_code, 200)
        self.assertEqual(summaries.json()["items"], [])
        self.assertEqual(poll.status_code, 409)
        self.assertEqual(discord.poll_calls, 0)

    def test_factory_disables_unprotected_documentation_endpoints(self) -> None:
        client, _, _ = self._build_client()

        self.assertEqual(client.get("/docs").status_code, 404)
        self.assertEqual(client.get("/redoc").status_code, 404)
        self.assertEqual(client.get("/openapi.json").status_code, 404)

    def test_runner_guidance_is_loopback_only(self) -> None:
        self.assertEqual(LOCAL_INTAKE_BIND_HOST, "127.0.0.1")
        self.assertEqual(DEFAULT_LOCAL_INTAKE_PORT, 8098)

    def test_runner_never_imports_the_full_application(self) -> None:
        runner_source = (Path(__file__).resolve().parents[1] / "runners" / "intake_local.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("from main import", runner_source)
        self.assertNotIn("import main", runner_source)

    def test_environment_factory_constructs_only_the_local_discord_reader(self) -> None:
        captured = {}

        def discord_factory(**kwargs):
            captured["discord"] = kwargs
            return _FakeDiscordService()

        env = {
            "JOB_SECRET": "test-job-secret",
            "INTAKE_LOCAL_DATA_DIR": "/tmp/intake-console-test-data",
            "DISCORD_ENABLED": "true",
            "DISCORD_BOT_TOKEN": "not-a-real-discord-token",
            "DISCORD_OPENAI_API_KEY": "not-a-real-openai-key",
            "DISCORD_OPENAI_MODEL": "gpt-5-mini",
            "DISCORD_CHANNEL_IDS": "123,456",
        }
        with patch.dict("os.environ", env, clear=True):
            app = create_intake_local_app_from_environment(
                discord_service_factory=discord_factory,
            )

        self.assertEqual(
            captured["discord"]["data_dir"],
            Path("/tmp/intake-console-test-data").resolve(),
        )
        self.assertEqual(captured["discord"]["channel_ids"], ["123", "456"])
        self.assertTrue(captured["discord"]["enabled"])
        self.assertIsNotNone(app)

    def test_local_telegram_poll_is_rejected_before_any_polling_method_is_called(self) -> None:
        client, _, telegram = self._build_client()

        response = client.post("/api/intake/telegram/poll?secret=top-secret")

        self.assertEqual(response.status_code, 409)
        self.assertIn("does not support local manual polling", response.json()["detail"])
        self.assertEqual(telegram.poll_calls, 0)

    def test_environment_runner_does_not_reference_shared_telegram_transport_settings(self) -> None:
        runner_source = (Path(__file__).resolve().parents[1] / "runners" / "intake_local.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("TELEGRAM_READER_BOT_TOKEN", runner_source)
        self.assertNotIn("TELEGRAM_READER_POLL_INTERVAL_MINUTES", runner_source)
        self.assertNotIn("agents.telegram_reader.service", runner_source)

    def test_local_host_normalizes_localhost_and_rejects_non_loopback_values(self) -> None:
        with patch.dict("os.environ", {"INTAKE_LOCAL_HOST": "localhost"}, clear=True):
            self.assertEqual(intake_local_host(), "127.0.0.1")
        with patch.dict("os.environ", {"INTAKE_LOCAL_HOST": "::1"}, clear=True):
            self.assertEqual(intake_local_host(), "::1")
        with patch.dict(
            "os.environ",
            {"INTAKE_LOCAL_HOST": "0.0.0.0", "INTAKE_LOCAL_PORT": "99999"},
            clear=True,
        ):
            self.assertEqual(intake_local_host(), "127.0.0.1")
            self.assertEqual(intake_local_port(), 65535)

    def test_runner_disables_uvicorn_access_logs(self) -> None:
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))

        with patch.dict(
            "sys.modules",
            {"uvicorn": SimpleNamespace(run=fake_run)},
            clear=False,
        ), patch.dict("os.environ", {"INTAKE_LOCAL_HOST": "localhost"}, clear=True):
            run_intake_local_app(object(), port=8098)

        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, (ANY,))
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 8098)
        self.assertFalse(kwargs["access_log"])

    def test_local_data_dir_rejects_the_home_assistant_data_root(self) -> None:
        with patch.dict("os.environ", {"INTAKE_LOCAL_DATA_DIR": "/data/telegram_reader"}, clear=True):
            self.assertEqual(intake_local_data_dir(), Path(".data/intake_local").resolve())

    def test_local_data_dir_rejects_other_home_assistant_runtime_roots(self) -> None:
        for protected_path in ("/config/intake", "/share/intake", "/media/intake", "/ssl/intake"):
            with self.subTest(protected_path=protected_path), patch.dict(
                "os.environ",
                {"INTAKE_LOCAL_DATA_DIR": protected_path},
                clear=True,
            ):
                self.assertEqual(intake_local_data_dir(), Path(".data/intake_local").resolve())

    def test_local_data_dir_fails_closed_when_its_fallback_would_be_in_home_assistant(self) -> None:
        with patch("runners.intake_local.DEFAULT_LOCAL_INTAKE_DATA_DIR", Path("/data/local-intake")), patch.dict(
            "os.environ",
            {"INTAKE_LOCAL_DATA_DIR": "/data/requested"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "fallback inside a Home Assistant runtime directory"):
                intake_local_data_dir()

    def test_local_runner_rejects_placeholder_job_secrets(self) -> None:
        for placeholder in ("", " false ", "NoNe", "NULL"):
            with self.subTest(placeholder=placeholder), patch.dict(
                "os.environ",
                {"JOB_SECRET": placeholder},
                clear=True,
            ):
                with self.assertRaisesRegex(SystemExit, "non-placeholder JOB_SECRET"):
                    intake_local_main()

    def test_token_bearing_service_failure_is_neither_logged_nor_reflected(self) -> None:
        class TokenBearingFailureService(_FakeTelegramService):
            def get_status(self):
                raise RuntimeError("https://api.telegram.org/botSUPER-SECRET-TOKEN/getUpdates")

        app = create_intake_local_app(
            job_secret="top-secret",
            discord_service=_FakeDiscordService(),
            telegram_service=TokenBearingFailureService(),
        )
        client = TestClient(app)

        with self.assertLogs("agent_runner.intake_local_ui", level="ERROR") as captured:
            response = client.get("/api/intake/telegram/status?secret=top-secret")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Local intake operation failed")
        self.assertNotIn("SUPER-SECRET-TOKEN", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
