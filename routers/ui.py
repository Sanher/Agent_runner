import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from routers.auth import ensure_request_authorized

logger = logging.getLogger("agent_runner.ui_router")


def _resolve_ui_version() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=1.5,
        )
        version = result.stdout.strip()
        if version:
            return version
    except Exception:  # pragma: no cover - best effort only
        pass
    return "local build"


UI_VERSION = _resolve_ui_version()


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
      --bg-app: #0a090b;
      --bg-panel: #151417;
      --bg-panel-soft: #1d1b20;
      --bg-elevated: #262229;
      --border-soft: rgba(255, 255, 255, 0.08);
      --border-strong: rgba(249, 115, 22, 0.26);
      --text-strong: #f7f1ea;
      --text-muted: #a79d95;
      --accent: #f97316;
      --accent-soft: rgba(249, 115, 22, 0.14);
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --shadow-panel: 0 24px 60px rgba(0, 0, 0, 0.42);

      --bg: var(--bg-app);
      --bg-soft: var(--bg-panel);
      --text: var(--text-strong);
      --muted: var(--text-muted);
      --card-bg: linear-gradient(180deg, rgba(24, 23, 27, 0.98) 0%, rgba(18, 18, 22, 0.98) 100%);
      --card-border: var(--border-soft);
      --input-bg: rgba(14, 14, 18, 0.94);
      --input-border: rgba(255, 255, 255, 0.1);
      --input-focus: var(--accent);
      --button-bg: linear-gradient(135deg, #fb923c 0%, #ea580c 100%);
      --button-hover: linear-gradient(135deg, #fdba74 0%, #f97316 100%);
      --button-text: #fff7ed;
      --shadow: var(--shadow-panel);
    }

    :root[data-theme='light'] {
      --bg-app: #f6f0ea;
      --bg-panel: #fffaf5;
      --bg-panel-soft: #f3e8dc;
      --bg-elevated: #ece1d5;
      --border-soft: rgba(122, 87, 57, 0.14);
      --border-strong: rgba(234, 88, 12, 0.28);
      --text-strong: #201a17;
      --text-muted: #7a6e65;
      --accent: #ea580c;
      --accent-soft: rgba(234, 88, 12, 0.12);
      --success: #15803d;
      --warning: #b45309;
      --danger: #b91c1c;

      --bg: var(--bg-app);
      --bg-soft: var(--bg-panel);
      --text: var(--text-strong);
      --muted: var(--text-muted);
      --card-bg: linear-gradient(180deg, rgba(255, 251, 247, 0.98) 0%, rgba(250, 243, 236, 0.98) 100%);
      --card-border: var(--border-soft);
      --input-bg: rgba(255, 255, 255, 0.96);
      --input-border: rgba(122, 87, 57, 0.18);
      --input-focus: var(--accent);
      --button-bg: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
      --button-hover: linear-gradient(135deg, #fb923c 0%, #f97316 100%);
      --button-text: #fff7ed;
      --shadow: 0 22px 50px rgba(109, 76, 44, 0.12);
    }

    body {
      font-family: 'Avenir Next', 'Inter', 'Segoe UI', sans-serif;
      margin: 0;
      background:
        radial-gradient(circle at top right, rgba(249, 115, 22, 0.15), transparent 34%),
        radial-gradient(circle at 20% 100%, rgba(59, 130, 246, 0.08), transparent 30%),
        var(--bg-app);
      color: var(--text);
      transition: background 0.2s ease, color 0.2s ease;
      padding: 24px;
      box-sizing: border-box;
      min-height: 100vh;
      position: relative;
    }

    body::before {
      content: '';
      position: fixed;
      inset: 0;
      background:
        radial-gradient(circle at 78% 8%, rgba(249, 115, 22, 0.16), transparent 22%),
        radial-gradient(circle at 12% 90%, rgba(37, 99, 235, 0.08), transparent 18%);
      pointer-events: none;
      z-index: 0;
    }

    .app-shell {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 22px;
      max-width: 1480px;
      margin: 0 auto;
      align-items: start;
      min-width: 0;
    }

    .sidebar {
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 26px;
      padding: 22px 18px 18px;
      position: sticky;
      top: 22px;
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      gap: 18px;
      min-width: 0;
    }

    .sidebar-brand {
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }

    .brand-mark {
      width: 52px;
      height: 52px;
      border-radius: 16px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, #fb923c 0%, #ea580c 100%);
      color: #fff7ed;
      font-size: 1.35rem;
      box-shadow: 0 14px 30px rgba(249, 115, 22, 0.28);
      flex: 0 0 auto;
    }

    .brand-copy {
      min-width: 0;
    }

    .brand-title {
      margin: 0;
      font-size: 1.85rem;
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .brand-version {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.84rem;
    }

    .sidebar-intro {
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.94rem;
    }

    .sidebar-section-label,
    .topbar-eyebrow {
      margin: 0;
      color: rgba(255, 255, 255, 0.46);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    :root[data-theme='light'] .sidebar-section-label,
    :root[data-theme='light'] .topbar-eyebrow {
      color: rgba(32, 26, 23, 0.48);
    }

    .tabs {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin: 0;
    }

    .tab-btn {
      width: 100%;
      text-align: left;
      margin: 0;
      background: transparent;
      border: 1px solid transparent;
      color: var(--text);
      padding: 0;
      border-radius: 18px;
      overflow: hidden;
      box-shadow: none;
    }

    .tab-btn:hover {
      transform: translateY(-1px);
      background: rgba(255, 255, 255, 0.02);
      border-color: rgba(255, 255, 255, 0.04);
      filter: none;
    }

    .tab-btn.active {
      background: linear-gradient(180deg, rgba(249, 115, 22, 0.18), rgba(249, 115, 22, 0.08));
      border-color: var(--border-strong);
      box-shadow:
        inset 0 0 0 1px rgba(249, 115, 22, 0.1),
        0 12px 30px rgba(0, 0, 0, 0.22);
    }

    .tab-nav {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 14px;
      padding: 14px 16px;
      min-width: 0;
    }

    .tab-icon {
      width: 40px;
      height: 40px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      font-size: 1rem;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.06);
      flex: 0 0 auto;
    }

    .tab-copy {
      display: flex;
      flex-direction: column;
      gap: 3px;
      min-width: 0;
    }

    .tab-title {
      font-size: 0.98rem;
      font-weight: 700;
      line-height: 1.2;
    }

    .tab-subtitle {
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .nav-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 38px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--card-border);
      background: rgba(255, 255, 255, 0.04);
      color: var(--muted);
      font-size: 0.72rem;
      line-height: 1;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .nav-badge.is-hidden {
      display: none;
    }

    .nav-badge[data-variant='live'] {
      color: #dcfce7;
      background: rgba(34, 197, 94, 0.16);
      border-color: rgba(34, 197, 94, 0.32);
    }

    .nav-badge[data-variant='count'] {
      color: #fff7ed;
      background: rgba(249, 115, 22, 0.18);
      border-color: rgba(249, 115, 22, 0.28);
    }

    .nav-badge[data-variant='neutral'] {
      color: var(--text);
      background: rgba(255, 255, 255, 0.05);
      border-color: rgba(255, 255, 255, 0.08);
    }

    .nav-badge[data-variant='warning'] {
      color: #fef3c7;
      background: rgba(245, 158, 11, 0.18);
      border-color: rgba(245, 158, 11, 0.3);
    }

    .nav-badge[data-variant='danger'] {
      color: #fee2e2;
      background: rgba(239, 68, 68, 0.16);
      border-color: rgba(239, 68, 68, 0.28);
    }

    .nav-badge[data-variant='success'] {
      color: #dcfce7;
      background: rgba(34, 197, 94, 0.16);
      border-color: rgba(34, 197, 94, 0.28);
    }

    .content-area {
      min-width: 0;
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .content-topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 2px 4px 8px 4px;
    }

    .topbar-copy {
      min-width: 0;
    }

    .page-title {
      margin: 8px 0 0;
      font-size: clamp(1.8rem, 3vw, 2.5rem);
      line-height: 1;
      letter-spacing: -0.05em;
    }

    .topbar-meta {
      margin: 10px 0 0;
      max-width: 720px;
    }

    .topbar-actions {
      display: flex;
      gap: 10px;
      flex: 0 0 auto;
    }

    .content-panels {
      min-width: 0;
    }

    .card {
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      border-radius: 22px;
      padding: 20px 22px;
      margin-bottom: 0;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
      min-width: 0;
      overflow-x: clip;
      position: relative;
    }

    .card::before {
      content: '';
      position: absolute;
      inset: 0;
      border-radius: inherit;
      pointer-events: none;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }

    .warm-card {
      background:
        linear-gradient(180deg, rgba(57, 32, 20, 0.55) 0%, rgba(27, 20, 18, 0.92) 100%);
      border-color: rgba(249, 115, 22, 0.18);
    }

    h1,
    h2,
    h3 {
      color: var(--text);
    }

    h3 {
      margin: 0 0 12px;
      font-size: 1.08rem;
      letter-spacing: -0.02em;
    }

    p {
      line-height: 1.6;
    }

    pre {
      white-space: pre-wrap;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 18px;
      padding: 14px;
    }

    textarea,
    input,
    select {
      width: 100%;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 14px;
      padding: 0 14px;
      box-sizing: border-box;
      transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
      font: inherit;
      min-width: 0;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }

    input,
    select {
      height: 48px;
      min-height: 48px;
    }

    textarea {
      min-height: 140px;
      padding: 13px 14px;
      resize: vertical;
    }

    select {
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
      padding-right: 38px;
    }

    textarea:focus,
    input:focus,
    select:focus {
      outline: none;
      border-color: rgba(249, 115, 22, 0.5);
      box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.16);
    }

    button {
      margin-right: 8px;
      margin-top: 8px;
      margin-bottom: 0;
      min-height: 42px;
      padding: 0 15px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      background: var(--button-bg);
      color: var(--button-text);
      border: 1px solid rgba(251, 146, 60, 0.3);
      border-radius: 14px;
      cursor: pointer;
      font-weight: 700;
      font-family: inherit;
      transition: transform 0.2s ease, filter 0.2s ease, box-shadow 0.2s ease;
      box-shadow: 0 12px 28px rgba(249, 115, 22, 0.2);
    }

    button:hover {
      background: var(--button-hover);
      transform: translateY(-1px);
      filter: brightness(1.02);
      box-shadow: 0 14px 30px rgba(249, 115, 22, 0.24);
    }

    button:active {
      transform: translateY(0);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.68;
      filter: grayscale(0.12);
      box-shadow: none;
    }

    .ghost-btn,
    details.settings-dropdown > summary {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text);
      border: 1px solid var(--input-border);
      box-shadow: none;
    }

    .ghost-btn:hover,
    details.settings-dropdown > summary:hover {
      background: rgba(255, 255, 255, 0.06);
      filter: none;
      box-shadow: none;
    }

    .icon-btn {
      width: 46px;
      min-width: 46px;
      height: 46px;
      padding: 0;
      border-radius: 14px;
      margin: 0;
      font-size: 1.08rem;
    }

    button.tab-btn {
      background: transparent;
      border: 1px solid transparent;
      box-shadow: none;
      min-height: 0;
      padding: 0;
      margin: 0;
    }

    button.tab-btn:hover {
      background: rgba(255, 255, 255, 0.02);
      border-color: rgba(255, 255, 255, 0.04);
      box-shadow: none;
    }

    button.tab-btn.active {
      background: linear-gradient(180deg, rgba(249, 115, 22, 0.18), rgba(249, 115, 22, 0.08));
      border-color: var(--border-strong);
      box-shadow:
        inset 0 0 0 1px rgba(249, 115, 22, 0.1),
        0 12px 30px rgba(0, 0, 0, 0.22);
    }

    details.settings-dropdown {
      margin-bottom: 0;
    }

    details.settings-dropdown > summary {
      list-style: none;
      cursor: pointer;
      padding: 13px 16px;
      border-radius: 16px;
      font-weight: 700;
      margin-bottom: 12px;
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

    .tab-panel {
      display: none;
      min-width: 0;
    }

    .tab-panel.active {
      display: flex;
      flex-direction: column;
      gap: 18px;
      animation: panelFade 0.18s ease;
    }

    .kv {
      margin: 0;
      line-height: 1.55;
    }

    .logs {
      white-space: pre-wrap;
      background: #0b0b0f;
      border: 1px solid rgba(249, 115, 22, 0.12);
      border-radius: 18px;
      padding: 14px;
      max-height: 280px;
      overflow: auto;
      font-family: 'SFMono-Regular', Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.6;
      color: #ddd6cf;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }

    .muted {
      color: var(--muted);
      font-size: 0.92em;
      line-height: 1.5;
    }

    #status {
      margin: 0;
      min-height: 0;
      padding: 13px 14px;
      border-radius: 16px;
      border: 1px solid var(--input-border);
      background: rgba(255, 255, 255, 0.03);
      color: var(--text);
      font-weight: 600;
      line-height: 1.45;
      opacity: 1;
      transition: opacity 0.2s ease, color 0.2s ease, border-color 0.2s ease;
    }

    #status:empty {
      display: none;
    }

    #status.status-error {
      color: #f87171;
    }

    #status.status-success {
      color: #86efac;
      text-shadow:
        0 0 8px rgba(34, 197, 94, 0.45),
        0 0 1px rgba(240, 253, 244, 0.9);
    }

    #status.status-warning {
      color: #facc15;
      text-shadow:
        0 0 8px rgba(250, 204, 21, 0.35),
        0 0 1px rgba(254, 249, 195, 0.9);
    }

    #status.status-hidden {
      opacity: 0;
    }
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
      border-radius: 24px;
      padding: 20px;
      box-sizing: border-box;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }

    .modal-card h3 { margin-top: 0; }
    .field {
      display: block;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      margin-bottom: 10px;
      box-sizing: border-box;
    }

    .email-original {
      min-height: 180px;
      max-height: 280px;
      overflow: auto;
      font-family: Menlo, Consolas, monospace;
      line-height: 1.45;
      white-space: pre-wrap;
    }

    #tabEmail {
      gap: 16px;
    }

    #tabEmail .email-toolbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      overflow: visible;
    }

    #tabEmail .email-toolbar-copy {
      min-width: 0;
    }

    #tabEmail .email-toolbar-copy h3 {
      margin-bottom: 6px;
    }

    #tabEmail .email-toolbar-copy p {
      margin: 0;
      max-width: 720px;
    }

    #tabEmail .email-toolbar-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
      flex: 0 0 auto;
    }

    #tabEmail .email-toolbar-actions button {
      margin: 0;
    }

    #tabEmail .email-settings-panel {
      margin: 0;
    }

    #tabEmail .email-settings-panel > summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 18px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02));
    }

    #tabEmail .email-settings-panel > summary::after {
      margin-left: auto;
      font-size: 0.9rem;
    }

    #tabEmail .email-settings-body {
      padding: 18px 20px 20px;
    }

    #tabEmail .email-settings-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px 16px;
    }

    #tabEmail .email-settings-field {
      min-width: 0;
    }

    #tabEmail .email-settings-field--full {
      grid-column: 1 / -1;
    }

    #tabEmail .email-settings-field .muted {
      display: block;
      margin-bottom: 6px;
    }

    #tabEmail .email-settings-field .field {
      margin-bottom: 0;
    }

    #tabEmail .email-field-note {
      margin: 8px 0 0;
    }

    #tabEmail .email-settings-save {
      margin-top: 16px;
    }

    #tabEmail .email-settings-save button {
      margin: 0;
    }

    #tabEmail .email-workbench {
      overflow: visible;
    }

    #tabEmail .email-workbench-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 18px;
    }

    #tabEmail .email-workbench-copy h3 {
      margin-bottom: 6px;
    }

    #tabEmail .email-workbench-copy p {
      margin: 0;
    }

    #tabEmail .email-workbench-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(249, 115, 22, 0.18);
      background: rgba(249, 115, 22, 0.12);
      color: #fdba74;
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      white-space: nowrap;
      flex: 0 0 auto;
    }

    #tabEmail #list {
      display: grid;
      grid-template-columns: minmax(280px, 330px) minmax(0, 1fr);
      gap: 14px 22px;
      align-items: start;
    }

    #tabEmail #list > .card {
      grid-column: 1 / -1;
    }

    #tabEmail .email-entry {
      display: contents;
    }

    #tabEmail .email-select {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }

    #tabEmail .email-summary {
      grid-column: 1;
      display: block;
      padding: 16px;
      border-radius: 20px;
      border: 1px solid var(--input-border);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0.018));
      color: var(--text);
      cursor: pointer;
      transition: border-color 0.22s ease, background 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025);
      min-width: 0;
    }

    #tabEmail .email-summary:hover {
      transform: translateY(-1px);
      border-color: rgba(249, 115, 22, 0.24);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(249, 115, 22, 0.035));
    }

    #tabEmail .email-select:focus-visible + .email-summary {
      outline: 2px solid rgba(249, 115, 22, 0.42);
      outline-offset: 2px;
    }

    #tabEmail .email-select:checked + .email-summary {
      border-color: rgba(249, 115, 22, 0.42);
      background:
        linear-gradient(180deg, rgba(249, 115, 22, 0.16), rgba(249, 115, 22, 0.06));
      box-shadow:
        inset 0 0 0 1px rgba(249, 115, 22, 0.14),
        0 18px 36px rgba(0, 0, 0, 0.22);
    }

    #tabEmail .email-summary-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
    }

    #tabEmail .email-summary-time {
      color: var(--muted);
      font-size: 0.74rem;
      white-space: nowrap;
    }

    #tabEmail .email-summary-subject {
      margin: 0 0 6px;
      font-size: 1rem;
      font-weight: 700;
      line-height: 1.3;
      color: var(--text);
      letter-spacing: -0.01em;
    }

    #tabEmail .email-summary-from {
      color: var(--muted);
      font-size: 0.84rem;
      margin: 0 0 10px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #tabEmail .email-summary-preview {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.55;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
      word-break: break-word;
    }

    #tabEmail .email-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 84px;
      padding: 6px 11px;
      border-radius: 999px;
      border: 1px solid var(--input-border);
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      line-height: 1;
      white-space: nowrap;
    }

    #tabEmail .email-badge.is-pending {
      color: #fef3c7;
      background: rgba(245, 158, 11, 0.16);
      border-color: rgba(245, 158, 11, 0.28);
    }

    #tabEmail .email-badge.is-reviewed {
      color: #dbeafe;
      background: rgba(100, 116, 139, 0.22);
      border-color: rgba(148, 163, 184, 0.28);
    }

    #tabEmail .email-badge.is-spam {
      color: #e5e7eb;
      background: rgba(55, 65, 81, 0.72);
      border-color: rgba(75, 85, 99, 0.7);
    }

    #tabEmail .email-badge.is-archive {
      color: var(--muted);
      background: transparent;
      border-color: var(--input-border);
    }

    #tabEmail .email-badge.is-sent {
      color: #dcfce7;
      background: rgba(34, 197, 94, 0.14);
      border-color: rgba(34, 197, 94, 0.26);
    }

    #tabEmail .email-badge.is-copied {
      color: #e0f2fe;
      background: rgba(56, 189, 248, 0.14);
      border-color: rgba(56, 189, 248, 0.24);
    }

    #tabEmail .email-detail-panel {
      grid-column: 2;
      grid-row: 1 / span 50;
      display: none;
      position: sticky;
      top: 0;
      align-self: start;
      padding: 22px;
      overflow: visible;
    }

    #tabEmail .email-select:checked + .email-summary + .email-detail-panel {
      display: block;
    }

    #tabEmail .email-detail-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 18px;
    }

    #tabEmail .email-detail-kicker {
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    #tabEmail .email-detail-title {
      margin: 6px 0 0;
      font-size: clamp(1.3rem, 1.8vw, 1.6rem);
      line-height: 1.1;
      letter-spacing: -0.03em;
    }

    #tabEmail .email-detail-meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    #tabEmail .email-meta-block {
      padding: 13px 14px;
      border-radius: 16px;
      border: 1px solid var(--input-border);
      background: var(--input-bg);
      min-width: 0;
    }

    #tabEmail .email-meta-label {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    #tabEmail .email-meta-value {
      display: block;
      color: var(--text);
      line-height: 1.45;
      word-break: break-word;
    }

    #tabEmail .email-detail-sections {
      display: grid;
      gap: 14px;
    }

    #tabEmail .email-panel-section,
    #tabEmail .email-compose-panel {
      border: 1px solid var(--input-border);
      border-radius: 20px;
      padding: 16px;
      background: var(--input-bg);
    }

    #tabEmail .email-ai-card {
      padding: 16px;
    }

    #tabEmail .email-section-heading-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }

    #tabEmail .email-section-heading {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    #tabEmail .email-section-note {
      color: rgba(253, 186, 116, 0.9);
      font-size: 0.84rem;
    }

    #tabEmail .email-original,
    #tabEmail .email-ai-compose {
      margin-bottom: 0;
      min-height: 190px;
      max-height: 330px;
      background: rgba(8, 8, 12, 0.86);
      border-radius: 16px;
    }

    #tabEmail .email-ai-compose {
      color: #fff7ed;
    }

    #tabEmail .email-compose-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px 14px;
    }

    #tabEmail .email-field-group {
      min-width: 0;
    }

    #tabEmail .email-field-group--wide {
      grid-column: 1 / -1;
    }

    #tabEmail .email-field-group .muted {
      display: block;
      margin-bottom: 6px;
    }

    #tabEmail .email-field-group .field {
      margin-bottom: 0;
    }

    #tabEmail .email-detail-actions {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--input-border);
    }

    #tabEmail .email-action-group {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    #tabEmail .email-action-group button {
      margin: 0;
    }

    #tabEmail .email-reviewed-section {
      border-style: dashed;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.015));
    }

    #tabEmail .email-reviewed-section p {
      margin-top: 0;
    }

    #tabEmail .email-reviewed-card {
      display: grid;
      gap: 12px;
    }

    #tabEmail .email-reviewed-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    #tabEmail .email-reviewed-title {
      margin: 0;
      font-size: 1rem;
      line-height: 1.3;
      letter-spacing: -0.01em;
    }

    #tabEmail .email-reviewed-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    #tabEmail .email-reviewed-actions button {
      margin: 0;
    }

    #tabIssue .issue-console-card {
      padding: 22px;
    }

    #tabIssue .issue-console-shell {
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(360px, 0.92fr);
      gap: 22px;
      align-items: start;
    }

    #tabIssue .issue-form-panel,
    #tabIssue .issue-draft-panel {
      min-width: 0;
      border-radius: 22px;
      padding: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.015), rgba(255, 255, 255, 0.01)),
        rgba(9, 13, 25, 0.72);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }

    #tabIssue .issue-draft-panel {
      border-color: rgba(249, 115, 22, 0.22);
      background:
        radial-gradient(circle at top right, rgba(249, 115, 22, 0.16), transparent 42%),
        linear-gradient(180deg, rgba(249, 115, 22, 0.06), rgba(255, 255, 255, 0.012)),
        rgba(17, 12, 10, 0.86);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.04),
        0 18px 44px rgba(0, 0, 0, 0.24);
    }

    #tabIssue .issue-panel-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 16px;
    }

    #tabIssue .issue-panel-copy {
      min-width: 0;
    }

    #tabIssue .issue-panel-kicker {
      margin: 0 0 6px;
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: rgba(251, 146, 60, 0.8);
    }

    #tabIssue .issue-panel-copy h3 {
      margin: 0;
      font-size: 1.35rem;
    }

    #tabIssue .issue-panel-subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.5;
    }

    #tabIssue input.field,
    #tabIssue select.field {
      height: 50px;
      min-height: 50px;
    }

    #tabIssue textarea.field {
      margin-bottom: 0;
      padding: 14px 16px;
      line-height: 1.55;
      border-radius: 16px;
    }

    #tabIssue .issue-compact-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }

    #tabIssue .issue-field-cell,
    #tabIssue .issue-field-row,
    #tabIssue .issue-input-stage,
    #tabIssue .issue-history-field {
      min-width: 0;
    }

    #tabIssue .issue-field-cell label,
    #tabIssue .issue-field-row label,
    #tabIssue .issue-input-stage label,
    #tabIssue .issue-history-field label {
      display: block;
      margin-bottom: 8px;
      font-weight: 600;
    }

    #tabIssue .issue-field-row {
      margin-bottom: 12px;
    }

    #tabIssue .issue-input-stage {
      margin: 14px 0 16px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(4, 8, 18, 0.5);
    }

    #tabIssue #issueUserInput {
      min-height: 280px;
      background: rgba(8, 12, 24, 0.9);
    }

    #tabIssue .issue-form-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-top: 14px;
    }

    #tabIssue .issue-form-actions .muted,
    #tabIssue .issue-draft-status {
      flex: 1 1 220px;
      min-width: 220px;
      margin: 0;
    }

    #tabIssue .issue-toggle-group {
      margin: 0;
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
      background: rgba(255, 255, 255, 0.12);
      transition: background 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
      box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.35);
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
      background: linear-gradient(135deg, #fb923c, #ea580c);
      border-color: rgba(249, 115, 22, 0.42);
      box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.16);
    }

    #tabIssue .issue-toggle-input:checked + .issue-toggle-track .issue-toggle-knob {
      transform: translateX(20px);
    }

    #tabIssue .issue-toggle-label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
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
      border-color: rgba(249, 115, 22, 0.36);
      background: rgba(249, 115, 22, 0.18);
      text-shadow: 0 0 8px rgba(249, 115, 22, 0.24);
    }

    #tabIssue .issue-toggle-input:checked ~ .issue-toggle-label .issue-toggle-state::before {
      content: 'ON';
    }

    #tabIssue #issueEnrichLinksRow {
      margin-bottom: 14px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid rgba(249, 115, 22, 0.16);
      background: rgba(249, 115, 22, 0.06);
    }

    #tabIssue #issueEnrichLinksRow .muted {
      margin-top: 10px;
      font-size: 0.92rem;
    }

    #tabIssue #issueGenerateBtn,
    #tabIssue #issueSubmitBtn {
      background: linear-gradient(135deg, #ff9a3d, #f97316);
      color: #fff7ed;
      border: 1px solid rgba(255, 186, 120, 0.3);
      box-shadow: 0 16px 32px rgba(249, 115, 22, 0.22);
    }

    #tabIssue #issueGenerateBtn:hover,
    #tabIssue #issueSubmitBtn:hover {
      transform: translateY(-1px);
      box-shadow: 0 18px 36px rgba(249, 115, 22, 0.3);
    }

    #tabIssue #issueClearDraftBtn,
    #tabIssue #issueToggleLogBtn,
    #tabIssue #issueHistoryCardToggleBtn,
    #tabIssue #issueListRunsBtn,
    #tabIssue #issueLoadHistoryBtn,
    #tabIssue #issueToggleHistoryBtn,
    #tabIssue #issueMarkResolvedBtn {
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: var(--text);
      box-shadow: none;
    }

    #tabIssue #issueClearDraftBtn:hover,
    #tabIssue #issueToggleLogBtn:hover,
    #tabIssue #issueHistoryCardToggleBtn:hover,
    #tabIssue #issueListRunsBtn:hover,
    #tabIssue #issueLoadHistoryBtn:hover,
    #tabIssue #issueToggleHistoryBtn:hover,
    #tabIssue #issueMarkResolvedBtn:hover {
      border-color: rgba(249, 115, 22, 0.28);
      color: #fff2e6;
      background: rgba(249, 115, 22, 0.1);
    }

    #tabIssue .issue-runtime-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      align-items: start;
      margin-top: 16px;
    }

    #tabIssue #issueDraftEditor {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(249, 115, 22, 0.16);
      background: rgba(12, 11, 17, 0.5);
    }

    #tabIssue #issueDraftTitle,
    #tabIssue #issueDraftDescription,
    #tabIssue #issueDraftSteps {
      background: rgba(8, 11, 20, 0.84);
    }

    #tabIssue #issueDraftWarningsWrap {
      margin: 16px 0 12px;
      padding: 14px;
      border-radius: 16px;
      border: 1px solid rgba(249, 115, 22, 0.15);
      background: rgba(249, 115, 22, 0.06);
    }

    #tabIssue #issueDraftSourceWarningsWrap,
    #tabIssue #issueDraftUserWarningsWrap {
      margin-top: 10px;
    }

    #tabIssue .issue-draft-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }

    #tabIssue .issue-draft-status {
      margin-top: 12px;
    }

    #tabIssue .issue-log-panel {
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 18px;
      background: rgba(5, 8, 16, 0.86);
      padding: 14px;
    }

    #tabIssue .issue-log-title {
      margin: 0 0 8px;
      font-size: 0.95rem;
      color: var(--text);
    }

    #tabIssue #issuePlaywrightLog,
    #tabIssue #issueHistoryLog,
    #tabIssue #issueDraftSourceWarnings,
    #tabIssue #issueDraftUserWarnings {
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(2, 6, 14, 0.92);
    }

    #tabIssue #issuePlaywrightLog {
      min-height: 220px;
      max-height: 320px;
    }

    #tabIssue .issue-history-card {
      padding: 22px;
    }

    #tabIssue .issue-history-card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }

    #tabIssue .issue-history-card-body {
      margin-top: 16px;
    }

    #tabIssue .issue-history-toolbar {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    #tabIssue .issue-status-pills {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    #tabIssue .issue-status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.01em;
      background: rgba(255, 255, 255, 0.04);
      color: #e2e8f0;
    }

    #tabIssue .issue-status-pill::before {
      content: '';
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: currentColor;
      opacity: 0.9;
    }

    #tabIssue .issue-status-pill--submitted {
      color: #34d399;
      background: rgba(52, 211, 153, 0.12);
      border-color: rgba(52, 211, 153, 0.22);
    }

    #tabIssue .issue-status-pill--resolved {
      color: #cbd5e1;
      background: rgba(148, 163, 184, 0.12);
      border-color: rgba(148, 163, 184, 0.22);
    }

    #tabIssue .issue-status-pill--failed {
      color: #f87171;
      background: rgba(248, 113, 113, 0.12);
      border-color: rgba(248, 113, 113, 0.22);
    }

    #tabIssue #issueRunTools {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.015), rgba(255, 255, 255, 0.008)),
        rgba(5, 9, 18, 0.66);
    }

    #tabIssue .issue-history-grid {
      display: grid;
      grid-template-columns: minmax(220px, 1.1fr) minmax(220px, 0.8fr) minmax(220px, 1fr);
      gap: 12px;
      align-items: end;
    }

    #tabIssue .issue-run-status {
      display: inline-flex;
      align-items: center;
      min-height: 50px;
      padding: 0 14px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.04);
      font-weight: 600;
      color: var(--text);
    }

    #tabIssue .issue-history-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    #tabIssue #issueRecentRunsList,
    #tabIssue #issueRunId {
      font-family: Menlo, Consolas, monospace;
    }

    #tabIssue #issueHistoryLogWrap {
      margin-top: 14px;
    }

    input.field[type="date"] {
      inline-size: 100%;
      max-inline-size: 100%;
      padding-right: 12px;
    }

    #tabWorkday {
      gap: 20px;
    }

    #tabWorkday .workday-hero-card {
      padding: 24px;
      border-color: rgba(249, 115, 22, 0.2);
      background:
        radial-gradient(circle at top right, rgba(249, 115, 22, 0.2), transparent 34%),
        linear-gradient(180deg, rgba(35, 28, 24, 0.96) 0%, rgba(18, 17, 21, 0.98) 100%);
      overflow: hidden;
    }

    #tabWorkday .workday-hero-card::after {
      content: '';
      position: absolute;
      inset: auto -8% -44% auto;
      width: 280px;
      height: 280px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(59, 130, 246, 0.14), transparent 68%);
      pointer-events: none;
      filter: blur(6px);
    }

    #tabWorkday .workday-hero-top {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }

    #tabWorkday .workday-hero-head {
      min-width: 0;
      max-width: 760px;
    }

    #tabWorkday .workday-section-kicker {
      margin: 0;
      color: rgba(255, 255, 255, 0.48);
      font-size: 0.75rem;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    :root[data-theme='light'] #tabWorkday .workday-section-kicker {
      color: rgba(32, 26, 23, 0.48);
    }

    #tabWorkday .workday-hero-title-row,
    #tabWorkday .workday-section-head,
    #tabWorkday .workday-terminal-toolbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
    }

    #tabWorkday .workday-hero-title-row {
      margin-top: 10px;
    }

    #tabWorkday .workday-hero-title-row h3,
    #tabWorkday .workday-section-head h3,
    #tabWorkday .workday-terminal-toolbar h3 {
      margin: 0;
      font-size: clamp(1.3rem, 2vw, 1.7rem);
      letter-spacing: -0.04em;
    }

    #tabWorkday .workday-section-head h3,
    #tabWorkday .workday-terminal-toolbar h3 {
      font-size: 1.12rem;
      letter-spacing: -0.02em;
    }

    #tabWorkday .workday-hero-summary {
      margin: 12px 0 0;
      max-width: 660px;
      color: var(--text);
      opacity: 0.86;
      line-height: 1.55;
    }

    #tabWorkday .workday-mini-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.04);
      color: var(--muted);
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      white-space: nowrap;
      flex: 0 0 auto;
    }

    #tabWorkday .workday-mini-badge[data-variant='live'] {
      color: #dcfce7;
      background: rgba(34, 197, 94, 0.16);
      border-color: rgba(34, 197, 94, 0.28);
      box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.06) inset;
    }

    #tabWorkday .workday-mini-badge[data-variant='warning'] {
      color: #fef3c7;
      background: rgba(245, 158, 11, 0.14);
      border-color: rgba(245, 158, 11, 0.26);
    }

    #tabWorkday .workday-mini-badge[data-variant='neutral'] {
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.08);
    }

    #tabWorkday .workday-hero-actions {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
      flex: 0 0 auto;
    }

    #tabWorkday .workday-hero-actions button,
    #tabWorkday .workday-block-actions button {
      margin: 0;
    }

    #tabWorkday #resetWorkdaySessionBtn {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text);
      border: 1px solid var(--input-border);
      box-shadow: none;
    }

    #tabWorkday #resetWorkdaySessionBtn:hover {
      background: rgba(255, 255, 255, 0.06);
      box-shadow: none;
      filter: none;
    }

    #tabWorkday #workdayRetryWrap {
      margin: 0;
    }

    #tabWorkday .workday-metric-strip {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 12px;
    }

    #tabWorkday .workday-metric-card {
      grid-column: span 3;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 18px;
      padding: 15px 16px;
      background: rgba(255, 255, 255, 0.035);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
      min-width: 0;
    }

    #tabWorkday .workday-metric-card--wide {
      grid-column: span 4;
    }

    #tabWorkday .workday-metric-label {
      display: block;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    #tabWorkday .workday-metric-value {
      min-height: 44px;
      color: var(--text);
      line-height: 1.55;
    }

    #tabWorkday #workdayStatusLine {
      font-size: 0.96rem;
    }

    #tabWorkday #workdayStatusLine b {
      color: #ffd8b4;
      font-weight: 800;
    }

    #tabWorkday #workdayTimingLine {
      color: var(--text);
      opacity: 0.9;
    }

    #tabWorkday #workdayExpected {
      color: var(--text);
      opacity: 0.86;
    }

    #tabWorkday #workdaySettingsStatus {
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
    }

    #tabWorkday .workday-window-stack {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-height: 44px;
      justify-content: center;
    }

    #tabWorkday .workday-window-time {
      font-size: 1.08rem;
      letter-spacing: -0.02em;
    }

    #tabWorkday .workday-dual-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 18px;
      align-items: start;
    }

    #tabWorkday .workday-click-stream {
      display: grid;
      gap: 10px;
    }

    #tabWorkday #workdayClicks .kv {
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.03);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025);
    }

    #tabWorkday .workday-block-copy {
      margin: 12px 0 16px;
      max-width: 52ch;
    }

    #tabWorkday .workday-date-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-items: end;
    }

    #tabWorkday .workday-date-field {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
    }

    #tabWorkday .workday-date-field .field {
      margin-bottom: 0;
    }

    #tabWorkday .workday-block-actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 14px;
    }

    #tabWorkday .workday-terminal-card {
      padding: 20px 22px 22px;
    }

    #tabWorkday .workday-terminal-toolbar {
      align-items: center;
      margin-bottom: 14px;
    }

    #tabWorkday .workday-terminal-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    #tabWorkday .workday-terminal-hint {
      color: var(--muted);
      font-size: 0.82rem;
    }

    #tabWorkday #workdayEvents {
      background:
        linear-gradient(180deg, rgba(9, 10, 14, 0.98) 0%, rgba(6, 7, 10, 1) 100%);
      border-color: rgba(249, 115, 22, 0.14);
      border-radius: 20px;
      padding: 16px 18px;
      min-height: 280px;
      max-height: 420px;
      font-size: 11.5px;
      line-height: 1.72;
      color: #e7ded6;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.04),
        inset 0 0 0 1px rgba(255, 255, 255, 0.02),
        0 12px 32px rgba(0, 0, 0, 0.22);
    }

    #tabAnswers {
      gap: 16px;
    }

    #tabAnswers #answersList {
      display: block;
      min-width: 0;
    }

    #tabAnswers .answers-panel-shell {
      padding: 18px;
      background:
        radial-gradient(circle at top right, rgba(249, 115, 22, 0.13), transparent 34%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.015), rgba(255, 255, 255, 0));
    }

    #tabAnswers .answers-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 16px;
    }

    #tabAnswers .answers-toolbar-copy {
      min-width: 0;
    }

    #tabAnswers .answers-toolbar-copy h3 {
      margin: 0 0 4px;
    }

    #tabAnswers .answers-toolbar-copy .muted {
      margin: 0;
    }

    #tabAnswers .answers-toolbar-kicker {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      color: #fdba74;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    #tabAnswers .answers-toolbar-kicker::before {
      content: '';
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: linear-gradient(180deg, #fb923c, #f97316);
      box-shadow: 0 0 12px rgba(249, 115, 22, 0.42);
    }

    #tabAnswers .answers-toolbar-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
    }

    #tabAnswers .answers-inbox {
      display: grid;
      grid-template-columns: minmax(280px, 0.84fr) minmax(0, 1.45fr);
      gap: 18px;
      align-items: start;
      min-width: 0;
    }

    #tabAnswers .answers-sidebar-summary {
      grid-column: 1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(249, 115, 22, 0.14);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.022), rgba(255, 255, 255, 0.01));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }

    #tabAnswers .answers-sidebar-summary strong {
      display: block;
      font-size: 1.05rem;
      color: var(--text);
    }

    #tabAnswers .answers-sidebar-summary span {
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    #tabAnswers .answers-sidebar-count {
      min-width: 48px;
      height: 48px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 16px;
      border: 1px solid rgba(249, 115, 22, 0.2);
      background: rgba(249, 115, 22, 0.14);
      color: #fed7aa;
      font-weight: 800;
      font-size: 1.05rem;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    }

    #tabAnswers .answers-chat-toggle {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }

    #tabAnswers .answers-conversation-item {
      grid-column: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
      padding: 14px 15px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.018);
      cursor: pointer;
      transition:
        border-color 0.2s ease,
        background 0.2s ease,
        transform 0.2s ease,
        box-shadow 0.2s ease;
    }

    #tabAnswers .answers-conversation-item:hover {
      border-color: rgba(249, 115, 22, 0.18);
      background: rgba(255, 255, 255, 0.03);
      transform: translateY(-1px);
    }

    #tabAnswers .answers-chat-toggle:checked + .answers-conversation-item {
      border-color: rgba(249, 115, 22, 0.35);
      background:
        linear-gradient(180deg, rgba(249, 115, 22, 0.14), rgba(249, 115, 22, 0.05)),
        rgba(255, 255, 255, 0.028);
      box-shadow:
        inset 0 0 0 1px rgba(249, 115, 22, 0.12),
        0 12px 26px rgba(0, 0, 0, 0.2);
    }

    #tabAnswers .answers-conversation-top,
    #tabAnswers .answers-detail-head,
    #tabAnswers .answers-suggestion-head,
    #tabAnswers .answers-composer-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }

    #tabAnswers .answers-conversation-name,
    #tabAnswers .answers-chat-title {
      margin: 0;
      font-size: 1rem;
      line-height: 1.2;
      color: var(--text);
      font-weight: 700;
    }

    #tabAnswers .answers-conversation-meta,
    #tabAnswers .answers-chat-submeta {
      margin: 0;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.4;
    }

    #tabAnswers .answers-detail-chips {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    #tabAnswers .answers-status-chip,
    #tabAnswers .answers-channel-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
      white-space: nowrap;
    }

    #tabAnswers .answers-channel-chip {
      color: #fdba74;
      border-color: rgba(249, 115, 22, 0.18);
      background: rgba(249, 115, 22, 0.1);
    }

    #tabAnswers .answers-status-chip[data-status="pending"] {
      color: #fde68a;
      border-color: rgba(250, 204, 21, 0.24);
      background: rgba(250, 204, 21, 0.12);
    }

    #tabAnswers .answers-status-chip[data-status="draft"] {
      color: #fdba74;
      border-color: rgba(249, 115, 22, 0.24);
      background: rgba(249, 115, 22, 0.12);
    }

    #tabAnswers .answers-status-chip[data-status="reviewed"] {
      color: #cbd5e1;
      border-color: rgba(148, 163, 184, 0.18);
      background: rgba(100, 116, 139, 0.14);
    }

    #tabAnswers .answers-status-chip[data-status="sent"] {
      color: #86efac;
      border-color: rgba(34, 197, 94, 0.2);
      background: rgba(34, 197, 94, 0.12);
    }

    #tabAnswers .answers-status-chip[data-status="spam"] {
      color: #fecaca;
      border-color: rgba(248, 113, 113, 0.2);
      background: rgba(127, 29, 29, 0.22);
    }

    #tabAnswers .answers-conversation-preview {
      margin: 0;
      color: #d8d2c8;
      font-size: 0.9rem;
      line-height: 1.45;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      min-height: calc(1.45em * 2);
    }

    #tabAnswers .answers-conversation-foot {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 0.78rem;
    }

    #tabAnswers .answers-conversation-count {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.05);
      color: #d5c7b6;
    }

    #tabAnswers .answers-chat-panel {
      grid-column: 2;
      grid-row: 1 / span 50;
      display: none;
      grid-template-rows: auto minmax(0, 1fr) auto;
      gap: 14px;
      min-height: 720px;
      border-radius: 24px;
      border: 1px solid rgba(249, 115, 22, 0.16);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.028), rgba(255, 255, 255, 0.012)),
        rgba(11, 11, 15, 0.78);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.025),
        0 18px 42px rgba(0, 0, 0, 0.22);
      overflow: hidden;
    }

    #tabAnswers .answers-chat-toggle:checked + .answers-conversation-item + .answers-chat-panel {
      display: grid;
    }

    #tabAnswers .answers-detail-header,
    #tabAnswers .answers-detail-body,
    #tabAnswers .answers-composer {
      padding: 18px 20px;
    }

    #tabAnswers .answers-detail-header {
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.01));
    }

    #tabAnswers .answers-detail-body {
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      gap: 14px;
      min-height: 0;
    }

    #tabAnswers .answers-thread {
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    #tabAnswers .answers-empty-state {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
      gap: 10px;
      min-height: 420px;
      padding: 32px;
      color: var(--muted);
      border: 1px dashed rgba(249, 115, 22, 0.18);
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.018);
    }

    #tabAnswers .answers-empty-state h3 {
      margin: 0;
    }

    #tabAnswers .answers-bubble {
      max-width: min(720px, 92%);
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.03);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }

    #tabAnswers .answers-bubble-user {
      align-self: flex-start;
      background: linear-gradient(180deg, rgba(42, 45, 56, 0.92), rgba(22, 24, 31, 0.92));
      border-color: rgba(148, 163, 184, 0.12);
      color: #f5f2ec;
    }

    #tabAnswers .answers-bubble-agent {
      align-self: flex-end;
      background: linear-gradient(180deg, rgba(249, 115, 22, 0.24), rgba(194, 65, 12, 0.16));
      border-color: rgba(249, 115, 22, 0.24);
      color: #fff7ed;
    }

    #tabAnswers .answers-bubble-meta {
      margin: 0 0 8px;
      font-size: 0.75rem;
      color: rgba(226, 220, 211, 0.72);
      letter-spacing: 0.02em;
    }

    #tabAnswers .answers-bubble-text {
      margin: 0;
      font-size: 0.95rem;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }

    #tabAnswers .answers-suggestion-card {
      border: 1px solid rgba(249, 115, 22, 0.18);
      border-radius: 22px;
      background:
        linear-gradient(180deg, rgba(249, 115, 22, 0.14), rgba(249, 115, 22, 0.05)),
        rgba(255, 255, 255, 0.018);
      padding: 16px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    }

    #tabAnswers .answers-suggestion-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }

    #tabAnswers .answers-suggestion-copy,
    #tabAnswers .answers-composer-copy {
      min-width: 0;
    }

    #tabAnswers .answers-suggestion-copy h4,
    #tabAnswers .answers-composer-copy h4 {
      margin: 0 0 4px;
    }

    #tabAnswers .answers-suggestion-copy .muted,
    #tabAnswers .answers-composer-copy .muted {
      margin: 0;
    }

    #tabAnswers .answers-suggestion-card textarea,
    #tabAnswers .answers-composer textarea {
      margin-top: 12px;
      margin-bottom: 0;
      min-height: 148px;
      resize: vertical;
    }

    #tabAnswers .answers-composer {
      border-top: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(9, 9, 13, 0.82);
      backdrop-filter: blur(12px);
      position: sticky;
      bottom: 0;
    }

    #tabAnswers .answers-composer textarea {
      min-height: 132px;
      max-height: 280px;
    }

    #tabAnswers .answers-composer-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-top: 12px;
    }

    #tabAnswers .answers-composer-actions .muted {
      margin: 0;
    }

    #tabAnswers .answers-primary-action {
      box-shadow: 0 12px 24px rgba(249, 115, 22, 0.18);
    }

    #tabAnswers .answers-archived-section {
      border-style: solid;
      border-color: rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.018);
    }

    .answers-messages {
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 16px;
      background: rgba(7, 7, 11, 0.62);
      padding: 12px;
      max-height: 240px;
      overflow: auto;
      margin-bottom: 10px;
    }

    .answers-msg {
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      padding: 10px 0;
    }

    .answers-msg:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    #list,
    #reviewedList,
    #answersArchivedList {
      display: grid;
      gap: 14px;
    }

    @keyframes panelFade {
      from {
        opacity: 0;
        transform: translateY(4px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @media (max-width: 1180px) {
      .app-shell {
        grid-template-columns: 272px minmax(0, 1fr);
      }

      .tab-subtitle {
        display: none;
      }

      #tabEmail #list {
        grid-template-columns: minmax(250px, 290px) minmax(0, 1fr);
      }
    }

    @media (max-width: 980px) {
      .app-shell { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        padding: 18px 16px;
      }
      body { padding: 14px; }
      .card { padding: 18px 16px; }
      #tabIssue .issue-console-shell { grid-template-columns: 1fr; }
      #tabIssue .issue-compact-grid { grid-template-columns: 1fr 1fr; }
      #tabIssue .issue-history-grid { grid-template-columns: 1fr 1fr; }
      #tabIssue .issue-runtime-grid { grid-template-columns: 1fr; }
      .content-topbar {
        flex-direction: column;
        align-items: stretch;
      }
      .topbar-actions {
        justify-content: flex-end;
      }
      #tabEmail .email-toolbar,
      #tabEmail .email-workbench-head {
        flex-direction: column;
        align-items: stretch;
      }
      #tabEmail .email-toolbar-actions {
        justify-content: flex-start;
      }
      #tabEmail #list,
      #tabEmail .email-detail-meta,
      #tabEmail .email-compose-grid,
      #tabEmail .email-settings-grid {
        grid-template-columns: 1fr;
      }
      #tabEmail .email-summary,
      #tabEmail .email-detail-panel {
        grid-column: 1;
      }
      #tabEmail .email-detail-panel {
        grid-row: auto;
        position: static;
      }
      #tabAnswers .answers-toolbar,
      #tabAnswers .answers-composer-actions {
        flex-direction: column;
        align-items: stretch;
      }
      #tabAnswers .answers-toolbar-actions {
        justify-content: stretch;
      }
      #tabAnswers .answers-inbox {
        grid-template-columns: 1fr;
      }
      #tabAnswers .answers-chat-panel {
        grid-column: 1;
        grid-row: auto;
        min-height: 0;
      }
      #tabWorkday .workday-hero-top,
      #tabWorkday .workday-section-head,
      #tabWorkday .workday-terminal-toolbar {
        flex-direction: column;
        align-items: stretch;
      }
      #tabWorkday .workday-hero-actions,
      #tabWorkday .workday-terminal-meta,
      #tabWorkday .workday-block-actions {
        justify-content: flex-start;
      }
      #tabWorkday .workday-metric-card {
        grid-column: span 6;
      }
      #tabWorkday .workday-metric-card--wide {
        grid-column: span 12;
      }
      #tabWorkday .workday-dual-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      .brand-title {
        font-size: 1.65rem;
      }

      .page-title {
        font-size: 1.62rem;
      }

      .tab-nav {
        grid-template-columns: auto minmax(0, 1fr);
      }

      .nav-badge {
        grid-column: 2;
        justify-self: start;
      }
      #tabIssue .issue-compact-grid,
      #tabIssue .issue-history-grid {
        grid-template-columns: 1fr;
      }
      #tabIssue .issue-panel-head,
      #tabIssue .issue-history-card-head {
        flex-direction: column;
        align-items: stretch;
      }
      #tabEmail .email-summary,
      #tabEmail .email-detail-panel,
      #tabEmail .email-settings-body {
        padding: 16px;
      }
      #tabEmail .email-detail-actions {
        flex-direction: column;
        align-items: stretch;
      }
      #tabEmail .email-action-group {
        width: 100%;
      }
      #tabWorkday .workday-hero-card,
      #tabWorkday .workday-terminal-card {
        padding: 18px 16px;
      }
      #tabWorkday .workday-metric-strip {
        grid-template-columns: 1fr;
      }
      #tabWorkday .workday-metric-card,
      #tabWorkday .workday-metric-card--wide {
        grid-column: auto;
      }
      #tabWorkday .workday-date-grid {
        grid-template-columns: 1fr;
      }
      #tabWorkday .workday-hero-actions {
        width: 100%;
      }
      #tabWorkday .workday-hero-actions button,
      #tabWorkday #workdayRetryWrap,
      #tabWorkday #workdayRetryWrap button,
      #tabWorkday .workday-block-actions button {
        width: 100%;
      }
      #tabAnswers .answers-panel-shell,
      #tabAnswers .answers-detail-header,
      #tabAnswers .answers-detail-body,
      #tabAnswers .answers-composer {
        padding-left: 16px;
        padding-right: 16px;
      }
      #tabAnswers .answers-bubble {
        max-width: 100%;
      }
    }
