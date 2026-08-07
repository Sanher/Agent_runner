"""Protected local HTML console for read-only chat intake services.

This router intentionally contains no integration-specific client code.  It
receives services from the local runner so the console can be tested with
fakes and cannot accidentally initialize the full Home Assistant application
or take over Telegram's shared Answers webhook.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from routers.auth import ensure_request_authorized


logger = logging.getLogger("agent_runner.intake_local_ui")


@dataclass(frozen=True)
class IntakeSourceBinding:
    """One read-only source exposed by the local intake console.

    ``service`` is deliberately typed loosely because each source has a
    different delivery contract.  The router only calls safe read methods:
    ``get_status``, ``list_summaries`` and, when explicitly allowed, one
    supported local poll method.  A webhook-delivered source must keep
    ``supports_manual_poll`` false so a local review console cannot steal or
    duplicate its delivery path.
    """

    key: str
    label: str
    service: Optional[Any]
    missing_config_fn: Callable[[], List[str]]
    baseline_mode: str = "none"
    supports_manual_poll: bool = False
    delivery_mode: str = "local_review"
    source_note: str = ""


_POLL_METHOD_NAMES = ("poll_new_messages", "poll_new_updates", "poll")
_TASK_DISMISS_REASONS = {"created", "duplicate", "not_actionable", "other"}
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class DismissLocalTaskRequest(BaseModel):
    """A human review choice that never creates an Issue or writes to chat."""

    reason: str


def _generic_operation_error() -> str:
    """Never reflect errors: Telegram request URLs include the bot token."""
    return "Local intake operation failed"


def _opaque_id(value: str, field_name: str, maximum_length: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > maximum_length or not _OPAQUE_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return normalized


def _dismiss_reason(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _TASK_DISMISS_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason must be one of {sorted(_TASK_DISMISS_REASONS)}",
        )
    return normalized


def _local_console_html() -> str:
    """Return the self-contained local console without interpolating data."""
    return r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="referrer" content="no-referrer" />
  <title>Local Intake Console</title>
  <style>
    :root {
      color-scheme: dark;
      --background: #0a090b;
      --surface: #151417;
      --surface-soft: #1d1b20;
      --border: rgba(255, 255, 255, .10);
      --border-strong: rgba(249, 115, 22, .34);
      --text: #f7f1ea;
      --muted: #aaa099;
      --accent: #f97316;
      --accent-hover: #fb923c;
      --danger: #ef4444;
      --success: #22c55e;
      --shadow: 0 20px 52px rgba(0, 0, 0, .38);
      font-family: "Avenir Next", Inter, "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }

    body {
      min-width: 320px;
      min-height: 100vh;
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at top right, rgba(249, 115, 22, .16), transparent 34%),
        radial-gradient(circle at 12% 96%, rgba(59, 130, 246, .08), transparent 28%),
        var(--background);
    }

    button, textarea, select { font: inherit; }

    button {
      border: 1px solid transparent;
      border-radius: 12px;
      cursor: pointer;
      font-size: .92rem;
      font-weight: 750;
      line-height: 1.15;
      padding: .7rem .95rem;
      transition: transform .16s ease, background .16s ease, border-color .16s ease, opacity .16s ease;
    }

    button:hover:not(:disabled) { transform: translateY(-1px); }
    button:focus-visible, textarea:focus-visible { outline: 3px solid rgba(249, 115, 22, .45); outline-offset: 2px; }
    button:disabled { cursor: wait; opacity: .6; }

    .shell { max-width: 1440px; margin: 0 auto; padding: 28px; }
    .topbar { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 24px; }
    h1, h2, h3, h4, p { margin-top: 0; }
    h1 { margin-bottom: 9px; font-size: clamp(1.85rem, 4vw, 2.7rem); letter-spacing: -.045em; }
    h2 { margin-bottom: 0; font-size: 1.17rem; letter-spacing: -.02em; }
    h3 { margin-bottom: 7px; font-size: 1.02rem; }
    h4 { margin-bottom: 7px; font-size: .96rem; }
    .intro, .muted { color: var(--muted); line-height: 1.55; }
    .intro { max-width: 760px; margin-bottom: 0; }
    .notice { max-width: 340px; margin: 0; color: #fed7aa; font-size: .88rem; line-height: 1.48; text-align: right; }

    .status-line {
      min-height: 24px;
      color: var(--muted);
      font-size: .93rem;
      line-height: 1.5;
      margin: 0 0 20px;
    }
    .status-line.error { color: #fca5a5; }
    .status-line.success { color: #bbf7d0; }

    .source-grid { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .source-panel, .summary-card, .draft-panel {
      background: linear-gradient(180deg, rgba(25, 24, 28, .98), rgba(17, 17, 21, .98));
      border: 1px solid var(--border);
      border-radius: 21px;
      box-shadow: var(--shadow);
    }
    .source-panel { padding: 20px; }
    .source-heading { align-items: start; display: flex; gap: 12px; justify-content: space-between; }
    .source-heading > div { min-width: 0; }
    .source-name { display: flex; align-items: center; gap: 9px; }
    .source-dot { background: var(--accent); border-radius: 99px; display: inline-block; height: 9px; width: 9px; }
    .source-state { color: var(--muted); font-size: .9rem; line-height: 1.45; margin: 9px 0 15px; min-height: 42px; }
    .source-actions { display: flex; flex-wrap: wrap; gap: 9px; }
    .baseline-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 13px; }
    .baseline-note { color: var(--muted); font-size: .83rem; line-height: 1.45; margin: 13px 0 0; }
    .primary-btn { background: linear-gradient(135deg, #fb923c, #ea580c); color: #fff7ed; }
    .primary-btn:hover:not(:disabled) { background: linear-gradient(135deg, #fdba74, #f97316); }
    .secondary-btn { background: rgba(255,255,255,.035); border-color: var(--border); color: var(--text); }
    .secondary-btn:hover:not(:disabled) { border-color: var(--border-strong); background: rgba(249, 115, 22, .10); }

    .workspace { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(330px, .8fr); gap: 20px; margin-top: 20px; align-items: start; }
    .summaries-panel { min-width: 0; }
    .section-heading { align-items: center; display: flex; gap: 16px; justify-content: space-between; margin: 6px 0 14px; }
    .section-heading .muted { font-size: .9rem; margin: 0; }
    .summary-list { display: grid; gap: 15px; }
    .summary-card { overflow: hidden; padding: 20px; }
    .summary-card header { align-items: start; display: flex; gap: 16px; justify-content: space-between; }
    .summary-meta { color: var(--muted); font-size: .84rem; line-height: 1.45; margin-bottom: 0; text-align: right; }
    .summary-body { line-height: 1.6; margin: 18px 0; white-space: pre-wrap; }
    .list-block { border-top: 1px solid var(--border); padding-top: 15px; }
    .inline-list { color: var(--muted); line-height: 1.55; margin: 7px 0 0; padding-left: 19px; }
    .task-list { display: grid; gap: 10px; margin-top: 12px; }
    .task-card { background: rgba(3, 3, 5, .32); border: 1px solid rgba(255,255,255,.08); border-radius: 15px; padding: 15px; }
    .task-head { align-items: start; display: flex; gap: 12px; justify-content: space-between; }
    .task-context { color: var(--muted); line-height: 1.52; margin: 10px 0 13px; white-space: pre-wrap; }
    .task-meta { color: var(--muted); font-size: .82rem; line-height: 1.45; margin: 0 0 13px; }
    .small-btn { background: rgba(249, 115, 22, .13); border-color: rgba(249, 115, 22, .3); color: #fed7aa; font-size: .84rem; padding: .58rem .72rem; }
    .small-btn:hover:not(:disabled) { background: rgba(249, 115, 22, .21); }
    .task-review-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
    .task-review-select { background: rgba(8,8,11,.75); border: 1px solid var(--border); border-radius: 10px; color: var(--text); font-size: .84rem; min-width: 155px; padding: .53rem .58rem; }
    .dismissed-note { color: #fed7aa; font-size: .84rem; line-height: 1.45; margin: 10px 0 0; }
    .empty { background: rgba(255,255,255,.025); border: 1px dashed var(--border); border-radius: 16px; color: var(--muted); line-height: 1.55; margin: 0; padding: 20px; }

    .draft-panel { padding: 20px; position: sticky; top: 20px; }
    .draft-panel > p { color: var(--muted); line-height: 1.52; }
    .draft-state { color: #fed7aa; font-size: .88rem; line-height: 1.48; min-height: 38px; }
    textarea { background: rgba(8,8,11,.75); border: 1px solid var(--border); border-radius: 13px; color: var(--text); line-height: 1.52; min-height: 370px; padding: 13px; resize: vertical; width: 100%; }
    .draft-actions { display: flex; justify-content: flex-end; margin-top: 10px; }

    @media (max-width: 900px) {
      .workspace { grid-template-columns: 1fr; }
      .draft-panel { position: static; }
    }
    @media (max-width: 650px) {
      .shell { padding: 18px; }
      .topbar, .summary-card header { align-items: start; flex-direction: column; }
      .notice, .summary-meta { text-align: left; }
      .source-grid { grid-template-columns: 1fr; }
      .source-heading { gap: 16px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <h1>Local Intake Console</h1>
        <p class="intro">Read-only summaries from Discord and Telegram. Discord can be manually read here; Telegram is review-only because its live updates arrive through the Answers webhook in Agent Runner.</p>
      </div>
      <p class="notice">This console only prepares a local draft. It never creates or submits an Issue.</p>
    </header>

    <p id="appStatus" class="status-line" role="status" aria-live="polite">Loading local intake sources…</p>

    <section class="source-grid" aria-label="Chat intake sources">
      <article class="source-panel" aria-labelledby="discordTitle">
        <div class="source-heading">
          <div>
            <div class="source-name"><span class="source-dot" aria-hidden="true"></span><h2 id="discordTitle">Discord</h2></div>
            <p id="discordSourceState" class="source-state">Loading status…</p>
          </div>
          <div class="source-actions">
            <button id="refreshDiscordBtn" class="secondary-btn" type="button">Refresh</button>
            <button id="pollDiscordBtn" class="primary-btn" type="button">Poll now</button>
          </div>
        </div>
        <div id="discordBaselineActions" class="baseline-actions"></div>
        <p class="baseline-note">A baseline starts future-only reading; it does not summarize prior chat history.</p>
      </article>

      <article class="source-panel" aria-labelledby="telegramTitle">
        <div class="source-heading">
          <div>
            <div class="source-name"><span class="source-dot" aria-hidden="true"></span><h2 id="telegramTitle">Telegram</h2></div>
            <p id="telegramSourceState" class="source-state">Loading status…</p>
          </div>
          <div class="source-actions">
            <button id="refreshTelegramBtn" class="secondary-btn" type="button">Refresh</button>
          </div>
        </div>
        <p class="baseline-note">Telegram updates arrive through the Answers webhook in Agent Runner. This local console does not connect to Telegram or start a Telegram baseline.</p>
      </article>
    </section>

    <div class="workspace">
      <section class="summaries-panel" aria-labelledby="summariesTitle">
        <div class="section-heading">
          <h2 id="summariesTitle">Summaries and suggested tasks</h2>
          <p class="muted">Message evidence remains an internal reference.</p>
        </div>
        <div id="summaryList" class="summary-list" aria-live="polite"></div>
      </section>

      <aside class="draft-panel" aria-labelledby="draftTitle">
        <h2 id="draftTitle">Issue draft</h2>
        <p>Choose a suggested task to prefill a local review draft. No request is sent to an Issue provider.</p>
        <p id="draftState" class="draft-state">No task selected.</p>
        <label class="muted" for="issueDraft">Editable local draft</label>
        <textarea id="issueDraft" spellcheck="true" placeholder="A selected task will appear here for review."></textarea>
        <div class="draft-actions"><button id="clearIssueDraftBtn" class="secondary-btn" type="button">Clear local draft</button></div>
      </aside>
    </div>
  </main>

  <script>
    'use strict';

    const sourceNames = {discord: 'Discord', telegram: 'Telegram'};
    const sourceItems = {discord: [], telegram: []};

    function initialJobSecret() {
      // Fragments never leave the browser.  The query form is only retained
      // for legacy local bookmarks and is removed immediately after reading.
      const fragmentSecret = window.location.hash.slice(1);
      const legacyQuerySecret = new URLSearchParams(window.location.search).get('secret') || '';
      if (window.location.search || window.location.hash) {
        window.history.replaceState(null, document.title, window.location.pathname);
      }
      return fragmentSecret || legacyQuerySecret;
    }

    const localJobSecret = initialJobSecret();

    function cleanText(value, fallback = '') {
      const text = String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
      return text || fallback;
    }

    function listOfStrings(value) {
      return Array.isArray(value) ? value.map((item) => cleanText(item)).filter(Boolean) : [];
    }

    function element(name, className, text) {
      const node = document.createElement(name);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function setAppStatus(text, variant = '') {
      const node = document.getElementById('appStatus');
      node.textContent = text;
      node.className = `status-line ${variant}`.trim();
    }

    async function api(path, options = {}) {
      const headers = new Headers(options.headers || {});
      if (localJobSecret) headers.set('X-Job-Secret', localJobSecret);
      const response = await fetch(path, Object.assign(
        {cache: 'no-store', referrerPolicy: 'no-referrer'},
        options,
        {headers},
      ));
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(cleanText(payload.detail || payload.error, `HTTP ${response.status}`));
      }
      return payload;
    }

    function sourcePath(source, suffix) {
      return `/api/intake/${encodeURIComponent(source)}${suffix}`;
    }

    function sourceStateText(source, payload) {
      const sourceNote = cleanText(payload?.source_note);
      if (!payload?.available) return sourceNote || 'Not wired into this local runner yet.';
      const status = payload.status || {};
      const missing = listOfStrings(payload.missing_configuration);
      if (missing.length) return `Configuration required: ${missing.join(', ')}.`;
      if (status.enabled === false) return 'Disabled by configuration.';
      const count = Array.isArray(sourceItems[source])
        ? sourceItems[source].length
        : Number(status.summary_count || 0);
      if (payload?.supports_manual_poll !== true) {
        return `${count} stored summaries. ${sourceNote || 'This source is review-only in the local console.'}`;
      }
      const sourceStates = Array.isArray(status.channels)
        ? status.channels
        : (Array.isArray(status.chats) ? status.chats : []);
      const baseline = sourceStates.filter((item) => item?.baseline_status === 'pending').length;
      if (baseline) return `${count} stored summaries. ${baseline} source(s) still await an initial baseline.`;
      return `${count} stored summaries. Ready for a manual read.`;
    }

    function renderSourceStatus(source, payload) {
      const node = document.getElementById(`${source}SourceState`);
      node.textContent = sourceStateText(source, payload);
      const pollButton = document.getElementById(`poll${source[0].toUpperCase()}${source.slice(1)}Btn`);
      if (pollButton) {
        pollButton.disabled = payload?.supports_manual_poll !== true
          || !payload?.available
          || !!listOfStrings(payload?.missing_configuration).length;
      }
      renderBaselineControls(source, payload);
    }

    function renderBaselineControls(source, payload) {
      const list = document.getElementById(`${source}BaselineActions`);
      if (!list) return;
      list.replaceChildren();
      if (!payload?.available || listOfStrings(payload?.missing_configuration).length) return;
      const status = payload.status || {};
      const mode = cleanText(payload?.baseline_mode);
      if (mode === 'channel') {
        const channels = Array.isArray(status.channels) ? status.channels : [];
        channels.forEach((channel) => {
          if (cleanText(channel?.baseline_status) === 'initialized') return;
          const channelId = cleanText(channel?.channel_id);
          if (!channelId) return;
          const button = element('button', 'small-btn', `Start ${channelId} from now`);
          button.type = 'button';
          button.addEventListener('click', () => baselineSource(source, button, channelId));
          list.appendChild(button);
        });
        return;
      }
      if (mode === 'stream') {
        const chats = Array.isArray(status.chats) ? status.chats : [];
        const hasPendingChat = chats.some((chat) => cleanText(chat?.baseline_status) !== 'initialized');
        if (chats.length && !hasPendingChat) return;
        const button = element('button', 'small-btn', 'Start Telegram from now');
        button.type = 'button';
        button.addEventListener('click', () => baselineSource(source, button));
        list.appendChild(button);
      }
    }

    function appendListBlock(card, title, values, emptyText) {
      const block = element('section', 'list-block');
      block.appendChild(element('h4', '', title));
      const items = listOfStrings(values);
      if (!items.length) {
        block.appendChild(element('p', 'muted', emptyText));
      } else {
        const list = element('ul', 'inline-list');
        items.forEach((value) => list.appendChild(element('li', '', value)));
        block.appendChild(list);
      }
      card.appendChild(block);
    }

    function taskEvidence(task) {
      const evidence = listOfStrings(task?.evidence_message_ids);
      return evidence.length ? evidence.join(', ') : 'No message IDs supplied';
    }

    function prepareIssueDraft(source, task, summary) {
      const sourceLabel = sourceNames[source] || source;
      const taskTitle = cleanText(task?.title, 'Untitled suggested task');
      const context = cleanText(task?.context, 'No task context was provided.');
      const summaryText = cleanText(summary?.summary, 'No summary text was provided.');
      const summaryId = cleanText(summary?.summary_id, 'unknown');
      const lines = [
        `# ${taskTitle}`,
        '',
        '## Suggested classification',
        `- Type: ${cleanText(task?.issue_type, 'task')}`,
        `- Repository: ${cleanText(task?.repo, 'backend')}`,
        `- Unit: ${cleanText(task?.unit, 'core')}`,
        `- Confidence: ${cleanText(task?.confidence, 'not specified')}`,
        '',
        '## Task context',
        context,
        '',
        '## Conversation summary',
        summaryText,
        '',
        '## Source evidence',
        `- Source: ${sourceLabel}`,
        `- Summary ID: ${summaryId}`,
        `- Message IDs: ${taskEvidence(task)}`,
        '',
        'Prepared locally for human review. No Issue has been created or submitted.',
      ];
      document.getElementById('issueDraft').value = lines.join('\n');
      document.getElementById('draftState').textContent = `Local draft prepared from ${sourceLabel}. Review and edit it before using another tool.`;
      document.getElementById('issueDraft').focus();
    }

    function renderTask(source, task, summary) {
      const card = element('article', 'task-card');
      const head = element('div', 'task-head');
      head.appendChild(element('h4', '', cleanText(task?.title, 'Untitled suggested task')));
      const actions = element('div', 'task-review-actions');
      const summaryId = cleanText(summary?.summary_id);
      const taskKey = cleanText(task?.task_key);
      const dismissed = task?.dismissed === true;
      if (dismissed) {
        const restoreAction = element('button', 'small-btn', 'Restore task');
        restoreAction.type = 'button';
        restoreAction.disabled = !summaryId || !taskKey;
        restoreAction.addEventListener('click', () => restoreTask(source, summaryId, taskKey, restoreAction));
        actions.appendChild(restoreAction);
      } else {
        const draftAction = element('button', 'small-btn', 'Prepare Issue draft');
        draftAction.type = 'button';
        draftAction.addEventListener('click', () => prepareIssueDraft(source, task, summary));
        actions.appendChild(draftAction);
        const reasonSelect = element('select', 'task-review-select');
        reasonSelect.setAttribute('aria-label', 'Reason for clearing this task');
        [
          ['', 'Clear as…'],
          ['created', 'Created'],
          ['duplicate', 'Duplicate'],
          ['not_actionable', 'Not an incident'],
          ['other', 'Other reason'],
        ].forEach(([value, label]) => {
          const option = element('option', '', label);
          option.value = value;
          reasonSelect.appendChild(option);
        });
        const clearAction = element('button', 'small-btn', 'Clear task');
        clearAction.type = 'button';
        clearAction.disabled = !summaryId || !taskKey;
        clearAction.addEventListener('click', () => dismissTask(source, summaryId, taskKey, reasonSelect.value, clearAction));
        actions.appendChild(reasonSelect);
        actions.appendChild(clearAction);
      }
      head.appendChild(actions);
      card.appendChild(head);
      card.appendChild(element('p', 'task-context', cleanText(task?.context, 'No task context was provided.')));
      card.appendChild(element(
        'p',
        'task-meta',
        `Type: ${cleanText(task?.issue_type, 'task')} · Repository: ${cleanText(task?.repo, 'backend')} · Unit: ${cleanText(task?.unit, 'core')} · Evidence: ${taskEvidence(task)}`,
      ));
      if (dismissed) {
        card.appendChild(element('p', 'dismissed-note', `Cleared: ${cleanText(task?.dismissed_reason, 'other')}. You can restore it for review.`));
      }
      return card;
    }

    function renderSummary(source, summary) {
      const card = element('article', 'summary-card');
      const header = element('header');
      const title = element('div');
      title.appendChild(element('h3', '', `${sourceNames[source] || source} summary`));
      title.appendChild(element('p', 'muted', cleanText(summary?.created_at, 'No creation timestamp supplied.')));
      header.appendChild(title);
      const tasks = Array.isArray(summary?.suggested_tasks) ? summary.suggested_tasks : [];
      header.appendChild(element('p', 'summary-meta', `${Number(summary?.message_count || 0)} messages\n${tasks.length} suggested tasks`));
      card.appendChild(header);
      card.appendChild(element('p', 'summary-body', cleanText(summary?.summary, 'No summary text was provided.')));
      appendListBlock(card, 'Decisions', summary?.decisions, 'No decisions recorded.');
      appendListBlock(card, 'Blockers', summary?.blockers, 'No blockers recorded.');
      const taskBlock = element('section', 'list-block');
      taskBlock.appendChild(element('h4', '', 'Suggested tasks'));
      if (!tasks.length) {
        taskBlock.appendChild(element('p', 'muted', 'No suggested tasks in this summary.'));
      } else {
        const list = element('div', 'task-list');
        tasks.forEach((task) => list.appendChild(renderTask(source, task, summary)));
        taskBlock.appendChild(list);
      }
      card.appendChild(taskBlock);
      return card;
    }

    function renderSummaries() {
      const list = document.getElementById('summaryList');
      list.replaceChildren();
      const entries = Object.entries(sourceItems).flatMap(([source, items]) =>
        (Array.isArray(items) ? items : []).map((summary) => ({source, summary})),
      );
      entries.sort((left, right) => cleanText(right.summary?.created_at).localeCompare(cleanText(left.summary?.created_at)));
      if (!entries.length) {
        list.appendChild(element('p', 'empty', 'No summaries are available yet. Manually poll an enabled Discord source, or wait for Telegram updates to arrive through Agent Runner.'));
        return;
      }
      entries.forEach(({source, summary}) => list.appendChild(renderSummary(source, summary)));
    }

    async function loadSource(source) {
      const [statusPayload, summariesPayload] = await Promise.all([
        api(sourcePath(source, '/status')),
        api(sourcePath(source, '/summaries')),
      ]);
      sourceItems[source] = Array.isArray(summariesPayload.items) ? summariesPayload.items : [];
      renderSourceStatus(source, statusPayload);
      renderSummaries();
    }

    async function loadAll() {
      setAppStatus('Loading local intake sources…');
      const results = await Promise.allSettled(Object.keys(sourceNames).map((source) => loadSource(source)));
      const failures = results.filter((result) => result.status === 'rejected');
      if (failures.length) {
        const first = failures[0]?.reason;
        setAppStatus(`Some local source data could not be loaded: ${cleanText(first?.message, 'unknown error')}`, 'error');
      } else {
        setAppStatus('Local intake sources loaded.', 'success');
      }
    }

    async function pollSource(source) {
      const button = document.getElementById(`poll${source[0].toUpperCase()}${source.slice(1)}Btn`);
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Polling…';
      setAppStatus(`Polling ${sourceNames[source]}…`);
      try {
        const payload = await api(sourcePath(source, '/poll'), {method: 'POST'});
        const warningCount = Array.isArray(payload?.result?.warnings) ? payload.result.warnings.length : 0;
        const completed = payload?.ok !== false;
        setAppStatus(
          completed
            ? (warningCount ? `${sourceNames[source]} poll completed with ${warningCount} warning(s).` : `${sourceNames[source]} poll completed.`)
            : `${sourceNames[source]} poll completed with source errors. Review the result before trying again.`,
          completed && !warningCount ? 'success' : '',
        );
      } catch (error) {
        setAppStatus(`Could not poll ${sourceNames[source]}: ${cleanText(error?.message, 'unknown error')}`, 'error');
      } finally {
        button.textContent = original;
        await loadSource(source).catch((error) => {
          setAppStatus(`Could not refresh ${sourceNames[source]}: ${cleanText(error?.message, 'unknown error')}`, 'error');
        });
      }
    }

    async function baselineSource(source, button, channelId = '') {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Starting…';
      setAppStatus(`Starting ${sourceNames[source]} from now…`);
      try {
        const suffix = channelId ? `/baseline?channel_id=${encodeURIComponent(channelId)}` : '/baseline';
        await api(sourcePath(source, suffix), {method: 'POST'});
        setAppStatus(`${sourceNames[source]} baseline saved. Earlier messages were not summarized.`, 'success');
      } catch (error) {
        setAppStatus(`Could not start ${sourceNames[source]} from now: ${cleanText(error?.message, 'unknown error')}`, 'error');
      } finally {
        button.textContent = original;
        await loadSource(source).catch((error) => {
          setAppStatus(`Could not refresh ${sourceNames[source]}: ${cleanText(error?.message, 'unknown error')}`, 'error');
        });
      }
    }

    function taskReviewPath(source, summaryId, taskKey) {
      return sourcePath(
        source,
        `/summaries/${encodeURIComponent(summaryId)}/tasks/${encodeURIComponent(taskKey)}/dismiss`,
      );
    }

    async function dismissTask(source, summaryId, taskKey, reason, button) {
      if (!reason) {
        setAppStatus('Choose a reason before clearing this task.', 'error');
        return;
      }
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Clearing…';
      try {
        await api(taskReviewPath(source, summaryId, taskKey), {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({reason}),
        });
        setAppStatus('Task cleared for human review. No chat or Issue was changed.', 'success');
      } catch (error) {
        setAppStatus(`Could not clear task: ${cleanText(error?.message, 'unknown error')}`, 'error');
      } finally {
        button.textContent = original;
        await loadSource(source).catch((error) => {
          setAppStatus(`Could not refresh ${sourceNames[source]}: ${cleanText(error?.message, 'unknown error')}`, 'error');
        });
      }
    }

    async function restoreTask(source, summaryId, taskKey, button) {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Restoring…';
      try {
        await api(taskReviewPath(source, summaryId, taskKey), {method: 'DELETE'});
        setAppStatus('Task restored for human review. No chat or Issue was changed.', 'success');
      } catch (error) {
        setAppStatus(`Could not restore task: ${cleanText(error?.message, 'unknown error')}`, 'error');
      } finally {
        button.textContent = original;
        await loadSource(source).catch((error) => {
          setAppStatus(`Could not refresh ${sourceNames[source]}: ${cleanText(error?.message, 'unknown error')}`, 'error');
        });
      }
    }

    document.getElementById('refreshDiscordBtn').addEventListener('click', () => loadSource('discord'));
    document.getElementById('refreshTelegramBtn').addEventListener('click', () => loadSource('telegram'));
    document.getElementById('pollDiscordBtn').addEventListener('click', () => pollSource('discord'));
    document.getElementById('clearIssueDraftBtn').addEventListener('click', () => {
      document.getElementById('issueDraft').value = '';
      document.getElementById('draftState').textContent = 'Local draft cleared. No Issue was created or changed.';
    });
    loadAll();
  </script>
</body>
</html>
"""


