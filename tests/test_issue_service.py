import logging
import json
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


def _load_issue_service():
    def _stub_missing_dependency(module_name: str) -> bool:
        if module_name in {"playwright", "playwright.sync_api"}:
            fake_sync_api = types.ModuleType("playwright.sync_api")

            class _FakeTimeoutError(Exception):
                pass

            def _unsupported_sync_playwright():
                raise RuntimeError("sync_playwright is not available in this test environment")

            fake_sync_api.sync_playwright = _unsupported_sync_playwright
            fake_sync_api.TimeoutError = _FakeTimeoutError
            fake_playwright = types.ModuleType("playwright")
            fake_playwright.sync_api = fake_sync_api
            sys.modules.setdefault("playwright", fake_playwright)
            sys.modules.setdefault("playwright.sync_api", fake_sync_api)
            return True

        if module_name == "httpx":
            fake_httpx = types.ModuleType("httpx")

            def _unsupported_httpx(*args, **kwargs):
                raise RuntimeError("httpx is not available in this test environment")

            fake_httpx.post = _unsupported_httpx
            sys.modules.setdefault("httpx", fake_httpx)
            return True

        return False

    try:
        from agents.issue_agent.service import IssueAgentService

        return IssueAgentService, True
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local environment
        if not _stub_missing_dependency(str(exc.name or "")):
            return None, False
        sys.modules.pop("agents.issue_agent.service", None)
        try:
            from agents.issue_agent.service import IssueAgentService
        except ModuleNotFoundError as second_exc:
            if not _stub_missing_dependency(str(second_exc.name or "")):
                return None, False
            sys.modules.pop("agents.issue_agent.service", None)
            from agents.issue_agent.service import IssueAgentService

        return IssueAgentService, True
    except Exception:
        return None, False


IssueAgentService, DEPS_AVAILABLE = _load_issue_service()


class _FailingLocator:
    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def click(self, *args, **kwargs):
        raise RuntimeError("click failed")

    def wait_for(self, *args, **kwargs):
        raise RuntimeError("wait failed")

    def count(self):
        return 1

    def get_attribute(self, *args, **kwargs):
        return "false"


class _FakeKeyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key, *args, **kwargs):
        self.pressed.append(str(key))
        return None


class _FailingPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()

    def locator(self, *args, **kwargs):
        return _FailingLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _SuccessLocator:
    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def click(self, *args, **kwargs):
        return None

    def wait_for(self, *args, **kwargs):
        return None

    def count(self):
        return 1

    def get_attribute(self, *args, **kwargs):
        return "false"


