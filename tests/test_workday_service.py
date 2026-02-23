import logging
import json
import sys
import tempfile
import types
import unittest
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


@unittest.skipUnless(DEPS_AVAILABLE, "workday dependencies are not installed in this environment")
class WorkdayServiceTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> WorkdayAgentService:
        return WorkdayAgentService(
            data_dir=data_dir,
            target_url="https://example.invalid/workday",
            sso_email="demo@example.invalid",
            webhook_start_url="",
            webhook_final_url="",
            webhook_start_break_url="",
            webhook_stop_break_url="",
            logger=logging.getLogger("tests.workday"),
        )

    def test_normalize_iso_date(self) -> None:
        self.assertEqual(WorkdayAgentService._normalize_iso_date("2026-02-19"), "2026-02-19")
        self.assertEqual(WorkdayAgentService._normalize_iso_date(""), "")
        with self.assertRaises(RuntimeError):
            WorkdayAgentService._normalize_iso_date("19/02/2026")

    def test_update_settings_requires_both_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            with self.assertRaises(RuntimeError):
                svc.update_settings("2026-02-20", "")

    def test_update_settings_persists_and_blocks_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            svc = self._build_service(base)

            updated = svc.update_settings("2026-02-20", "2026-02-22")
            self.assertEqual(updated["blocked_start_date"], "2026-02-20")
            self.assertEqual(updated["blocked_end_date"], "2026-02-22")
            self.assertTrue(svc.is_automatic_start_blocked_for_day("2026-02-21"))
            self.assertFalse(svc.is_automatic_start_blocked_for_day("2026-02-25"))

            reloaded = self._build_service(base)
            self.assertEqual(reloaded.get_settings()["blocked_start_date"], "2026-02-20")
            self.assertEqual(reloaded.get_settings()["blocked_end_date"], "2026-02-22")

    def test_build_planned_clicks_uses_given_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            planned = svc._build_planned_clicks(
                first_click_ts=1000.0,
                planned_start_break_ts=2000.0,
                planned_stop_break_ts=3000.0,
                planned_final_ts=4000.0,
            )
            self.assertEqual(planned["planned_start_break_ts"], 2000.0)
            self.assertEqual(planned["planned_stop_break_ts"], 3000.0)
            self.assertEqual(planned["planned_final_ts"], 4000.0)

    def test_build_planned_clicks_generated_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            first_click = 10_000.0
            planned = svc._build_planned_clicks(first_click_ts=first_click)

            start_ts = planned["planned_start_break_ts"]
            self.assertGreaterEqual(start_ts, first_click + (4 * 3600))
            self.assertLessEqual(start_ts, first_click + (4 * 3600) + (45 * 60))

            stop_ts = planned["planned_stop_break_ts"]
            self.assertGreaterEqual(stop_ts, start_ts + (14 * 60) + 30)
            self.assertLessEqual(stop_ts, start_ts + (15 * 60) + 59)

            final_ts = planned["planned_final_ts"]
            self.assertGreaterEqual(final_ts, first_click + (7 * 3600) + (45 * 60))
            self.assertLessEqual(final_ts, first_click + (7 * 3600) + (45 * 60) + 59)

    def test_is_playwright_executable_error(self) -> None:
        err = RuntimeError("BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium")
        self.assertTrue(WorkdayAgentService._is_playwright_executable_error(err))
        self.assertFalse(WorkdayAgentService._is_playwright_executable_error(RuntimeError("other error")))

    def test_reset_session_rejects_active_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._set_runtime_state("working_before_break", "Working", run_id="r1", job="workday_flow", ok=None)
            with self.assertRaises(RuntimeError):
                svc.reset_session()

    def test_reset_session_transitions_failed_to_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            svc._set_runtime_state(
                "failed",
                "Workday failed",
                run_id="auto-1",
                job="workday_flow",
                ok=False,
                failed_phase="working_before_break",
            )

            result = svc.reset_session()
            self.assertTrue(result.get("ok"))
            self.assertTrue(result.get("reset"))
            self.assertEqual(result.get("phase"), "before_start")
            self.assertEqual(result.get("previous_phase"), "failed")

            state = svc._get_runtime_state()
            self.assertEqual(state.get("phase"), "before_start")
            self.assertEqual(state.get("run_id"), "")
            self.assertTrue(bool(state.get("manual_reset")))

            lines = [
                json.loads(line)
                for line in svc.runtime_events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(item.get("event") == "manual_session_reset" for item in lines))

    def test_reset_session_noop_when_already_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = self._build_service(Path(tmp))
            result = svc.reset_session()
            self.assertTrue(result.get("ok"))
            self.assertFalse(result.get("reset"))
            self.assertEqual(result.get("phase"), "before_start")

            lines = [
                json.loads(line)
                for line in svc.runtime_events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(item.get("event") == "manual_session_reset_noop" for item in lines))


if __name__ == "__main__":
    unittest.main()