</style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-mark">⚡</div>
        <div class="brand-copy">
          <h1 class="brand-title">Agent Runner</h1>
          <p class="brand-version">__UI_VERSION__</p>
        </div>
      </div>
      <p class="sidebar-intro">Monitor and manage web, email, issue and answers agents from one operational workspace.</p>
      <p class="sidebar-section-label">Agents</p>
      <div class="tabs">
        <button id="tabWorkdayBtn" class="tab-btn active" onclick="showTab('workday')">
          <span class="tab-nav">
            <span class="tab-icon">🌐</span>
            <span class="tab-copy">
              <span class="tab-title">Web Interaction</span>
              <span class="tab-subtitle">Scheduler and browser runner</span>
            </span>
            <span id="tabWorkdayBadge" class="nav-badge" data-variant="neutral">Ready</span>
          </span>
        </button>
        <button id="tabEmailBtn" class="tab-btn" onclick="showTab('email')">
          <span class="tab-nav">
            <span class="tab-icon">✉</span>
            <span class="tab-copy">
              <span class="tab-title">Email Agent</span>
              <span class="tab-subtitle">Inbox triage and reply drafting</span>
            </span>
            <span id="tabEmailBadge" class="nav-badge is-hidden" data-variant="count"></span>
          </span>
        </button>
        <button id="tabIssueBtn" class="tab-btn" onclick="showTab('issue')">
          <span class="tab-nav">
            <span class="tab-icon">⚡</span>
            <span class="tab-copy">
              <span class="tab-title">Issue Agent</span>
              <span class="tab-subtitle">Drafting, warnings and Playwright runs</span>
            </span>
            <span id="tabIssueBadge" class="nav-badge" data-variant="neutral">Ready</span>
          </span>
        </button>
        <button id="tabAnswersBtn" class="tab-btn" onclick="showTab('answers')">
          <span class="tab-nav">
            <span class="tab-icon">💬</span>
            <span class="tab-copy">
              <span class="tab-title">Answers Agent</span>
              <span class="tab-subtitle">Support chats and suggested replies</span>
            </span>
            <span id="tabAnswersBadge" class="nav-badge is-hidden" data-variant="count"></span>
          </span>
        </button>
      </div>
      <p id="status" role="status" aria-live="polite"></p>
    </aside>

    <main class="content-area">
      <div class="content-topbar">
        <div class="topbar-copy">
          <p class="topbar-eyebrow">Operations Console</p>
          <h2 id="activeTabTitle" class="page-title">Web Interaction Agent</h2>
          <p id="activeTabMeta" class="muted topbar-meta">Scheduler, click history and runtime logs.</p>
        </div>
        <div class="topbar-actions">
          <button onclick="refreshActivePanel()" id="refreshActivePanelBtn" class="icon-btn ghost-btn" aria-label="Refresh current panel" title="Refresh current panel">↻</button>
          <button onclick="toggleTheme()" id="themeToggle" class="icon-btn ghost-btn" aria-label="Toggle theme" title="Toggle theme">🌙</button>
        </div>
      </div>
      <div class="content-panels">
  <section id=\"tabWorkday\" class=\"tab-panel active\">
    <div class=\"card workday-hero-card\">
      <div class=\"workday-hero-top\">
        <div class=\"workday-hero-head\">
          <p class=\"workday-section-kicker\">Operational overview</p>
          <div class=\"workday-hero-title-row\">
            <h3>Workday control deck</h3>
            <span class=\"workday-mini-badge\" data-variant=\"live\">Live sync</span>
          </div>
          <p class=\"workday-hero-summary\">Read the current status, action window, scheduling signals and recovery path in one focused control surface.</p>
        </div>
        <div class=\"workday-hero-actions\">
          <button onclick=\"resetWorkdaySession()\" id=\"resetWorkdaySessionBtn\">Reset session</button>
          <div id=\"workdayRetryWrap\" style=\"display:none;\">
            <button onclick=\"retryFailedAction()\" id=\"retryFailedBtn\">Retry failed action now</button>
          </div>
        </div>
      </div>
      <div class=\"workday-metric-strip\">
        <div class=\"workday-metric-card workday-metric-card--wide\">
          <span class=\"workday-metric-label\">Current state</span>
          <div id=\"workdayStatusLine\" class=\"workday-metric-value kv\">Loading status...</div>
        </div>
        <div class=\"workday-metric-card\">
          <span class=\"workday-metric-label\">Live timer</span>
          <div id=\"workdayTimingLine\" class=\"workday-metric-value muted\"></div>
        </div>
        <div class=\"workday-metric-card\">
          <span class=\"workday-metric-label\">Operating window</span>
          <div class=\"workday-window-stack\">
            <strong class=\"workday-window-time\">06:57 - 09:30</strong>
            <span class=\"muted\">Automatic start window</span>
          </div>
        </div>
        <div class=\"workday-metric-card\">
          <span class=\"workday-metric-label\">Planned schedule</span>
          <div id=\"workdayExpected\" class=\"workday-metric-value muted\"></div>
        </div>
        <div class=\"workday-metric-card\">
          <span class=\"workday-metric-label\">Blocked period</span>
          <div id=\"workdaySettingsStatus\" class=\"workday-metric-value muted\">Loading blocked range...</div>
        </div>
      </div>
    </div>
    <div class=\"workday-dual-grid\">
      <div class=\"card\">
        <div class=\"workday-section-head\">
          <div>
            <p class=\"workday-section-kicker\">Today</p>
            <h3>Click history</h3>
          </div>
          <span class=\"workday-mini-badge\" data-variant=\"neutral\">Timeline</span>
        </div>
        <div id=\"workdayClicks\" class=\"muted workday-click-stream\">Loading history...</div>
      </div>
      <div class=\"card\">
        <div class=\"workday-section-head\">
          <div>
            <p class=\"workday-section-kicker\">Scheduler policy</p>
            <h3>Blocked days</h3>
          </div>
          <span class=\"workday-mini-badge\" data-variant=\"warning\">Auto-start guard</span>
        </div>
        <p class=\"muted workday-block-copy\">If today is inside this range, the scheduler will not start requests automatically.</p>
        <div class=\"workday-date-grid\">
          <label class=\"workday-date-field\">
            <span class=\"muted\">Start date</span>
            <input id=\"workdayBlockedStartDate\" type=\"date\" class=\"field\" />
          </label>
          <label class=\"workday-date-field\">
            <span class=\"muted\">End date</span>
            <input id=\"workdayBlockedEndDate\" type=\"date\" class=\"field\" />
          </label>
        </div>
        <div class=\"workday-block-actions\">
          <button onclick=\"saveWorkdaySettings()\" id=\"workdaySaveSettingsBtn\">Save blocked dates</button>
        </div>
      </div>
    </div>
    <div class=\"card workday-terminal-card\">
      <div class=\"workday-terminal-toolbar\">
        <div>
          <p class=\"workday-section-kicker\">Telemetry</p>
          <h3>Runtime logs</h3>
        </div>
        <div class=\"workday-terminal-meta\">
          <span class=\"workday-mini-badge\" data-variant=\"neutral\">Real time</span>
          <span class=\"workday-terminal-hint\">Latest 120 events</span>
        </div>
      </div>
      <div id=\"workdayEvents\" class=\"logs\">Loading events...</div>
    </div>
  </section>

  <section id=\"tabEmail\" class=\"tab-panel\">
    <div class=\"card email-toolbar\">
      <div class=\"email-toolbar-copy\">
        <h3>Email workbench</h3>
        <p class=\"muted\">Triage incoming messages, review AI drafts and send polished replies from a support-style inbox layout.</p>
      </div>
      <div class=\"email-toolbar-actions\">
        <button onclick=\"checkNew()\" id=\"checkNewBtn\">Check new messages</button>
        <button onclick=\"openManualModal()\" id=\"manualBtn\" class=\"ghost-btn\">Generate from text</button>
        <button onclick=\"loadSuggestions()\" class=\"ghost-btn\">Refresh list</button>
        <button id=\"emailReviewedToggleBtn\" onclick=\"toggleReviewedSuggestions()\" class=\"ghost-btn\">View reviewed</button>
      </div>
    </div>

    <details id=\"emailSettingsDetails\" class=\"settings-dropdown email-settings-panel\" open>
      <summary id=\"emailSettingsSummary\">Email settings</summary>
      <div class=\"card email-settings-body\">
        <div class=\"email-settings-grid\">
          <div class=\"email-settings-field\">
            <label class=\"muted\">From (fixed)</label>
            <input id=\"defaultFromEmail\" class=\"field\" readonly />
          </div>
          <div class=\"email-settings-field\">
            <label class=\"muted\">Default CC (optional)</label>
            <input id=\"defaultCcEmail\" class=\"field\" placeholder=\"cc1@example.com, cc2@example.com\" />
          </div>
          <div class=\"email-settings-field\">
            <label class=\"muted\">Signature assets dir</label>
            <input id=\"signatureAssetsDir\" class=\"field\" placeholder=\"/config/media/signature\" />
          </div>
          <div class=\"email-settings-field email-settings-field--full\">
            <label class=\"muted\">Signature</label>
            <textarea id=\"emailSignature\" class=\"field\" style=\"min-height:90px\" placeholder=\"Best regards,\"></textarea>
            <p class=\"muted email-field-note\">Available placeholders: {{logo}}, {{linkedin}}, {{tiktok}}, {{instagram}}, {{twitter}}, {{youtube}}, {{telegram}}</p>
          </div>
          <div class=\"email-settings-field email-settings-field--full\">
            <label class=\"muted\">Whitelist</label>
            <p class=\"muted email-field-note\">One sender per line or comma-separated. Only these senders generate suggestions.</p>
            <textarea id=\"allowedWhitelist\" class=\"field\" style=\"min-height:90px\" placeholder=\"alerts@example.com\"></textarea>
          </div>
        </div>
        <div class=\"email-settings-save\">
          <button onclick=\"saveSettings()\" id=\"saveSettingsBtn\">Save email settings</button>
        </div>
      </div>
    </details>

    <div class=\"card email-workbench\">
      <div class=\"email-workbench-head\">
        <div class=\"email-workbench-copy\">
          <h3>Suggestion queue</h3>
          <p class=\"muted\">Use the left inbox rail to switch between messages. The selected draft stays visible on the right for review and sending.</p>
        </div>
        <span class=\"email-workbench-pill\">Active queue</span>
      </div>
      <div id=\"list\"></div>
    </div>

    <div id=\"emailReviewedSection\" class=\"card email-reviewed-section\" style=\"display:none;\">
      <h3>Reviewed emails</h3>
      <p class=\"muted\">Reviewed suggestions stay out of the active queue until unarchived again.</p>
      <div id=\"reviewedList\"></div>
    </div>
  </section>

  <section id=\"tabIssue\" class=\"tab-panel\">
    <div class=\"card issue-console-card\">
      <div class=\"issue-console-shell\">
        <div class=\"issue-form-panel\">
          <div class=\"issue-panel-head\">
            <div class=\"issue-panel-copy\">
              <p class=\"issue-panel-kicker\">Drafting console</p>
              <h3>Generate issue draft</h3>
              <p class=\"issue-panel-subtitle\">Configure the target, define the briefing and keep the execution mode visible from the start.</p>
            </div>
            <div class=\"issue-toggle-group\">
              <label class=\"issue-toggle\" for=\"issueAddAsComment\">
                <input type=\"checkbox\" id=\"issueAddAsComment\" class=\"issue-toggle-input\" onchange=\"toggleIssueMode()\" />
                <span class=\"issue-toggle-track\" aria-hidden=\"true\"><span class=\"issue-toggle-knob\"></span></span>
                <span class=\"issue-toggle-label\">Add as comment <span class=\"issue-toggle-state\"></span></span>
              </label>
            </div>
          </div>

          <div class=\"issue-compact-grid\">
            <div id=\"issueIssueTypeRow\" class=\"issue-field-cell\">
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
            <div id=\"issueRepoRow\" class=\"issue-field-cell\">
              <label class=\"muted\">Repository</label>
              <select id=\"issueRepo\" class=\"field\">
                <option value=\"backend\">backend</option>
                <option value=\"frontend\">frontend</option>
                <option value=\"management\">management</option>
              </select>
            </div>
            <div id=\"issueUnitRow\" class=\"issue-field-cell\">
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
          </div>

          <div id=\"issueCommentNumberRow\" class=\"issue-field-row\">
            <label class=\"muted\">Issue number to reply to</label>
            <input id=\"issueCommentNumber\" class=\"field\" placeholder=\"e.g. 12345\">
          </div>

          <div id=\"issueEnrichLinksRow\" style=\"display:none;\">
            <label class=\"issue-toggle\" for=\"issueEnrichLinks\">
              <input type=\"checkbox\" id=\"issueEnrichLinks\" class=\"issue-toggle-input\" />
              <span class=\"issue-toggle-track\" aria-hidden=\"true\"><span class=\"issue-toggle-knob\"></span></span>
              <span id=\"issueEnrichLinksLabel\" class=\"issue-toggle-label\">Enrich from detected links</span>
            </label>
            <div class=\"muted\">Uses detected external links to complete the new-feature template when the information can be verified.</div>
          </div>

          <div id=\"issueUserInputRow\" class=\"issue-input-stage\">
            <label class=\"muted\">Issue briefing</label>
            <textarea id=\"issueUserInput\" class=\"field\" style=\"min-height:130px\" placeholder=\"Information\"></textarea>
          </div>

          <div class=\"issue-form-actions\">
            <button onclick=\"generateIssueDraft()\" id=\"issueGenerateBtn\">Generate draft</button>
            <div id=\"issueGenerateStatus\" class=\"muted\"></div>
          </div>
        </div>

        <div class=\"issue-draft-panel\">
          <div class=\"issue-panel-head\">
            <div class=\"issue-panel-copy\">
              <p class=\"issue-panel-kicker\">Generated draft</p>
              <h3>Review, adjust and execute</h3>
              <p class=\"issue-panel-subtitle\">Warnings, editable fields and Playwright execution stay grouped in a single warm workspace.</p>
            </div>
          </div>

          <div id=\"issueDraftRuntimeGrid\" class=\"issue-runtime-grid\" style=\"display:none;\">
            <div id=\"issueDraftEditor\" style=\"display:none;\">
              <div id=\"issueDraftTitleRow\" class=\"issue-field-row\">
                <label class=\"muted\">Draft title (editable)</label>
                <input id=\"issueDraftTitle\" class=\"field\" placeholder=\"Draft title\" />
              </div>
              <div id=\"issueDraftDescriptionRow\" class=\"issue-field-row\">
                <label id=\"issueDraftDescriptionLabel\" class=\"muted\">Draft description (editable)</label>
                <textarea id=\"issueDraftDescription\" class=\"field\" style=\"min-height:120px\" placeholder=\"Draft description\"></textarea>
              </div>
              <div id=\"issueDraftStepsRow\" class=\"issue-field-row\" style=\"display:none;\">
                <label class=\"muted\">Draft steps to reproduce (editable, bug only)</label>
                <textarea id=\"issueDraftSteps\" class=\"field\" style=\"min-height:110px\" placeholder=\"1. Go to ...&#10;2. Click ...&#10;3. See ...\"></textarea>
              </div>
              <div id=\"issueDraftWarningsWrap\" style=\"display:none;\">
                <label class=\"muted\">Draft warnings</label>
                <div id=\"issueDraftSourceWarningsWrap\" style=\"display:none; margin-bottom:8px;\">
                  <div class=\"muted\">Warnings from provided links</div>
                  <div id=\"issueDraftSourceWarnings\" class=\"logs\">No source warnings.</div>
                </div>
                <div id=\"issueDraftUserWarningsWrap\" style=\"display:none;\">
                  <div class=\"muted\">Warnings from missing user input</div>
                  <div id=\"issueDraftUserWarnings\" class=\"logs\">No user warnings.</div>
                </div>
              </div>
              <div class=\"issue-draft-actions\">
                <button onclick=\"submitIssueDraft()\" id=\"issueSubmitBtn\">Run in Playwright</button>
                <button onclick=\"clearIssueDraft()\" id=\"issueClearDraftBtn\">Clear suggestion (mark as done)</button>
                <button onclick=\"toggleIssuePlaywrightLog()\" id=\"issueToggleLogBtn\" style=\"display:none;\">Show Playwright log</button>
              </div>
              <div id=\"issueSubmitStatus\" class=\"muted issue-draft-status\"></div>
            </div>
            <div id=\"issuePlaywrightLogWrap\" class=\"issue-log-panel\" style=\"display:none;\">
              <h4 class=\"issue-log-title\">Playwright execution log</h4>
              <div id=\"issuePlaywrightLog\" class=\"logs\">No execution logs yet.</div>
            </div>
          </div>
          <pre id=\"issueGeneratedJson\" style=\"display:none;\">{}</pre>
        </div>
      </div>
    </div>

    <div class=\"card issue-history-card\">
      <div class=\"issue-history-card-head\">
        <div class=\"issue-panel-copy\">
          <p class=\"issue-panel-kicker\">Run history</p>
          <h3>Historical runs & execution log</h3>
          <p class=\"issue-panel-subtitle\">Load previous execution traces by run id, inspect the historical log and close the review loop on older runs.</p>
        </div>
        <div class=\"issue-history-toolbar\">
          <div class=\"issue-status-pills\" aria-hidden=\"true\">
            <span class=\"issue-status-pill issue-status-pill--submitted\">Submitted</span>
            <span class=\"issue-status-pill issue-status-pill--resolved\">Resolved</span>
            <span class=\"issue-status-pill issue-status-pill--failed\">Failed</span>
          </div>
          <button onclick=\"toggleIssueHistoryCard()\" id=\"issueHistoryCardToggleBtn\">Show run history</button>
        </div>
      </div>

      <div id=\"issueHistoryCardBody\" class=\"issue-history-card-body\" style=\"display:none; margin-top:12px;\">
        <div id=\"issueRunTools\">
          <div class=\"issue-history-grid\">
            <div class=\"issue-history-field\">
              <label class=\"muted\">Run ID / historical log</label>
              <input id=\"issueRunId\" class=\"field\" placeholder=\"issue-YYYYMMDD-HHMMSS\" oninput=\"updateIssueRunControls()\">
            </div>
            <div class=\"issue-history-field\">
              <label class=\"muted\">Run status</label>
              <div id=\"issueRunResolvedState\" class=\"issue-run-status\">Run status: no active run</div>
            </div>
            <div class=\"issue-history-field\">
              <label class=\"muted\">Recent runs</label>
              <select id=\"issueRecentRunsList\" class=\"field\" onchange=\"selectIssueRecentRun()\">
                <option value=\"\">Recent runs will appear here</option>
              </select>
            </div>
          </div>

          <div class=\"issue-history-actions\">
            <button onclick=\"listIssueRecentRuns()\" id=\"issueListRunsBtn\">List recent runs</button>
            <button onclick=\"loadIssueHistoryLog()\" id=\"issueLoadHistoryBtn\">View historical log</button>
          </div>
        </div>

        <div id=\"issueHistoryLogWrap\" class=\"issue-log-panel\" style=\"display:none;\">
          <div style=\"display:flex; gap:8px; align-items:center; justify-content:space-between; margin-bottom:8px;\">
            <h4 class=\"issue-log-title\" style=\"margin:0;\">Historical execution log</h4>
            <div style=\"display:flex; gap:8px; align-items:center;\">
              <button onclick=\"toggleIssueHistoryLog()\" id=\"issueToggleHistoryBtn\">Show historical log</button>
              <button onclick=\"markIssueRunResolved()\" id=\"issueMarkResolvedBtn\" style=\"display:none;\">Mark resolved</button>
            </div>
          </div>
          <div id=\"issueHistoryLog\" class=\"logs\" style=\"display:none;\">No historical logs loaded.</div>
        </div>
      </div>
    </div>
  </section>

  <section id=\"tabAnswers\" class=\"tab-panel\">
    <div class=\"card answers-panel-shell\">
      <div class=\"answers-toolbar\">
        <div class=\"answers-toolbar-copy\">
          <div class=\"answers-toolbar-kicker\">Support Inbox</div>
          <h3>Answers Agent</h3>
          <p class=\"muted\">Review live conversations, refine AI suggestions, and reply from a single support workspace.</p>
        </div>
        <div class=\"answers-toolbar-actions\">
          <button onclick=\"loadAnswersChats()\">Refresh chats</button>
          <button id=\"answersArchivedToggleBtn\" onclick=\"toggleArchivedAnswers()\">View archived</button>
        </div>
      </div>
      <div id=\"answersList\"></div>
    </div>
    <div id=\"answersArchivedSection\" class=\"card answers-archived-section\" style=\"display:none;\">
      <h3>Archived conversations</h3>
      <p class=\"muted\">Archived conversations are auto-deleted after 7 days.</p>
      <div id=\"answersArchivedList\"></div>
    </div>
  </section>
      </div>

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
let statusDismissTimer = null;
let issuePlaywrightLogLines = [];
let issueLogToggleAllowed = false;
let issueCurrentRunId = '';
let issueActiveRunId = '';
let issueResolvedRunIds = new Set();
let issueRecentRuns = [];
let issueHistoryLogLines = [];
let issueHistoryToggleAllowed = false;
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
  if (!statusEl) return;
  const message = String(text || '').trim();

  if (statusDismissTimer) {
    clearTimeout(statusDismissTimer);
    statusDismissTimer = null;
  }

  statusEl.classList.remove('status-hidden');
  statusEl.classList.remove('status-error');
  statusEl.classList.remove('status-success');
  statusEl.classList.remove('status-warning');

  if (!message) {
    statusEl.innerText = '';
    return;
  }

  const isError = /(error|failed|invalid|unauthorized|forbidden|denied|unable|reject|timeout|exception)/i.test(message);
  const isWarning = !isError && /(warning|partial|non-blocking|check log|check logs|review log)/i.test(message);
  const isSuccess = !isError && !isWarning && /(saved|sent|created|updated|marked|unarchived|archived|executed|generated|received|moved|removed|completed|reset|succeeded|success|all post-create clicks succeeded|todo ok)/i.test(message);
  if (isError) {
    statusEl.classList.add('status-error');
  } else if (isWarning) {
    statusEl.classList.add('status-warning');
  } else if (isSuccess) {
    statusEl.classList.add('status-success');
  }

  statusEl.innerText = message;
  statusDismissTimer = setTimeout(() => {
    statusEl.classList.add('status-hidden');
    statusEl.innerText = '';
    statusEl.classList.remove('status-error');
    statusEl.classList.remove('status-success');
    statusEl.classList.remove('status-warning');
    statusDismissTimer = null;
  }, 20000);
}

