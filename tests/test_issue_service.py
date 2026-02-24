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
    def press(self, *args, **kwargs):
        return None


class _FailingPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()

    def locator(self, *args, **kwargs):
        return _FailingLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


@unittest.skipUnless(DEPS_AVAILABLE, "issue agent dependencies are not installed in this environment")
class IssueServiceTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> IssueAgentService:
        return IssueAgentService(
            data_dir=data_dir,
            repo_base_url="https://github.com/dextools-io",
            project_name="Dextools",
            storage_state_path=str(data_dir / "storage" / "issue_agent.json"),
            openai_api_key="x",
            openai_model="gpt-5",
            openai_style_law="",
            webhook_url="",
            logger=logging.getLogger("tests.issue"),
            bug_parent_repo_by_repo={},
            bug_parent_issue_number_by_repo={},
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


if __name__ == "__main__":
    unittest.main()
