import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.ui import create_ui_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class DiscordUiBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(create_ui_router(job_secret="top-secret"))
        self.client = TestClient(app)

    def _html(self) -> str:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_discord_tab_uses_the_planned_read_only_endpoints(self) -> None:
        html = self._html()
        self.assertIn('id="tabDiscordBtn"', html)
        self.assertIn('id="tabDiscord"', html)
        self.assertIn('id="discordPollBtn"', html)
        self.assertIn('id="discordSummaryList"', html)
        self.assertIn("const discordBase = `${rootBase}/discord-agent`;", html)
        self.assertIn("fetch(withDiscordSecret('/status'))", html)
        self.assertIn("fetch(withDiscordSecret('/summaries'))", html)
        self.assertIn("fetch(withDiscordSecret('/poll'), {method: 'POST'})", html)
        self.assertIn("function renderDiscordStatusError(error)", html)
        self.assertIn("Discord está desactivado.", html)
        self.assertIn("El bot no publica mensajes en Discord.", html)
        self.assertIn("Primera lectura: ventana reciente", html)
        self.assertIn("Atraso recortado", html)
        self.assertIn("Consulta de Discord completada con incidencias", html)
        self.assertIn("Consulta de Discord completada con aviso", html)

    def test_discord_task_transfer_only_prefills_the_issue_form(self) -> None:
        html = self._html()
        start = html.index("function transferDiscordTaskToIssues(task, summary) {")
        end = html.index("\nfunction renderDiscordTask(task, summary) {", start)
        transfer_body = html[start:end]

        self.assertIn("issueInput.value = lines.join(", transfer_body)
        self.assertIn("setDiscordIssueSelectValue('issueIssueType'", transfer_body)
        self.assertIn("setDiscordIssueSelectValue('issueRepo'", transfer_body)
        self.assertIn("setDiscordIssueSelectValue('issueUnit'", transfer_body)
        self.assertIn("showTab('issue');", transfer_body)
        self.assertIn("no se ha creado ningún issue", transfer_body)
        self.assertNotIn("fetch(", transfer_body)
        self.assertNotIn("withIssueSecret", transfer_body)
        self.assertNotIn("/issue-agent/submit", transfer_body)


if __name__ == "__main__":
    unittest.main()
