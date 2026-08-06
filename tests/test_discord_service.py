import json
import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from agents.discord_agent.service import DiscordAgentService


def _discord_message(message_id: str, content: str, *, bot: bool = False) -> dict:
    return {
        "id": message_id,
        "content": content,
        "timestamp": "2026-08-05T10:00:00+00:00",
        "author": {"id": "user-123456", "bot": bot},
    }


def _openai_response(tasks=None) -> dict:
    return {
        "status": "completed",
        "output_text": json.dumps(
            {
                "summary": "Resumen de prueba.",
                "decisions": ["Se acordó revisar el cambio."],
                "blockers": [],
                "suggested_tasks": tasks
                if tasks is not None
                else [
                    {
                        "title": "Revisar integración",
                        "context": "Validar la integración propuesta.",
                        "issue_type": "task",
                        "repo": "backend",
                        "unit": "core",
                        "confidence": "high",
                        "evidence_message_ids": ["101"],
                    }
                ],
            }
        ),
    }


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://discord.com/api/v10/test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def json(self):
        return self.payload


class DiscordAgentServiceTests(unittest.TestCase):
    def _service(self, directory: Path, **overrides) -> DiscordAgentService:
        values = {
            "bot_token": "discord-token",
            "openai_api_key": "openai-key",
            "openai_model": "gpt-5-mini",
            "channel_ids": ["123"],
            "poll_interval_minutes": 15,
            "summary_min_messages": 2,
            "retention_days": 14,
            "logger": logging.getLogger("tests.discord"),
            "enabled": True,
        }
        values.update(overrides)
        return DiscordAgentService(data_dir=directory, **values)

    @staticmethod
    def _seed_channel_cursor(service: DiscordAgentService, message_id: str = "100") -> None:
        service._save_json(
            service.state_path,
            {
                "channels": {
                    "123": {
                        "last_message_id": message_id,
                        "baseline_at": "2026-08-05T09:00:00+00:00",
                        "baseline_source": "test",
                    }
                },
                "last_poll_at": "",
                "last_error": "",
            },
        )

    def test_status_hides_secrets_and_reports_missing_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), bot_token="", channel_ids=["not-an-id"])

            status = service.get_status()

        self.assertFalse(status["has_bot_token"])
        self.assertNotIn("discord-token", json.dumps(status))
        self.assertIn("discord_bot_token", status["missing_required_config"])
        self.assertIn("discord_channel_ids_invalid", status["missing_required_config"])

    def test_false_placeholder_secrets_are_not_treated_as_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                bot_token="false",
                openai_api_key="false",
            )

            status = service.get_status()

        self.assertFalse(status["has_bot_token"])
        self.assertFalse(status["has_openai_api_key"])
        self.assertIn("discord_bot_token", status["missing_required_config"])
        self.assertIn("discord_openai_api_key", status["missing_required_config"])

    def test_disabled_service_does_not_create_persistent_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), enabled=False)

            status = service.get_status()

        self.assertFalse(service.data_dir.exists())
        self.assertFalse(status["enabled"])

    def test_status_exposes_safe_baseline_state_without_raw_cursor_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service, "123456789")

            status = service.get_status()

        self.assertEqual(status["channels"][0]["channel_id"], "123")
        self.assertEqual(status["channels"][0]["baseline_status"], "initialized")
        self.assertTrue(status["channels"][0]["has_cursor"])
        self.assertNotIn("last_message_id", status["channels"][0])
        self.assertNotIn("123456789", json.dumps(status))

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_first_poll_sets_a_privacy_first_baseline_without_openai(self, get, post):
        get.return_value = _Response([_discord_message("100", "Mensaje histórico")])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))
            status = service.get_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message_count"], 0)
        self.assertEqual(result["summary_count"], 0)
        self.assertEqual(result["channels"][0]["status"], "baseline_initialized")
        self.assertEqual(get.call_count, 1)
        self.assertTrue(get.call_args.args[0].endswith("/channels/123/messages"))
        self.assertEqual(get.call_args.kwargs["params"], {"limit": 1})
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        self.assertEqual(state["channels"]["123"]["baseline_source"], "automatic")
        self.assertEqual(status["channels"][0]["baseline_status"], "initialized")
        self.assertTrue(status["channels"][0]["has_cursor"])
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_messages_after_automatic_baseline_are_summarized_from_the_cursor(self, get, post):
        get.side_effect = [
            _Response([_discord_message("100", "Mensaje anterior")]),
            _Response([_discord_message("102", "Segundo nuevo"), _discord_message("101", "Primero nuevo")]),
        ]
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            baseline = service.poll_new_messages()
            summarized = service.poll_new_messages()
            summary = service.list_summaries()[0]

        self.assertEqual(baseline["channels"][0]["status"], "baseline_initialized")
        self.assertEqual(summarized["summary_count"], 1)
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"after": "100", "limit": 100})
        self.assertEqual(summary["collection_scope"], "since_baseline")
        post.assert_called_once()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_manual_baseline_marks_an_empty_channel_without_sending_content_to_openai(self, get, post):
        get.return_value = _Response([])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            result = service.baseline_channel_from_now("123")
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "baseline_initialized")
        self.assertFalse(result["has_cursor"])
        self.assertEqual(get.call_args.kwargs["params"], {"limit": 1})
        self.assertEqual(state["channels"]["123"]["last_message_id"], "")
        self.assertTrue(state["channels"]["123"]["baseline_cursor"])
        self.assertEqual(state["channels"]["123"]["baseline_source"], "manual")
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.get")
    def test_empty_baseline_captures_its_boundary_before_the_latest_message_read(self, get):
        baseline_timestamp = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            with patch("agents.discord_agent.service.datetime") as clock:
                clock.now.return_value = baseline_timestamp

                def empty_channel_response(*_args, **_kwargs):
                    self.assertTrue(clock.now.called)
                    return _Response([])

                get.side_effect = empty_channel_response
                service.baseline_channel_from_now("123")
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(
            state["channels"]["123"]["baseline_cursor"],
            service._discord_snowflake_floor(baseline_timestamp),
        )

    @patch("agents.discord_agent.service.httpx.get")
    def test_manual_baseline_never_overwrites_an_existing_cursor(self, get):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service, "100")

            result = service.baseline_channel_from_now("123")
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "already_initialized")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        get.assert_not_called()

    @patch("agents.discord_agent.service.httpx.get")
    def test_manual_baseline_rejects_a_numeric_channel_outside_the_allow_list(self, get):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            with self.assertRaises(ValueError):
                service.baseline_channel_from_now("999")

        get.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_empty_channel_baseline_marks_the_next_summary_as_since_baseline(self, get, post):
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            get.return_value = _Response([])
            service.baseline_channel_from_now("123")
            baseline_state = json.loads(service.state_path.read_text(encoding="utf-8"))
            baseline_cursor = baseline_state["channels"]["123"]["baseline_cursor"]
            cursor_number = int(baseline_cursor)
            get.return_value = _Response(
                [
                    _discord_message(str(cursor_number + 2), "Segundo mensaje"),
                    _discord_message(str(cursor_number + 1), "Primer mensaje"),
                ]
            )
            result = service.poll_new_messages()
            summary = service.list_summaries()[0]

        self.assertEqual(result["summary_count"], 1)
        self.assertEqual(
            get.call_args_list[1].kwargs["params"],
            {"after": baseline_cursor, "limit": 100},
        )
        self.assertEqual(summary["collection_scope"], "since_baseline")
        post.assert_called_once()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_empty_channel_baseline_paginates_a_full_post_baseline_page(self, get, post):
        post.return_value = _Response(_openai_response(tasks=[]))
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            get.return_value = _Response([])
            service.baseline_channel_from_now("123")
            baseline_cursor = json.loads(service.state_path.read_text(encoding="utf-8"))["channels"]["123"][
                "baseline_cursor"
            ]
            cursor_number = int(baseline_cursor)
            get.reset_mock()

            def paginated_messages(_url, **kwargs):
                params = kwargs["params"]
                if params == {"after": baseline_cursor, "limit": 100}:
                    return _Response(
                        [
                            _discord_message(str(cursor_number + 200 - offset), "Mensaje nuevo")
                            for offset in range(100)
                        ]
                    )
                if params == {"before": str(cursor_number + 101), "limit": 100}:
                    return _Response(
                        [
                            _discord_message(str(cursor_number + 100 - offset), "Mensaje nuevo")
                            for offset in range(100)
                        ]
                    )
                if params == {"before": str(cursor_number + 1), "limit": 100}:
                    return _Response([])
                self.fail(f"Unexpected Discord query: {params}")

            get.side_effect = paginated_messages
            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["message_count"], 200)
        self.assertFalse(result["warnings"])
        self.assertEqual(state["channels"]["123"]["last_message_id"], str(cursor_number + 200))
        self.assertEqual(get.call_count, 3)
        post.assert_called_once()

    @patch("agents.discord_agent.service.httpx.get")
    def test_baseline_failure_does_not_create_a_cursor(self, get):
        get.return_value = _Response([], status_code=403)
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            with self.assertRaises(httpx.HTTPStatusError):
                service.baseline_channel_from_now("123")

            self.assertFalse(service.state_path.exists())

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_poll_only_gets_discord_messages_and_persists_summary(self, get, post):
        get.return_value = _Response([
            _discord_message("102", "Segundo mensaje"),
            _discord_message("101", "Primer mensaje"),
        ])
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            result = service.poll_new_messages()
            summaries = service.list_summaries()
            status = service.get_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message_count"], 2)
        self.assertEqual(result["summary_count"], 1)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(get.call_args.args[0].endswith("/channels/123/messages"))
        self.assertEqual(post.call_args.args[0], service.OPENAI_RESPONSES_URL)
        self.assertEqual(summaries[0]["summary_id"], "discord-123-102")
        self.assertEqual(summaries[0]["suggested_tasks"][0]["evidence_message_ids"], ["101"])
        self.assertEqual(summaries[0]["collection_scope"], "since_cursor")
        self.assertTrue(summaries[0]["suggested_tasks"][0]["task_key"])
        self.assertFalse(summaries[0]["suggested_tasks"][0]["dismissed"])
        self.assertFalse(status["last_error"])

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_poll_does_not_repeat_processed_messages(self, get, post):
        get.side_effect = [
            _Response([_discord_message("102", "Segundo"), _discord_message("101", "Primero")]),
            _Response([]),
        ]
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            first = service.poll_new_messages()
            second = service.poll_new_messages()

        self.assertEqual(first["summary_count"], 1)
        self.assertEqual(second["message_count"], 0)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["after"], "102")

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_poll_waits_without_advancing_cursor_until_threshold(self, get, post):
        get.side_effect = [
            _Response([_discord_message("101", "Solo uno")]),
            _Response([_discord_message("102", "Dos"), _discord_message("101", "Uno")]),
        ]
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            waiting = service.poll_new_messages()
            summarized = service.poll_new_messages()

        self.assertEqual(waiting["channels"][0]["status"], "waiting_for_threshold")
        self.assertEqual(summarized["summary_count"], 1)
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"after": "100", "limit": 100})
        self.assertEqual(post.call_count, 1)

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_invalid_ai_task_evidence_is_removed_before_ui_can_use_it(self, get, post):
        get.return_value = _Response([
            _discord_message("102", "Segundo"),
            _discord_message("101", "Primero"),
        ])
        post.return_value = _Response(
            _openai_response(
                [
                    {
                        "title": "Sin evidencia",
                        "context": "No debe llegar a Issues.",
                        "issue_type": "task",
                        "repo": "backend",
                        "unit": "core",
                        "confidence": "high",
                        "evidence_message_ids": ["unknown"],
                    }
                ]
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)
            service.poll_new_messages()
            summaries = service.list_summaries()

        self.assertEqual(summaries[0]["suggested_tasks"], [])

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_openai_failure_keeps_cursor_unmodified(self, get, post):
        get.return_value = _Response([
            _discord_message("102", "Segundo"),
            _discord_message("101", "Primero"),
        ])
        post.side_effect = httpx.TimeoutException("timeout")
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        self.assertEqual(post.call_count, 1)

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_bot_messages_are_ignored_without_openai_call(self, get, post):
        get.return_value = _Response([_discord_message("101", "No analizar", bot=True)])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)
            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["channels"][0]["status"], "ignored_non_text")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "101")
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_unreadable_non_bot_messages_report_an_intent_warning(self, get, post):
        get.return_value = _Response([_discord_message("101", "")])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(result["warnings"][0]["code"], "no_readable_text")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_unreadable_non_bot_messages_keep_the_existing_cursor(self, get, post):
        get.return_value = _Response([_discord_message("101", "")])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service._save_json(
                service.state_path,
                {"channels": {"123": {"last_message_id": "100"}}, "last_poll_at": "", "last_error": ""},
            )

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        self.assertEqual(get.call_args.kwargs["params"], {"after": "100", "limit": 100})
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_mixed_unreadable_messages_do_not_advance_the_baselined_cursor(self, get, post):
        get.return_value = _Response(
            [
                _discord_message("103", "Tercer mensaje"),
                _discord_message("102", "Segundo mensaje"),
                _discord_message("101", ""),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(result["warnings"][0]["code"], "no_readable_text")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_mixed_unreadable_messages_keep_the_existing_cursor(self, get, post):
        get.return_value = _Response(
            [
                _discord_message("102", "Segundo mensaje"),
                _discord_message("101", ""),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service._save_json(
                service.state_path,
                {"channels": {"123": {"last_message_id": "100"}}, "last_poll_at": "", "last_error": ""},
            )

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "100")
        self.assertEqual(get.call_args.kwargs["params"], {"after": "100", "limit": 100})
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_summary_threshold_is_capped_to_the_initial_read_window(self, get, post):
        get.return_value = _Response(
            [
                _discord_message(str(200 - offset), "Mensaje de prueba")
                for offset in range(100)
            ]
        )
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), summary_min_messages=101)
            self._seed_channel_cursor(service)

            result = service.poll_new_messages()

        self.assertEqual(service.summary_min_messages, 100)
        self.assertEqual(service.get_status()["summary_min_messages"], 100)
        self.assertEqual(result["summary_count"], 1)
        post.assert_called_once()

    def test_listing_summaries_purges_expired_records_from_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), retention_days=1)
            service._save_json(
                service.summaries_path,
                {
                    "items": [
                        {
                            "summary_id": "expired",
                            "created_at": "2020-01-01T00:00:00+00:00",
                        },
                        {
                            "summary_id": "current",
                            "created_at": "2099-01-01T00:00:00+00:00",
                        },
                    ]
                },
            )

            summaries = service.list_summaries()
            stored = json.loads(service.summaries_path.read_text(encoding="utf-8"))

        self.assertEqual([item["summary_id"] for item in summaries], ["current"])
        self.assertEqual([item["summary_id"] for item in stored["items"]], ["current"])

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_legacy_tasks_get_keys_and_persist_dismissal_across_service_instances(self, get, post):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            service = self._service(data_dir)
            service._save_json(
                service.summaries_path,
                {
                    "items": [
                        {
                            "summary_id": "discord-123-102",
                            "created_at": "2099-01-01T00:00:00+00:00",
                            "suggested_tasks": [
                                {
                                    "title": "Corregir el fallo",
                                    "context": "El error sigue abierto.",
                                    "issue_type": "bug",
                                    "evidence_message_ids": ["101"],
                                }
                            ],
                        }
                    ]
                },
            )

            task = service.list_summaries()[0]["suggested_tasks"][0]
            task_key = task["task_key"]
            dismissed = service.dismiss_suggested_task("discord-123-102", task_key, "duplicate")
            reloaded = self._service(data_dir)
            persisted = reloaded.list_summaries()[0]["suggested_tasks"][0]
            restored = reloaded.restore_suggested_task("discord-123-102", task_key)

        self.assertTrue(task_key)
        self.assertTrue(dismissed["dismissed"])
        self.assertEqual(dismissed["dismissed_reason"], "duplicate")
        self.assertTrue(persisted["dismissed"])
        self.assertEqual(persisted["dismissed_reason"], "duplicate")
        self.assertFalse(restored["dismissed"])
        self.assertEqual(restored["dismissed_reason"], "")
        get.assert_not_called()
        post.assert_not_called()

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_replayed_summary_keeps_the_existing_human_review_record(self, get, post):
        get.return_value = _Response([
            _discord_message("102", "Segundo mensaje"),
            _discord_message("101", "Primer mensaje"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            self._seed_channel_cursor(service)
            existing_record = {
                "summary_id": "discord-123-102",
                "created_at": "2099-01-01T00:00:00+00:00",
                "summary": "Resumen humano original.",
                "decisions": [],
                "blockers": [],
                "suggested_tasks": [
                    {
                        "title": "Incidencia ya revisada",
                        "context": "Mantener esta revisión humana.",
                        "issue_type": "bug",
                        "evidence_message_ids": ["101"],
                        "dismissed": True,
                        "dismissed_reason": "duplicate",
                    }
                ],
            }
            service._ensure_summary_task_metadata(existing_record)
            service._save_json(service.summaries_path, {"items": [existing_record]})

            result = service.poll_new_messages()
            persisted = service.list_summaries()[0]

        self.assertEqual(result["summary_count"], 0)
        self.assertEqual(persisted["summary"], "Resumen humano original.")
        self.assertTrue(persisted["suggested_tasks"][0]["dismissed"])
        self.assertEqual(persisted["suggested_tasks"][0]["dismissed_reason"], "duplicate")
        post.assert_not_called()

    def test_summary_validation_keeps_distinct_bug_and_task_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            validated = service._validate_summary(
                {
                    "summary": "Dos elementos pendientes.",
                    "decisions": [],
                    "blockers": [],
                    "suggested_tasks": [
                        {
                            "title": "Corregir error de inicio",
                            "context": "La aplicación falla al iniciar.",
                            "issue_type": "bug",
                            "repo": "backend",
                            "unit": "auth",
                            "confidence": "high",
                            "evidence_message_ids": ["101"],
                        },
                        {
                            "title": "Documentar recuperación",
                            "context": "Preparar una guía de recuperación.",
                            "issue_type": "task",
                            "repo": "management",
                            "unit": "operations",
                            "confidence": "medium",
                            "evidence_message_ids": ["102"],
                        },
                    ],
                },
                {"101", "102"},
            )

        self.assertEqual([task["issue_type"] for task in validated["suggested_tasks"]], ["bug", "task"])
        self.assertEqual(len(validated["suggested_tasks"]), 2)

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_large_backlog_is_marked_and_does_not_block_future_polls(self, get, post):
        pages = []
        next_message_id = 3_000
        for _ in range(21):
            pages.append(
                _Response(
                    [
                        _discord_message(str(next_message_id - offset), "Mensaje de backlog")
                        for offset in range(100)
                    ]
                )
            )
            next_message_id -= 100
        get.side_effect = pages
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service._save_json(
                service.state_path,
                {"channels": {"123": {"last_message_id": "100"}}, "last_poll_at": "", "last_error": ""},
            )

            result = service.poll_new_messages()
            summary = service.list_summaries()[0]
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"][0]["code"], "backlog_truncated")
        self.assertTrue(result["channels"][0]["backlog_truncated"])
        self.assertTrue(summary["backlog_truncated"])
        self.assertEqual(summary["collection_scope"], "bounded_recent_backlog")
        self.assertEqual(state["channels"]["123"]["last_message_id"], "3000")


if __name__ == "__main__":
    unittest.main()
