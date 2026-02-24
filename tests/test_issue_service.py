import logging
import sys
import tempfile
import types
import unittest
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


if __name__ == "__main__":
    unittest.main()
