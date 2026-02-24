import re
import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.ui import create_ui_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class IssueUiBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(create_ui_router(job_secret="top-secret"))
        self.client = TestClient(app)

    def test_issue_ui_contains_log_toggle_button(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="issueToggleLogBtn"', html)
        self.assertIn("Show Playwright log", html)
        self.assertIn("function toggleIssuePlaywrightLog()", html)

    def test_clear_draft_hides_log_and_disables_toggle(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("function clearIssueDraft()", html)
        self.assertIn("setIssueLogToggle(false, false);", html)
        self.assertIn("renderIssueDraftEditor();", html)

    def test_submit_flow_keeps_log_visible_while_running_and_restores_after_result(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("setIssueLogToggle(false, true);", html)
        self.assertIn("setIssueLogToggle(true, false);", html)
        self.assertIn("setIssueLogToggle(true, true);", html)
        self.assertRegex(html, re.compile(r"Todo OK: issue created and all post-create clicks succeeded"))


if __name__ == "__main__":
    unittest.main()