async function readApiPayload(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_err) {
    return {detail: text};
  }
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

const TAB_META = {
  workday: {
    title: 'Web Interaction Agent',
    subtitle: 'Scheduler, click history and runtime logs.'
  },
  email: {
    title: 'Email Agent',
    subtitle: 'Suggestions, sender settings and response workflows.'
  },
  issue: {
    title: 'Issue Agent',
    subtitle: 'Draft generation, warnings and Playwright-assisted execution.'
  },
  answers: {
    title: 'Answers Agent',
    subtitle: 'Support chats, AI suggestions and outbound replies.'
  }
};

function updateTopbar(name) {
  const meta = TAB_META[String(name || '').trim()] || TAB_META.workday;
  const title = document.getElementById('activeTabTitle');
  const subtitle = document.getElementById('activeTabMeta');
  if (title) title.innerText = meta.title;
  if (subtitle) subtitle.innerText = meta.subtitle;
}

function setSidebarBadge(id, text, variant) {
  const badge = document.getElementById(id);
  if (!badge) return;
  const clean = String(text || '').trim();
  badge.innerText = clean;
  badge.dataset.variant = String(variant || 'neutral');
  badge.classList.toggle('is-hidden', !clean);
}

async function refreshActivePanel() {
  if (activeTab === 'workday') {
    await refreshWorkdayPanel();
    await loadWorkdaySettings();
    return;
  }
  if (activeTab === 'email') {
    await loadSettings();
    await loadSuggestions();
    if (emailReviewedVisible) await loadReviewedSuggestions();
    return;
  }
  if (activeTab === 'issue') {
    renderIssueDraftEditor();
    await listIssueRecentRuns();
    return;
  }
  if (activeTab === 'answers') {
    await loadAnswersChats();
    if (answersArchivedVisible) await loadArchivedAnswersChats();
  }
}

