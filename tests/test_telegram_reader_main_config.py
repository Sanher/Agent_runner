"""Reader configuration checks that load main against an isolated data directory."""

import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import Mock, patch


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


@contextmanager
def _stub_playwright_when_unavailable() -> Iterator[None]:
    """Allow this configuration-only import to run without browser tooling."""
    try:
        import playwright.sync_api  # noqa: F401
    except ModuleNotFoundError:
        fake_sync_api = types.ModuleType("playwright.sync_api")

        class _FakeTimeoutError(Exception):
            pass

        def _unsupported_sync_playwright():
            raise RuntimeError("Playwright is unavailable in this configuration test")

        fake_sync_api.TimeoutError = _FakeTimeoutError
        fake_sync_api.sync_playwright = _unsupported_sync_playwright
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.sync_api = fake_sync_api
        with patch.dict(
            sys.modules,
            {"playwright": fake_playwright, "playwright.sync_api": fake_sync_api},
            clear=False,
        ):
            yield
    else:
        yield


@contextmanager
def _load_isolated_main(
    *,
    answers_token: str,
    webhook_secret: str,
    legacy_answers_token: str = "",
    legacy_webhook_secret: str = "",
    misspelled_webhook_secret: str = "",
    reader_enabled: bool = True,
) -> Iterator[object]:
    """Load the application without reading the repository's runtime options."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        environment = {
            "AGENT_RUNNER_DATA_DIR": str(data_dir),
            "ANSWERS_DATA_DIR": str(data_dir / "answers_agent"),
            "JOB_SECRET": "test-job-secret",
            "WORKDAY_TIMEZONE": "UTC",
            "TELEGRAM_READER_ENABLED": "true" if reader_enabled else "false",
            "TELEGRAM_READER_CHAT_IDS": "123456789",
            "DISCORD_OPENAI_API_KEY": "test-openai-key",
            "DISCORD_OPENAI_MODEL": "test-model",
            "ANSWERS_TELEGRAM_BOT_TOKEN": answers_token,
            "TELEGRAM_BOT_TOKEN": legacy_answers_token,
            "ANSWERS_WEBHOOK_SECRET": webhook_secret,
            "TELEGRAM_WEBHOOK_SECRET": legacy_webhook_secret,
            "TELEGRAM_WEHBOOK_SECRET": misspelled_webhook_secret,
        }
        module_name = "_test_telegram_reader_main_config"
        spec = importlib.util.spec_from_file_location(module_name, MAIN_PATH)
        if spec is None or spec.loader is None:  # pragma: no cover - source is always present
            raise RuntimeError("Unable to load main.py for isolated config test")
        module = importlib.util.module_from_spec(spec)
        previous_module = sys.modules.get(module_name)

        try:
            with _stub_playwright_when_unavailable(), patch.dict(os.environ, environment, clear=False):
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                    yield module
                finally:
                    if previous_module is None:
                        sys.modules.pop(module_name, None)
                    else:
                        sys.modules[module_name] = previous_module
        finally:
            # main.py applies its configured timezone during import. Restore the
            # interpreter timezone after this isolated configuration exercise.
            if hasattr(time, "tzset"):
                time.tzset()


class TelegramReaderMainConfigTests(unittest.TestCase):
    def test_reader_rejects_common_credential_placeholders(self) -> None:
        for placeholder in (" false ", "NoNe", " NULL "):
            with self.subTest(placeholder=placeholder):
                with _load_isolated_main(
                    answers_token=placeholder,
                    webhook_secret=placeholder,
                ) as app:
                    payload = app._telegram_reader_health_payload()

                self.assertIn("answers_telegram_bot_token", payload["missing_required_config"])
                self.assertIn("answers_webhook_secret", payload["missing_required_config"])
                self.assertFalse(payload["has_answers_telegram_token"])
                self.assertFalse(payload["has_answers_webhook_secret"])
                self.assertFalse(payload["config_valid"])

    def test_reader_accepts_non_placeholder_shared_answers_credentials(self) -> None:
        with _load_isolated_main(
            answers_token="test-bot-token",
            webhook_secret="test-webhook-secret",
        ) as app:
            payload = app._telegram_reader_health_payload()

        self.assertNotIn("answers_telegram_bot_token", payload["missing_required_config"])
        self.assertNotIn("answers_webhook_secret", payload["missing_required_config"])
        self.assertTrue(payload["has_answers_telegram_token"])
        self.assertTrue(payload["has_answers_webhook_secret"])
        self.assertTrue(payload["config_valid"])

    def test_answers_webhook_secret_is_canonical_and_legacy_values_remain_available(self) -> None:
        with _load_isolated_main(
            answers_token="test-bot-token",
            webhook_secret="canonical-secret",
            legacy_webhook_secret="legacy-secret",
            misspelled_webhook_secret="legacy-typo-secret",
        ) as app:
            webhook_secrets = app.ANSWERS_TELEGRAM_WEBHOOK_SECRETS
            primary_secret = app.ANSWERS_TELEGRAM_WEBHOOK_SECRET

        self.assertEqual(primary_secret, "canonical-secret")
        self.assertEqual(
            webhook_secrets,
            ["canonical-secret", "legacy-secret", "legacy-typo-secret"],
        )

    def test_placeholder_canonical_values_fall_back_to_valid_legacy_credentials(self) -> None:
        with _load_isolated_main(
            answers_token="false",
            legacy_answers_token="legacy-bot-token",
            webhook_secret="none",
            legacy_webhook_secret="legacy-webhook-secret",
        ) as app:
            payload = app._telegram_reader_health_payload()

        self.assertEqual(app.ANSWERS_TELEGRAM_BOT_TOKEN, "legacy-bot-token")
        self.assertEqual(app.ANSWERS_TELEGRAM_WEBHOOK_SECRETS, ["legacy-webhook-secret"])
        self.assertEqual(app.ANSWERS_TELEGRAM_WEBHOOK_SECRET, "legacy-webhook-secret")
        self.assertTrue(payload["has_answers_telegram_token"])
        self.assertTrue(payload["has_answers_webhook_secret"])
        self.assertTrue(payload["config_valid"])

    def test_unready_reader_clears_local_intake_before_starting_workers(self) -> None:
        with _load_isolated_main(
            answers_token="false",
            webhook_secret="false",
        ) as app:
            deactivate = Mock(return_value={"ok": True, "pending_messages_removed": 2})
            baseline = Mock()
            app.telegram_reader_service.deactivate = deactivate
            app.telegram_reader_service.baseline_from_now = baseline
            app.AGENT_MODULES = []

            app._on_startup()

        deactivate.assert_called_once_with()
        baseline.assert_not_called()

    def test_disabled_reader_clears_local_intake_before_starting_workers(self) -> None:
        with _load_isolated_main(
            answers_token="test-bot-token",
            webhook_secret="test-webhook-secret",
            reader_enabled=False,
        ) as app:
            deactivate = Mock(return_value={"ok": True, "pending_messages_removed": 0})
            baseline = Mock()
            app.telegram_reader_service.deactivate = deactivate
            app.telegram_reader_service.baseline_from_now = baseline
            app.AGENT_MODULES = []

            app._on_startup()

        deactivate.assert_called_once_with()
        baseline.assert_not_called()

    def test_webhook_fanout_requires_complete_reader_configuration(self) -> None:
        with _load_isolated_main(
            answers_token="false",
            webhook_secret="false",
        ) as app:
            with patch.object(app, "create_answers_router") as create_router:
                modules = app._build_agent_modules()
                next(module for module in modules if module.name == "answers_agent").router_factory()

        self.assertIsNone(create_router.call_args.kwargs["telegram_reader_sink"])

    def test_unready_retention_cleanup_keeps_the_reader_deactivated(self) -> None:
        with _load_isolated_main(
            answers_token="false",
            webhook_secret="false",
        ) as app:
            cleanup = Mock(
                return_value={
                    "ok": True,
                    "pending_messages_removed": 0,
                    "summaries_removed": 0,
                }
            )
            app.telegram_reader_service.cleanup_retained_data = cleanup

            app._telegram_reader_retention_cleanup_once()

        cleanup.assert_called_once_with(intake_ready=False)


if __name__ == "__main__":
    unittest.main()
