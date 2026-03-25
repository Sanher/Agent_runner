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

    def nth(self, idx):
        return self

    def locator(self, *args, **kwargs):
        return self

    def get_attribute(self, *args, **kwargs):
        return "false"

    def is_visible(self):
        return False


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

    def nth(self, idx):
        return self

    def locator(self, *args, **kwargs):
        return self

    def get_attribute(self, *args, **kwargs):
        return "false"

    def is_visible(self):
        return False


class _SuccessPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()

    def locator(self, *args, **kwargs):
        return _SuccessLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _FrontendSubmitLocator(_SuccessLocator):
    def fill(self, *args, **kwargs):
        return None


class _FrontendSubmitPage:
    def locator(self, *args, **kwargs):
        return _FrontendSubmitLocator()

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

    def is_visible(self):
        return bool(self.page.business_unit_visible)


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
        if selector == "button[data-component='IconButton']":
            return _ChevronGroupLocator(self)
        if selector == "svg.octicon-chevron-down, svg.octicon-triangle-down":
            return _SuccessLocator()
        if selector == "svg.octicon-chevron-down":
            return _SuccessLocator()
        return _SuccessLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _ProjectFieldsVisibilityLocator:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.page.business_unit_visible else 0

    def is_visible(self):
        return bool(self.page.business_unit_visible)


class _ProjectButtonRootLocator:
    def __init__(self, page):
        self.page = page

    def filter(self, **kwargs):
        has_text = kwargs.get("has_text")
        rendered = str(has_text or "")
        if "Business Unit" in rendered:
            return _ProjectFieldsVisibilityLocator(self.page)
        return _SuccessLocator()


class _ProjectToggleItemLocator:
    def __init__(self, page, group_id: str):
        self.page = page
        self.group_id = group_id

    def scroll_into_view_if_needed(self, *args, **kwargs):
        return None

    def click(self, *args, **kwargs):
        self.page.click_log.append(self.group_id)
        if self.group_id in self.page.expand_on_groups:
            self.page.business_unit_visible = True
        return None


class _ProjectToggleGroupLocator:
    def __init__(self, page, group_id: str):
        self.page = page
        self.group_id = group_id

    def filter(self, **kwargs):
        return self

    def count(self):
        return int(self.page.group_counts.get(self.group_id, 0))

    def nth(self, idx):
        return _ProjectToggleItemLocator(self.page, self.group_id)


class _ProjectSectionLocator:
    def __init__(self, page, kind: str):
        self.page = page
        self.kind = kind

    def filter(self, **kwargs):
        has_text = str(kwargs.get("has_text") or "")
        lowered = has_text.lower()
        if "projects" in lowered and self.kind == "root":
            return _ProjectSectionLocator(self.page, "projects")
        if "sampleproject" in lowered and self.kind in {"root", "projects"}:
            return _ProjectSectionLocator(self.page, "projects_and_name")
        if "status" in lowered and self.kind in {"root", "projects_and_name"}:
            return _ProjectSectionLocator(self.page, "project_status")
        return self

    def locator(self, selector, *args, **kwargs):
        if self.kind == "projects_and_name":
            if selector == "button[data-component='IconButton'][aria-expanded='false']":
                return _ProjectToggleGroupLocator(self.page, "projects_collapsed")
            if selector == "button[data-component='IconButton']":
                return _ProjectToggleGroupLocator(self.page, "projects_any")
        if self.kind == "project_status":
            if selector == "button[data-component='IconButton'][aria-expanded='false']":
                return _ProjectToggleGroupLocator(self.page, "project_status_collapsed")
            if selector == "button[data-component='IconButton']":
                return _ProjectToggleGroupLocator(self.page, "project_status_any")
        return _ProjectToggleGroupLocator(self.page, "none")


class _ProjectStatusXPathLocator:
    def __init__(self, page):
        self.page = page

    def locator(self, selector, *args, **kwargs):
        if selector == "button[data-component='IconButton'][aria-expanded='false']":
            return _ProjectToggleGroupLocator(self.page, "xpath_status_collapsed")
        if selector == "button[data-component='IconButton']":
            return _ProjectToggleGroupLocator(self.page, "xpath_status_any")
        return _ProjectToggleGroupLocator(self.page, "none")