function showTab(name) {
  activeTab = name;
  const isWorkday = name === 'workday';
  const isEmail = name === 'email';
  const isIssue = name === 'issue';
  const isAnswers = name === 'answers';
  updateTopbar(name);
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
    const workdayBadgeText = data.blocked_today && phase === 'before_start'
      ? 'Blocked'
      : phase === 'failed'
      ? 'Fail'
      : phase === 'completed'
      ? 'Done'
      : phase === 'before_start'
      ? 'Ready'
      : 'Live';
    const workdayBadgeVariant = data.blocked_today && phase === 'before_start'
      ? 'warning'
      : phase === 'failed'
      ? 'danger'
      : phase === 'completed'
      ? 'success'
      : phase === 'before_start'
      ? 'neutral'
      : 'live';
    setSidebarBadge('tabWorkdayBadge', workdayBadgeText, workdayBadgeVariant);
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
    setSidebarBadge('tabWorkdayBadge', 'Error', 'danger');
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
  updateIssueLinkEnrichmentControl();
}

function issueExtractUrls(text) {
  const matches = String(text || '').match(/https?:\\/\\/[^ <>()"']+/gi) || [];
  const unique = [];
  const seen = new Set();
  matches.forEach((raw) => {
    const candidate = String(raw || '').trim().replace(/[.,);:]+$/, '');
    if (!candidate || seen.has(candidate)) return;
    seen.add(candidate);
    unique.push(candidate);
  });
  return unique;
}

function normalizeIssueDraftWarnings(raw) {
  // Keep source-derived warnings separate from missing-user-input warnings so the
  // draft review step makes it obvious what comes from provided links vs. missing context.
  const normalized = {source: [], user: []};
  if (Array.isArray(raw)) {
    normalized.source = raw.map((item) => String(item || '').trim()).filter(Boolean);
    return normalized;
  }
  if (raw && typeof raw === 'object') {
    normalized.source = Array.isArray(raw.source)
      ? raw.source.map((item) => String(item || '').trim()).filter(Boolean)
      : [];
    normalized.user = Array.isArray(raw.user)
      ? raw.user.map((item) => String(item || '').trim()).filter(Boolean)
      : [];
  }
  return normalized;
}

function issueIsLocalOrPrivateHost(hostname) {
  const host = String(hostname || '').trim().toLowerCase().replaceAll('[', '').replaceAll(']', '');
  if (!host) return true;
  if (host === 'localhost' || host === '::1' || host.endsWith('.local')) return true;
  if (host.startsWith('127.') || host.startsWith('10.') || host.startsWith('192.168.')) return true;
  const hostParts = host.split('.');
  if (hostParts.length >= 2 && hostParts[0] === '172') {
    const second = Number(hostParts[1]);
    if (second >= 16 && second <= 31) return true;
  }
  return false;
}

function getIssueDetectedLinkCandidates() {
  const input = document.getElementById('issueUserInput');
  return issueExtractUrls((input && input.value) || '').filter((url) => {
    try {
      return !issueIsLocalOrPrivateHost(new URL(url).hostname);
    } catch (_) {
      return false;
    }
  });
}

function updateIssueLinkEnrichmentControl() {
  const row = document.getElementById('issueEnrichLinksRow');
  const toggle = document.getElementById('issueEnrichLinks');
  const label = document.getElementById('issueEnrichLinksLabel');
  const addComment = document.getElementById('issueAddAsComment');
  const issueType = document.getElementById('issueIssueType');
  const shouldOffer = !!issueType
    && !((addComment && addComment.checked) || false)
    && String(issueType.value || '').trim().toLowerCase() === 'new feature';
  const urls = shouldOffer ? getIssueDetectedLinkCandidates() : [];
  if (row) row.style.display = urls.length ? 'block' : 'none';
  if (toggle) {
    toggle.disabled = urls.length === 0;
    if (!urls.length) toggle.checked = false;
  }
  if (label) {
    label.innerText = urls.length
      ? `Enrich from detected links (${urls.length})`
      : 'Enrich from detected links';
  }
}

function clearIssuePlaywrightLog(hidePanel = false) {
  // Client-side execution timeline for the latest submit run.
  issuePlaywrightLogLines = [];
  const logBox = document.getElementById('issuePlaywrightLog');
  const logWrap = document.getElementById('issuePlaywrightLogWrap');
  const logToggle = document.getElementById('issueToggleLogBtn');
  if (logBox) logBox.innerText = 'No execution logs yet.';
  if (hidePanel && logWrap) logWrap.style.display = 'none';
  if (hidePanel && logToggle) logToggle.style.display = 'none';
  if (hidePanel) issueLogToggleAllowed = false;
}

function getIssueSelectedRunId() {
  const input = document.getElementById('issueRunId');
  const typed = String((input && input.value) || '').trim();
  return typed || issueCurrentRunId;
}

function setIssueCurrentRunId(runId) {
  issueCurrentRunId = String(runId || '').trim();
  const input = document.getElementById('issueRunId');
  if (input && issueCurrentRunId) input.value = issueCurrentRunId;
  updateIssueRunControls();
}

function setIssueHistoryCardExpanded(openPanel = false) {
  const body = document.getElementById('issueHistoryCardBody');
  const toggle = document.getElementById('issueHistoryCardToggleBtn');
  if (body) body.style.display = openPanel ? 'block' : 'none';
  if (toggle) toggle.innerText = openPanel ? 'Hide run history' : 'Show run history';
}

function toggleIssueHistoryCard() {
  const body = document.getElementById('issueHistoryCardBody');
  const currentlyVisible = !!body && body.style.display !== 'none';
  setIssueHistoryCardExpanded(!currentlyVisible);
}

function setIssueActiveRunId(runId) {
  issueActiveRunId = String(runId || '').trim();
  updateIssueRunControls();
}

function updateIssueRunControls() {
  const input = document.getElementById('issueRunId');
  const state = document.getElementById('issueRunResolvedState');
  const markBtn = document.getElementById('issueMarkResolvedBtn');
  const selectedRunId = String((input && input.value) || '').trim() || issueCurrentRunId;
  const isResolved = !!selectedRunId && issueResolvedRunIds.has(selectedRunId);
  const isPastRun = !!selectedRunId && (!issueActiveRunId || selectedRunId !== issueActiveRunId);
  if (state) {
    state.innerText = selectedRunId
      ? `Run status: ${isResolved ? 'resolved' : 'pending review'}`
      : 'Run status: no active run';
  }
  if (markBtn) {
    markBtn.style.display = isPastRun && !isResolved ? 'inline-block' : 'none';
    markBtn.disabled = !selectedRunId || isResolved || !isPastRun;
  }
}

function issueRunStatusLabel(runId) {
  if (!runId) return '';
  return issueResolvedRunIds.has(runId) ? 'resolved' : 'pending';
}

function renderIssueRecentRunsList() {
  const select = document.getElementById('issueRecentRunsList');
  if (!select) return;
  const options = ['<option value=\"\">Recent runs will appear here</option>'];
  issueRecentRuns.forEach((item) => {
    const runId = String((item && item.run_id) || '').trim();
    if (!runId) return;
    const status = String((item && item.status) || '').trim();
    const selected = runId === getIssueSelectedRunId() ? ' selected' : '';
    options.push(`<option value=\"${runId}\"${selected}>${runId}${status ? ` (${status})` : ''}</option>`);
  });
  select.innerHTML = options.join('');
}

function selectIssueRecentRun() {
  const select = document.getElementById('issueRecentRunsList');
  const input = document.getElementById('issueRunId');
  const runId = String((select && select.value) || '').trim();
  if (input) input.value = runId;
  if (runId) setIssueCurrentRunId(runId);
  updateIssueRunControls();
}

function appendIssuePlaywrightLog(message) {
  // Keep a bounded rolling buffer to avoid unbounded growth in long sessions.
  const logBox = document.getElementById('issuePlaywrightLog');
  const logWrap = document.getElementById('issuePlaywrightLogWrap');
  if (!logBox || !logWrap) return;
  const ts = new Date().toLocaleTimeString();
  issuePlaywrightLogLines.push(`[${ts}] ${String(message || '').trim()}`);
  if (issuePlaywrightLogLines.length > 150) {
    issuePlaywrightLogLines = issuePlaywrightLogLines.slice(-150);
  }
  logWrap.style.display = 'block';
  logBox.innerText = issuePlaywrightLogLines.join('\\n');
  logBox.scrollTop = logBox.scrollHeight;
  const logToggle = document.getElementById('issueToggleLogBtn');
  if (issueLogToggleAllowed && logToggle) {
    logToggle.innerText = 'Hide Playwright log';
  }
}

function setIssueLogToggle(allowed, openPanel = false) {
  issueLogToggleAllowed = !!allowed;
  const logWrap = document.getElementById('issuePlaywrightLogWrap');
  const logToggle = document.getElementById('issueToggleLogBtn');
  if (logToggle) {
    logToggle.style.display = issueLogToggleAllowed ? 'inline-block' : 'none';
  }
  if (logWrap) {
    logWrap.style.display = openPanel ? 'block' : 'none';
  }
  if (logToggle) {
    logToggle.innerText = (logWrap && logWrap.style.display !== 'none')
      ? 'Hide Playwright log'
      : 'Show Playwright log';
  }
}

function toggleIssuePlaywrightLog() {
  if (!issueLogToggleAllowed) return;
  const logWrap = document.getElementById('issuePlaywrightLogWrap');
  const logToggle = document.getElementById('issueToggleLogBtn');
  if (!logWrap || !logToggle) return;
  const currentlyVisible = logWrap.style.display !== 'none';
  logWrap.style.display = currentlyVisible ? 'none' : 'block';
  logToggle.innerText = currentlyVisible ? 'Show Playwright log' : 'Hide Playwright log';
}

function clearIssueHistoryLog(hidePanel = false) {
  issueHistoryLogLines = [];
  const logWrap = document.getElementById('issueHistoryLogWrap');
  const logBox = document.getElementById('issueHistoryLog');
  const logToggle = document.getElementById('issueToggleHistoryBtn');
  if (logBox) logBox.innerText = 'No historical logs loaded.';
  if (hidePanel && logWrap) logWrap.style.display = 'none';
  if (logBox && hidePanel) logBox.style.display = 'none';
  if (hidePanel) issueHistoryToggleAllowed = false;
  if (logToggle) logToggle.innerText = 'Show historical log';
  if (hidePanel) setIssueHistoryCardExpanded(false);
}

function setIssueHistoryToggle(allowed, openPanel = false) {
  issueHistoryToggleAllowed = !!allowed;
  const logWrap = document.getElementById('issueHistoryLogWrap');
  const logBox = document.getElementById('issueHistoryLog');
  const logToggle = document.getElementById('issueToggleHistoryBtn');
  if (logWrap) logWrap.style.display = issueHistoryToggleAllowed ? 'block' : 'none';
  if (logBox) logBox.style.display = openPanel ? 'block' : 'none';
  if (logToggle) logToggle.innerText = openPanel ? 'Hide historical log' : 'Show historical log';
}

function toggleIssueHistoryLog() {
  if (!issueHistoryToggleAllowed) return;
  const logBox = document.getElementById('issueHistoryLog');
  const logToggle = document.getElementById('issueToggleHistoryBtn');
  if (!logBox || !logToggle) return;
  const currentlyVisible = logBox.style.display !== 'none';
  logBox.style.display = currentlyVisible ? 'none' : 'block';
  logToggle.innerText = currentlyVisible ? 'Show historical log' : 'Hide historical log';
}

function renderIssueDraftEditor() {
  const box = document.getElementById('issueDraftEditor');
  const runtimeGrid = document.getElementById('issueDraftRuntimeGrid');
  const jsonBox = document.getElementById('issueGeneratedJson');
  if (!box) return;
  if (!currentIssue) {
    setSidebarBadge('tabIssueBadge', 'Ready', 'neutral');
    box.style.display = 'none';
    if (runtimeGrid) runtimeGrid.style.display = 'none';
    clearIssuePlaywrightLog(true);
    if (jsonBox) {
      jsonBox.style.display = 'none';
      jsonBox.innerText = '{}';
    }
    updateIssueRunControls();
    return;
  }
  const title = document.getElementById('issueDraftTitle');
  const titleRow = document.getElementById('issueDraftTitleRow');
  const description = document.getElementById('issueDraftDescription');
  const descriptionLabel = document.getElementById('issueDraftDescriptionLabel');
  const stepsRow = document.getElementById('issueDraftStepsRow');
  const steps = document.getElementById('issueDraftSteps');
  const warningsWrap = document.getElementById('issueDraftWarningsWrap');
  const sourceWarningsWrap = document.getElementById('issueDraftSourceWarningsWrap');
  const sourceWarningsBox = document.getElementById('issueDraftSourceWarnings');
  const userWarningsWrap = document.getElementById('issueDraftUserWarningsWrap');
  const userWarningsBox = document.getElementById('issueDraftUserWarnings');
  const issueType = String((currentIssue && currentIssue.issue_type) || '').trim().toLowerCase();
  const isCommentMode = !!currentIssue.include_comment && !!String(currentIssue.comment_issue_number || '').trim();
  const showSteps = issueType === 'bug';
  const draftWarnings = normalizeIssueDraftWarnings(currentIssue.draft_warnings);
  const sourceWarnings = Array.isArray(draftWarnings.source) ? draftWarnings.source : [];
  const userWarnings = Array.isArray(draftWarnings.user) ? draftWarnings.user : [];
  const hasWarnings = sourceWarnings.length || userWarnings.length;
  setSidebarBadge('tabIssueBadge', hasWarnings ? 'Warn' : 'Draft', hasWarnings ? 'warning' : 'count');
  if (title) title.value = String(currentIssue.title || '');
  if (titleRow) titleRow.style.display = isCommentMode ? 'none' : 'block';
  if (descriptionLabel) {
    descriptionLabel.innerText = isCommentMode ? 'Draft comment (editable)' : 'Draft description (editable)';
  }
  if (description) {
    description.value = isCommentMode
      ? String(currentIssue.comment || currentIssue.description || '')
      : String(currentIssue.description || '');
    description.placeholder = isCommentMode ? 'Draft comment' : 'Draft description';
  }
  if (stepsRow) stepsRow.style.display = showSteps ? 'block' : 'none';
  if (steps) steps.value = showSteps ? String(currentIssue.steps_to_reproduce || '') : '';
  if (warningsWrap) warningsWrap.style.display = hasWarnings ? 'block' : 'none';
  if (sourceWarningsWrap) sourceWarningsWrap.style.display = sourceWarnings.length ? 'block' : 'none';
  if (sourceWarningsBox) sourceWarningsBox.innerText = sourceWarnings.length
    ? sourceWarnings.map((item) => `- ${item}`).join('\\n')
    : 'No source warnings.';
  if (userWarningsWrap) userWarningsWrap.style.display = userWarnings.length ? 'block' : 'none';
  if (userWarningsBox) userWarningsBox.innerText = userWarnings.length
    ? userWarnings.map((item) => `- ${item}`).join('\\n')
    : 'No user warnings.';
  box.style.display = 'block';
  if (runtimeGrid) runtimeGrid.style.display = 'grid';
  if (!issueLogToggleAllowed) setIssueLogToggle(false, false);
  if (jsonBox) {
    jsonBox.style.display = 'block';
    jsonBox.innerText = JSON.stringify(currentIssue || {}, null, 2);
  }
  updateIssueRunControls();
}

function syncIssueDraftFromEditor() {
  if (!currentIssue) return;
  const title = document.getElementById('issueDraftTitle');
  const description = document.getElementById('issueDraftDescription');
  const steps = document.getElementById('issueDraftSteps');
  const issueType = String(currentIssue.issue_type || '').trim().toLowerCase();
  const isCommentMode = !!currentIssue.include_comment && !!String(currentIssue.comment_issue_number || '').trim();
  if (title && !isCommentMode) currentIssue.title = String(title.value || '').trim();
  if (description) {
    const descriptionText = String(description.value || '').trim();
    if (isCommentMode) {
      currentIssue.comment = descriptionText;
      currentIssue.description = descriptionText;
    } else {
      currentIssue.description = descriptionText;
    }
  }
  if (steps && issueType === 'bug') {
    currentIssue.steps_to_reproduce = String(steps.value || '').trim();
  }
}

function clearIssueDraft() {
  currentIssue = null;
  const issueSubmitStatus = document.getElementById('issueSubmitStatus');
  const issueGenerateStatus = document.getElementById('issueGenerateStatus');
  const issueUserInput = document.getElementById('issueUserInput');
  const issueCommentNumber = document.getElementById('issueCommentNumber');
  const issueEnrichLinks = document.getElementById('issueEnrichLinks');
  if (issueSubmitStatus) issueSubmitStatus.innerText = '';
  if (issueGenerateStatus) issueGenerateStatus.innerText = 'Draft cleared manually';
  if (issueUserInput) issueUserInput.value = '';
  if (issueCommentNumber) issueCommentNumber.value = '';
  if (issueEnrichLinks) issueEnrichLinks.checked = false;
  setIssueLogToggle(false, false);
  updateIssueLinkEnrichmentControl();
  renderIssueDraftEditor();
  setStatus('Todo OK: draft cleared manually and marked as done');
  setTimeout(() => {
    const statusEl = document.getElementById('issueGenerateStatus');
    if (statusEl && String(statusEl.innerText || '').trim() === 'Draft cleared manually') {
      statusEl.innerText = '';
    }
  }, 10000);
}

function formatIssueHistoryEvent(item) {
  const eventName = String((item && item.event) || '').trim();
  const meta = (item && item.meta) || {};
  const ts = String((item && item.ts) || '').trim();
  const prefix = ts ? `[${ts}] ` : '';
  if (eventName === 'issue_playwright_step') {
    const message = String(meta.message || '').trim();
    return message ? `${prefix}${message}` : '';
  }
  if (eventName === 'issue_submitted') {
    const finalUrl = String(meta.final_url || '').trim();
    return finalUrl ? `${prefix}Submitted: ${finalUrl}` : `${prefix}Submitted`;
  }
  if (eventName === 'issue_submit_failed') {
    const reason = String(meta.reason || '').trim();
    return reason ? `${prefix}Submit failed: ${reason}` : `${prefix}Submit failed`;
  }
  if (eventName === 'issue_run_resolved') {
    return `${prefix}Marked resolved`;
  }
  return '';
}

async function loadIssueHistoryLog() {
  const runId = getIssueSelectedRunId();
  if (!runId) {
    setStatus('Provide a run ID first');
    return;
  }
  // Historical view replays the persisted backend events for one concrete run_id.
  const statusBox = document.getElementById('issueSubmitStatus');
  setIssueHistoryCardExpanded(true);
  stopIssuePlaywrightRealtime();
  clearIssueHistoryLog(false);
  setIssueHistoryToggle(true, true);
  const historyBox = document.getElementById('issueHistoryLog');
  if (historyBox) historyBox.innerText = `Loading historical log for ${runId}...`;
  try {
    const r = await fetch(withIssueSecret(`/events?limit=200&run_id=${encodeURIComponent(runId)}`));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const items = Array.isArray(data.events) ? data.events : [];
    const lines = items.map(formatIssueHistoryEvent).filter(Boolean);
    const isResolved = items.some((item) => String((item && item.event) || '').trim() === 'issue_run_resolved');
    if (isResolved) issueResolvedRunIds.add(runId);
    issueHistoryLogLines = lines.length ? lines : [`No stored events found for ${runId}.`];
    const logBox = document.getElementById('issueHistoryLog');
    if (logBox) {
      logBox.innerText = issueHistoryLogLines.join('\\n');
      logBox.scrollTop = 0;
    }
    setIssueCurrentRunId(runId);
    if (statusBox) statusBox.innerText = `Historical log loaded: ${runId}`;
    setStatus(`Historical Playwright log loaded: ${runId}`);
  } catch (err) {
    if (historyBox) historyBox.innerText = `Historical log failed: ${String(err || '')}`;
    setIssueHistoryToggle(true, true);
    setStatus(`Error loading historical log: ${String(err || '')}`);
  } finally {
    updateIssueRunControls();
  }
}

async function markIssueRunResolved() {
  const runId = getIssueSelectedRunId();
  if (!runId) {
    setStatus('Provide a run ID first');
    return;
  }
  // Resolved is an operator-side acknowledgement for the current run timeline.
  issueResolvedRunIds.add(runId);
  updateIssueRunControls();
  if (issueHistoryLogLines.length) {
    issueHistoryLogLines.push(`[${new Date().toLocaleTimeString()}] Marked resolved`);
    const historyBox = document.getElementById('issueHistoryLog');
    if (historyBox) historyBox.innerText = issueHistoryLogLines.join('\\n');
  }
  setStatus(`Run marked as resolved: ${runId}`);
  try {
    await fetch(withIssueSecret(`/resolve/${encodeURIComponent(runId)}`), {
      method: 'POST'
    });
  } catch (_) {
    // best effort: the UI state is enough even if the historical event write fails
  }
  issueRecentRuns = issueRecentRuns.map((item) => {
    if (String((item && item.run_id) || '').trim() !== runId) return item;
    return {...item, status: 'resolved'};
  });
  renderIssueRecentRunsList();
}

async function listIssueRecentRuns() {
  const btn = document.getElementById('issueListRunsBtn');
  const oldText = btn ? btn.innerText : '';
  setIssueHistoryCardExpanded(true);
  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Loading...';
  }
  try {
    // The recent-run list is derived from the shared event stream, newest first.
    const r = await fetch(withIssueSecret('/events?limit=200'));
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const items = Array.isArray(data.events) ? data.events : [];
    const seen = new Set();
    const recent = [];
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const item = items[i] || {};
      const meta = item.meta || {};
      const runId = String(meta.run_id || '').trim();
      if (!runId || seen.has(runId)) continue;
      seen.add(runId);
      const relatedItems = items.filter((candidate) => String((((candidate || {}).meta) || {}).run_id || '').trim() === runId);
      const resolved = relatedItems.some((candidate) => String((candidate || {}).event || '').trim() === 'issue_run_resolved');
      const failed = relatedItems.some((candidate) => String((candidate || {}).event || '').trim() === 'issue_submit_failed');
      const submitted = relatedItems.some((candidate) => String((candidate || {}).event || '').trim() === 'issue_submitted');
      if (resolved) issueResolvedRunIds.add(runId);
      recent.push({
        run_id: runId,
        status: resolved ? 'resolved' : (failed ? 'failed' : (submitted ? 'submitted' : 'pending'))
      });
      if (recent.length >= 20) break;
    }
    issueRecentRuns = recent;
    renderIssueRecentRunsList();
    updateIssueRunControls();
    setStatus(`Loaded ${recent.length} recent run(s)`);
  } catch (err) {
    setStatus(`Error loading recent runs: ${String(err || '')}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = oldText || 'List recent runs';
    }
  }
}

let issuePlaywrightPollTimer = null;
let issuePlaywrightPollBusy = false;
let issuePlaywrightSeen = new Set();

function stopIssuePlaywrightRealtime() {
  if (issuePlaywrightPollTimer) {
    clearInterval(issuePlaywrightPollTimer);
    issuePlaywrightPollTimer = null;
  }
}

async function pollIssuePlaywrightSteps(runId) {
  if (!runId || issuePlaywrightPollBusy) return;
  issuePlaywrightPollBusy = true;
  try {
    const r = await fetch(withIssueSecret(`/events?limit=40&run_id=${encodeURIComponent(runId)}&event=issue_playwright_step`));
    const data = await r.json();
    if (!r.ok) return;
    const items = Array.isArray(data.events) ? data.events : [];
    items.forEach((item) => {
      const ts = String(item.ts || '').trim();
      const msg = String((((item.meta || {}).message) || '')).trim();
      if (!msg) return;
      const key = `${ts}|${msg}`;
      if (issuePlaywrightSeen.has(key)) return;
      issuePlaywrightSeen.add(key);
      appendIssuePlaywrightLog(msg);
    });
  } catch (_) {
    // best-effort live polling; ignore transient read errors
  } finally {
    issuePlaywrightPollBusy = false;
  }
}

function startIssuePlaywrightRealtime(runId) {
  stopIssuePlaywrightRealtime();
  issuePlaywrightSeen = new Set();
  pollIssuePlaywrightSteps(runId);
  issuePlaywrightPollTimer = setInterval(() => {
    pollIssuePlaywrightSteps(runId);
  }, 2500);
}

function extractIssueUrlFromRunEvents(items, runId) {
  if (!Array.isArray(items) || !runId) return '';
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i] || {};
    if (String(item.event || '').trim() !== 'issue_playwright_step') continue;
    const meta = item.meta || {};
    if (String(meta.run_id || '').trim() !== runId) continue;
    const url = String(meta.url || '').trim();
    if (url && url.includes('/issues/') && /[0-9]+([?#].*)?$/.test(url)) return url;
  }
  return '';
}

async function reconcileIssueSubmitByRunId(runId, attempts = 30, waitMs = 2000) {
  if (!runId) return {state: 'unknown', finalUrl: ''};
  for (let i = 0; i < attempts; i += 1) {
    try {
      const r = await fetch(withIssueSecret(`/events?limit=80&run_id=${encodeURIComponent(runId)}`));
      const data = await r.json();
      if (r.ok) {
        const items = Array.isArray(data.events) ? data.events : [];
        const submitted = items.some((item) => {
          const meta = (item && item.meta) || {};
          return String(item.event || '').trim() === 'issue_submitted'
            && String(meta.run_id || '').trim() === runId;
        });
        if (submitted) {
          return {state: 'submitted', finalUrl: extractIssueUrlFromRunEvents(items, runId)};
        }
        const failed = items.some((item) => {
          const meta = (item && item.meta) || {};
          return String(item.event || '').trim() === 'issue_submit_failed'
            && String(meta.run_id || '').trim() === runId;
        });
        if (failed) return {state: 'failed', finalUrl: ''};
      }
    } catch (_) {
      // best effort
    }
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
  return {state: 'unknown', finalUrl: ''};
}

async function submitIssueDraft() {
  if (!currentIssue) {
    document.getElementById('issueSubmitStatus').innerText = 'Generate a draft first';
    return;
  }
  syncIssueDraftFromEditor();
  const isCommentMode = !!currentIssue.include_comment && !!String(currentIssue.comment_issue_number || '').trim();
  const draftTitle = String(currentIssue.title || '').trim();
  const draftDescription = isCommentMode
    ? String(currentIssue.comment || currentIssue.description || '').trim()
    : String(currentIssue.description || '').trim();
  if ((!isCommentMode && (!draftTitle || !draftDescription)) || (isCommentMode && !draftDescription)) {
    document.getElementById('issueSubmitStatus').innerText = isCommentMode
      ? 'Comment body is required before submit'
      : 'Title and description are required before submit';
    appendIssuePlaywrightLog(
      isCommentMode
        ? 'Validation failed: comment body cannot be empty.'
        : 'Validation failed: title/description cannot be empty.'
    );
    return;
  }
  appendIssuePlaywrightLog('Draft validated. Preparing Playwright execution.');
  const btn = document.getElementById('issueSubmitBtn');
  const oldText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Submitting...';
  document.getElementById('issueSubmitStatus').innerText = '';
  // While Playwright is running, keep the log panel visible as live output.
  setIssueLogToggle(false, true);
  const expectedRunId = String((currentIssue && currentIssue.issue_id) || '').trim();
  if (expectedRunId) {
    issueResolvedRunIds.delete(expectedRunId);
    setIssueActiveRunId(expectedRunId);
    setIssueCurrentRunId(expectedRunId);
  }
  startIssuePlaywrightRealtime(expectedRunId);
  try {
    appendIssuePlaywrightLog('Sending draft to /issue-agent/submit...');
    const r = await fetch(withIssueSecret('/submit'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        issue: currentIssue,
        selectors: {},
        non_headless: false
      })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const result = (data || {}).result || {};
    const finalUrl = String(result.final_url || '').trim();
    const runId = String(result.run_id || '').trim();
    const artifactsDir = String(result.artifacts_dir || '').trim();
    const summary = String(result.summary || '').trim();
    const warnings = Array.isArray(result.warnings) ? result.warnings : [];
    const createdInGithub = finalUrl.includes('/issues/') && /[0-9]+([?#].*)?$/.test(finalUrl);
    if (finalUrl) currentIssue.generated_link = finalUrl;
    if (runId) {
      setIssueActiveRunId(runId);
      setIssueCurrentRunId(runId);
    }
    appendIssuePlaywrightLog('Playwright execution finished successfully.');
    if (summary) appendIssuePlaywrightLog(summary);
    if (finalUrl) appendIssuePlaywrightLog(`Issue created/updated at: ${finalUrl}`);
    if (runId) appendIssuePlaywrightLog(`Run ID: ${runId}`);
    if (artifactsDir) appendIssuePlaywrightLog(`Artifacts path: ${artifactsDir}`);
    if (warnings.length) {
      appendIssuePlaywrightLog(`Completed with ${warnings.length} non-blocking warning(s):`);
      warnings.forEach((w) => appendIssuePlaywrightLog(`- ${String(w)}`));
    }
    if (runId && runId !== expectedRunId) {
      await pollIssuePlaywrightSteps(runId);
    }
    if (createdInGithub && warnings.length === 0) {
      document.getElementById('issueSubmitStatus').innerText = `Submitted: ${finalUrl}`;
      setStatus('Todo OK: issue created and all post-create clicks succeeded');
      setIssueLogToggle(false, false);
    } else if (createdInGithub) {
      document.getElementById('issueSubmitStatus').innerText = `Submitted with warnings: ${finalUrl}`;
      setStatus('Warning: issue created but some fields were not clicked. Check Playwright log.');
      setIssueLogToggle(true, false);
    } else {
      document.getElementById('issueSubmitStatus').innerText = 'Create did not complete issue creation';
      setStatus('Error: issue was not created (Create did not navigate). Check Playwright log.');
      setIssueLogToggle(true, true);
    }
    renderIssueDraftEditor();
  } catch (err) {
    const errText = String(err || '');
    appendIssuePlaywrightLog(`Playwright execution failed: ${errText}`);
    appendIssuePlaywrightLog('Checking backend run status...');
    document.getElementById('issueSubmitStatus').innerText = 'Connection lost; checking backend status...';
    setStatus('Warning: UI connection failed while the backend may still be processing. Checking status...');
    const reconcile = await reconcileIssueSubmitByRunId(expectedRunId);
    if (reconcile.state === 'submitted') {
      const recoveredUrl = String(reconcile.finalUrl || '').trim();
      appendIssuePlaywrightLog('Recovered: backend completed the issue submit.');
      if (recoveredUrl) {
        currentIssue.generated_link = recoveredUrl;
        appendIssuePlaywrightLog(`Issue created/updated at: ${recoveredUrl}`);
        document.getElementById('issueSubmitStatus').innerText = `Submitted (recovered): ${recoveredUrl}`;
      } else {
        document.getElementById('issueSubmitStatus').innerText = `Submitted (recovered): run ${expectedRunId}`;
      }
      setStatus('Warning: UI request failed, but backend completed the issue submission.');
      setIssueLogToggle(true, false);
      setIssueActiveRunId(expectedRunId);
      setIssueCurrentRunId(expectedRunId);
      renderIssueDraftEditor();
    } else if (reconcile.state === 'failed') {
      appendIssuePlaywrightLog('Backend confirms submit failed for this run.');
      document.getElementById('issueSubmitStatus').innerText = `Error submitting draft: ${errText}`;
      setIssueLogToggle(true, true);
      setStatus(`Error submitting issue: ${errText}`);
    } else {
      document.getElementById('issueSubmitStatus').innerText = `Error submitting draft: ${errText}`;
      setIssueLogToggle(true, true);
      if (/Create did not navigate to created issue/i.test(errText)) {
        setStatus('Error: issue was not created by Create. Check Playwright log.');
      } else if (/load failed/i.test(errText)) {
        setStatus('Warning: request connection failed while processing. Check Playwright log and addon logs.');
      } else {
        setStatus(`Error submitting issue: ${errText}`);
      }
    }
  } finally {
    await pollIssuePlaywrightSteps(expectedRunId);
    stopIssuePlaywrightRealtime();
    btn.disabled = false;
    btn.innerText = oldText;
    updateIssueRunControls();
  }
}

async function generateIssueDraft() {
  const input = document.getElementById('issueUserInput').value.trim();
  const selectedIssueType = document.getElementById('issueIssueType').value;
  let issueType = selectedIssueType;
  let repo = document.getElementById('issueRepo').value;
  const unit = document.getElementById('issueUnit').value;
  const includeComment = !!document.getElementById('issueAddAsComment').checked;
  const enrichLinks = !!document.getElementById('issueEnrichLinks')?.checked;
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
        as_third_party: asThirdParty,
        enrich_links: asNewFeature && enrichLinks
      })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    currentIssue = data.item || null;
    const draftWarnings = normalizeIssueDraftWarnings((currentIssue && currentIssue.draft_warnings) || {});
    const draftWarningCount = (draftWarnings.source || []).length + (draftWarnings.user || []).length;
    document.getElementById('issueGenerateStatus').innerText = draftWarningCount
      ? `Draft generated with ${draftWarningCount} warning(s): ${currentIssue && currentIssue.issue_id ? currentIssue.issue_id : 'unknown'}`
      : `Draft generated: ${currentIssue && currentIssue.issue_id ? currentIssue.issue_id : 'unknown'}`;
    document.getElementById('issueSubmitStatus').innerText = '';
    clearIssuePlaywrightLog(true);
    setIssueLogToggle(false, false);
    appendIssuePlaywrightLog('Draft generated and ready for review.');
    if (draftWarningCount) {
      appendIssuePlaywrightLog('Draft generated with warnings; review the draft warnings before running Playwright.');
      setStatus('Warning: draft generated with missing or non-verified fields. Review draft warnings.');
    }
    renderIssueDraftEditor();
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
    const data = await readApiPayload(r);
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

async function markAnswersSpam(chatId) {
  try {
    const r = await fetch(withAnswersSecret(`/chats/${encodeURIComponent(chatId)}/status`), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: 'spam'})
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    setStatus(`Chat ${chatId} marked as spam and archived`);
    await loadAnswersChats();
    if (answersArchivedVisible) await loadArchivedAnswersChats();
  } catch (err) {
    setStatus(`Error marking chat as spam: ${err}`);
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
    setSidebarBadge('tabAnswersBadge', '!', 'danger');
    setStatus(`Error loading answers chats: ${err}`);
    return;
  }

  const chatItems = Array.isArray(data.items) ? data.items : [];
  setSidebarBadge('tabAnswersBadge', chatItems.length ? String(chatItems.length) : '', 'count');
  list.innerHTML = '';
  if (chatItems.length === 0) {
    list.innerHTML = `
      <div class="answers-inbox">
        <div class="answers-sidebar-summary">
          <div>
            <span>Active conversations</span>
            <strong>Answers queue</strong>
          </div>
          <div class="answers-sidebar-count">0</div>
        </div>
        <div class="answers-empty-state">
          <h3>No chats with received messages yet.</h3>
          <p class="muted">When a new Telegram message arrives, it will appear here with a suggested reply and quick actions.</p>
        </div>
      </div>
    `;
    return;
  }

  const inboxMarkup = chatItems.map((item, index) => {
    const chatId = String(item.chat_id || '');
    const toggleId = `answers-chat-toggle-${safeDomId(chatId)}`;
    const safeReplyId = answersReplyAreaId(chatId);
    const messages = Array.isArray(item.received_messages) ? item.received_messages : [];
    const lastMessage = messages.length
      ? String(messages[messages.length - 1].content || '').trim()
      : 'No user messages in this chat.';
    const renderedMessages = messages.length
      ? messages.map((message) => {
          const ts = formatTs(message.timestamp);
          const content = String(message.content || '').trim();
          const name = String(message.name || item.name || '').trim();
          return `
            <div class="answers-bubble answers-bubble-user">
              <p class="answers-bubble-meta">${escapeHtml(name)} · ${escapeHtml(ts)}</p>
              <p class="answers-bubble-text">${escapeHtml(content)}</p>
            </div>
          `;
        }).join('')
      : `<div class="answers-empty-state"><p class="muted">No user messages in this chat.</p></div>`;
    const status = String(item.status || 'pending').toLowerCase();
    const suggestionText = String(item.suggested_reply || '').trim();

    return `
      <input type="radio" class="answers-chat-toggle" name="answers-active-chat" id="${toggleId}" ${index === 0 ? 'checked' : ''}>
      <label class="answers-conversation-item" for="${toggleId}">
        <div class="answers-conversation-top">
          <div>
            <p class="answers-conversation-name">${escapeHtml(item.name || `Chat ${chatId}`)}</p>
            <p class="answers-conversation-meta">Telegram · Chat ${escapeHtml(chatId)}</p>
          </div>
          <span class="answers-status-chip" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>
        </div>
        <p class="answers-conversation-preview">${escapeHtml(lastMessage || 'No preview available.')}</p>
        <div class="answers-conversation-foot">
          <span>${escapeHtml(formatTs(item.last_received_ts))}</span>
          <span class="answers-conversation-count">${escapeHtml(item.received_count || 0)} msgs</span>
        </div>
      </label>
      <section class="answers-chat-panel">
        <div class="answers-detail-header">
          <div class="answers-detail-head">
            <div>
              <h3 class="answers-chat-title">${escapeHtml(item.name || `Chat ${chatId}`)}</h3>
              <p class="answers-chat-submeta">Telegram support conversation · Chat ${escapeHtml(chatId)} · Last message ${escapeHtml(formatTs(item.last_received_ts))}</p>
            </div>
            <div class="answers-detail-chips">
              <span class="answers-channel-chip">Telegram</span>
              <span class="answers-status-chip" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>
            </div>
          </div>
        </div>
        <div class="answers-detail-body">
          <div class="answers-thread">
            ${renderedMessages}
            ${suggestionText ? `
              <div class="answers-bubble answers-bubble-agent">
                <p class="answers-bubble-meta">Suggested reply</p>
                <p class="answers-bubble-text">${escapeHtml(suggestionText)}</p>
              </div>
            ` : ''}
          </div>
          <div class="answers-suggestion-card">
            <div class="answers-suggestion-head">
              <div class="answers-suggestion-copy">
                <h4>AI suggestion</h4>
                <p class="muted">Refine the draft before sending, or generate a new version if the context changed.</p>
              </div>
              <span class="answers-channel-chip">Warm draft</span>
            </div>
            <textarea class="field" readonly>${escapeHtml(suggestionText || 'No AI suggestion yet. Use AI suggest or Suggest changes to create one.')}</textarea>
            <div class="answers-suggestion-actions">
              <button onclick="requestAnswersAiSuggestion('${escapeHtml(chatId)}')">AI suggest</button>
              <button onclick="openAnswersSuggestModal('${escapeHtml(chatId)}')">Suggest changes</button>
              <button onclick="markAnswersReviewed('${escapeHtml(chatId)}')">Mark reviewed</button>
              <button onclick="markAnswersSpam('${escapeHtml(chatId)}')">Mark spam</button>
            </div>
          </div>
        </div>
        <div class="answers-composer">
          <div class="answers-composer-head">
            <div class="answers-composer-copy">
              <h4>Reply composer</h4>
              <p class="muted">Final check before sending to the user.</p>
            </div>
          </div>
          <textarea id="${safeReplyId}" class="field" style="min-height:120px" placeholder="Write or refine the reply before sending.">${escapeHtml(item.suggested_reply || '')}</textarea>
          <div class="answers-composer-actions">
            <p class="muted">Next action: send the prepared reply or generate a fresh AI draft.</p>
            <button class="answers-primary-action" onclick="sendAnswersReply('${escapeHtml(chatId)}')">Send reply</button>
          </div>
        </div>
      </section>
    `;
  }).join('');

  list.innerHTML = `
    <div class="answers-inbox">
      <div class="answers-sidebar-summary">
        <div>
          <span>Active conversations</span>
          <strong>Support queue</strong>
        </div>
        <div class="answers-sidebar-count">${escapeHtml(chatItems.length)}</div>
      </div>
      ${inboxMarkup}
    </div>
  `;
}

async function loadSuggestions() {
  let data;
  try {
    const r = await fetch(withEmailSecret('/suggestions'));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  } catch (err) {
    setSidebarBadge('tabEmailBadge', '!', 'danger');
    setStatus(`Error loading suggestions: ${err}`);
    return;
  }
  const list = document.getElementById('list');
  const activeItems = Array.isArray(data.items)
    ? data.items.filter((item) => String(item.status || 'draft') !== 'reviewed')
    : [];
  setSidebarBadge('tabEmailBadge', activeItems.length ? String(activeItems.length) : '', 'count');
  list.innerHTML = '';
  if (activeItems.length === 0) {
    list.innerHTML = `<div class="card email-empty-state"><p class="muted">No suggestions yet. Use <b>Check new messages</b> or <b>Generate from text</b>.</p></div>`;
    return;
  }

  const orderedItems = activeItems.slice().reverse();
  for (const [index, item] of orderedItems.entries()) {
    const div = document.createElement('div');
    div.className = 'email-entry';
    const safeId = String(item.suggestion_id || '');
    const selectId = `email-select-${safeId}`;
    const replySubject = buildReplySubject(item.subject);
    const currentTo = String(item.sent_to || '');
    const currentCc = String(item.sent_cc || emailSettingsCache.default_cc_email || '');
    const rawStatus = String(item.status || 'draft').trim().toLowerCase();
    const statusLabel = rawStatus === 'reviewed'
      ? 'Reviewed'
      : rawStatus === 'spam'
      ? 'Spam'
      : rawStatus === 'archived'
      ? 'Archive'
      : rawStatus === 'sent'
      ? 'Sent'
      : rawStatus === 'copied'
      ? 'Copied'
      : 'Pending';
    const statusClass = rawStatus === 'reviewed'
      ? 'is-reviewed'
      : rawStatus === 'spam'
      ? 'is-spam'
      : rawStatus === 'archived'
      ? 'is-archive'
      : rawStatus === 'sent'
      ? 'is-sent'
      : rawStatus === 'copied'
      ? 'is-copied'
      : 'is-pending';
    const originalBody = String(item.original_body || '');
    const flattenedPreview = originalBody.replace(/\\s+/g, ' ').trim();
    const preview = flattenedPreview.length > 180 ? `${flattenedPreview.slice(0, 177)}...` : flattenedPreview;
    const updatedAt = String(item.updated_at || item.created_at || '').trim();
    const updatedLabel = updatedAt ? formatTs(updatedAt) : 'Just now';
    const checkedAttr = index === 0 ? 'checked' : '';
    div.innerHTML = `
      <input type='radio' name='email-active-ticket' id='${safeId ? escapeHtml(selectId) : ''}' class='email-select' ${checkedAttr}>
      <label for='${safeId ? escapeHtml(selectId) : ''}' class='email-summary'>
        <div class='email-summary-top'>
          <span class='email-badge ${statusClass}'>${escapeHtml(statusLabel)}</span>
          <span class='email-summary-time'>${escapeHtml(updatedLabel)}</span>
        </div>
        <h4 class='email-summary-subject'>${escapeHtml(item.subject || '(no subject)')}</h4>
        <div class='email-summary-from'>${escapeHtml(item.from || 'Unknown sender')}</div>
        <div class='email-summary-preview'>${escapeHtml(preview || 'No preview available yet.')}</div>
      </label>
      <div class='card email-detail-panel'>
        <div class='email-detail-header'>
          <div>
            <div class='email-detail-kicker'>Selected message</div>
            <h3 class='email-detail-title'>${escapeHtml(item.subject || '(no subject)')}</h3>
          </div>
          <span class='email-badge ${statusClass}'>${escapeHtml(statusLabel)}</span>
        </div>

        <div class='email-detail-meta'>
          <div class='email-meta-block'>
            <span class='email-meta-label'>From</span>
            <span class='email-meta-value'>${escapeHtml(item.from || 'Unknown sender')}</span>
          </div>
          <div class='email-meta-block'>
            <span class='email-meta-label'>Updated</span>
            <span class='email-meta-value'>${escapeHtml(updatedLabel)}</span>
          </div>
        </div>

        <div class='email-detail-sections'>
          <section class='email-panel-section'>
            <div class='email-section-heading'>Original email</div>
            <textarea class='field email-original' readonly>${escapeHtml(originalBody)}</textarea>
          </section>

          <section class='card warm-card email-ai-card'>
            <div class='email-section-heading-row'>
              <div class='email-section-heading'>AI suggestion</div>
              <span class='email-section-note'>Edit directly before sending if needed</span>
            </div>
            <textarea id='reply-${safeId}' class='field email-ai-compose'></textarea>
          </section>

          <section class='email-compose-panel'>
            <div class='email-section-heading'>Compose reply</div>
            <div class='email-compose-grid'>
              <div class='email-field-group'>
                <label class='muted' for='to-${safeId}'>Recipient</label>
                <input id='to-${safeId}' class='field' placeholder='Recipient email' value='${escapeHtml(currentTo)}'>
              </div>
              <div class='email-field-group'>
                <label class='muted' for='cc-${safeId}'>CC</label>
                <input id='cc-${safeId}' class='field' placeholder='CC emails (optional, comma-separated)' value='${escapeHtml(currentCc)}'>
              </div>
              <div class='email-field-group email-field-group--wide'>
                <label class='muted'>Subject</label>
                <input class='field' readonly value='${escapeHtml(replySubject)}'>
              </div>
            </div>
          </section>
        </div>

        <div class='email-detail-actions'>
          <div class='email-action-group'>
            <button onclick="sendSuggestion('${safeId}')">Send</button>
            <button onclick="openSuggestionModal('${safeId}')" class='ghost-btn'>Regenerate</button>
            <button onclick="document.getElementById('reply-${safeId}').focus()" class='ghost-btn'>Edit</button>
          </div>
          <div class='email-action-group'>
            <button onclick="copyText('${safeId}')" class='ghost-btn'>Copy</button>
            <button type='button' class='ghost-btn' disabled title='Spam status is not available in the current email flow'>Spam</button>
            <button onclick="markStatus('${safeId}','reviewed')" class='ghost-btn'>Archive</button>
          </div>
        </div>
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
    card.className = 'card email-reviewed-card';
    card.innerHTML = `
      <div class='email-reviewed-head'>
        <div>
          <h4 class='email-reviewed-title'>${escapeHtml(item.subject || '(no subject)')}</h4>
          <div class='muted'>From: ${escapeHtml(item.from || '')} | Reviewed: ${escapeHtml(formatTs(item.reviewed_at || item.updated_at))}</div>
        </div>
        <span class='email-badge is-reviewed'>Reviewed</span>
      </div>
      <div class='email-section-heading'>Suggested reply</div>
      <textarea class='field' style='min-height:100px' readonly>${escapeHtml(item.suggested_reply || '')}</textarea>
      <div class='email-reviewed-actions'>
        <button onclick="markStatus('${safeId}','draft')" class='ghost-btn'>Unarchive</button>
      </div>
    `;
    list.appendChild(card);
  }
}

toggleIssueMode();
document.getElementById('issueIssueType')?.addEventListener('change', () => toggleIssueMode());
document.getElementById('issueUserInput')?.addEventListener('input', () => updateIssueLinkEnrichmentControl());
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
            """.strip().replace("__UI_VERSION__", UI_VERSION)
        )

    return router