class _SuccessPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()

    def locator(self, *args, **kwargs):
        return _SuccessLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _FlakyFieldLocator:
    def __init__(self):
        self.attempts = 0

    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def wait_for(self, *args, **kwargs):
        return None

    def scroll_into_view_if_needed(self, *args, **kwargs):
        return None

    def click(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts < 3:
            raise RuntimeError("click failed")
        return None


class _FlakyFieldPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()
        self.field_locator = _FlakyFieldLocator()

    def locator(self, *args, **kwargs):
        return self.field_locator

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _BusinessUnitLocator:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def count(self):
        return 1 if self.page.business_unit_visible else 0


class _ButtonRootLocator:
    def __init__(self, page):
        self.page = page

    def filter(self, **kwargs):
        has_text = kwargs.get("has_text")
        if has_text is not None and "Business Unit" in str(has_text):
            return _BusinessUnitLocator(self.page)
        return _SuccessLocator()


class _ChevronItemLocator:
    def __init__(self, page):
        self.page = page

    def scroll_into_view_if_needed(self, *args, **kwargs):
        return None

    def click(self, *args, **kwargs):
        self.page.chevron_clicks += 1
        self.page.business_unit_visible = True
        return None


class _ChevronGroupLocator:
    def __init__(self, page):
        self.page = page

    def filter(self, **kwargs):
        return self

    def count(self):
        return 1

    def nth(self, idx):
        return _ChevronItemLocator(self.page)


class _ChevronExpansionPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()
        self.business_unit_visible = False
        self.chevron_clicks = 0

    def locator(self, selector, *args, **kwargs):
        if selector == "button":
            return _ButtonRootLocator(self)
        if selector == "button[data-component='IconButton'][aria-expanded='false']":
            return _ChevronGroupLocator(self)
        if selector == "svg.octicon-chevron-down":
            return _SuccessLocator()
        return _SuccessLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


@unittest.skipUnless(DEPS_AVAILABLE, "issue agent dependencies are not installed in this environment")
class IssueServiceTests(unittest.TestCase):
    def _build_service(
        self,
        data_dir: Path,
        *,
        bug_parent_repo_by_repo: dict | None = None,
        bug_parent_issue_number_by_repo: dict | None = None,
    ) -> IssueAgentService:
        return IssueAgentService(
            data_dir=data_dir,
            repo_base_url="https://example.test/test-org",
            project_name="SampleProject",
            storage_state_path=str(data_dir / "storage" / "issue_agent.json"),
            openai_api_key="x",
            openai_model="gpt-5",
            openai_style_law="",
            webhook_url="",
            logger=logging.getLogger("tests.issue"),
            bug_parent_repo_by_repo=bug_parent_repo_by_repo or {},
            bug_parent_issue_number_by_repo=bug_parent_issue_number_by_repo or {},
        )

    def test_apply_bug_parent_relationship_returns_warning_when_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            warning = svc._apply_bug_parent_relationship(page=None, repo="frontend")
            self.assertIsInstance(warning, str)
            self.assertIn("Parent relationship skipped", warning)

    def test_apply_post_creation_fields_is_non_blocking_and_returns_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _FailingPage()
            warnings = svc._apply_post_creation_fields(
                page=page,
                unit_label="Customer",
                team_label="Frontend",
                status_label="Todo",
            )
            self.assertIsInstance(warnings, list)
            self.assertGreaterEqual(len(warnings), 3)
            self.assertTrue(any("status selection failed" in item for item in warnings))
            self.assertTrue(any("business unit failed" in item for item in warnings))

    def test_apply_bug_parent_relationship_uses_management_repo_for_configured_parent_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(
                Path(tmp),
                bug_parent_repo_by_repo={
                    "frontend": "example-org/frontend",
                    "backend": "example-org/backend",
                    "management": "example-org/management",
                },
                bug_parent_issue_number_by_repo={
                    "frontend": "101",
                    "backend": "202",
                    "management": "303",
                },
            )
            warning = svc._apply_bug_parent_relationship(page=_FailingPage(), repo="frontend")
            self.assertIsInstance(warning, str)
            self.assertIn("parent_repo=example-org/management", warning)
            self.assertIn("parent_issue=101", warning)

    def test_apply_post_creation_fields_drops_collapsed_warning_when_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _SuccessPage()
            calls = {"count": 0}

            def _ensure_visible(_page):
                calls["count"] += 1
                return calls["count"] > 1

            svc._ensure_project_post_fields_visible = _ensure_visible
            svc._click_option_by_text = lambda *args, **kwargs: None

            warnings = svc._apply_post_creation_fields(
                page=page,
                unit_label="Customer",
                team_label="Frontend",
                status_label="Todo",
            )
            self.assertEqual([], warnings)

    def test_apply_post_creation_fields_dismisses_overlays_after_field_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _SuccessPage()
            warnings = svc._apply_post_creation_fields(
                page=page,
                unit_label="Customer",
                team_label="Frontend",
                status_label="Backlog",
            )
            self.assertEqual([], warnings)
            self.assertGreaterEqual(page.keyboard.pressed.count("Escape"), 2)

    def test_open_project_field_button_retries_until_click_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _FlakyFieldPage()
            svc._open_project_field_button(page, "Business Unit", timeout_ms=50)
            self.assertEqual(3, page.field_locator.attempts)
            self.assertGreaterEqual(page.keyboard.pressed.count("Escape"), 2)

    def test_ensure_project_post_fields_visible_expands_with_chevron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _ChevronExpansionPage()
            visible = svc._ensure_project_post_fields_visible(page)
            self.assertTrue(visible)
            self.assertGreaterEqual(page.chevron_clicks, 1)

    def test_weekly_cleanup_removes_old_runs_and_old_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            svc = self._build_service(base)

            runs_root = base / "runs" / "issue_flow"
            old_run = runs_root / "old-run"
            new_run = runs_root / "new-run"
            old_run.mkdir(parents=True, exist_ok=True)
            new_run.mkdir(parents=True, exist_ok=True)

            now_ts = time.time()
            old_ts = now_ts - (8 * 24 * 60 * 60)
            new_ts = now_ts - 60
            old_file = old_run / "old.png"
            new_file = new_run / "new.png"
            old_file.write_text("x", encoding="utf-8")
            new_file.write_text("y", encoding="utf-8")
            os_old = (old_ts, old_ts)
            os_new = (new_ts, new_ts)
            import os
            os.utime(old_run, os_old)
            os.utime(old_file, os_old)
            os.utime(new_run, os_new)
            os.utime(new_file, os_new)

            old_event_ts = (datetime.now() - timedelta(days=8)).isoformat()
            new_event_ts = (datetime.now() - timedelta(hours=1)).isoformat()
            svc.events_path.parent.mkdir(parents=True, exist_ok=True)
            svc.events_path.write_text(
                "\n".join(
                    [
                        json.dumps({"ts": old_event_ts, "event": "old"}),
                        json.dumps({"ts": new_event_ts, "event": "new"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stale_state = {"last_weekly_cleanup": (datetime.now() - timedelta(days=8)).isoformat()}
            svc._save_cleanup_state(stale_state)
            svc._maybe_weekly_cleanup()

            self.assertFalse(old_run.exists())
            self.assertTrue(new_run.exists())

            remaining_lines = svc.events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(remaining_lines))
            self.assertIn('"event": "new"', remaining_lines[0])

            state = svc._load_cleanup_state()
            self.assertIn("last_weekly_cleanup", state)

    def test_weekly_cleanup_skips_when_recently_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            svc = self._build_service(base)

            runs_root = base / "runs" / "issue_flow"
            old_run = runs_root / "old-run"
            old_run.mkdir(parents=True, exist_ok=True)
            old_file = old_run / "old.png"
            old_file.write_text("x", encoding="utf-8")
            old_ts = time.time() - (8 * 24 * 60 * 60)
            import os
            os.utime(old_run, (old_ts, old_ts))
            os.utime(old_file, (old_ts, old_ts))

            recent_state = {"last_weekly_cleanup": datetime.now().isoformat()}
            svc._save_cleanup_state(recent_state)
            svc._maybe_weekly_cleanup()

            self.assertTrue(old_run.exists())


if __name__ == "__main__":
    unittest.main()
