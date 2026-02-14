from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
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


def create_email_router(service: EmailAgentService) -> APIRouter:
    """Crea router HTTP y UI para revisión manual de respuestas de email."""
    router = APIRouter(prefix="/email-agent", tags=["email-agent"])

    @router.post("/check-new")
    def check_new(req: CheckNewRequest):
        """Detecta nuevos correos y genera sugerencias (sin enviar email)."""
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
    def list_suggestions(status: Optional[str] = None):
        """Devuelve sugerencias almacenadas opcionalmente filtradas por estado."""
        items = service.load_suggestions()
        if status:
            items = [item for item in items if item.get("status") == status]
        return {"ok": True, "count": len(items), "items": items}

    @router.post("/suggestions/{suggestion_id}/regenerate")
    def regenerate(suggestion_id: str, req: RegenerateRequest):
        """Regenera una sugerencia aplicando instrucciones del usuario."""
        try:
            item = service.regenerate_suggestion(suggestion_id, req.instruction)
            return {"ok": True, "item": item}
        except RuntimeError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    @router.post("/suggestions/{suggestion_id}/status")
    def mark_status(suggestion_id: str, req: MarkStatusRequest):
        """Actualiza estado de revisión/copiado de una sugerencia."""
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

    @router.get("/ui", response_class=HTMLResponse)
    def ui():
        """UI ligera para revisar, ajustar y copiar propuestas de respuesta."""
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
  </style>
</head>
<body>
  <h1>Email suggestion inbox</h1>
  <p class=\"muted\">Genera propuestas desde Gmail, notifícalas por webhook y copia/pega la respuesta final manualmente en Gmail.</p>

  <button onclick=\"toggleTheme()\" id=\"themeToggle\">Switch to light mode</button>
  <button onclick=\"checkNew()\">Check new emails</button>
  <button onclick=\"loadSuggestions()\">Refresh list</button>
  <p id=\"status\"></p>
  <div id=\"list\"></div>

<script>
async function checkNew() {
  const r = await fetch('/email-agent/check-new', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({max_emails: 5, unread_only: true, mailbox: 'INBOX'})
  });
  const data = await r.json();
  document.getElementById('status').innerText = `Created ${data.created} new suggestions`;
  await loadSuggestions();
}

async function regenerate(id) {
  const instruction = prompt('Write a change request (e.g. make it shorter, friendlier, include ETA):');
  if (!instruction) return;
  await fetch(`/email-agent/suggestions/${id}/regenerate`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({instruction})
  });
  await loadSuggestions();
}

async function markStatus(id, status) {
  await fetch(`/email-agent/suggestions/${id}/status`, {
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

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadSuggestions() {
  const r = await fetch('/email-agent/suggestions');
  const data = await r.json();
  const list = document.getElementById('list');
  list.innerHTML = '';
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
        <button onclick="regenerate('${safeId}')">Suggest changes</button>
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

loadSuggestions();
</script>
</body>
</html>
            """.strip()
        )

    return router
