import inspect
import json
import logging
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from agents.telegram_reader.service import TelegramReaderService


def _webhook_update(
    update_id: int,
    message_id: int,
    text: str,
    *,
    chat_id: str = "123",
    kind: str = "message",
    bot: bool = False,
    sender_business_bot: bool = False,
    offline: bool = False,
    sender_id: int | None = None,
    chat_type: str = "private",
    date: object | None = None,
) -> dict:
    message = {
        "message_id": message_id,
        # The service deliberately activates at the next whole second.  Make
        # ordinary fixtures clearly post-activation; boundary behaviour is
        # covered explicitly in the authorization tests below.
        "date": date if date is not None else int(datetime.now(timezone.utc).timestamp()) + 60,
        "chat": {"id": int(chat_id), "type": chat_type},
        "from": {
            "id": sender_id if sender_id is not None else int(chat_id),
            "is_bot": bot,
            "username": "private_sender",
            "first_name": "Private",
        },
        "text": text,
    }
    if sender_business_bot:
        message["sender_business_bot"] = {"id": 999, "username": "answers_bot"}
    if offline:
        message["is_from_offline"] = True
    return {"update_id": update_id, kind: message}


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
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def json(self):
        return self.payload


class TelegramReaderServiceTests(unittest.TestCase):
    def _service(self, directory: Path, **overrides) -> TelegramReaderService:
        values = {
            "openai_api_key": "shared-openai-key",
            "openai_model": "gpt-5-mini",
            "chat_ids": ["123"],
            "summary_min_messages": 2,
            "retention_days": 14,
            "logger": logging.getLogger("tests.telegram_reader"),
            "enabled": True,
        }
        values.update(overrides)
        return TelegramReaderService(data_dir=directory, **values)

    def test_constructor_has_no_telegram_token_or_polling_dependency(self):
        signature = inspect.signature(TelegramReaderService)
        source = inspect.getsource(TelegramReaderService)

        self.assertNotIn("bot_token", signature.parameters)
        self.assertNotIn("poll_interval_minutes", signature.parameters)
        self.assertNotIn("httpx.get", source)
        self.assertNotIn("getUpdates", source)
        self.assertNotIn("api.telegram.org", source)

    def test_status_uses_answers_webhook_source_and_canonical_missing_config_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                openai_api_key="",
                chat_ids=["not-a-chat"],
                enabled=False,
            )

            status = service.get_status()

        self.assertEqual(status["source"], "answers_webhook")
        self.assertNotIn("has_bot_token", status)
        self.assertFalse(status["has_openai_api_key"])
        self.assertEqual(
            status["missing_required_config"],
            [
                "telegram_reader_enabled",
                "discord_openai_api_key",
                "telegram_reader_chat_ids",
                "telegram_reader_chat_ids_invalid",
            ],
        )

    def test_disabled_or_misconfigured_webhook_input_is_harmless_and_unpersisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), enabled=False)

            disabled = service.ingest_webhook_update(_webhook_update(101, 1, "No guardar"))
            misconfigured = self._service(Path(temporary), openai_api_key="")
            no_key = misconfigured.ingest_webhook_update(_webhook_update(102, 2, "No guardar tampoco"))

        self.assertTrue(disabled["ok"])
        self.assertTrue(disabled["ignored"])
        self.assertEqual(disabled["reason"], "reader_unavailable")
        self.assertTrue(no_key["ignored"])
        self.assertFalse(service.data_dir.exists())

    @patch("agents.telegram_reader.service.httpx.post")
    def test_local_baseline_is_idempotent_and_does_not_call_openai(self, post):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            initialized = service.baseline_from_now()
            already_initialized = service.baseline_from_now()
            accepted = service.ingest_webhook_update(_webhook_update(101, 101, "Mensaje nuevo"))
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertEqual(initialized["status"], "baseline_initialized")
        self.assertEqual(initialized["source"], "answers_webhook")
        self.assertEqual(already_initialized["status"], "already_initialized")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(state["baseline_source"], "manual")
        self.assertEqual(len(state["chats"]["123"]["pending_messages"]), 1)
        post.assert_not_called()

    def test_message_before_per_chat_authorization_boundary_is_never_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            with patch.object(service, "_now_epoch_seconds", return_value=1_000):
                service.baseline_from_now()
            boundary = json.loads(service.state_path.read_text(encoding="utf-8"))["chats"]["123"][
                "authorized_after_epoch"
            ]

            stale = service.ingest_webhook_update(
                _webhook_update(101, 1, "No persistir texto anterior", date=boundary - 1)
            )
            state_text = service.state_path.read_text(encoding="utf-8")

        self.assertEqual(boundary, 1_001)
        self.assertTrue(stale["ignored"])
        self.assertEqual(stale["reason"], "message_before_authorization")
        self.assertNotIn("No persistir texto anterior", state_text)

    def test_message_at_per_chat_authorization_boundary_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            with patch.object(service, "_now_epoch_seconds", return_value=1_000):
                service.baseline_from_now()
            boundary = json.loads(service.state_path.read_text(encoding="utf-8"))["chats"]["123"][
                "authorized_after_epoch"
            ]

            accepted = service.ingest_webhook_update(
                _webhook_update(101, 1, "Texto desde el límite", date=boundary)
            )
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(accepted["accepted"])
        self.assertEqual(
            state["chats"]["123"]["pending_messages"][0]["message_date_epoch"],
            boundary,
        )

    def test_missing_or_invalid_message_date_is_never_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            with patch.object(service, "_now_epoch_seconds", return_value=1_000):
                service.baseline_from_now()
            boundary = json.loads(service.state_path.read_text(encoding="utf-8"))["chats"]["123"][
                "authorized_after_epoch"
            ]
            missing_date = _webhook_update(101, 1, "No persistir fecha ausente", date=boundary)
            missing_date["message"].pop("date")
            invalid_date = _webhook_update(102, 2, "No persistir fecha inválida", date="not-a-date")

            missing = service.ingest_webhook_update(missing_date)
            invalid = service.ingest_webhook_update(invalid_date)
            state_text = service.state_path.read_text(encoding="utf-8")

        self.assertEqual(missing["reason"], "invalid_message_date")
        self.assertEqual(invalid["reason"], "invalid_message_date")
        self.assertNotIn("No persistir fecha ausente", state_text)
        self.assertNotIn("No persistir fecha inválida", state_text)

    def test_adding_a_chat_creates_a_new_boundary_and_purges_residual_pending_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original = self._service(data_dir, chat_ids=["123"])
            with patch.object(original, "_now_epoch_seconds", return_value=1_000):
                original.baseline_from_now()
            state = json.loads(original.state_path.read_text(encoding="utf-8"))
            original_boundary = state["chats"]["123"]["authorized_after_epoch"]
            # Simulate a stale residual entry from a previously unlisted chat.
            state["chats"]["456"] = {
                "authorized_after_epoch": 1,
                "pending_messages": [
                    {
                        "message_id": "old",
                        "update_id": "9",
                        "message_date_epoch": 1,
                        "content": "No conservar chat añadido",
                    }
                ],
            }
            original._save_json(original.state_path, state)

            added = self._service(data_dir, chat_ids=["123", "456"])
            with patch.object(added, "_now_epoch_seconds", return_value=2_000):
                initialized = added.baseline_from_now()
            state = json.loads(added.state_path.read_text(encoding="utf-8"))
            added_boundary = state["chats"]["456"]["authorized_after_epoch"]
            stale = added.ingest_webhook_update(
                _webhook_update(101, 1, "No conservar historial añadido", chat_id="456", date=2_000)
            )
            current = added.ingest_webhook_update(
                _webhook_update(102, 2, "Texto tras añadir el chat", chat_id="456", date=added_boundary)
            )
            state_text = added.state_path.read_text(encoding="utf-8")

        self.assertEqual(initialized["status"], "baseline_initialized")
        self.assertEqual(initialized["activated_chat_ids"], ["456"])
        self.assertEqual(state["chats"]["123"]["authorized_after_epoch"], original_boundary)
        self.assertEqual(added_boundary, 2_001)
        self.assertEqual(stale["reason"], "message_before_authorization")
        self.assertTrue(current["accepted"])
        self.assertNotIn("No conservar chat añadido", state_text)
        self.assertNotIn("No conservar historial añadido", state_text)
        self.assertIn("Texto tras añadir el chat", state_text)

    def test_removing_and_readding_a_chat_creates_a_new_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original = self._service(data_dir)
            with patch.object(original, "_now_epoch_seconds", return_value=1_000):
                original.baseline_from_now()
            original.ingest_webhook_update(_webhook_update(101, 1, "Texto antes de retirar", date=1_001))

            removed = self._service(data_dir, chat_ids=[])
            cleanup = removed.cleanup_retained_data()
            state_after_removal = json.loads(removed.state_path.read_text(encoding="utf-8"))

            readded = self._service(data_dir)
            with patch.object(readded, "_now_epoch_seconds", return_value=2_000):
                initialized = readded.baseline_from_now()
            state = json.loads(readded.state_path.read_text(encoding="utf-8"))
            boundary = state["chats"]["123"]["authorized_after_epoch"]
            state_text = readded.state_path.read_text(encoding="utf-8")

        self.assertEqual(cleanup["pending_messages_removed"], 1)
        self.assertEqual(state_after_removal["active_chat_ids"], [])
        self.assertEqual(state_after_removal["chats"], {})
        self.assertEqual(initialized["activated_chat_ids"], ["123"])
        self.assertEqual(boundary, 2_001)
        self.assertNotIn("Texto antes de retirar", state_text)

    def test_allowlist_removal_is_persisted_even_when_other_chat_baseline_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original = self._service(data_dir, chat_ids=["123", "456"])
            with patch.object(original, "_now_epoch_seconds", return_value=1_000):
                original.baseline_from_now()
            state = json.loads(original.state_path.read_text(encoding="utf-8"))
            first_boundary = state["chats"]["123"]["authorized_after_epoch"]

            removed = self._service(data_dir, chat_ids=["123"])
            removal = removed.baseline_from_now()
            state_after_removal = json.loads(removed.state_path.read_text(encoding="utf-8"))

            readded = self._service(data_dir, chat_ids=["123", "456"])
            with patch.object(readded, "_now_epoch_seconds", return_value=2_000):
                readd = readded.baseline_from_now()
            final_state = json.loads(readded.state_path.read_text(encoding="utf-8"))

        self.assertEqual(removal["status"], "already_initialized")
        self.assertTrue(removal["state_changed"])
        self.assertEqual(state_after_removal["active_chat_ids"], ["123"])
        self.assertNotIn("456", state_after_removal["chats"])
        self.assertEqual(readd["activated_chat_ids"], ["456"])
        self.assertEqual(final_state["chats"]["123"]["authorized_after_epoch"], first_boundary)
        self.assertEqual(final_state["chats"]["456"]["authorized_after_epoch"], 2_001)

    def test_deactivate_then_reenable_creates_a_new_boundary_and_purges_raw_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            enabled = self._service(data_dir)
            with patch.object(enabled, "_now_epoch_seconds", return_value=1_000):
                enabled.baseline_from_now()
            enabled.ingest_webhook_update(_webhook_update(101, 1, "Texto antes de desactivar", date=1_001))

            disabled = self._service(data_dir, enabled=False)
            deactivated = disabled.deactivate()
            state_after_disable = json.loads(disabled.state_path.read_text(encoding="utf-8"))

            reenabled = self._service(data_dir)
            with patch.object(reenabled, "_now_epoch_seconds", return_value=2_000):
                initialized = reenabled.baseline_from_now()
            state = json.loads(reenabled.state_path.read_text(encoding="utf-8"))
            boundary = state["chats"]["123"]["authorized_after_epoch"]
            state_text = reenabled.state_path.read_text(encoding="utf-8")

        self.assertTrue(deactivated["ok"])
        self.assertEqual(deactivated["pending_messages_removed"], 1)
        self.assertFalse(state_after_disable["reader_enabled"])
        self.assertEqual(state_after_disable["chats"], {})
        self.assertEqual(initialized["activated_chat_ids"], ["123"])
        self.assertEqual(boundary, 2_001)
        self.assertNotIn("Texto antes de desactivar", state_text)

    def test_unready_cleanup_never_reactivates_a_cleared_reader_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            service = self._service(data_dir)
            with patch.object(service, "_now_epoch_seconds", return_value=1_000):
                service.baseline_from_now()
            service.ingest_webhook_update(
                _webhook_update(101, 1, "Texto previo a una configuración incompleta", date=1_001)
            )

            service.deactivate()
            cleanup = service.cleanup_retained_data(intake_ready=False)
            state_after_cleanup = json.loads(service.state_path.read_text(encoding="utf-8"))

            with patch.object(service, "_now_epoch_seconds", return_value=2_000):
                reactivated = service.baseline_from_now()
            state_after_reactivation = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(cleanup["ok"])
        self.assertFalse(state_after_cleanup["reader_enabled"])
        self.assertEqual(state_after_cleanup["active_chat_ids"], [])
        self.assertEqual(state_after_cleanup["chats"], {})
        self.assertEqual(reactivated["activated_chat_ids"], ["123"])
        self.assertEqual(
            state_after_reactivation["chats"]["123"]["authorized_after_epoch"],
            2_001,
        )

    def test_normal_restart_preserves_existing_chat_boundary_and_new_pending_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original = self._service(data_dir)
            with patch.object(original, "_now_epoch_seconds", return_value=1_000):
                original.baseline_from_now()
            original.ingest_webhook_update(_webhook_update(101, 1, "Texto antes de reiniciar", date=1_001))

            restarted = self._service(data_dir)
            with patch.object(restarted, "_now_epoch_seconds", return_value=2_000):
                baseline = restarted.baseline_from_now()
            current = restarted.ingest_webhook_update(
                _webhook_update(102, 2, "Texto nuevo tras reinicio", date=2_000)
            )
            state = json.loads(restarted.state_path.read_text(encoding="utf-8"))

        self.assertEqual(baseline["status"], "already_initialized")
        self.assertFalse(baseline["state_changed"])
        self.assertTrue(current["accepted"])
        self.assertEqual(state["chats"]["123"]["authorized_after_epoch"], 1_001)
        self.assertEqual(
            [message["content"] for message in state["chats"]["123"]["pending_messages"]],
            ["Texto antes de reiniciar", "Texto nuevo tras reinicio"],
        )

    @patch("agents.telegram_reader.service.httpx.post")
    def test_first_webhook_delivery_initializes_and_accepts_a_fresh_message(self, post):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            accepted = service.ingest_webhook_update(_webhook_update(101, 1, "Primero desde activación"))
            state = json.loads(service.state_path.read_text(encoding="utf-8"))
            state_text = service.state_path.read_text(encoding="utf-8")

        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["baseline"], "baseline_initialized")
        self.assertEqual(state["baseline_source"], "automatic_webhook")
        self.assertIn("Primero desde activación", state_text)
        post.assert_not_called()

    @patch("agents.telegram_reader.service.httpx.post")
    def test_only_allowed_incoming_text_is_persisted_without_sender_identity(self, post):
        edited = _webhook_update(106, 6, "No conservar edición", kind="edited_business_message")
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            accepted = service.ingest_webhook_update(
                _webhook_update(101, 1, "Mensaje del cliente", kind="business_message")
            )
            service.ingest_webhook_update(_webhook_update(102, 2, "Otro chat", chat_id="999"))
            service.ingest_webhook_update(_webhook_update(103, 3, "Bot", bot=True))
            service.ingest_webhook_update(_webhook_update(104, 4, "Business bot", sender_business_bot=True))
            service.ingest_webhook_update(_webhook_update(105, 5, "Offline", offline=True))
            service.ingest_webhook_update(edited)
            state_text = service.state_path.read_text(encoding="utf-8")
            state = json.loads(state_text)

        self.assertTrue(accepted["accepted"])
        self.assertEqual(len(state["chats"]["123"]["pending_messages"]), 1)
        self.assertIn("Mensaje del cliente", state_text)
        self.assertNotIn("private_sender", state_text)
        self.assertNotIn("Private", state_text)
        self.assertNotIn("Otro chat", state_text)
        self.assertNotIn("Business bot", state_text)
        self.assertNotIn("No conservar edición", state_text)
        post.assert_not_called()

    def test_inbound_only_private_chat_guard_rejects_groups_and_sender_mismatches(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            group = service.ingest_webhook_update(
                _webhook_update(101, 1, "No guardar grupo", chat_type="group")
            )
            outgoing = service.ingest_webhook_update(
                _webhook_update(102, 2, "No guardar saliente", sender_id=999)
            )
            state_text = service.state_path.read_text(encoding="utf-8")

        self.assertEqual(group["reason"], "non_private_chat")
        self.assertEqual(outgoing["reason"], "non_customer_origin")
        self.assertNotIn("No guardar grupo", state_text)
        self.assertNotIn("No guardar saliente", state_text)

    def test_legacy_polling_state_is_reset_at_the_webhook_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service._save_json(
                service.state_path,
                {
                    "baseline_at": "2020-01-01T00:00:00+00:00",
                    "baseline_source": "automatic",
                    "last_update_id": "999",
                    "processed_update_ids": ["999"],
                    "chats": {
                        "123": {
                            "pending_messages": [
                                {
                                    "message_id": "old",
                                    "update_id": "999",
                                    "content": "No conservar histórico de polling",
                                }
                            ]
                        }
                    },
                },
            )

            accepted = service.ingest_webhook_update(_webhook_update(101, 1, "Mensaje nuevo"))
            state_text = service.state_path.read_text(encoding="utf-8")
            state = json.loads(state_text)

        self.assertTrue(accepted["accepted"])
        self.assertEqual(state["schema_version"], 3)
        self.assertEqual(state["baseline_source"], "automatic_webhook")
        self.assertEqual(state["processed_update_ids"], ["101"])
        self.assertNotIn("No conservar histórico de polling", state_text)

    def test_webhook_retries_are_deduplicated_and_processed_id_state_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            first = service.ingest_webhook_update(_webhook_update(101, 1, "Una vez"))
            retry = service.ingest_webhook_update(_webhook_update(101, 1, "Una vez"))
            state_before_bound = json.loads(service.state_path.read_text(encoding="utf-8"))
            state_before_bound["processed_update_ids"] = [
                str(200_000 + offset) for offset in range(service.MAX_PROCESSED_UPDATE_IDS)
            ]
            service._save_json(service.state_path, state_before_bound)
            service.ingest_webhook_update(_webhook_update(999_999, 2, "No permitido", chat_id="999"))
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(first["accepted"])
        self.assertTrue(retry["ignored"])
        self.assertEqual(retry["reason"], "duplicate_update")
        self.assertEqual(len(state["chats"]["123"]["pending_messages"]), 1)
        self.assertEqual(len(state["processed_update_ids"]), service.MAX_PROCESSED_UPDATE_IDS)
        self.assertNotIn("200000", state["processed_update_ids"])

    @patch("agents.telegram_reader.service.httpx.get")
    @patch("agents.telegram_reader.service.httpx.post")
    def test_pending_messages_are_summarized_by_openai_without_telegram_http_calls(self, post, get):
        post.return_value = _Response(_openai_response())
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Primer mensaje"))
            service.ingest_webhook_update(_webhook_update(102, 102, "Segundo mensaje"))

            result = service.process_pending_summaries()
            summaries = service.list_summaries()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary_count"], 1)
        self.assertEqual(post.call_args.args[0], service.OPENAI_RESPONSES_URL)
        self.assertFalse(post.call_args.kwargs["json"]["store"])
        model_input = json.loads(post.call_args.kwargs["json"]["input"])
        self.assertNotIn("chat_id", model_input)
        self.assertEqual(model_input["messages"][0]["message_id"], "101")
        get.assert_not_called()
        self.assertEqual(summaries[0]["source"], "answers_webhook")
        self.assertEqual(summaries[0]["chat_id"], "123")
        self.assertEqual(summaries[0]["suggested_tasks"][0]["evidence_message_ids"], ["101"])
        self.assertTrue(summaries[0]["suggested_tasks"][0]["task_key"])
        self.assertFalse(state["chats"]["123"]["pending_messages"])

    @patch("agents.telegram_reader.service.httpx.post")
    def test_pre_authorization_pending_text_is_purged_before_openai_processing(self, post):
        post.return_value = _Response(_openai_response(tasks=[]))
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), summary_min_messages=1)
            stored_at = datetime.now(timezone.utc).isoformat()
            service._save_json(
                service.state_path,
                {
                    "schema_version": 3,
                    "reader_enabled": True,
                    "active_chat_ids": ["123"],
                    "chats": {
                        "123": {
                            "authorized_after_epoch": 1_000,
                            "baseline_at": "1970-01-01T00:16:40+00:00",
                            "baseline_source": "manual",
                            "pending_messages": [
                                {
                                    "message_id": "stale",
                                    "update_id": "101",
                                    "message_date_epoch": 999,
                                    "content": "Nunca debe llegar a OpenAI",
                                    "stored_at": stored_at,
                                },
                                {
                                    "message_id": "fresh",
                                    "update_id": "102",
                                    "message_date_epoch": 1_000,
                                    "content": "Texto posterior autorizado",
                                    "stored_at": stored_at,
                                },
                            ],
                        }
                    },
                },
            )

            processed = service.process_pending_summaries()
            model_input = json.loads(post.call_args.kwargs["json"]["input"])
            state_text = service.state_path.read_text(encoding="utf-8")

        self.assertTrue(processed["ok"])
        self.assertEqual(processed["summary_count"], 1)
        self.assertEqual([item["message_id"] for item in model_input["messages"]], ["fresh"])
        self.assertNotIn("Nunca debe llegar a OpenAI", state_text)
        self.assertIn("Texto posterior autorizado", model_input["messages"][0]["content"])

    @patch("agents.telegram_reader.service.httpx.post")
    def test_under_threshold_input_waits_until_later_webhook_delivery(self, post):
        post.return_value = _Response(_openai_response(tasks=[]))
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Uno"))

            waiting = service.process_pending_summaries()
            service.ingest_webhook_update(_webhook_update(102, 102, "Dos"))
            summarized = service.process_pending_summaries()

        self.assertEqual(waiting["chats"][0]["status"], "waiting_for_threshold")
        self.assertEqual(summarized["summary_count"], 1)
        post.assert_called_once()

    @patch("agents.telegram_reader.service.httpx.post")
    def test_openai_failure_retains_pending_messages_for_a_later_retry(self, post):
        post.side_effect = [httpx.TimeoutException("timeout"), _Response(_openai_response())]
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Uno"))
            service.ingest_webhook_update(_webhook_update(102, 102, "Dos"))

            failed = service.process_pending_summaries()
            state_after_failure = json.loads(service.state_path.read_text(encoding="utf-8"))
            recovered = service.process_pending_summaries()

        self.assertFalse(failed["ok"])
        self.assertEqual(len(state_after_failure["chats"]["123"]["pending_messages"]), 2)
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["summary_count"], 1)
        self.assertEqual(post.call_count, 2)

    @patch("agents.telegram_reader.service.httpx.post")
    def test_slow_openai_processing_does_not_block_later_webhook_ingestion(self, post):
        started = threading.Event()
        unblock = threading.Event()

        def slow_response(*_args, **_kwargs):
            started.set()
            self.assertTrue(unblock.wait(timeout=2), "test did not release mocked OpenAI")
            return _Response(_openai_response(tasks=[]))

        post.side_effect = slow_response
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Uno"))
            service.ingest_webhook_update(_webhook_update(102, 102, "Dos"))
            result_holder = {}
            worker = threading.Thread(
                target=lambda: result_holder.setdefault("result", service.process_pending_summaries())
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2), "OpenAI was not reached")

            later = service.ingest_webhook_update(_webhook_update(103, 103, "Tres mientras resume"))
            unblock.set()
            worker.join(timeout=3)
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertFalse(worker.is_alive())
        self.assertTrue(later["accepted"])
        self.assertTrue(result_holder["result"]["ok"])
        pending = state["chats"]["123"]["pending_messages"]
        self.assertEqual([item["update_id"] for item in pending], ["103"])

    @patch("agents.telegram_reader.service.httpx.post")
    def test_expired_snapshot_during_openai_is_not_persisted_as_a_summary(self, post):
        started = threading.Event()
        unblock = threading.Event()

        def slow_response(*_args, **_kwargs):
            started.set()
            self.assertTrue(unblock.wait(timeout=2), "test did not release mocked OpenAI")
            return _Response(_openai_response(tasks=[]))

        post.side_effect = slow_response
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), retention_days=1)
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Uno"))
            service.ingest_webhook_update(_webhook_update(102, 102, "Dos"))
            result_holder = {}
            worker = threading.Thread(
                target=lambda: result_holder.setdefault("result", service.process_pending_summaries())
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2), "OpenAI was not reached")

            with service._lock:
                state = service._load_json(service.state_path, service._default_state())
                for message in state["chats"]["123"]["pending_messages"]:
                    message["stored_at"] = "2020-01-01T00:00:00+00:00"
                service._save_json(service.state_path, state)
            cleanup = service.cleanup_retained_data()
            unblock.set()
            worker.join(timeout=3)
            summaries = service.list_summaries()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertFalse(worker.is_alive())
        self.assertEqual(cleanup["pending_messages_removed"], 2)
        self.assertTrue(result_holder["result"]["ok"])
        self.assertEqual(result_holder["result"]["summary_count"], 0)
        self.assertEqual(result_holder["result"]["message_count"], 0)
        self.assertEqual(result_holder["result"]["chats"][0]["status"], "snapshot_discarded")
        self.assertTrue(
            any(item["code"] == "pending_snapshot_discarded" for item in result_holder["result"]["warnings"])
        )
        self.assertEqual(summaries, [])
        self.assertEqual(state["chats"]["123"]["pending_messages"], [])

    @patch("agents.telegram_reader.service.httpx.post")
    def test_processing_reentry_is_skipped_while_one_run_is_active(self, post):
        started = threading.Event()
        unblock = threading.Event()

        def slow_response(*_args, **_kwargs):
            started.set()
            unblock.wait(timeout=2)
            return _Response(_openai_response(tasks=[]))

        post.side_effect = slow_response
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            service.baseline_from_now()
            service.ingest_webhook_update(_webhook_update(101, 101, "Uno"))
            service.ingest_webhook_update(_webhook_update(102, 102, "Dos"))
            worker = threading.Thread(target=service.process_pending_summaries)
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            reentrant = service.process_pending_summaries()
            unblock.set()
            worker.join(timeout=3)

        self.assertTrue(reentrant["ok"])
        self.assertTrue(reentrant["skipped"])
        self.assertEqual(reentrant["reason"], "processing_in_progress")

    def test_retention_purges_expired_pending_input_and_summary_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), retention_days=1)
            service._save_json(
                service.state_path,
                {
                    "schema_version": 3,
                    "baseline_at": "2020-01-01T00:00:00+00:00",
                    "baseline_source": "manual",
                    "reader_enabled": True,
                    "active_chat_ids": ["123"],
                    "processed_update_ids": [],
                    "chats": {
                        "123": {
                            "authorized_after_epoch": 1,
                            "pending_messages": [
                                {
                                    "message_id": "1",
                                    "update_id": "1",
                                    "message_date_epoch": 1,
                                    "content": "caducado",
                                    "stored_at": "2020-01-01T00:00:00+00:00",
                                }
                            ]
                        }
                    },
                },
            )
            service._save_json(
                service.summaries_path,
                {
                    "items": [
                        {"summary_id": "expired", "created_at": "2020-01-01T00:00:00+00:00"},
                        {"summary_id": "current", "created_at": "2099-01-01T00:00:00+00:00"},
                    ]
                },
            )

            processed = service.process_pending_summaries()
            summaries = service.list_summaries()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))

        self.assertTrue(processed["ok"])
        self.assertTrue(any(item["code"] == "pending_messages_expired" for item in processed["warnings"]))
        self.assertFalse(state["chats"]["123"]["pending_messages"])
        self.assertEqual([item["summary_id"] for item in summaries], ["current"])

    @patch("agents.telegram_reader.service.httpx.post")
    def test_disabled_cleanup_purges_all_raw_reader_data_without_network_calls(self, post):
        """Disabled intake must clear raw text before any later re-enable."""
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                enabled=False,
                openai_api_key="",
                chat_ids=[],
                retention_days=1,
            )
            service._save_json(
                service.state_path,
                {
                    "schema_version": 3,
                    "reader_enabled": True,
                    "active_chat_ids": ["456"],
                    "chats": {
                        # This intentionally is no longer in the allow-list.
                        "456": {
                            "pending_messages": [
                                {
                                    "message_id": "old",
                                    "update_id": "1",
                                    "content": "expired private text",
                                    "stored_at": "2020-01-01T00:00:00+00:00",
                                },
                                {
                                    "message_id": "fresh",
                                    "update_id": "2",
                                    "content": "fresh private text",
                                    "stored_at": "2099-01-01T00:00:00+00:00",
                                },
                            ]
                        }
                    },
                },
            )
            service._save_json(
                service.summaries_path,
                {
                    "items": [
                        {"summary_id": "old", "created_at": "2020-01-01T00:00:00+00:00"},
                        {"summary_id": "fresh", "created_at": "2099-01-01T00:00:00+00:00"},
                    ]
                },
            )

            cleaned = service.cleanup_retained_data()
            state = json.loads(service.state_path.read_text(encoding="utf-8"))
            summaries = json.loads(service.summaries_path.read_text(encoding="utf-8"))
            data_dir_exists = service.data_dir.exists()

        self.assertTrue(cleaned["ok"])
        self.assertEqual(cleaned["pending_messages_removed"], 2)
        self.assertEqual(cleaned["summaries_removed"], 1)
        self.assertFalse(state["reader_enabled"])
        self.assertEqual(state["active_chat_ids"], [])
        self.assertEqual(state["chats"], {})
        self.assertEqual([item["summary_id"] for item in summaries["items"]], ["fresh"])
        self.assertTrue(data_dir_exists)
        post.assert_not_called()

    @patch("agents.telegram_reader.service.httpx.post")
    def test_retention_cleanup_does_not_create_empty_state_files(self, post):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                enabled=False,
                openai_api_key="",
                chat_ids=[],
            )

            cleaned = service.cleanup_retained_data()
            data_dir_exists = service.data_dir.exists()

        self.assertTrue(cleaned["ok"])
        self.assertEqual(cleaned["pending_messages_removed"], 0)
        self.assertEqual(cleaned["summaries_removed"], 0)
        self.assertFalse(data_dir_exists)
        post.assert_not_called()

    def test_dismissal_and_restore_persist_without_network_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            service = self._service(data_dir)
            service._save_json(
                service.summaries_path,
                {
                    "items": [
                        {
                            "summary_id": "telegram-123-102",
                            "created_at": "2099-01-01T00:00:00+00:00",
                            "source": "answers_webhook",
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
            task_key = service.list_summaries()[0]["suggested_tasks"][0]["task_key"]
            dismissed = service.dismiss_suggested_task("telegram-123-102", task_key, "duplicate")
            reloaded = self._service(data_dir)
            persisted = reloaded.list_summaries()[0]["suggested_tasks"][0]
            restored = reloaded.restore_suggested_task("telegram-123-102", task_key)

        self.assertTrue(dismissed["dismissed"])
        self.assertEqual(dismissed["dismissed_reason"], "duplicate")
        self.assertTrue(persisted["dismissed"])
        self.assertFalse(restored["dismissed"])
        self.assertEqual(restored["dismissed_reason"], "")


if __name__ == "__main__":
    unittest.main()