class _ProjectExpansionPriorityPage:
    def __init__(self, *, group_counts=None, expand_on_groups=None):
        self.keyboard = _FakeKeyboard()
        self.business_unit_visible = False
        self.group_counts = group_counts or {}
        self.expand_on_groups = set(expand_on_groups or [])
        self.click_log = []

    def locator(self, selector, *args, **kwargs):
        if selector == "button":
            return _ProjectButtonRootLocator(self)
        if selector == "svg.octicon-chevron-down, svg.octicon-triangle-down":
            return _SuccessLocator()
        if selector == "div,section,aside":
            return _ProjectSectionLocator(self, "root")
        if selector == "xpath=//span[normalize-space()='Status']/ancestor::*[self::div or self::section or self::aside][1]":
            return _ProjectStatusXPathLocator(self)
        if selector == "button[data-component='IconButton'][aria-expanded='false']":
            return _ProjectToggleGroupLocator(self, "global_collapsed")
        if selector == "button[data-component='IconButton']":
            return _ProjectToggleGroupLocator(self, "global_any")
        return _SuccessLocator()

    def wait_for_timeout(self, *args, **kwargs):
        return None


class _IssueTypeKeyboard:
    def __init__(self, page):
        self.page = page
        self.pressed = []

    def press(self, key, *args, **kwargs):
        key_text = str(key)
        self.pressed.append(key_text)
        if key_text == "ArrowDown" and self.page.arrow_reveals_menuitem:
            self.page.menuitem_visible = True
        return None


class _IssueTypeEditButtonLocator:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def wait_for(self, *args, **kwargs):
        return None

    def click(self, *args, **kwargs):
        self.page.edit_type_clicks += 1
        return None


class _IssueTypeTypeChipLocator:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.page.type_chip_visible else 0

    def is_visible(self):
        return bool(self.page.type_chip_visible)


class _IssueTypeOptionLocator:
    def __init__(self, page, kind: str):
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def count(self):
        if self.kind == "input":
            return 0 if self.page.no_filter_input else 1
        return 1

    def wait_for(self, *args, **kwargs):
        if self.kind == "option" and not self.page.option_visible:
            raise RuntimeError("option not visible")
        if self.kind == "menuitem" and not self.page.menuitem_visible:
            raise RuntimeError("menuitem not visible")
        if self.kind == "button_option" and not self.page.button_option_visible:
            raise RuntimeError("button option not visible")
        if self.kind == "input" and self.page.no_filter_input:
            raise RuntimeError("filter input not visible")
        return None

    def click(self, *args, **kwargs):
        if self.kind in {"option", "menuitem", "button_option"}:
            self.page.type_selected = True
        return None

    def get_attribute(self, *args, **kwargs):
        return "true" if self.page.type_selected else "false"

    def fill(self, text, *args, **kwargs):
        self.page.last_filter_text = str(text)
        return None


class _IssueTypeButtonRootLocator:
    def __init__(self, page):
        self.page = page

    def filter(self, **kwargs):
        has_text = kwargs.get("has_text")
        rendered = str(has_text)
        if "Edit Type" in rendered:
            return _IssueTypeEditButtonLocator(self.page)
        if "Type" in rendered:
            return _IssueTypeTypeChipLocator(self.page)
        return _IssueTypeEditButtonLocator(self.page)


