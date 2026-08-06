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
        self.assertIn('id="discordBaselineList"', html)
        self.assertIn('id="discordDismissedToggleBtn"', html)
        self.assertIn('id="discordSummaryList"', html)
        self.assertIn("const discordBase = `${rootBase}/discord-agent`;", html)
        self.assertIn("fetch(withDiscordSecret('/status'))", html)
        self.assertIn("fetch(withDiscordSecret('/summaries'))", html)
        self.assertIn("fetch(withDiscordSecret('/poll'), {method: 'POST'})", html)
        self.assertIn("function renderDiscordStatusError(error)", html)
        self.assertIn("Discord está desactivado.", html)
        self.assertIn("El bot no publica mensajes en Discord.", html)
        self.assertIn("Primera lectura: ventana reciente", html)
        self.assertIn("Desde el inicio de vigilancia", html)
        self.assertIn("Inicio desde ahora: este resumen incluye solo mensajes posteriores", html)
        self.assertIn("Atraso recortado", html)
        self.assertIn("Consulta de Discord completada con incidencias", html)
        self.assertIn("Consulta de Discord completada con aviso", html)
        poll_start = html.index("async function pollDiscordNow() {")
        poll_end = html.index("\nfunction answersReplyAreaId", poll_start)
        poll_body = html[poll_start:poll_end]
        self.assertIn("const initializedChannels = Array.isArray(data?.result?.channels)", poll_body)
        self.assertIn("channel?.status === 'baseline_initialized'", poll_body)
        self.assertIn("no se resumió historial anterior", poll_body)

    def test_discord_baseline_starts_from_now_through_the_authenticated_ui_api(self) -> None:
        html = self._html()
        start = html.index("async function baselineDiscordChannel(channelId, button) {")
        end = html.index("\nasync function dismissDiscordTask(", start)
        baseline_body = html[start:end]

        self.assertIn('Empezar desde ahora', html)
        self.assertIn('No se resumieron mensajes anteriores.', html)
        self.assertIn("function discordBaselineSourceLabel(source)", html)
        self.assertIn("automatic: 'inicio automático'", html)
        self.assertIn("manual: 'inicio manual'", html)
        self.assertIn("legacy_cursor: 'cursor existente'", html)
        self.assertIn("legacy: 'estado anterior'", html)
        self.assertIn("withDiscordSecret(`/channels/${encodeURIComponent(normalizedChannelId)}/baseline`)", baseline_body)
        self.assertIn("{method: 'POST'}", baseline_body)
        self.assertIn("await loadDiscordPanel();", baseline_body)
        self.assertNotIn("discord.com", baseline_body)

    def test_discord_task_dismissal_and_restore_use_authenticated_review_endpoints(self) -> None:
        html = self._html()
        dismiss_start = html.index("async function dismissDiscordTask(task, summary, reason, button, reasonSelect) {")
        restore_start = html.index("\nasync function restoreDiscordTask(task, summary, button) {", dismiss_start)
        dismiss_body = html[dismiss_start:restore_start]
        restore_end = html.index("\nfunction appendDiscordListSection(", restore_start)
        restore_body = html[restore_start:restore_end]

        self.assertIn("function discordTaskDismissPath(task, summary) {", html)
        self.assertIn("/summaries/${encodeURIComponent(summaryId)}/tasks/${encodeURIComponent(taskKey)}/dismiss", html)
        self.assertIn("fetch(withDiscordSecret(endpoint), {", dismiss_body)
        self.assertIn("method: 'POST'", dismiss_body)
        self.assertIn("body: JSON.stringify({reason: normalizedReason})", dismiss_body)
        self.assertIn("fetch(withDiscordSecret(endpoint), {method: 'DELETE'})", restore_body)
        self.assertIn("await loadDiscordSummaries();", dismiss_body)
        self.assertIn("await loadDiscordSummaries();", restore_body)
        self.assertIn("['created', 'Creada']", html)
        self.assertIn("['duplicate', 'Duplicada']", html)
        self.assertIn("['not_actionable', 'No es una incidencia']", html)
        self.assertIn("['other', 'Otro motivo']", html)

    def test_discord_summaries_render_each_active_task_and_can_show_discarded_tasks(self) -> None:
        html = self._html()
        start = html.index("function renderDiscordSummaries(items) {")
        end = html.index("\nfunction renderDiscordSummariesError(error)", start)
        summaries_body = html[start:end]

        self.assertIn("function toggleDiscordDismissedTasks()", html)
        self.assertIn("Mostrar descartadas", html)
        self.assertIn("Ocultar descartadas", html)
        self.assertIn("Descartar", html)
        self.assertIn("Restaurar", html)
        self.assertIn("const visibleTasks = discordShowDismissedTasks", summaries_body)
        self.assertIn("visibleTasks.forEach((task) => taskList.appendChild(renderDiscordTask(task, summary)));", summaries_body)
        self.assertIn("Todas las tareas de este resumen se han descartado.", summaries_body)

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
