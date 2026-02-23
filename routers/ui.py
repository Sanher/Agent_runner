import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from routers.auth import ensure_request_authorized

logger = logging.getLogger("agent_runner.ui_router")


def create_ui_router(job_secret: str) -> APIRouter:
    """Crea router HTTP para la UI integrada multiagente."""
    router = APIRouter(tags=["ui"])

    @router.get("/ui", response_class=HTMLResponse)
    def ui(request: Request):
        ensure_request_authorized(request, job_secret, logger)
        return HTMLResponse(
            """
<!doctype html>
<html data-theme="dark">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\" />
  <title>Agent Runner UI</title>
  <style>
    *,
    *::before,
    *::after {
      box-sizing: border-box;
    }

    html,
    body {
      width: 100%;
      max-width: 100%;
      overflow-x: hidden;
      -webkit-text-size-adjust: 100%;
    }

    :root {
      --bg: #020617;
      --bg-soft: #0f172a;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --card-bg: rgba(15, 23, 42, 0.84);
      --card-border: rgba(148, 163, 184, 0.22);
      --input-bg: rgba(15, 23, 42, 0.78);
      --input-border: rgba(148, 163, 184, 0.32);
      --input-focus: #38bdf8;
      --button-bg: linear-gradient(135deg, #2563eb, #7c3aed);
      --button-hover: linear-gradient(135deg, #1d4ed8, #6d28d9);
      --button-text: #f8fafc;
      --shadow: 0 18px 35px rgba(2, 6, 23, 0.45);
    }

    :root[data-theme='light'] {
      --bg: #f1f5f9;
      --bg-soft: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --card-bg: rgba(255, 255, 255, 0.95);
      --card-border: rgba(148, 163, 184, 0.45);
      --input-bg: #ffffff;
      --input-border: rgba(148, 163, 184, 0.72);
      --input-focus: #0ea5e9;
      --button-bg: linear-gradient(135deg, #2563eb, #0ea5e9);
      --button-hover: linear-gradient(135deg, #1d4ed8, #0284c7);
      --button-text: #ffffff;
      --shadow: 0 15px 30px rgba(148, 163, 184, 0.35);
    }

    body {
      font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
      margin: 0;
      background: radial-gradient(circle at 20% 0%, #1e293b 0%, var(--bg) 45%);
      color: var(--text);
      transition: background 0.2s ease, color 0.2s ease;
      padding: 24px;
      box-sizing: border-box;
      min-height: 100vh;
    }

    .theme-floating-btn {
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 20;
      width: 44px;
      height: 44px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      padding: 0;
      margin: 0;
    }

    .app-shell {
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 18px;
      max-width: 1320px;
      margin: 0 auto;
      align-items: start;
      min-width: 0;
    }

    .sidebar {
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 16px;
      padding: 18px;
      position: sticky;
      top: 20px;
      backdrop-filter: blur(6px);
      box-shadow: var(--shadow);
    }

    .brand-title { margin: 0; }
    .content-area {
      min-width: 0;
      width: 100%;
    }

    .card {
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 14px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(4px);
      min-width: 0;
      overflow-x: clip;
    }

    pre {
      white-space: pre-wrap;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 10px;
      padding: 10px;
    }

    textarea,
    input,
    select {
      width: 100%;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 10px;
      padding: 10px 12px;
      box-sizing: border-box;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    textarea { min-height: 140px; }

    textarea:focus,
    input:focus,
    select:focus {
      outline: none;
      border-color: var(--input-focus);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--input-focus) 25%, transparent);
    }

    button {
      margin-right: 8px;
      margin-top: 8px;
      margin-bottom: 10px;
      background: var(--button-bg);
      color: var(--button-text);
      border: 0;
      border-radius: 10px;
      padding: 9px 14px;
      cursor: pointer;
      font-weight: 600;
      transition: transform 0.2s ease, filter 0.2s ease;
    }

    button:hover {
      background: var(--button-hover);
      transform: translateY(-1px);
      filter: brightness(1.05);
    }

    .tabs {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin: 14px 0;
    }

    .tab-btn {
      width: 100%;
      text-align: left;
      margin: 0;
      opacity: 0.86;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      color: var(--text);
    }

    .tab-btn.active {
      opacity: 1;
      border-color: var(--input-focus);
      box-shadow: inset 0 0 0 1px var(--input-focus);
    }

    details.settings-dropdown {
      margin-bottom: 14px;
    }

    details.settings-dropdown > summary {
      list-style: none;
      cursor: pointer;
      padding: 10px 12px;
      border: 1px solid var(--input-border);
      border-radius: 10px;
      background: var(--input-bg);
      font-weight: 600;
      margin-bottom: 10px;
    }

    details.settings-dropdown > summary::-webkit-details-marker {
      display: none;
    }

    details.settings-dropdown > summary::after {
      content: '▾';
      float: right;
      opacity: 0.9;
    }

    details.settings-dropdown:not([open]) > summary::after {
      content: '▸';
    }

    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .kv { margin: 4px 0; }

    .logs {
      white-space: pre-wrap;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 10px;
      padding: 10px;
      max-height: 260px;
      overflow: auto;
      font-family: Menlo, Consolas, monospace;
      font-size: 12px;
    }

    .muted { color: var(--muted); font-size: 0.9em; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10;
    }

    .modal-backdrop.hidden { display: none; }

    .modal-card {
      width: min(760px, 92vw);
      max-height: 88vh;
      overflow: auto;
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 14px;
      padding: 16px;
      box-sizing: border-box;
      box-shadow: var(--shadow);
    }

    .modal-card h3 { margin-top: 0; }
    .field {
      display: block;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      margin-bottom: 8px;
      box-sizing: border-box;
    }

    #tabIssue input.field,
    #tabIssue select.field {
      height: 44px;
      min-height: 44px;
    }

    #tabIssue .issue-toggle-group {
      margin: 6px 0 12px;
    }

    #tabIssue .issue-toggle {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      cursor: pointer;
      user-select: none;
      color: var(--text);
      font-weight: 600;
      letter-spacing: 0.01em;
    }

    #tabIssue .issue-toggle-input {
      position: absolute;
      opacity: 0;
      width: 1px;
      height: 1px;
      pointer-events: none;
    }

    #tabIssue .issue-toggle-track {
      position: relative;
      width: 48px;
      height: 28px;
      border-radius: 999px;
      border: 1px solid var(--input-border);
      background: rgba(148, 163, 184, 0.22);
      transition: background 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
      box-shadow: inset 0 1px 2px rgba(2, 6, 23, 0.35);
      flex: 0 0 auto;
    }

    #tabIssue .issue-toggle-knob {
      position: absolute;
      top: 3px;
      left: 3px;
      width: 20px;
      height: 20px;
      border-radius: 999px;
      background: #f8fafc;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.45);
      transition: transform 0.22s ease;
    }

    #tabIssue .issue-toggle-input:focus-visible + .issue-toggle-track {
      outline: 2px solid var(--input-focus);
      outline-offset: 2px;
    }

    #tabIssue .issue-toggle-input:checked + .issue-toggle-track {
      background: linear-gradient(135deg, #2563eb, #0ea5e9);
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.18);
    }

    #tabIssue .issue-toggle-input:checked + .issue-toggle-track .issue-toggle-knob {
      transform: translateX(20px);
    }

    #tabIssue .issue-toggle-label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    #tabIssue .issue-toggle-state {
      font-size: 11px;
      padding: 2px 7px;
      min-width: 34px;
      border-radius: 999px;
      border: 1px solid var(--input-border);
      color: var(--muted);
      background: var(--input-bg);
      transition: all 0.2s ease;
      text-align: center;
    }

    #tabIssue .issue-toggle-state::before {
      content: 'OFF';
    }

    #tabIssue .issue-toggle-input:checked ~ .issue-toggle-label .issue-toggle-state {
      color: #ffffff;
      border-color: #38bdf8;
      background: #0284c7;
    }

    #tabIssue .issue-toggle-input:checked ~ .issue-toggle-label .issue-toggle-state::before {
      content: 'ON';
    }

    #tabIssue select.field {
      padding-right: 38px;
      -webkit-appearance: none;
      appearance: none;
      background-image:
        linear-gradient(45deg, transparent 50%, var(--muted) 50%),
        linear-gradient(135deg, var(--muted) 50%, transparent 50%);
      background-position:
        calc(100% - 18px) center,
        calc(100% - 12px) center;
      background-size: 6px 6px, 6px 6px;
      background-repeat: no-repeat;
    }

    input.field[type="date"] {
      inline-size: 100%;
      max-inline-size: 100%;
      padding-right: 12px;
    }

    .answers-messages {
      border: 1px solid var(--input-border);
      border-radius: 10px;
      background: var(--input-bg);
      padding: 8px;
      max-height: 220px;
      overflow: auto;
      margin-bottom: 10px;
    }

    .answers-msg {
      border-bottom: 1px solid var(--input-border);
      padding: 8px 0;
    }

    .answers-msg:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    @media (max-width: 980px) {
      .app-shell { grid-template-columns: 1fr; }
      .sidebar { position: static; }
      body { padding: 14px; }
      .card { padding: 14px; }
      .theme-floating-btn {
        top: 10px;
        right: 10px;
      }
    }
</style>
</head>
<body>
  <button onclick="toggleTheme()" id="themeToggle" class="theme-floating-btn" aria-label="Toggle theme" title="Toggle theme">🌙</button>

  <div class="app-shell">
    <aside class="sidebar">
      <h1 class="brand-title">Agent Runner</h1>
      <p class="muted">Monitor and manage web, email, issue and answers agents in a single interface.</p>
      <p id="status"></p>
      <div class="tabs">
        <button id="tabWorkdayBtn" class="tab-btn active" onclick="showTab('workday')">Web Interaction Agent</button>
        <button id="tabEmailBtn" class="tab-btn" onclick="showTab('email')">Email Agent</button>
        <button id="tabIssueBtn" class="tab-btn" onclick="showTab('issue')">Issue Agent</button>
        <button id="tabAnswersBtn" class="tab-btn" onclick="showTab('answers')">Answers Agent</button>
      </div>
    </aside>

    <main class="content-area">
  <section id=\"tabWorkday\" class=\"tab-panel active\">
    <div class=\"card\">
      <h3>Real-time status</h3>
      <div id=\"workdayStatusLine\" class=\"kv\">Loading status...</div>
      <div id=\"workdayTimingLine\" class=\"kv muted\"></div>
      <div id=\"workdayExpected\" class=\"kv muted\"></div>
      <button onclick=\"resetWorkdaySession()\" id=\"resetWorkdaySessionBtn\">Reset session</button>
      <div id=\"workdayRetryWrap\" style=\"display:none;\">
        <button onclick=\"retryFailedAction()\" id=\"retryFailedBtn\">Retry failed action now</button>
      </div>
    </div>
    <div class=\"card\">
      <h3>Click history (today)</h3>
      <div id=\"workdayClicks\" class=\"muted\">Loading history...</div>
    </div>
    <div class=\"card\">
      <h3>Runtime logs (real-time)</h3>
      <div id=\"workdayEvents\" class=\"logs\">Loading events...</div>
    </div>
    <div class=\"card\">
      <h3>Blocked days (no auto start)</h3>
      <p class=\"muted\">If today is inside this range, the scheduler will not start requests automatically.</p>
      <label class=\"muted\">Start date</label>
      <input id=\"workdayBlockedStartDate\" type=\"date\" class=\"field\" />
      <label class=\"muted\">End date</label>
      <input id=\"workdayBlockedEndDate\" type=\"date\" class=\"field\" />
      <button onclick=\"saveWorkdaySettings()\" id=\"workdaySaveSettingsBtn\">Save blocked dates</button>
      <div id=\"workdaySettingsStatus\" class=\"muted\"></div>
    </div>
  </section>

  <section id=\"tabEmail\" class=\"tab-panel\">
    <button onclick=\"checkNew()\" id=\"checkNewBtn\">Check new messages</button>
    <button onclick=\"openManualModal()\" id=\"manualBtn\">Generate from text</button>
    <button onclick=\"loadSuggestions()\">Refresh list</button>
    <button id=\"emailReviewedToggleBtn\" onclick=\"toggleReviewedSuggestions()\">View reviewed</button>

    <details id=\"emailSettingsDetails\" class=\"settings-dropdown\" open>
      <summary id=\"emailSettingsSummary\">Email settings</summary>
      <div class=\"card\">
        <label class=\"muted\">From (fixed)</label>
        <input id=\"defaultFromEmail\" class=\"field\" readonly />
        <label class=\"muted\">Default CC (optional)</label>
        <input id=\"defaultCcEmail\" class=\"field\" placeholder=\"cc1@example.com, cc2@example.com\" />
        <label class=\"muted\">Signature assets dir</label>
        <input id=\"signatureAssetsDir\" class=\"field\" placeholder=\"/config/media/signature\" />
        <label class=\"muted\">Signature</label>
        <textarea id=\"emailSignature\" class=\"field\" style=\"min-height:90px\" placeholder=\"Best regards,\"></textarea>
        <p class=\"muted\">Available placeholders: {{logo}}, {{linkedin}}, {{tiktok}}, {{instagram}}, {{twitter}}, {{youtube}}, {{telegram}}</p>
        <label class=\"muted\">Whitelist</label>
        <p class=\"muted\">One sender per line (or comma-separated). Only these senders generate suggestions.</p>
        <textarea id=\"allowedWhitelist\" class=\"field\" style=\"min-height:90px\" placeholder=\"alerts@example.com\"></textarea>
        <button onclick=\"saveSettings()\" id=\"saveSettingsBtn\">Save email settings</button>
      </div>
    </details>
    <div id=\"list\"></div>
    <div id=\"emailReviewedSection\" class=\"card\" style=\"display:none;\">
      <h3>Reviewed emails</h3>
      <p class=\"muted\">Reviewed suggestions are hidden from the active list until unarchived.</p>
      <div id=\"reviewedList\"></div>
    </div>
  </section>

  <section id=\"tabIssue\" class=\"tab-panel\">
    <div class=\"card\">
      <h3>Generate issue draft</h3>
      <div class=\"issue-toggle-group\">
        <label class=\"issue-toggle\" for=\"issueAddAsComment\">
          <input type=\"checkbox\" id=\"issueAddAsComment\" class=\"issue-toggle-input\" onchange=\"toggleIssueMode()\" />
          <span class=\"issue-toggle-track\" aria-hidden=\"true\"><span class=\"issue-toggle-knob\"></span></span>
          <span class=\"issue-toggle-label\">Add as comment <span class=\"issue-toggle-state\"></span></span>
        </label>
      </div>
      <div id=\"issueIssueTypeRow\">
        <label class=\"muted\">Issue type</label>
        <select id=\"issueIssueType\" class=\"field\">
          <option value=\"bug\">bug</option>
          <option value=\"feature\">feature</option>
          <option value=\"task\">task</option>
          <option value=\"enhacement\">enhacement</option>
          <option value=\"blockchain\">blockchain</option>
          <option value=\"exchange\">exchange</option>
          <option value=\"new feature\">new feature</option>
          <option value=\"third party bug\">third party bug</option>
          <option value=\"third party feature\">third party feature</option>
          <option value=\"third party task\">third party task</option>
        </select>
      </div>
      <div id=\"issueRepoRow\">
        <label class=\"muted\">Repository</label>
        <select id=\"issueRepo\" class=\"field\">
          <option value=\"backend\">backend</option>
          <option value=\"frontend\">frontend</option>
          <option value=\"management\">management</option>
        </select>
      </div>
      <div id=\"issueUnitRow\">
        <label class=\"muted\">Unit</label>
        <select id=\"issueUnit\" class=\"field\">
          <option value=\"core\">core</option>
          <option value=\"customer\">customer</option>
          <option value=\"bot\">bot</option>
          <option value=\"integrations\">integrations</option>
          <option value=\"marketing\">marketing</option>
          <option value=\"it\">it</option>
        </select>
      </div>
      <div id=\"issueCommentNumberRow\">
        <label class=\"muted\">Issue number to reply to</label>
        <input id=\"issueCommentNumber\" class=\"field\" placeholder=\"e.g. 12345\">
      </div>
      <div id=\"issueUserInputRow\">
        <textarea id=\"issueUserInput\" class=\"field\" style=\"min-height:130px\" placeholder=\"Information\"></textarea>
      </div>
      <button onclick=\"generateIssueDraft()\" id=\"issueGenerateBtn\">Generate draft</button>
      <div id=\"issueGenerateStatus\" class=\"muted\"></div>
      <pre id=\"issueGeneratedJson\">{}</pre>
    </div>
  </section>

  <section id=\"tabAnswers\" class=\"tab-panel\">
    <button onclick=\"loadAnswersChats()\">Refresh chats</button>
    <button id=\"answersArchivedToggleBtn\" onclick=\"toggleArchivedAnswers()\">View archived</button>
    <div id=\"answersList\"></div>
    <div id=\"answersArchivedSection\" class=\"card\" style=\"display:none;\">
      <h3>Archived conversations</h3>
      <p class=\"muted\">Archived conversations are auto-deleted after 7 days.</p>
      <div id=\"answersArchivedList\"></div>
    </div>
  </section>

      </main>
  </div>

  <div id=\"suggestionModal\" class=\"modal-backdrop hidden\">
    <div class=\"modal-card\">
      <h3>Suggest changes</h3>
      <p class=\"muted\">Write your request and generate a new response version.</p>
      <textarea id=\"suggestionInstruction\" class=\"field\" style=\"min-height:180px\"></textarea>
      <button onclick=\"submitRegenerate()\" id=\"submitRegenerateBtn\">Generate response</button>
      <button onclick=\"closeSuggestionModal()\">Cancel</button>
    </div>
  </div>

  <div id=\"manualModal\" class=\"modal-backdrop hidden\">
    <div class=\"modal-card\">
      <h3>Generate from email text</h3>
      <p class=\"muted\">Paste an email and force a suggested response.</p>
      <input id=\"manualFrom\" class=\"field\" placeholder=\"From (optional)\">
      <input id=\"manualSubject\" class=\"field\" placeholder=\"Subject (optional)\">
      <textarea id=\"manualBody\" class=\"field\" style=\"min-height:220px\" placeholder=\"Paste email body\"></textarea>
      <button onclick=\"submitManualSuggestion()\" id=\"submitManualBtn\">Create response</button>
      <button onclick=\"closeManualModal()\">Cancel</button>
    </div>
  </div>

  <div id=\"answersSuggestModal\" class=\"modal-backdrop hidden\">
    <div class=\"modal-card\">
      <h3>Suggest changes (Answers)</h3>
      <p class=\"muted\">Describe how to adjust the suggested reply for this chat.</p>
      <textarea id=\"answersSuggestInstruction\" class=\"field\" style=\"min-height:180px\"></textarea>
      <button onclick=\"submitAnswersSuggest()\" id=\"submitAnswersSuggestBtn\">Generate response</button>
      <button onclick=\"closeAnswersSuggestModal()\">Cancel</button>
    </div>
  </div>

<script>
// Base paths to work the same locally and behind a proxy.
const currentPath = window.location.pathname.endsWith('/')
  ? window.location.pathname.slice(0, -1)
  : window.location.pathname;
const rootBase = currentPath.endsWith('/ui') ? currentPath.slice(0, -3) : currentPath;
const emailBase = `${rootBase}/email-agent`;
const workdayBase = rootBase;
const issueBase = `${rootBase}/issue-agent`;
const answersBase = `${rootBase}/answers-agent`;
const apiSecret = new URLSearchParams(window.location.search).get('secret') || '';
const statusEl = document.getElementById('status');
let currentSuggestionId = '';
let currentAnswersChatId = '';
let currentIssue = null;
let activeTab = 'workday';
let workdayPollTimer = null;
let workdayTickerTimer = null;
let workdayTickerAlignTimer = null;
let workdayTickerSnapshot = null;
let answersArchivedVisible = false;
let emailReviewedVisible = false;
let emailSettingsCache = {
  default_from_email: '',
  default_cc_email: ''
};

function withEmailSecret(path) {
  const fullPath = `${emailBase}${path}`;
  if (!apiSecret) return fullPath;
  const join = fullPath.includes('?') ? '&' : '?';
  return `${fullPath}${join}secret=${encodeURIComponent(apiSecret)}`;
}

function withWorkdaySecret(path) {
  const fullPath = `${workdayBase}${path}`;
  if (!apiSecret) return fullPath;
  const join = fullPath.includes('?') ? '&' : '?';
  return `${fullPath}${join}secret=${encodeURIComponent(apiSecret)}`;
}

function withIssueSecret(path) {
  const fullPath = `${issueBase}${path}`;
  if (!apiSecret) return fullPath;
  const join = fullPath.includes('?') ? '&' : '?';
  return `${fullPath}${join}secret=${encodeURIComponent(apiSecret)}`;
}

function withAnswersSecret(path) {
  const fullPath = `${answersBase}${path}`;
  if (!apiSecret) return fullPath;
  const join = fullPath.includes('?') ? '&' : '?';
  return `${fullPath}${join}secret=${encodeURIComponent(apiSecret)}`;
}

function setStatus(text) {
  statusEl.innerText = text;
}

function phaseLabel(phase) {
  const map = {
    before_start: 'Before start',
    waiting_start: 'Waiting start',
    working_before_break: 'Working before break',
    on_break: 'On break',
    working_after_break: 'Working after break',
    completed: 'Completed',
    failed: 'Failed'
  };
  return map[String(phase || '').trim()] || String(phase || 'unknown');
}

function clickLabel(name) {
  const map = {
    start_click: 'Start workday',
    start_break_click: 'Start break',
    stop_break_click: 'End break',
    final_click: 'End workday'
  };
  return map[String(name || '').trim()] || String(name || 'click');
}

function buildReplySubject(subject) {
  const clean = String(subject || '').trim();
  if (!clean) return 'RE: (no subject)';
  if (clean.toLowerCase().startsWith('re:')) return clean;
  return `RE: ${clean}`;
}

function showTab(name) {
  activeTab = name;
  const isWorkday = name === 'workday';
  const isEmail = name === 'email';
  const isIssue = name === 'issue';
  const isAnswers = name === 'answers';
  document.getElementById('tabWorkday').classList.toggle('active', isWorkday);
  document.getElementById('tabEmail').classList.toggle('active', isEmail);
  document.getElementById('tabIssue').classList.toggle('active', isIssue);
  document.getElementById('tabAnswers').classList.toggle('active', isAnswers);
  document.getElementById('tabWorkdayBtn').classList.toggle('active', isWorkday);
  document.getElementById('tabEmailBtn').classList.toggle('active', isEmail);
  document.getElementById('tabIssueBtn').classList.toggle('active', isIssue);
  document.getElementById('tabAnswersBtn').classList.toggle('active', isAnswers);
  if (isWorkday) {
    refreshWorkdayPanel();
    loadWorkdaySettings();
  } else if (isEmail) {
    loadSettings();
    loadSuggestions();
  } else if (isIssue) {
    refreshIssuePanel();
  } else if (isAnswers) {
    loadAnswersChats();
  }
}

function formatDuration(totalSeconds) {
  const sec = Math.max(0, Number(totalSeconds || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatTs(value) {
  if (!value) return '-';
  if (typeof value === 'number') return new Date(value * 1000).toLocaleTimeString();
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function updateWorkdayTimingFromTicker() {
  const line = document.getElementById('workdayTimingLine');
  if (!line) return;
  if (!workdayTickerSnapshot) {
    line.innerText = 'No active timer right now.';
    return;
  }

  const elapsedDelta = Math.max(0, Math.floor((Date.now() - workdayTickerSnapshot.syncedAtMs) / 1000));
  const parts = [];

  if (typeof workdayTickerSnapshot.elapsedBase === 'number') {
    parts.push(`Elapsed: ${formatDuration(workdayTickerSnapshot.elapsedBase + elapsedDelta)}`);
  }
  if (typeof workdayTickerSnapshot.remainingBase === 'number') {
    parts.push(`Remaining: ${formatDuration(Math.max(0, workdayTickerSnapshot.remainingBase - elapsedDelta))}`);
  }

  line.innerText = parts.length ? parts.join(' | ') : 'No active timer right now.';
}

function syncWorkdayTickerFromStatus(data) {
  const hasElapsed = typeof data.elapsed_seconds === 'number';
  const hasRemaining = typeof data.remaining_seconds === 'number';

  if (!hasElapsed && !hasRemaining) {
    workdayTickerSnapshot = null;
    updateWorkdayTimingFromTicker();
    return;
  }

  workdayTickerSnapshot = {
    elapsedBase: hasElapsed ? Number(data.elapsed_seconds) : null,
    remainingBase: hasRemaining ? Number(data.remaining_seconds) : null,
    syncedAtMs: Date.now()
  };
  // Recalibrate ticker baseline on every poll response to minimize local drift.
  updateWorkdayTimingFromTicker();
}

function startWorkdayTicker() {
  if (workdayTickerTimer) clearInterval(workdayTickerTimer);
  if (workdayTickerAlignTimer) clearTimeout(workdayTickerAlignTimer);

  const startAlignedInterval = () => {
    updateWorkdayTimingFromTicker();
    workdayTickerTimer = setInterval(updateWorkdayTimingFromTicker, 1000);
  };

  const delayToNextSecond = 1000 - (Date.now() % 1000);
  workdayTickerAlignTimer = setTimeout(startAlignedInterval, delayToNextSecond === 1000 ? 0 : delayToNextSecond);
}

async function refreshWorkdayPanel() {
  await Promise.all([loadWorkdayStatus(), loadWorkdayHistory(), loadWorkdayEvents()]);
}

async function loadWorkdaySettings() {
  try {
    const r = await fetch(withWorkdaySecret('/settings'));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const settings = (data && data.settings) ? data.settings : {};
    const start = String(settings.blocked_start_date || '');
    const end = String(settings.blocked_end_date || '');
    document.getElementById('workdayBlockedStartDate').value = start;
    document.getElementById('workdayBlockedEndDate').value = end;
    document.getElementById('workdaySettingsStatus').innerText = (start && end)
      ? `Active block: ${start} - ${end}`
      : 'No blocked range configured.';
  } catch (err) {
    document.getElementById('workdaySettingsStatus').innerText = `Error loading workday settings: ${err}`;
  }
}

async function saveWorkdaySettings() {
  const btn = document.getElementById('workdaySaveSettingsBtn');
  const oldText = btn.innerText;
  const start = String(document.getElementById('workdayBlockedStartDate').value || '').trim();
  const end = String(document.getElementById('workdayBlockedEndDate').value || '').trim();
  const statusBox = document.getElementById('workdaySettingsStatus');

  if ((start && !end) || (!start && end)) {
    statusBox.innerText = 'You must provide both dates: start and end.';
    return;
  }
  if (start && end && start > end) {
    statusBox.innerText = 'Start date cannot be later than end date.';
    return;
  }

  btn.disabled = true;
  btn.innerText = 'Saving...';
  try {
    const r = await fetch(withWorkdaySecret('/settings'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        blocked_start_date: start,
        blocked_end_date: end
      })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const updated = (data && data.settings) ? data.settings : {};
    const updatedStart = String(updated.blocked_start_date || '');
    const updatedEnd = String(updated.blocked_end_date || '');
    document.getElementById('workdayBlockedStartDate').value = updatedStart;
    document.getElementById('workdayBlockedEndDate').value = updatedEnd;
    statusBox.innerText = (updatedStart && updatedEnd)
      ? `Block saved: ${updatedStart} - ${updatedEnd}`
      : 'Blocked range removed.';
    await loadWorkdayStatus();
  } catch (err) {
    statusBox.innerText = `Error saving workday settings: ${err}`;
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function loadWorkdayStatus() {
  try {
    const r = await fetch(withWorkdaySecret('/status'));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const phase = String(data.phase || 'unknown');
    const phaseText = phaseLabel(phase);
    const message = String(data.message || '');
    document.getElementById('workdayStatusLine').innerHTML = `<b>Phase:</b> ${escapeHtml(phaseText)}<br/><b>Status:</b> ${escapeHtml(message)}`;

    syncWorkdayTickerFromStatus(data);

    const expected = [];
    if (data.blocked_start_date && data.blocked_end_date) {
      expected.push(`Auto-start block: ${data.blocked_start_date} - ${data.blocked_end_date}`);
    }
    if (phase === 'before_start' && data.blocked_today) {
      expected.push('Today is blocked by date settings');
    }
    if (phase === 'before_start') {
      expected.push('Start window: 06:57 - 09:30');
    }
    if (phase === 'waiting_start' && data.planned_first_ts) {
      expected.push(`Planned first click: ${formatTs(data.planned_first_ts)}`);
    }
    if (data.planned_start_break_ts) expected.push(`Expected break start: ${formatTs(data.planned_start_break_ts)}`);
    if (data.planned_stop_break_ts) expected.push(`Expected break end: ${formatTs(data.planned_stop_break_ts)}`);
    if (data.planned_final_ts) expected.push(`Expected final click: ${formatTs(data.planned_final_ts)}`);
    if (!expected.length && phase === 'completed' && data.ok) {
      expected.push('Workday finished successfully.');
    }
    document.getElementById('workdayExpected').innerText = expected.join(' | ');

    const retryWrap = document.getElementById('workdayRetryWrap');
    const retryable = phase === 'failed' && !!String(data.failed_phase || '').trim();
    retryWrap.style.display = retryable ? 'block' : 'none';
  } catch (err) {
    document.getElementById('workdayStatusLine').innerText = `Error loading workday status: ${err}`;
  }
}

async function loadWorkdayHistory() {
  const today = new Date().toISOString().slice(0, 10);
  try {
    const r = await fetch(withWorkdaySecret(`/history?day=${today}`));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const box = document.getElementById('workdayClicks');
    if (!Array.isArray(data.items) || data.items.length === 0) {
      box.innerHTML = '<span class="muted">No clicks registered today.</span>';
      return;
    }
    box.innerHTML = data.items.map((item) => {
      const ok = item.ok ? 'OK' : 'ERROR';
      const when = item.executed_at || item.ts || '';
      return `<div class="kv"><b>${escapeHtml(clickLabel(item.click_name || 'click'))}</b> - ${escapeHtml(ok)} - ${escapeHtml(formatTs(when))}${item.recovered ? ' (recovered)' : ''}</div>`;
    }).join('');
  } catch (err) {
    document.getElementById('workdayClicks').innerText = `Error loading history: ${err}`;
  }
}

async function loadWorkdayEvents() {
  const today = new Date().toISOString().slice(0, 10);
  try {
    const r = await fetch(withWorkdaySecret(`/events?limit=120&day=${today}`));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const lines = Array.isArray(data.items) ? data.items.map((item) => {
      const ts = formatTs(item.ts || '');
      const ev = item.event || '';
      const phase = phaseLabel(item.phase || '');
      const run = item.run_id || '';
      return `[${ts}] ${ev} phase=${phase} run=${run}`;
    }) : [];
    document.getElementById('workdayEvents').innerText = lines.length ? lines.join('\\n') : 'No runtime events yet.';
  } catch (err) {
    document.getElementById('workdayEvents').innerText = `Error loading events: ${err}`;
  }
}

async function retryFailedAction() {
  const btn = document.getElementById('retryFailedBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Retrying...';
  setStatus('Retrying failed workday action...');
  try {
    const r = await fetch(withWorkdaySecret('/retry-failed'), { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus('Retry command executed');
    await refreshWorkdayPanel();
  } catch (err) {
    setStatus(`Retry failed: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function resetWorkdaySession() {
  const btn = document.getElementById('resetWorkdaySessionBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Resetting...';
  setStatus('Resetting workday session...');
  console.info('[workday-ui] reset session requested');
  try {
    const r = await fetch(withWorkdaySecret('/reset-session'), { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    if (data && data.reset) {
      console.info('[workday-ui] reset session completed', data);
      setStatus('Workday session reset to before start');
    } else {
      console.info('[workday-ui] reset session noop (already before start)', data);
      setStatus('Session already at before start');
    }
    await refreshWorkdayPanel();
  } catch (err) {
    console.error('[workday-ui] reset session failed', err);
    setStatus(`Reset session failed: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function checkNew() {
  const btn = document.getElementById('checkNewBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Checking new messages...';
  setStatus('Checking new messages...');
  try {
    const r = await fetch(withEmailSecret('/check-new'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({max_emails: 5, unread_only: true, mailbox: 'INBOX'})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`Created ${data.created} new suggestions`);
    await loadSuggestions();
  } catch (err) {
    setStatus(`Error checking email: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

function parseJsonOrThrow(raw, emptyFallback = {}) {
  const value = String(raw || '').trim();
  if (!value) return emptyFallback;
  return JSON.parse(value);
}

async function refreshIssuePanel() {
  return;
}

function toggleIssueMode() {
  const addComment = document.getElementById('issueAddAsComment');
  const issueType = document.getElementById('issueIssueType');
  const repo = document.getElementById('issueRepo');
  const unit = document.getElementById('issueUnit');
  const commentNumber = document.getElementById('issueCommentNumber');
  const issueTypeRow = document.getElementById('issueIssueTypeRow');
  const repoRow = document.getElementById('issueRepoRow');
  const unitRow = document.getElementById('issueUnitRow');
  const commentNumberRow = document.getElementById('issueCommentNumberRow');
  const userInput = document.getElementById('issueUserInput');
  const userInputRow = document.getElementById('issueUserInputRow');

  const isComment = addComment.checked;
  const selectedType = String(issueType.value || '').toLowerCase();
  const isManagementSpecial = selectedType === 'new feature' || selectedType.startsWith('third party ');

  // Two visual modes:
  // - comment mode: only repo + issue number + comment text
  // - create mode: full issue form
  if (isComment) {
    if (issueTypeRow) issueTypeRow.style.display = 'none';
    if (unitRow) unitRow.style.display = 'none';
    if (commentNumberRow) commentNumberRow.style.display = 'block';
    if (repoRow) repoRow.style.display = 'block';
    if (userInputRow) userInputRow.style.display = 'block';
    issueType.disabled = true;
    repo.disabled = false;
    unit.disabled = true;
    commentNumber.disabled = false;
    if (userInput) userInput.placeholder = 'Comment text';
  } else if (isManagementSpecial) {
    if (issueTypeRow) issueTypeRow.style.display = 'block';
    if (unitRow) unitRow.style.display = 'block';
    if (commentNumberRow) commentNumberRow.style.display = 'none';
    if (repoRow) repoRow.style.display = 'block';
    if (userInputRow) userInputRow.style.display = 'block';
    issueType.disabled = false;
    repo.value = 'management';
    repo.disabled = true;
    unit.disabled = false;
    commentNumber.disabled = true;
    if (userInput) userInput.placeholder = 'Information';
  } else {
    if (issueTypeRow) issueTypeRow.style.display = 'block';
    if (unitRow) unitRow.style.display = 'block';
    if (commentNumberRow) commentNumberRow.style.display = 'none';
    if (repoRow) repoRow.style.display = 'block';
    if (userInputRow) userInputRow.style.display = 'block';
    issueType.disabled = false;
    repo.disabled = false;
    unit.disabled = false;
    commentNumber.disabled = true;
    if (userInput) userInput.placeholder = 'Information';
  }
}

async function generateIssueDraft() {
  const input = document.getElementById('issueUserInput').value.trim();
  const selectedIssueType = document.getElementById('issueIssueType').value;
  let issueType = selectedIssueType;
  let repo = document.getElementById('issueRepo').value;
  const unit = document.getElementById('issueUnit').value;
  const includeComment = !!document.getElementById('issueAddAsComment').checked;
  let asNewFeature = false;
  let asThirdParty = false;
  const commentNumber = document.getElementById('issueCommentNumber').value.trim();
  if (includeComment) {
    // Comment mode is neutral and must never trigger special management mappings.
    issueType = 'task';
    asNewFeature = false;
    asThirdParty = false;
  } else if (selectedIssueType === 'new feature') {
    asNewFeature = true;
    issueType = 'feature';
    repo = 'management';
  } else if (selectedIssueType === 'third party bug') {
    asThirdParty = true;
    issueType = 'bug';
    repo = 'management';
  } else if (selectedIssueType === 'third party feature') {
    asThirdParty = true;
    issueType = 'feature';
    repo = 'management';
  } else if (selectedIssueType === 'third party task') {
    asThirdParty = true;
    issueType = 'task';
    repo = 'management';
  }
  if (!input) {
    document.getElementById('issueGenerateStatus').innerText = 'Please provide issue context';
    return;
  }
  if (includeComment && !commentNumber) {
    document.getElementById('issueGenerateStatus').innerText = 'Please provide the issue number to reply to';
    return;
  }
  const btn = document.getElementById('issueGenerateBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Generating...';
  try {
    const r = await fetch(withIssueSecret('/generate'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        user_input: input,
        issue_type: issueType,
        repo,
        unit,
        include_comment: includeComment,
        comment_issue_number: commentNumber,
        as_new_feature: asNewFeature,
        as_third_party: asThirdParty
      })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    currentIssue = data.item || null;
    document.getElementById('issueGeneratedJson').innerText = JSON.stringify(currentIssue || {}, null, 2);
    document.getElementById('issueGenerateStatus').innerText = `Draft generated: ${currentIssue && currentIssue.issue_id ? currentIssue.issue_id : 'unknown'}`;
    if (includeComment) {
      document.getElementById('issueAddAsComment').checked = false;
      document.getElementById('issueCommentNumber').value = '';
      toggleIssueMode();
    }
    await refreshIssuePanel();
  } catch (err) {
    document.getElementById('issueGenerateStatus').innerText = `Error generating issue draft: ${err}`;
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

function openSuggestionModal(id) {
  currentSuggestionId = id;
  const modal = document.getElementById('suggestionModal');
  const area = document.getElementById('suggestionInstruction');
  area.value = '';
  modal.classList.remove('hidden');
  area.focus();
}

function closeSuggestionModal() {
  document.getElementById('suggestionModal').classList.add('hidden');
  currentSuggestionId = '';
}

async function submitRegenerate() {
  const area = document.getElementById('suggestionInstruction');
  const instruction = area.value.trim();
  if (!instruction || !currentSuggestionId) return;
  const btn = document.getElementById('submitRegenerateBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Creating...';
  setStatus('Suggestion received');
  setStatus('Creating new response based on suggestion...');
  try {
    const r = await fetch(withEmailSecret(`/suggestions/${currentSuggestionId}/regenerate`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({instruction})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    closeSuggestionModal();
    setStatus('Suggested response updated');
    await loadSuggestions();
  } catch (err) {
    setStatus(`Error regenerating suggestion: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

function openManualModal() {
  document.getElementById('manualModal').classList.remove('hidden');
  document.getElementById('manualBody').focus();
}

function closeManualModal() {
  document.getElementById('manualModal').classList.add('hidden');
}

function parseWhitelistInput(raw) {
  const pieces = String(raw || '').replace(/\\n/g, ',').split(',');
  const unique = new Set();
  for (const piece of pieces) {
    const value = piece.trim().toLowerCase();
    if (value) unique.add(value);
  }
  return Array.from(unique.values());
}

function updateEmailSettingsDisclosure(hasSavedConfig) {
  const details = document.getElementById('emailSettingsDetails');
  if (!details) return;
  details.open = !hasSavedConfig;
}

async function loadSettings() {
  try {
    const r = await fetch(withEmailSecret('/settings'));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const settings = (data && data.settings) ? data.settings : {};
    const items = Array.isArray(settings.allowed_from_whitelist)
      ? settings.allowed_from_whitelist
      : [];
    document.getElementById('allowedWhitelist').value = items.join('\\n');
    const signature = String(settings.signature || '');
    const defaultFrom = String(settings.default_from_email || '');
    const defaultCc = String(settings.default_cc_email || '');
    const signatureAssetsDir = String(settings.signature_assets_dir || '/config/media/signature');
    emailSettingsCache = {
      default_from_email: defaultFrom,
      default_cc_email: defaultCc
    };
    document.getElementById('emailSignature').value = signature;
    document.getElementById('defaultFromEmail').value = defaultFrom;
    document.getElementById('defaultCcEmail').value = defaultCc;
    document.getElementById('signatureAssetsDir').value = signatureAssetsDir;
    const hasSavedConfig = Boolean(defaultFrom || defaultCc || signature || items.length);
    updateEmailSettingsDisclosure(hasSavedConfig);
  } catch (err) {
    setStatus(`Error loading settings: ${err}`);
  }
}

async function saveSettings() {
  const btn = document.getElementById('saveSettingsBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Saving...';
  const allowed_from_whitelist = parseWhitelistInput(
    document.getElementById('allowedWhitelist').value
  );
  const signature = document.getElementById('emailSignature').value;
  const default_cc_email = document.getElementById('defaultCcEmail').value.trim();
  const signature_assets_dir = document.getElementById('signatureAssetsDir').value.trim();
  try {
    const r = await fetch(withEmailSecret('/settings'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({allowed_from_whitelist, signature, default_cc_email, signature_assets_dir})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const settings = (data && data.settings) ? data.settings : {};
    const items = Array.isArray(settings.allowed_from_whitelist)
      ? settings.allowed_from_whitelist
      : [];
    const savedSignature = String(settings.signature || '');
    const defaultFrom = String(settings.default_from_email || '');
    const defaultCc = String(settings.default_cc_email || '');
    const signatureAssetsDir = String(settings.signature_assets_dir || '/config/media/signature');
    emailSettingsCache = {
      default_from_email: defaultFrom,
      default_cc_email: defaultCc
    };
    document.getElementById('allowedWhitelist').value = items.join('\\n');
    document.getElementById('emailSignature').value = savedSignature;
    document.getElementById('defaultFromEmail').value = defaultFrom;
    document.getElementById('defaultCcEmail').value = defaultCc;
    document.getElementById('signatureAssetsDir').value = signatureAssetsDir;
    const hasSavedConfig = Boolean(defaultFrom || defaultCc || savedSignature || items.length);
    updateEmailSettingsDisclosure(hasSavedConfig);
    setStatus(`Email settings saved (${items.length} sender${items.length === 1 ? '' : 's'} in whitelist)`);
  } catch (err) {
    setStatus(`Error saving settings: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function submitManualSuggestion() {
  const fromText = document.getElementById('manualFrom').value.trim();
  const subject = document.getElementById('manualSubject').value.trim();
  const body = document.getElementById('manualBody').value.trim();
  if (!body) {
    setStatus('Please provide the email body');
    return;
  }
  const btn = document.getElementById('submitManualBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Creating...';
  setStatus('Email text received');
  setStatus('Creating new response based on provided email text...');
  try {
    const r = await fetch(withEmailSecret('/suggestions/manual'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({from_text: fromText, subject, body})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    closeManualModal();
    document.getElementById('manualFrom').value = '';
    document.getElementById('manualSubject').value = '';
    document.getElementById('manualBody').value = '';
    setStatus('New response created from manual email text');
    await loadSuggestions();
  } catch (err) {
    setStatus(`Error creating manual suggestion: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function markStatus(id, status) {
  try {
    const r = await fetch(withEmailSecret(`/suggestions/${id}/status`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    if (status === 'reviewed' && data.removed) {
      setStatus('Suggestion marked as reviewed and archived from active list');
    } else if (status === 'draft') {
      setStatus('Suggestion moved back to active list');
    } else {
      setStatus(`Suggestion marked as ${status}`);
    }
    await loadSuggestions();
    if (emailReviewedVisible) await loadReviewedSuggestions();
  } catch (err) {
    setStatus(`Error updating suggestion status: ${err}`);
  }
}

async function copyText(id) {
  const area = document.getElementById(`reply-${id}`);
  const text = area.value;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    area.select();
    document.execCommand('copy');
  }
  await markStatus(id, 'copied');
}

async function sendSuggestion(id) {
  const toInput = document.getElementById(`to-${id}`);
  const ccInput = document.getElementById(`cc-${id}`);
  const bodyInput = document.getElementById(`reply-${id}`);
  if (!toInput || !bodyInput) return;

  const to_email = toInput.value.trim();
  const cc_email = ccInput ? ccInput.value.trim() : '';
  const body = bodyInput.value.trim();
  if (!to_email) {
    setStatus('Recipient email is required');
    return;
  }
  if (!body) {
    setStatus('Reply body is required');
    return;
  }

  setStatus('Sending email...');
  try {
    const r = await fetch(withEmailSecret(`/suggestions/${id}/send`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({to_email, cc_email, body})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const sentCc = data && data.item ? String(data.item.sent_cc || '') : '';
    setStatus(`Email sent to ${to_email}${sentCc ? ` (cc: ${sentCc})` : ''}`);
    await loadSuggestions();
  } catch (err) {
    setStatus(`Error sending email: ${err}`);
  }
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('emailAgentTheme', theme);
  const btn = document.getElementById('themeToggle');
  if (btn) {
    const toLight = theme === 'dark';
    btn.innerText = toLight ? '☀️' : '🌙';
    btn.setAttribute('aria-label', toLight ? 'Switch to light mode' : 'Switch to dark mode');
    btn.setAttribute('title', toLight ? 'Switch to light mode' : 'Switch to dark mode');
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  setTheme(current === 'dark' ? 'light' : 'dark');
}

(function initTheme() {
  const saved = localStorage.getItem('emailAgentTheme') || 'dark';
  setTheme(saved);
})();

(function bindModalCloseHandlers() {
  const suggestionModal = document.getElementById('suggestionModal');
  const manualModal = document.getElementById('manualModal');
  const answersSuggestModal = document.getElementById('answersSuggestModal');
  suggestionModal.addEventListener('click', function(event) {
    if (event.target === suggestionModal) closeSuggestionModal();
  });
  manualModal.addEventListener('click', function(event) {
    if (event.target === manualModal) closeManualModal();
  });
  answersSuggestModal.addEventListener('click', function(event) {
    if (event.target === answersSuggestModal) closeAnswersSuggestModal();
  });
  document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;
    closeSuggestionModal();
    closeManualModal();
    closeAnswersSuggestModal();
  });
})();

function escapeHtml(value) {
  const raw = (value === null || value === undefined) ? '' : String(value);
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeDomId(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function answersReplyAreaId(chatId) {
  return `answers-reply-${safeDomId(chatId)}`;
}

function openAnswersSuggestModal(chatId) {
  currentAnswersChatId = String(chatId || '');
  const modal = document.getElementById('answersSuggestModal');
  const area = document.getElementById('answersSuggestInstruction');
  area.value = '';
  modal.classList.remove('hidden');
  area.focus();
}

function closeAnswersSuggestModal() {
  currentAnswersChatId = '';
  document.getElementById('answersSuggestModal').classList.add('hidden');
}

async function submitAnswersSuggest() {
  const instruction = document.getElementById('answersSuggestInstruction').value.trim();
  if (!instruction || !currentAnswersChatId) return;
  const btn = document.getElementById('submitAnswersSuggestBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Generating...';
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(currentAnswersChatId)}/suggest`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({instruction})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    closeAnswersSuggestModal();
    setStatus(`Suggested response updated for chat ${currentAnswersChatId}`);
    await loadAnswersChats();
  } catch (err) {
    setStatus(`Error suggesting changes: ${err}`);
  } finally {
    btn.disabled = false;
    btn.innerText = oldText;
  }
}

async function sendAnswersReply(chatId) {
  const area = document.getElementById(answersReplyAreaId(chatId));
  if (!area) return;
  const text = String(area.value || '').trim();
  if (!text) {
    setStatus('Suggested reply is empty');
    return;
  }
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(chatId)}/send`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`Reply sent to chat ${chatId}`);
    await loadAnswersChats();
  } catch (err) {
    setStatus(`Error sending reply: ${err}`);
  }
}

async function requestAnswersAiSuggestion(chatId) {
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(chatId)}/suggest-ai`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'}
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`AI suggestion generated for chat ${chatId}`);
    await loadAnswersChats();
  } catch (err) {
    setStatus(`Error generating AI suggestion: ${err}`);
  }
}

async function markAnswersReviewed(chatId) {
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(chatId)}/status`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: 'reviewed'})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`Chat ${chatId} marked as reviewed`);
    await loadAnswersChats();
    if (answersArchivedVisible) await loadArchivedAnswersChats();
  } catch (err) {
    setStatus(`Error marking reviewed chat: ${err}`);
  }
}

function toggleArchivedAnswers() {
  answersArchivedVisible = !answersArchivedVisible;
  const btn = document.getElementById('answersArchivedToggleBtn');
  const section = document.getElementById('answersArchivedSection');
  if (!btn || !section) return;
  section.style.display = answersArchivedVisible ? 'block' : 'none';
  btn.innerText = answersArchivedVisible ? 'Hide archived' : 'View archived';
  if (answersArchivedVisible) {
    loadArchivedAnswersChats();
  }
}

async function loadArchivedAnswersChats() {
  const section = document.getElementById('answersArchivedSection');
  const list = document.getElementById('answersArchivedList');
  if (!section || !list) return;
  let data;
  try {
    const r = await fetch(withAnswersSecret('/chats/archived'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setStatus(`Error loading archived chats: ${err}`);
    return;
  }

  list.innerHTML = '';
  if (!Array.isArray(data.items) || data.items.length === 0) {
    list.innerHTML = `<p class="muted">No archived conversations.</p>`;
    return;
  }

  for (const item of data.items) {
    const chatId = String(item.chat_id || '');
    const archiveId = String(item.archive_id || '');
    const messages = Array.isArray(item.received_messages) ? item.received_messages : [];
    const renderedMessages = messages.length
      ? messages.map((message) => {
          const ts = formatTs(message.timestamp);
          const content = String(message.content || '').trim();
          const name = String(message.name || item.name || '').trim();
          return `
            <div class="answers-msg">
              <div class="muted">${escapeHtml(ts)} | Chat ${escapeHtml(chatId)} | ${escapeHtml(name)}</div>
              <div>${escapeHtml(content)}</div>
            </div>
          `;
        }).join('')
      : `<div class="muted">No user messages in this archived conversation.</div>`;

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div><b>${escapeHtml(item.name || '')}</b> · Chat ${escapeHtml(chatId)}</div>
      <div class="muted">Archived: ${escapeHtml(formatTs(item.archived_at))} | Last: ${escapeHtml(formatTs(item.last_received_ts))} | Received messages: ${escapeHtml(item.received_count || 0)}</div>
      <p><b>Received messages</b></p>
      <div class="answers-messages">${renderedMessages}</div>
      <p><b>Suggested reply at archive time</b></p>
      <textarea class="field" style="min-height:100px" readonly>${escapeHtml(item.suggested_reply || '')}</textarea>
      <div>
        <button onclick="unarchiveAnswersChat('${escapeHtml(chatId)}','${escapeHtml(archiveId)}')">Unarchive</button>
      </div>
    `;
    list.appendChild(card);
  }
}

async function unarchiveAnswersChat(chatId, archiveId) {
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(chatId)}/unarchive`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({archive_id: String(archiveId || '')})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`Chat ${chatId} unarchived`);
    await loadAnswersChats();
    await loadArchivedAnswersChats();
  } catch (err) {
    setStatus(`Error unarchiving chat: ${err}`);
  }
}

async function loadAnswersChats() {
  const list = document.getElementById('answersList');
  if (!list) return;
  let data;
  try {
    const r = await fetch(withAnswersSecret('/chats'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setStatus(`Error loading answers chats: ${err}`);
    return;
  }

  list.innerHTML = '';
  if (!Array.isArray(data.items) || data.items.length === 0) {
    list.innerHTML = `<div class="card"><p class="muted">No chats with received messages yet.</p></div>`;
    return;
  }

  for (const item of data.items) {
    const chatId = String(item.chat_id || '');
    const safeReplyId = answersReplyAreaId(chatId);
    const messages = Array.isArray(item.received_messages) ? item.received_messages : [];
    const renderedMessages = messages.length
      ? messages.map((message) => {
          const ts = formatTs(message.timestamp);
          const content = String(message.content || '').trim();
          const name = String(message.name || item.name || '').trim();
          return `
            <div class="answers-msg">
              <div class="muted">${escapeHtml(ts)} | Chat ${escapeHtml(chatId)} | ${escapeHtml(name)}</div>
              <div>${escapeHtml(content)}</div>
            </div>
          `;
        }).join('')
      : `<div class="muted">No user messages in this chat.</div>`;

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div><b>${escapeHtml(item.name || '')}</b> · Chat ${escapeHtml(chatId)}</div>
      <div class="muted">Status: ${escapeHtml(item.status || 'pending')} | Received messages: ${escapeHtml(item.received_count || 0)} | Last: ${escapeHtml(formatTs(item.last_received_ts))}</div>
      <p><b>Received messages</b></p>
      <div class="answers-messages">${renderedMessages}</div>
      <p><b>Suggested reply</b></p>
      <textarea id="${safeReplyId}" class="field" style="min-height:120px">${escapeHtml(item.suggested_reply || '')}</textarea>
      <div>
        <button onclick="requestAnswersAiSuggestion('${escapeHtml(chatId)}')">AI suggest</button>
        <button onclick="openAnswersSuggestModal('${escapeHtml(chatId)}')">Suggest changes</button>
        <button onclick="sendAnswersReply('${escapeHtml(chatId)}')">Send reply</button>
        <button onclick="markAnswersReviewed('${escapeHtml(chatId)}')">Mark reviewed</button>
      </div>
    `;
    list.appendChild(card);
  }
}

async function loadSuggestions() {
  let data;
  try {
    const r = await fetch(withEmailSecret('/suggestions'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setStatus(`Error loading suggestions: ${err}`);
    return;
  }
  const list = document.getElementById('list');
  const activeItems = Array.isArray(data.items)
    ? data.items.filter((item) => String(item.status || 'draft') !== 'reviewed')
    : [];
  list.innerHTML = '';
  if (activeItems.length === 0) {
    list.innerHTML = `<div class="card"><p class="muted">No suggestions yet. Use <b>Check new messages</b> or <b>Generate from text</b>.</p></div>`;
    return;
  }
  for (const item of activeItems.reverse()) {
    const div = document.createElement('div');
    div.className = 'card';
    const safeId = String(item.suggestion_id || '');
    const replySubject = buildReplySubject(item.subject);
    const currentTo = String(item.sent_to || '');
    const currentCc = String(item.sent_cc || emailSettingsCache.default_cc_email || '');
    div.innerHTML = `
      <div><b>${escapeHtml(item.subject)}</b></div>
      <div class='muted'>From: ${escapeHtml(item.from)} | Status: ${escapeHtml(item.status)}</div>
      <p><b>Original</b></p>
      <pre>${escapeHtml((item.original_body || '').slice(0, 400))}</pre>
      <p><b>Suggested reply</b></p>
      <textarea id='reply-${safeId}'></textarea>
      <p><b>Compose email</b></p>
      <input id='to-${safeId}' class='field' placeholder='Recipient email' value='${escapeHtml(currentTo)}'>
      <input id='cc-${safeId}' class='field' placeholder='CC emails (optional, comma-separated)' value='${escapeHtml(currentCc)}'>
      <input class='field' readonly value='Subject: ${escapeHtml(replySubject)}'>
      <div>
        <button onclick="openSuggestionModal('${safeId}')">Suggest changes</button>
        <button onclick="copyText('${safeId}')">Copy</button>
        <button onclick="sendSuggestion('${safeId}')">Send email</button>
        <button onclick="markStatus('${safeId}','reviewed')">Mark reviewed</button>
      </div>
    `;
    list.appendChild(div);
    const textarea = document.getElementById(`reply-${safeId}`);
    if (textarea) {
      textarea.value = String(item.suggested_reply || '');
    }
  }
}

function toggleReviewedSuggestions() {
  emailReviewedVisible = !emailReviewedVisible;
  const btn = document.getElementById('emailReviewedToggleBtn');
  const section = document.getElementById('emailReviewedSection');
  if (!btn || !section) return;
  section.style.display = emailReviewedVisible ? 'block' : 'none';
  btn.innerText = emailReviewedVisible ? 'Hide reviewed' : 'View reviewed';
  if (emailReviewedVisible) {
    loadReviewedSuggestions();
  }
}

async function loadReviewedSuggestions() {
  const list = document.getElementById('reviewedList');
  if (!list) return;
  let data;
  try {
    const r = await fetch(withEmailSecret('/suggestions?status=reviewed'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setStatus(`Error loading reviewed suggestions: ${err}`);
    return;
  }

  const reviewedItems = Array.isArray(data.items) ? data.items : [];
  list.innerHTML = '';
  if (reviewedItems.length === 0) {
    list.innerHTML = `<p class="muted">No reviewed emails.</p>`;
    return;
  }

  for (const item of reviewedItems.reverse()) {
    const safeId = String(item.suggestion_id || '');
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div><b>${escapeHtml(item.subject || '')}</b></div>
      <div class='muted'>From: ${escapeHtml(item.from || '')} | Reviewed: ${escapeHtml(formatTs(item.reviewed_at || item.updated_at))}</div>
      <p><b>Suggested reply</b></p>
      <textarea class='field' style='min-height:100px' readonly>${escapeHtml(item.suggested_reply || '')}</textarea>
      <div>
        <button onclick="markStatus('${safeId}','draft')">Unarchive</button>
      </div>
    `;
    list.appendChild(card);
  }
}

toggleIssueMode();
document.getElementById('issueIssueType')?.addEventListener('change', () => toggleIssueMode());
showTab('workday');
startWorkdayTicker();
if (workdayPollTimer) clearInterval(workdayPollTimer);
// Light polling for near-real-time feedback without full page reloads.
workdayPollTimer = setInterval(() => {
  if (activeTab === 'workday') refreshWorkdayPanel();
  if (activeTab === 'issue') refreshIssuePanel();
  if (activeTab === 'answers') loadAnswersChats();
}, 10000);
</script>
</body>
</html>
            """.strip()
        )

    return router