class _IssueTypePage:
    def __init__(self):
        self.keyboard = _IssueTypeKeyboard(self)
        self.edit_type_clicks = 0
        self.type_selected = False
        self.option_visible = False
        self.menuitem_visible = False
        self.button_option_visible = False
        self.no_filter_input = True
        self.type_chip_visible = False
        self.arrow_reveals_menuitem = True
        self.last_filter_text = ""

    def locator(self, selector, *args, **kwargs):
        if selector == "button":
            return _IssueTypeButtonRootLocator(self)
        if selector == "li[role='option']":
            return _IssueTypeOptionLocator(self, "option")
        if selector == "li[role='menuitem']":
            return _IssueTypeOptionLocator(self, "menuitem")
        if selector == "button[role='option']":
            return _IssueTypeOptionLocator(self, "button_option")
        if selector == 'input[aria-label="Choose an option"], input[placeholder*="Choose an option" i]':
            return _IssueTypeOptionLocator(self, "input")
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

    def test_ensure_project_post_fields_visible_prioritizes_project_container_before_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _ProjectExpansionPriorityPage(
                group_counts={
                    "projects_collapsed": 1,
                    "global_collapsed": 1,
                    "global_any": 1,
                },
                expand_on_groups={"projects_collapsed"},
            )
            visible = svc._ensure_project_post_fields_visible(page)
            self.assertTrue(visible)
            self.assertIn("projects_collapsed", page.click_log)
            self.assertNotIn("global_collapsed", page.click_log)

    def test_ensure_project_post_fields_visible_uses_global_fallback_when_context_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _ProjectExpansionPriorityPage(
                group_counts={
                    "projects_collapsed": 0,
                    "projects_any": 0,
                    "project_status_collapsed": 0,
                    "project_status_any": 0,
                    "xpath_status_collapsed": 0,
                    "xpath_status_any": 0,
                    "global_collapsed": 1,
                },
                expand_on_groups={"global_collapsed"},
            )
            visible = svc._ensure_project_post_fields_visible(page)
            self.assertTrue(visible)
            self.assertIn("global_collapsed", page.click_log)

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

    def test_get_events_filters_by_run_id_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc.events_path.parent.mkdir(parents=True, exist_ok=True)
            svc.events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ts": "2026-03-09T15:01:27",
                                "event": "issue_playwright_step",
                                "meta": {"run_id": "run-a", "message": "Page loaded"},
                            }
                        ),
                        json.dumps(
                            {
                                "ts": "2026-03-09T15:01:28",
                                "event": "issue_submitted",
                                "meta": {"run_id": "run-a"},
                            }
                        ),
                        json.dumps(
                            {
                                "ts": "2026-03-09T15:01:29",
                                "event": "issue_playwright_step",
                                "meta": {"run_id": "run-b", "message": "Page loaded"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = svc.get_events(limit=20, run_id="run-a", event="issue_playwright_step")

            self.assertEqual(1, len(payload["events"]))
            self.assertEqual("run-a", payload["events"][0]["meta"]["run_id"])
            self.assertEqual("issue_playwright_step", payload["events"][0]["event"])

    def test_mark_run_resolved_appends_historical_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))

            result = svc.mark_run_resolved("issue-20260309-144724")
            payload = svc.get_events(limit=20, run_id="issue-20260309-144724")

            self.assertTrue(result["ok"])
            self.assertEqual(1, len(payload["events"]))
            self.assertEqual("issue_run_resolved", payload["events"][0]["event"])
            self.assertEqual("issue-20260309-144724", payload["events"][0]["meta"]["run_id"])

    def test_extract_enrichment_urls_filters_local_and_repo_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))

            urls = svc._extract_enrichment_urls(
                "Docs https://docs.example.com/api and local http://127.0.0.1/test "
                "and repo https://example.test/test-org/backend/issues/new"
            )

            self.assertEqual(["https://docs.example.com/api"], urls)

    def test_generate_issue_new_feature_applies_enriched_fields_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._call_openai_issue_writer = lambda **kwargs: {
                "title": "Integrar API externa",
                "description": "ignored",
                "steps_to_reproduce": "",
                "comment": "",
                "close_issue": False,
                "warnings": {"user": ["missing_success_metric"], "source": []},
            }
            svc._enrich_new_feature_from_links = lambda **kwargs: {
                "fields": {
                    "competition": "Sí, hay soluciones similares verificadas.",
                    "why_better": "Podemos integrarlo con el flujo actual sin cambiar la UX.",
                    "third_party_integration": "Sí, habría que integrar la API pública y su autenticación.",
                },
                "warnings": ["No se ha podido verificar pricing desde las URLs aportadas."],
                "urls": ["https://docs.example.com/api"],
            }

            draft = svc.generate_issue(
                user_input="Integrar https://docs.example.com/api en el flujo de auditorías",
                issue_type="feature",
                repo="management",
                unit="customer",
                include_comment=False,
                comment_issue_number="",
                as_new_feature=True,
                as_third_party=False,
                enrich_links=True,
            )

            self.assertIn("Sí, hay soluciones similares verificadas.", draft["description"])
            self.assertIn("Podemos integrarlo con el flujo actual sin cambiar la UX.", draft["description"])
            self.assertEqual(
                {
                    "source": ["No se ha podido verificar pricing desde las URLs aportadas."],
                    "user": ["Falta definir una métrica de éxito."],
                },
                draft["draft_warnings"],
            )

    def test_generate_issue_new_feature_warns_when_enrichment_requested_without_valid_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._call_openai_issue_writer = lambda **kwargs: {
                "title": "Integrar API interna",
                "description": "ignored",
                "steps_to_reproduce": "",
                "comment": "",
                "close_issue": False,
            }

            draft = svc.generate_issue(
                user_input="Integrar http://127.0.0.1:8000/docs",
                issue_type="feature",
                repo="management",
                unit="customer",
                include_comment=False,
                comment_issue_number="",
                as_new_feature=True,
                as_third_party=False,
                enrich_links=True,
            )

            self.assertEqual(
                {
                    "source": ["No se han detectado enlaces externos válidos para enriquecer la solicitud."],
                    "user": [],
                },
                draft["draft_warnings"],
            )

    def test_generate_issue_blockchain_preserves_ai_draft_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._call_openai_issue_writer = lambda **kwargs: {
                "title": "base",
                "description": "**Blockchain relevant info**",
                "steps_to_reproduce": "",
                "comment": "",
                "close_issue": False,
                "warnings": {
                    "source": ["source_missing_tvl", "source_missing_exchange_confirmation"],
                    "user": [],
                },
            }

            draft = svc.generate_issue(
                user_input="Chain docs https://chain.example/docs",
                issue_type="blockchain",
                repo="backend",
                unit="core",
                include_comment=False,
                comment_issue_number="",
                as_new_feature=False,
                as_third_party=False,
            )

            self.assertEqual(
                {
                    "source": [
                        "No se ha podido verificar el TVL desde las fuentes aportadas.",
                        "No se ha podido confirmar el exchange principal desde las fuentes aportadas.",
                    ],
                    "user": [],
                },
                draft["draft_warnings"],
            )

    def test_generate_issue_exchange_preserves_ai_draft_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._call_openai_issue_writer = lambda **kwargs: {
                "title": "ExampleSwap",
                "description": "**Exchange relevant info**",
                "steps_to_reproduce": "",
                "comment": "",
                "close_issue": False,
                "warnings": {
                    "source": ["source_missing_factory"],
                    "user": ["missing_dependency_context"],
                },
            }

            draft = svc.generate_issue(
                user_input="Exchange docs https://exchange.example/docs",
                issue_type="exchange",
                repo="backend",
                unit="core",
                include_comment=False,
                comment_issue_number="",
                as_new_feature=False,
                as_third_party=False,
            )

            self.assertEqual(
                {
                    "source": ["No se ha podido verificar el contrato factory desde las fuentes aportadas."],
                    "user": ["Falta contexto sobre dependencias o integraciones implicadas."],
                },
                draft["draft_warnings"],
            )

    def test_generate_issue_backend_title_strips_issue_type_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._call_openai_issue_writer = lambda **kwargs: {
                "title": "[BUG] locks, audits - inconsistency in aggregation",
                "description": "desc",
                "steps_to_reproduce": "steps",
                "comment": "",
                "close_issue": False,
            }

            draft = svc.generate_issue(
                user_input="test",
                issue_type="bug",
                repo="backend",
                unit="core",
                include_comment=False,
                comment_issue_number="",
                as_new_feature=False,
                as_third_party=False,
            )

            self.assertEqual("LOCKS, AUDITS - inconsistency in aggregation", draft["title"])

    def test_apply_issue_type_accepts_menuitem_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _IssueTypePage()
            page.menuitem_visible = True
            warning = svc._apply_issue_type(page, "feature")
            self.assertIsNone(warning)
            self.assertTrue(page.type_selected)

    def test_apply_issue_type_handles_picker_without_filter_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _IssueTypePage()
            page.menuitem_visible = False
            page.no_filter_input = True
            warning = svc._apply_issue_type(page, "feature")
            self.assertIsNone(warning)
            self.assertIn("ArrowDown", page.keyboard.pressed)
            self.assertTrue(page.type_selected)

    def test_apply_issue_type_treats_already_selected_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _IssueTypePage()
            page.arrow_reveals_menuitem = False
            page.type_chip_visible = True
            warning = svc._apply_issue_type(page, "feature")
            self.assertIsNone(warning)

    def test_submit_frontend_task_corrects_issue_type_after_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            page = _FrontendSubmitPage()
            applied_types: list[str] = []

            svc._open_projects_editor = lambda _page: None
            svc._ensure_project_selected = lambda _page: None
            svc._click_create_and_wait_created = lambda *args, **kwargs: None
            svc._apply_post_creation_fields = lambda *args, **kwargs: []
            svc._apply_issue_type = lambda _page, issue_type: applied_types.append(issue_type) or None

            svc._submit_frontend_issue(
                page,
                {
                    "issue_id": "issue-1",
                    "repo": "frontend",
                    "issue_type": "task",
                    "title": "Review websocket failures",
                    "description": "desc",
                    "steps_to_reproduce": "",
                    "unit": "customer",
                },
            )

            self.assertEqual(["task"], applied_types)


if __name__ == "__main__":
    unittest.main()
