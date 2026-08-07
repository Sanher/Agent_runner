import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.ui import create_ui_router

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi is not installed in this environment")
class TelegramUiBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(create_ui_router(job_secret="top-secret"))
        self.client = TestClient(app)

    def _html(self) -> str:
        response = self.client.get("/ui?secret=top-secret")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_telegram_tab_uses_only_authenticated_local_reader_endpoints(self) -> None:
        html = self._html()
        telegram_start = html.index("function telegramText")
        telegram_end = html.index("\nfunction answersReplyAreaId", telegram_start)
        telegram_body = html[telegram_start:telegram_end]

        self.assertIn('id="tabTelegramBtn"', html)
        self.assertIn('id="tabTelegram"', html)
        self.assertIn('id="telegramProcessBtn"', html)
        self.assertIn('id="telegramDismissedToggleBtn"', html)
        self.assertIn('id="telegramSummaryList"', html)
        self.assertIn("const telegramBase = ", html)
        self.assertIn("/telegram-reader", html)
        self.assertIn("fetch(withTelegramSecret('/status'))", telegram_body)
        self.assertIn("fetch(withTelegramSecret('/summaries'))", telegram_body)
        self.assertIn("fetch(withTelegramSecret('/process'), {method: 'POST'})", telegram_body)
        self.assertIn("fetch(withTelegramSecret(endpoint), {", telegram_body)
        self.assertIn("fetch(withTelegramSecret(endpoint), {method: 'DELETE'})", telegram_body)
        self.assertNotIn("/poll", telegram_body)
        self.assertNotIn("api.telegram.org", telegram_body)
        self.assertNotIn("getUpdates", telegram_body)

    def test_telegram_panel_documents_answers_webhook_and_read_only_behavior(self) -> None:
        html = self._html()

        self.assertIn("webhook existente de Answers", html)
        self.assertIn("nunca envía, edita, elimina mensajes ni añade reacciones en Telegram", html)
        self.assertIn("Procesa únicamente los mensajes que el webhook ya haya almacenado localmente.", html)
        self.assertIn("Telegram está desactivado.", html)
        self.assertIn("La configuración de Telegram está incompleta.", html)
        self.assertIn("processButton.disabled = !controlsEnabled;", html)

    def test_telegram_dismissal_and_restore_support_human_review(self) -> None:
        html = self._html()
        dismiss_start = html.index(
            "async function dismissTelegramTask(task, summary, reason, button, reasonSelect) {"
        )
        restore_start = html.index(
            "\nasync function restoreTelegramTask(task, summary, button) {", dismiss_start
        )
        restore_end = html.index("\nfunction appendTelegramListSection(", restore_start)
        dismiss_body = html[dismiss_start:restore_start]
        restore_body = html[restore_start:restore_end]

        self.assertIn("function telegramTaskDismissPath(task, summary) {", html)
        self.assertIn("'/summaries/' + encodeURIComponent(summaryId)", html)
        self.assertIn("'/tasks/' + encodeURIComponent(taskKey) + '/dismiss'", html)
        self.assertIn("body: JSON.stringify({reason: normalizedReason})", dismiss_body)
        self.assertIn("method: 'POST'", dismiss_body)
        self.assertIn("method: 'DELETE'", restore_body)
        self.assertIn("await loadTelegramSummaries();", dismiss_body)
        self.assertIn("await loadTelegramSummaries();", restore_body)
        self.assertIn("Mostrar descartadas", html)
        self.assertIn("Ocultar descartadas", html)
        self.assertIn("Descartar", html)
        self.assertIn("Restaurar", html)
        self.assertIn("const visibleTasks = telegramShowDismissedTasks", html)

    def test_telegram_task_transfer_only_prefills_the_issue_form(self) -> None:
        html = self._html()
        start = html.index("function transferTelegramTaskToIssues(task, summary) {")
        end = html.index("\nfunction renderTelegramTask(task, summary) {", start)
        transfer_body = html[start:end]

        self.assertIn("issueInput.value = lines.join('\\n');", transfer_body)
        self.assertIn("setTelegramIssueSelectValue('issueIssueType'", transfer_body)
        self.assertIn("setTelegramIssueSelectValue('issueRepo'", transfer_body)
        self.assertIn("setTelegramIssueSelectValue('issueUnit'", transfer_body)
        self.assertIn("showTab('issue');", transfer_body)
        self.assertIn("no se ha creado ningún issue", transfer_body)
        self.assertNotIn("fetch(", transfer_body)
        self.assertNotIn("withIssueSecret", transfer_body)
        self.assertNotIn("/issue-agent/submit", transfer_body)


if __name__ == "__main__":
    unittest.main()
