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
        self.assertIn('id="issueDraftStepsRow"', html)
        self.assertIn('id="issueDraftSteps"', html)
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
        self.assertIn("function makeIssueSubmitRunId(", html)
        self.assertIn("const issuePayload = Object.assign({}, currentIssue, {submit_run_id: expectedRunId});", html)
        self.assertIn("issue: issuePayload", html)
        self.assertRegex(html, re.compile(r"Todo OK: issue created and all post-create clicks succeeded"))

    def test_issue_ui_contains_separate_collapsed_historical_log_panel(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="issueHistoryLogWrap"', html)
        self.assertIn('id="issueHistoryLog"', html)
        self.assertIn('id="issueToggleHistoryBtn"', html)
        self.assertIn("Show historical log", html)
        self.assertIn("function toggleIssueHistoryLog()", html)
        self.assertIn("function clearIssueHistoryLog(", html)
        self.assertIn("function setIssueHistoryToggle(", html)

    def test_comment_mode_uses_comment_body_instead_of_title(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="issueDraftTitleRow"', html)
        self.assertIn('id="issueDraftDescriptionLabel"', html)
        self.assertIn("const isCommentMode = !!currentIssue.include_comment", html)
        self.assertIn("titleRow.style.display = isCommentMode ? 'none' : 'block';", html)
        self.assertIn("descriptionLabel.innerText = isCommentMode ? 'Draft comment (editable)'", html)
        self.assertIn("currentIssue.comment = descriptionText;", html)
        self.assertIn("Comment body is required before submit", html)
        self.assertIn("Validation failed: comment body cannot be empty.", html)

    def test_issue_ui_contains_link_enrichment_toggle_and_draft_warnings(self) -> None:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="issueEnrichLinksRow"', html)
        self.assertIn('id="issueEnrichLinks"', html)
        self.assertIn("Enrich from detected links", html)
        self.assertIn("function updateIssueLinkEnrichmentControl()", html)
        self.assertIn("function getIssueDetectedLinkCandidates()", html)
        self.assertIn("enrich_links: asNewFeature && enrichLinks", html)
        self.assertIn('id="issueDraftWarningsWrap"', html)
        self.assertIn('id="issueDraftSourceWarningsWrap"', html)
        self.assertIn('id="issueDraftSourceWarnings"', html)
        self.assertIn('id="issueDraftUserWarningsWrap"', html)
        self.assertIn('id="issueDraftUserWarnings"', html)
        self.assertIn("function normalizeIssueDraftWarnings(", html)
        self.assertIn("Warnings from provided links", html)
        self.assertIn("Warnings from missing user input", html)
        self.assertIn("Review draft warnings", html)


if __name__ == "__main__":
    unittest.main()
