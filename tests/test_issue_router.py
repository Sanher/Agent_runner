import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.issue_agent import create_issue_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    DEPS_AVAILABLE = False


class _FakeIssueService:
    def __init__(self) -> None:
        self.last_generate_call = None
        self.last_submit_call = None

    def generate_issue(
        self,
        user_input,
        issue_type,
        repo,
        unit,
        include_comment,
        comment_issue_number="",
        as_new_feature=False,
        as_third_party=False,
    ):
        self.last_generate_call = {
            "user_input": user_input,
            "issue_type": issue_type,
            "repo": repo,
            "unit": unit,
            "include_comment": include_comment,
            "comment_issue_number": comment_issue_number,
            "as_new_feature": as_new_feature,
            "as_third_party": as_third_party,
        }
        return {
            "issue_id": "issue-test-1",
            "title": "x",
            "description": "y",
            "generated_link": "https://example.test/issues/new",
        }

    def submit_issue_via_playwright(self, issue, selectors, non_headless):
        self.last_submit_call = {
            "issue": issue,
            "selectors": selectors,
            "non_headless": non_headless,
        }
        return {"ok": True}

    def send_webhook_report(self, reason, details=None):
        return {"ok": True}

    def get_status(self):
        return {"ok": True}

    def get_events(self, limit=200):
        return {"events": []}


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi no está instalado en este entorno")
class IssueRouterMappingTests(unittest.TestCase):
    def _build_client(self):
        service = _FakeIssueService()
        app = FastAPI()
        app.include_router(
            create_issue_router(
                service=service,
                job_secret="top-secret",
                missing_config_fn=lambda: [],
            )
        )
        return TestClient(app), service

    def test_generate_maps_new_feature_to_management_flow(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/issue-agent/generate?secret=top-secret",
            json={
                "user_input": "test",
                "issue_type": "new feature",
                "repo": "frontend",
                "unit": "core",
                "include_comment": False,
                "comment_issue_number": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_generate_call)
        self.assertEqual(service.last_generate_call["issue_type"], "feature")
        self.assertEqual(service.last_generate_call["repo"], "management")
        self.assertTrue(service.last_generate_call["as_new_feature"])
        self.assertFalse(service.last_generate_call["as_third_party"])

    def test_generate_maps_third_party_feature_to_management_flow(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/issue-agent/generate?secret=top-secret",
            json={
                "user_input": "test",
                "issue_type": "third party feature",
                "repo": "backend",
                "unit": "core",
                "include_comment": False,
                "comment_issue_number": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_generate_call)
        self.assertEqual(service.last_generate_call["issue_type"], "feature")
        self.assertEqual(service.last_generate_call["repo"], "management")
        self.assertFalse(service.last_generate_call["as_new_feature"])
        self.assertTrue(service.last_generate_call["as_third_party"])

    def test_generate_comment_mode_is_neutral_and_does_not_force_management(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/issue-agent/generate?secret=top-secret",
            json={
                "user_input": "comment text",
                "issue_type": "third party task",
                "repo": "frontend",
                "unit": "core",
                "include_comment": True,
                "comment_issue_number": "123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_generate_call)
        self.assertEqual(service.last_generate_call["issue_type"], "task")
        self.assertEqual(service.last_generate_call["repo"], "frontend")
        self.assertFalse(service.last_generate_call["as_new_feature"])
        self.assertFalse(service.last_generate_call["as_third_party"])

    def test_generate_comment_mode_has_priority_over_new_feature_alias(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/issue-agent/generate?secret=top-secret",
            json={
                "user_input": "comment text",
                "issue_type": "new feature",
                "repo": "backend",
                "unit": "core",
                "include_comment": True,
                "comment_issue_number": "321",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_generate_call)
        self.assertEqual(service.last_generate_call["issue_type"], "task")
        self.assertEqual(service.last_generate_call["repo"], "backend")
        self.assertFalse(service.last_generate_call["as_new_feature"])
        self.assertFalse(service.last_generate_call["as_third_party"])

    def test_submit_comment_mode_in_management_does_not_require_selectors(self) -> None:
        client, service = self._build_client()
        response = client.post(
            "/issue-agent/submit?secret=top-secret",
            json={
                "issue": {
                    "issue_id": "issue-1",
                    "title": "comment title",
                    "description": "comment desc",
                    "generated_link": "https://example.test/management/issues/10",
                    "repo": "management",
                    "issue_type": "task",
                    "include_comment": True,
                    "comment_issue_number": "10",
                },
                "selectors": {},
                "non_headless": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_submit_call)
        self.assertEqual(service.last_submit_call["issue"]["repo"], "management")

    def test_submit_management_plain_issue_requires_selectors(self) -> None:
        client, _ = self._build_client()
        response = client.post(
            "/issue-agent/submit?secret=top-secret",
            json={
                "issue": {
                    "issue_id": "issue-2",
                    "title": "plain issue",
                    "description": "plain desc",
                    "generated_link": "https://example.test/management/issues/new",
                    "repo": "management",
                    "issue_type": "bug",
                    "include_comment": False,
                    "comment_issue_number": "",
                },
                "selectors": {},
                "non_headless": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing selector", response.json().get("detail", ""))


if __name__ == "__main__":
    unittest.main()
