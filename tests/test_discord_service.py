import json
import logging
import tempfile
import unittest
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
        self.assertEqual(summaries[0]["collection_scope"], "initial_recent_window")
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

            waiting = service.poll_new_messages()
            summarized = service.poll_new_messages()

        self.assertEqual(waiting["channels"][0]["status"], "waiting_for_threshold")
        self.assertEqual(summarized["summary_count"], 1)
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"limit": 100})
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

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(state["channels"], {})
        self.assertEqual(post.call_count, 1)

    @patch("agents.discord_agent.service.httpx.post")
    @patch("agents.discord_agent.service.httpx.get")
    def test_bot_messages_are_ignored_without_openai_call(self, get, post):
        get.return_value = _Response([_discord_message("101", "No analizar", bot=True)])
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
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

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(result["warnings"][0]["code"], "no_readable_text")
        self.assertEqual(state["channels"], {})
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
    def test_mixed_unreadable_messages_do_not_advance_the_initial_cursor(self, get, post):
        get.return_value = _Response(
            [
                _discord_message("103", "Tercer mensaje"),
                _discord_message("102", "Segundo mensaje"),
                _discord_message("101", ""),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            result = service.poll_new_messages()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["channels"][0]["status"], "waiting_for_readable_text")
        self.assertEqual(result["warnings"][0]["code"], "no_readable_text")
        self.assertEqual(state["channels"], {})
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
