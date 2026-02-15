from datetime import datetime
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agents.email_agent.service import EmailAgentService


class CheckNewRequest(BaseModel):
    max_emails: int = 5
    unread_only: bool = True
    mailbox: str = "INBOX"


class RegenerateRequest(BaseModel):
    instruction: str


class MarkStatusRequest(BaseModel):
    status: str


class ManualSuggestionRequest(BaseModel):
    from_text: str = ""
    subject: str = ""
    body: str


class EmailSettingsRequest(BaseModel):
    allowed_from_whitelist: List[str] = []


def create_email_router(
    service: EmailAgentService,
    job_secret: str,
    missing_config_fn: Callable[[], List[str]],
) -> APIRouter:
    """Crea router HTTP y UI para revisión manual de respuestas de email."""
    router = APIRouter(prefix="/email-agent", tags=["email-agent"])

    def ensure_config() -> None:
        missing = missing_config_fn()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Email config inválida. Faltan: {', '.join(sorted(missing))}",
            )

    def ensure_auth(request: Request) -> None:
        if not job_secret:
            return
        provided = (
            request.headers.get("x-job-secret", "").strip()
            or request.query_params.get("secret", "").strip()
        )
        if provided != job_secret:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @router.post("/check-new")
    def check_new(req: CheckNewRequest, request: Request):
        """Detecta nuevos correos y genera sugerencias (sin enviar email)."""
        ensure_auth(request)
        ensure_config()
        created = service.check_new_and_suggest(
            max_emails=max(1, min(req.max_emails, 20)),
            unread_only=req.unread_only,
            mailbox=req.mailbox,
        )
        return {
            "ok": True,
            "created": len(created),
            "note": "Webhook notification was sent for each new suggestion when configured.",
            "items": created,
        }

    @router.get("/suggestions")
    def list_suggestions(request: Request, status: Optional[str] = None):
        """Devuelve sugerencias almacenadas opcionalmente filtradas por estado."""
        ensure_auth(request)
        items = service.load_suggestions()
        if status:
            items = [item for item in items if item.get("status") == status]
        return {"ok": True, "count": len(items), "items": items}

    @router.post("/suggestions/{suggestion_id}/regenerate")
    def regenerate(suggestion_id: str, req: RegenerateRequest, request: Request):
        """Regenera una sugerencia aplicando instrucciones del usuario."""
        ensure_auth(request)
        ensure_config()
        try:
            item = service.regenerate_suggestion(suggestion_id, req.instruction)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    @router.post("/suggestions/{suggestion_id}/status")
    def mark_status(suggestion_id: str, req: MarkStatusRequest, request: Request):
        """Actualiza estado de revisión/copiado de una sugerencia."""
        ensure_auth(request)
        valid_statuses = {"draft", "reviewed", "copied"}
        if req.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid_statuses)}")
        items = service.load_suggestions()
        for item in items:
            if item["suggestion_id"] == suggestion_id:
                item["status"] = req.status
                item["updated_at"] = datetime.now().isoformat()
                service.save_suggestions(items)
                return {"ok": True, "item": item}
        raise HTTPException(status_code=404, detail=f"Suggestion not found: {suggestion_id}")

    @router.post("/suggestions/manual")
    def manual_suggestion(req: ManualSuggestionRequest, request: Request):
        """Genera una sugerencia nueva a partir de texto pegado manualmente."""
        ensure_auth(request)
        ensure_config()
        try:
            item = service.create_suggestion_from_text(
                from_text=req.from_text,
                subject=req.subject,
                body=req.body,
            )
            return {"ok": True, "item": item}
        except RuntimeError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @router.get("/settings")
    def get_settings(request: Request):
        """Devuelve configuración editable del agente de correo."""
        ensure_auth(request)
        return {"ok": True, "settings": service.get_settings()}

    @router.post("/settings")
    def update_settings(req: EmailSettingsRequest, request: Request):
        """Actualiza configuración editable del agente de correo."""
        ensure_auth(request)
        updated = service.update_settings(req.allowed_from_whitelist)
        return {"ok": True, "settings": updated}

    @router.get("/ui", response_class=HTMLResponse)
    def ui(request: Request):
        """UI ligera para revisar, ajustar y copiar propuestas de respuesta."""
        ensure_auth(request)
        return HTMLResponse(
            """
<!doctype html>
<html data-theme="dark">
<head>
  <meta charset=\"utf-8\" />
  <title>Email Agent UI</title>
  <style>
    :root {
      --bg: #0f172a;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --card-bg: #111827;
      --card-border: #334155;
      --input-bg: #0b1220;
      --input-border: #475569;
      --button-bg: #1d4ed8;
      --button-hover: #1e40af;
      --button-text: #ffffff;
    }

    :root[data-theme='light'] {
      --bg: #f8fafc;
      --text: #0f172a;
      --muted: #475569;
      --card-bg: #ffffff;
      --card-border: #cbd5e1;
      --input-bg: #ffffff;
      --input-border: #94a3b8;
      --button-bg: #2563eb;
      --button-hover: #1d4ed8;
      --button-text: #ffffff;
    }

    body {
      font-family: Arial, sans-serif;
      max-width: 1000px;
      margin: 24px auto;
      background: var(--bg);
      color: var(--text);
      transition: background 0.2s ease, color 0.2s ease;
      padding: 0 12px;
    }

    .card {
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }

    pre {
      white-space: pre-wrap;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 8px;
    }

    textarea {
      width: 100%;
      min-height: 140px;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 8px;
    }

    button {
      margin-right: 8px;
      margin-top: 8px;
      background: var(--button-bg);
      color: var(--button-text);
      border: 0;
      border-radius: 6px;
      padding: 8px 12px;
      cursor: pointer;
    }

    button:hover { background: var(--button-hover); }
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
      border-radius: 10px;
      padding: 16px;
    }
    .modal-card h3 { margin-top: 0; }
    .field {
      width: 100%;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 8px;
      margin-bottom: 8px;
    }
  </style>
</head>
<body>
  <h1>Email suggestion inbox</h1>
  <p class=\"muted\">Genera propuestas desde Gmail, notifícalas por webhook y copia/pega la respuesta final manualmente en Gmail.</p>

  <button onclick=\"toggleTheme()\" id=\"themeToggle\">Switch to light mode</button>
  <button onclick=\"checkNew()\" id=\"checkNewBtn\">Check new messages</button>
  <button onclick=\"openManualModal()\" id=\"manualBtn\">Generate from text</button>
  <button onclick=\"loadSuggestions()\">Refresh list</button>
  <p id=\"status\"></p>
  <div class=\"card\">
    <h3>Whitelist settings</h3>
    <p class=\"muted\">One sender per line (or comma-separated). Only these senders generate suggestions.</p>
    <textarea id=\"allowedWhitelist\" class=\"field\" style=\"min-height:90px\" placeholder=\"info@dextools.io\"></textarea>
    <button onclick=\"saveSettings()\" id=\"saveSettingsBtn\">Save whitelist</button>
  </div>
  <div id=\"list\"></div>

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

<script>
const currentPath = window.location.pathname.endsWith('/')
  ? window.location.pathname.slice(0, -1)
  : window.location.pathname;
const apiBase = currentPath.endsWith('/ui') ? currentPath.slice(0, -3) : currentPath;
const apiSecret = new URLSearchParams(window.location.search).get('secret') || '';
const statusEl = document.getElementById('status');
let currentSuggestionId = '';

function withSecret(path) {
  if (!apiSecret) return `${apiBase}${path}`;
  const join = path.includes('?') ? '&' : '?';
  return `${apiBase}${path}${join}secret=${encodeURIComponent(apiSecret)}`;
}

function setStatus(text) {
  statusEl.innerText = text;
}

async function checkNew() {
  const btn = document.getElementById('checkNewBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Checking new messages...';
  setStatus('Checking new messages...');
  try {
    const r = await fetch(withSecret('/check-new'), {
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
    const r = await fetch(withSecret(`/suggestions/${currentSuggestionId}/regenerate`), {
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
  const pieces = String(raw || '').replaceAll('\n', ',').split(',');
  const unique = new Set();
  for (const piece of pieces) {
    const value = piece.trim().toLowerCase();
    if (value) unique.add(value);
  }
  return Array.from(unique.values());
}

async function loadSettings() {
  try {
    const r = await fetch(withSecret('/settings'));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const items = Array.isArray(data.settings?.allowed_from_whitelist)
      ? data.settings.allowed_from_whitelist
      : [];
    document.getElementById('allowedWhitelist').value = items.join('\n');
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
  try {
    const r = await fetch(withSecret('/settings'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({allowed_from_whitelist})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const items = Array.isArray(data.settings?.allowed_from_whitelist)
      ? data.settings.allowed_from_whitelist
      : [];
    document.getElementById('allowedWhitelist').value = items.join('\n');
    setStatus(`Whitelist saved (${items.length} sender${items.length === 1 ? '' : 's'})`);
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
    const r = await fetch(withSecret('/suggestions/manual'), {
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
  await fetch(withSecret(`/suggestions/${id}/status`), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status})
  });
  await loadSuggestions();
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



function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('emailAgentTheme', theme);
  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.innerText = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
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
  suggestionModal.addEventListener('click', (event) => {
    if (event.target === suggestionModal) closeSuggestionModal();
  });
  manualModal.addEventListener('click', (event) => {
    if (event.target === manualModal) closeManualModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    closeSuggestionModal();
    closeManualModal();
  });
})();

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadSuggestions() {
  let data;
  try {
    const r = await fetch(withSecret('/suggestions'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setStatus(`Error loading suggestions: ${err}`);
    return;
  }
  const list = document.getElementById('list');
  list.innerHTML = '';
  if (!Array.isArray(data.items) || data.items.length === 0) {
    list.innerHTML = `<div class="card"><p class="muted">No suggestions yet. Use <b>Check new messages</b> or <b>Generate from text</b>.</p></div>`;
    return;
  }
  for (const item of data.items.reverse()) {
    const div = document.createElement('div');
    div.className = 'card';
    const safeId = String(item.suggestion_id || '');
    div.innerHTML = `
      <div><b>${escapeHtml(item.subject)}</b></div>
      <div class='muted'>From: ${escapeHtml(item.from)} | Status: ${escapeHtml(item.status)}</div>
      <p><b>Original</b></p>
      <pre>${escapeHtml((item.original_body || '').slice(0, 400))}</pre>
      <p><b>Suggested reply</b></p>
      <textarea id='reply-${safeId}'></textarea>
      <div>
        <button onclick="openSuggestionModal('${safeId}')">Suggest changes</button>
        <button onclick="copyText('${safeId}')">Copy</button>
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

loadSettings();
loadSuggestions();
</script>
</body>
</html>
            """.strip()
        )

    return router
