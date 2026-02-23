import json
import logging
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path


def _load_workday_service():
    def _stub_missing_dependency(module_name: str) -> bool:
        if module_name in {"playwright", "playwright.sync_api"}:
            fake_sync_api = types.ModuleType("playwright.sync_api")

            def _unsupported_sync_playwright():
                raise RuntimeError("sync_playwright is not available in this test environment")

            fake_sync_api.sync_playwright = _unsupported_sync_playwright
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
        from agents.workday_agent.service import WorkdayAgentService

        return WorkdayAgentService, True
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local environment
        if not _stub_missing_dependency(str(exc.name or "")):
            return None, False
        sys.modules.pop("agents.workday_agent.service", None)
        try:
            from agents.workday_agent.service import WorkdayAgentService
        except ModuleNotFoundError as second_exc:
            if not _stub_missing_dependency(str(second_exc.name or "")):
                return None, False
            sys.modules.pop("agents.workday_agent.service", None)
            from agents.workday_agent.service import WorkdayAgentService
        return WorkdayAgentService, True
    except Exception:
        return None, False


WorkdayAgentService, DEPS_AVAILABLE = _load_workday_service()


class _FakeElement:
    def __init__(self, *, visible: bool, box):
        self._visible = visible
        self._box = box

    def is_visible(self):
        return self._visible

    def bounding_box(self):
        return self._box


class _FakeGroup:
    def __init__(self, elements):
        self._elements = list(elements)

    def count(self):
        return len(self._elements)

    def nth(self, index: int):
        return self._elements[index]

    @property
    def first(self):
        return self._elements[0]


class _FakePage:
    def __init__(self, selector_map):
        self._selector_map = selector_map

    def wait_for_selector(self, selector: str, timeout=None):
        elements = self._selector_map.get(selector, [])
        if not elements:
            raise RuntimeError(f"selector not found: {selector}")

    def locator(self, selector: str):
        return _FakeGroup(self._selector_map.get(selector, []))


@unittest.skipUnless(DEPS_AVAILABLE, "workday dependencies are not installed in this environment")
class WorkdayResilienceTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> WorkdayAgentService:
        return WorkdayAgentService(
            data_dir=data_dir,
            target_url="https://example.invalid/workday",
            sso_email="demo@example.invalid",
            webhook_start_url="",
            webhook_final_url="",
            webhook_start_break_url="",
            webhook_stop_break_url="",
            logger=logging.getLogger("tests.workday.resilience"),
        )

    def test_get_status_on_break_unknown_timing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._set_runtime_state("on_break", "On break", run_id="r1", job="workday_flow", ok=None)
            status = svc.get_status()
            self.assertEqual(status.get("phase"), "on_break")
            self.assertIn("unknown", str(status.get("message", "")).lower())
            self.assertNotIn("remaining_seconds", status)

    def test_runtime_resume_fields_keeps_required_context(self) -> None:
        source = {
            "planned_first_ts": 1.0,
            "first_click_ts": 2.0,
            "planned_start_break_ts": 3.0,
            "start_break_ts": 4.0,
            "planned_stop_break_ts": 5.0,
            "stop_break_ts": 6.0,
            "planned_final_ts": 7.0,
            "final_click_ts": 8.0,
            "other": "x",
        }
        extracted = WorkdayAgentService._runtime_resume_fields(source)
        self.assertEqual(set(extracted.keys()), {
            "planned_first_ts",
            "first_click_ts",
            "planned_start_break_ts",
            "start_break_ts",
            "planned_stop_break_ts",
            "stop_break_ts",
            "planned_final_ts",
            "final_click_ts",
        })
        self.assertEqual(extracted["first_click_ts"], 2.0)

    def test_retry_failed_action_infers_missing_timestamps_from_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            run_id = "auto-20260223-065718"

            now_iso = datetime.now().isoformat()
            lines = [
                {
                    "ts": now_iso,
                    "event": "click_webhook_sent",
                    "run_id": run_id,
                    "phase": "working_before_break",
                    "meta": {"click_name": "start_click", "meta": {"executed_at": now_iso}},
                },
                {
                    "ts": now_iso,
                    "event": "click_webhook_sent",
                    "run_id": run_id,
                    "phase": "on_break",
                    "meta": {"click_name": "start_break_click", "meta": {"executed_at": now_iso}},
                },
                {
                    "ts": now_iso,
                    "event": "click_webhook_sent",
                    "run_id": run_id,
                    "phase": "working_after_break",
                    "meta": {"click_name": "stop_break_click", "meta": {"executed_at": now_iso}},
                },
            ]
            svc.runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
            svc.runtime_events_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n",
                encoding="utf-8",
            )

            svc._set_runtime_state(
                "failed",
                "Workday failed",
                run_id=run_id,
                job="workday_flow",
                ok=False,
                failed_phase="working_before_break",
                first_click_ts=0.0,
                start_break_ts=0.0,
                stop_break_ts=0.0,
                planned_start_break_ts=0.0,
                planned_stop_break_ts=0.0,
                planned_final_ts=0.0,
            )

            svc.resume_pending_flow = lambda: {"ok": True, "resumed": True, "phase": "working_before_break"}
            result = svc.retry_failed_action()
            self.assertTrue(result.get("ok"))
            current = svc._get_runtime_state()
            self.assertEqual(current.get("phase"), "working_before_break")
            self.assertGreater(float(current.get("first_click_ts", 0) or 0), 0.0)
            self.assertGreater(float(current.get("start_break_ts", 0) or 0), 0.0)
            self.assertGreater(float(current.get("stop_break_ts", 0) or 0), 0.0)

    def test_pick_largest_visible_locator_prefers_bigger_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            selector = "button:has(svg[aria-label='Icon-pause'])"
            small = _FakeElement(visible=True, box={"x": 0, "y": 0, "width": 20, "height": 20})
            large = _FakeElement(visible=True, box={"x": 5, "y": 5, "width": 60, "height": 60})
            hidden = _FakeElement(visible=False, box={"x": 0, "y": 0, "width": 100, "height": 100})
            page = _FakePage({selector: [small, hidden, large]})

            picked = svc._pick_largest_visible_locator(page, selector)
            self.assertIs(picked, large)


if __name__ == "__main__":
    unittest.main()