def create_intake_local_ui_router(
    *,
    sources: Sequence[IntakeSourceBinding],
    job_secret: str,
) -> APIRouter:
    """Create a local-only console and its authenticated JSON endpoints.

    The caller controls which services exist.  Passing ``None`` deliberately
    shows an unavailable source instead of importing or starting other agents.
    """
    bindings: Dict[str, IntakeSourceBinding] = {}
    for source in sources:
        key = str(source.key or "").strip().lower()
        if not key or key in bindings:
            raise ValueError("Each local intake source needs a unique key")
        bindings[key] = source

    router = APIRouter(tags=["local-intake"])

    def ensure_auth(request: Request) -> str:
        return ensure_request_authorized(request, job_secret, logger)

    def binding_for(source_key: str) -> IntakeSourceBinding:
        binding = bindings.get(str(source_key or "").strip().lower())
        if binding is None:
            raise HTTPException(status_code=404, detail="Unknown local intake source")
        return binding

    def missing_configuration(binding: IntakeSourceBinding) -> List[str]:
        try:
            values = binding.missing_config_fn() or []
        except Exception as error:
            logger.error(
                "Local intake config check failed for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise RuntimeError("Local source configuration check failed") from error
        return list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))

    def unavailable_status(binding: IntakeSourceBinding) -> Dict[str, Any]:
        return {
            "ok": True,
            "source": binding.key,
            "available": False,
            "baseline_mode": binding.baseline_mode,
            "supports_manual_poll": binding.supports_manual_poll,
            "delivery_mode": binding.delivery_mode,
            "source_note": binding.source_note,
            "status": {
                "ok": True,
                "enabled": False,
                "local_runner_state": "not_wired",
            },
            "missing_configuration": [],
        }

    def require_service(binding: IntakeSourceBinding) -> Any:
        if binding.service is None:
            raise HTTPException(
                status_code=503,
                detail=f"{binding.label} is not wired into this local runner",
            )
        return binding.service

    def require_complete_configuration(binding: IntakeSourceBinding) -> None:
        missing = missing_configuration(binding)
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {binding.key} config. Missing: {', '.join(sorted(missing))}",
            )

    def poll_service(service: Any) -> Dict[str, Any]:
        for method_name in _POLL_METHOD_NAMES:
            method = getattr(service, method_name, None)
            if callable(method):
                result = method()
                if not isinstance(result, dict):
                    raise TypeError(f"{method_name} must return a dictionary")
                return result
        raise AttributeError("Service does not expose a supported local poll method")

    def baseline_service(binding: IntakeSourceBinding, service: Any, channel_id: str) -> Dict[str, Any]:
        mode = str(binding.baseline_mode or "none").strip().lower()
        if mode == "channel":
            normalized_channel_id = str(channel_id or "").strip()
            if not normalized_channel_id.isdecimal():
                raise HTTPException(status_code=400, detail="A numeric channel_id is required")
            method = getattr(service, "baseline_channel_from_now", None)
            if not callable(method):
                raise AttributeError("Service does not expose channel baseline support")
            result = method(normalized_channel_id)
        elif mode == "stream":
            method = getattr(service, "baseline_from_now", None)
            if not callable(method):
                raise AttributeError("Service does not expose stream baseline support")
            result = method()
        else:
            raise HTTPException(status_code=404, detail="This local source does not support a baseline")
        if not isinstance(result, dict):
            raise TypeError("baseline method must return a dictionary")
        return result

    def dismiss_task(service: Any, summary_id: str, task_key: str, reason: str) -> Dict[str, Any]:
        method = getattr(service, "dismiss_suggested_task", None)
        if not callable(method):
            raise AttributeError("Service does not expose task review support")
        result = method(summary_id, task_key, reason)
        if not isinstance(result, dict):
            raise TypeError("dismiss_suggested_task must return a dictionary")
        return result

    def restore_task(service: Any, summary_id: str, task_key: str) -> Dict[str, Any]:
        method = getattr(service, "restore_suggested_task", None)
        if not callable(method):
            raise AttributeError("Service does not expose task review support")
        result = method(summary_id, task_key)
        if not isinstance(result, dict):
            raise TypeError("restore_suggested_task must return a dictionary")
        return result

    @router.get("/", response_class=HTMLResponse)
    def console() -> HTMLResponse:
        """Serve only the credential-free local bootstrap document.

        A URL fragment is not sent to the server, so the static document must
        load without the secret.  Every data-bearing JSON endpoint remains
        authenticated with ``X-Job-Secret`` before it reaches a service.
        """
        return HTMLResponse(
            _local_console_html(),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )

    @router.get("/api/intake/{source_key}/status")
    def source_status(source_key: str, request: Request) -> Dict[str, Any]:
        ensure_auth(request)
        binding = binding_for(source_key)
        if binding.service is None:
            return unavailable_status(binding)
        try:
            status = binding.service.get_status()
            if not isinstance(status, dict):
                raise TypeError("get_status must return a dictionary")
            return {
                "ok": True,
                "source": binding.key,
                "available": True,
                "baseline_mode": binding.baseline_mode,
                "supports_manual_poll": binding.supports_manual_poll,
                "delivery_mode": binding.delivery_mode,
                "source_note": binding.source_note,
                "status": status,
                "missing_configuration": missing_configuration(binding),
            }
        except HTTPException:
            raise
        except Exception as error:
            logger.error(
                "Local intake status failed for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    @router.get("/api/intake/{source_key}/summaries")
    def source_summaries(
        source_key: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> Dict[str, Any]:
        ensure_auth(request)
        binding = binding_for(source_key)
        if binding.service is None:
            return {
                "ok": True,
                "source": binding.key,
                "available": False,
                "count": 0,
                "items": [],
            }
        try:
            items = binding.service.list_summaries(limit=limit)
            if not isinstance(items, list):
                raise TypeError("list_summaries must return a list")
            return {
                "ok": True,
                "source": binding.key,
                "available": True,
                "count": len(items),
                "items": items,
            }
        except Exception as error:
            logger.error(
                "Local intake summaries failed for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    @router.post("/api/intake/{source_key}/poll")
    def poll_source(source_key: str, request: Request) -> Dict[str, Any]:
        ensure_auth(request)
        binding = binding_for(source_key)
        if not binding.supports_manual_poll:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{binding.label} does not support local manual polling; "
                    "its updates are delivered by its configured source transport"
                ),
            )
        service = require_service(binding)
        try:
            require_complete_configuration(binding)
            result = poll_service(service)
            ok = bool(result.get("ok", True))
            if ok:
                logger.info("Local intake poll completed for %s", binding.key)
            else:
                logger.warning("Local intake poll completed with source errors for %s", binding.key)
            return {"ok": ok, "source": binding.key, "result": result}
        except HTTPException:
            raise
        except Exception as error:
            logger.error(
                "Local intake poll failed for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    @router.post("/api/intake/{source_key}/baseline")
    def baseline_source(
        source_key: str,
        request: Request,
        channel_id: str = Query(default="", max_length=30),
    ) -> Dict[str, Any]:
        """Persist a future-only read boundary without sending chat content."""
        ensure_auth(request)
        binding = binding_for(source_key)
        if str(binding.baseline_mode or "none").strip().lower() == "none":
            raise HTTPException(
                status_code=409,
                detail=f"{binding.label} does not support a local baseline",
            )
        service = require_service(binding)
        try:
            require_complete_configuration(binding)
            result = baseline_service(binding, service, channel_id)
            logger.info("Local intake baseline initialized for %s", binding.key)
            return {"ok": True, "source": binding.key, "result": result}
        except HTTPException:
            raise
        except LookupError as error:
            logger.warning(
                "Local intake baseline target was not found for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=404, detail="Local intake target was not found") from None
        except ValueError as error:
            logger.warning(
                "Local intake baseline request was invalid for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=400, detail="Invalid local intake baseline request") from None
        except Exception as error:
            logger.error(
                "Local intake baseline failed for %s (error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    @router.post("/api/intake/{source_key}/summaries/{summary_id}/tasks/{task_key}/dismiss")
    def dismiss_source_task(
        source_key: str,
        summary_id: str,
        task_key: str,
        request: Request,
        payload: DismissLocalTaskRequest,
    ) -> Dict[str, Any]:
        """Persist an explicit human clear decision without touching chat or Issues."""
        ensure_auth(request)
        binding = binding_for(source_key)
        service = require_service(binding)
        normalized_summary_id = _opaque_id(summary_id, "summary_id", 200)
        normalized_task_key = _opaque_id(task_key, "task_key", 128)
        reason = _dismiss_reason(payload.reason)
        try:
            result = dismiss_task(service, normalized_summary_id, normalized_task_key, reason)
            logger.info(
                "Local intake task cleared (source=%s, summary_id=%s, task_key=%s, reason=%s)",
                binding.key,
                normalized_summary_id,
                normalized_task_key,
                reason,
            )
            return {"ok": True, "source": binding.key, "result": result}
        except LookupError as error:
            logger.warning(
                "Local intake task to clear was not found (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=404, detail="Local intake task was not found") from None
        except ValueError as error:
            logger.warning(
                "Local intake task clear request was invalid (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=400, detail="Invalid local intake task review request") from None
        except Exception as error:
            logger.error(
                "Local intake task clear failed (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    @router.delete("/api/intake/{source_key}/summaries/{summary_id}/tasks/{task_key}/dismiss")
    def restore_source_task(
        source_key: str,
        summary_id: str,
        task_key: str,
        request: Request,
    ) -> Dict[str, Any]:
        """Restore a cleared task to human review without chat or Issue writes."""
        ensure_auth(request)
        binding = binding_for(source_key)
        service = require_service(binding)
        normalized_summary_id = _opaque_id(summary_id, "summary_id", 200)
        normalized_task_key = _opaque_id(task_key, "task_key", 128)
        try:
            result = restore_task(service, normalized_summary_id, normalized_task_key)
            logger.info(
                "Local intake task restored (source=%s, summary_id=%s, task_key=%s)",
                binding.key,
                normalized_summary_id,
                normalized_task_key,
            )
            return {"ok": True, "source": binding.key, "result": result}
        except LookupError as error:
            logger.warning(
                "Local intake task to restore was not found (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=404, detail="Local intake task was not found") from None
        except ValueError as error:
            logger.warning(
                "Local intake task restore request was invalid (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=400, detail="Invalid local intake task review request") from None
        except Exception as error:
            logger.error(
                "Local intake task restore failed (source=%s, error_type=%s)",
                binding.key,
                type(error).__name__,
            )
            raise HTTPException(status_code=500, detail=_generic_operation_error()) from None

    return router
