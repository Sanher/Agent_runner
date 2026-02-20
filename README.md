# Agent Runner

Servicio Python (FastAPI + Playwright) para ejecutar automatizaciones web y gestión de borradores de email por API HTTP.

## Estructura (agentes por carpeta)

`main.py` actúa como compositor de servicios:

- `agents/workday_agent/service.py`: lógica del agente de interacción web por fases.
- `routers/workday_agent.py`: endpoints del agente web (`/run/{job_name}`, `/jobs`, `/status`, etc.).
- `agents/email_agent/service.py`: lógica del agente de correo (IMAP + OpenAI + memoria + webhook).
- `routers/email_agent.py`: endpoints del agente de correo (`/email-agent/*`).
- `agents/issue_agent/service.py`: lógica del agente de issues (OpenAI + Playwright + memoria + webhook).
- `routers/issue_agent.py`: endpoints del agente de issues (`/issue-agent/*`).
- `routers/auth.py`: utilidades de autenticación compartidas para routers.
- `routers/ui.py`: UI integrada multiagente (`/ui`).
- `main.py`: carga configuración, instancia servicios y monta routers.

## Requisitos

- Python 3.11+
- Dependencias en `requirements.txt`
- Usa siempre el mismo intérprete para instalar y ejecutar (evita mezclar `python3.13` y `python3.14` en el mismo `.venv`)

## Configuración por agente

La app admite configuración por variables de entorno y también desde `DATA_DIR/options.json`.

### Compartido

- `JOB_SECRET`

### Agente web (`workday_agent`)

- `WORKDAY_TARGET_URL` (legacy: `TARGET_URL`)
- `WORKDAY_SSO_EMAIL` (legacy: `SSO_EMAIL`, opcional)
- `WORKDAY_TIMEZONE` (legacy: `TIMEZONE`, también acepta `TZ`; por defecto usa `TZ` de entorno o `UTC`)
- `WORKDAY_WEBHOOK_START_URL` (legacy: `WORKDAY_WEBHOOK_STATUS_URL` / `HASS_WEBHOOK_URL_STATUS`)
- `WORKDAY_WEBHOOK_FINAL_URL` (legacy: `HASS_WEBHOOK_URL_FINAL`)
- `WORKDAY_WEBHOOK_START_BREAK_URL`
- `WORKDAY_WEBHOOK_STOP_BREAK_URL`

Campos obligatorios para ejecución automática:

- `JOB_SECRET`
- `WORKDAY_TARGET_URL`
- `WORKDAY_WEBHOOK_START_URL`
- `WORKDAY_WEBHOOK_FINAL_URL`
- `WORKDAY_WEBHOOK_START_BREAK_URL`
- `WORKDAY_WEBHOOK_STOP_BREAK_URL`

### Agente correo (`email_agent`)

- `EMAIL_OPENAI_API_KEY` (legacy: `OPENAI_API_KEY`)
- `EMAIL_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-4o-mini`)
- `EMAIL_IMAP_EMAIL` (legacy: `GMAIL_EMAIL`)
- `EMAIL_IMAP_PASSWORD` (legacy: `GMAIL_APP_PASSWORD`)
- `EMAIL_IMAP_HOST` (legacy: `GMAIL_IMAP_HOST`, por defecto `imap.gmail.com`)
- `EMAIL_SMTP_EMAIL` (por defecto usa `EMAIL_IMAP_EMAIL`)
- `EMAIL_SMTP_PASSWORD` (por defecto usa `EMAIL_IMAP_PASSWORD`)
- `EMAIL_SMTP_HOST` (legacy: `GMAIL_SMTP_HOST`, por defecto `smtp.gmail.com`)
- `EMAIL_SMTP_PORT` (por defecto `465`)
- `EMAIL_DEFAULT_FROM` (legacy: `EMAIL_SENDER`, por defecto usa `EMAIL_SMTP_EMAIL`)
- `EMAIL_DEFAULT_CC` (legacy: `EMAIL_CC`, opcional; admite lista CSV)
- `EMAIL_SIGNATURE_ASSETS_DIR` (por defecto `/config/media/signature`; assets inline para firma HTML)
- `EMAIL_WEBHOOK_NOTIFY_URL` (legacy: `EMAIL_AGENT_WEBHOOK_NOTIFY`; por defecto reutiliza `WORKDAY_WEBHOOK_START_URL`)
- `EMAIL_ALLOWED_FROM_WHITELIST` (array de remitentes permitidos)
- `EMAIL_BACKGROUND_INTERVAL_HOURS` (por defecto `4`)
- `SUPPORT_TELEGRAM_URL` (URL del grupo de soporte para flujos de updates/listings/socials)
- `SUPPORT_MARKETING_URL` (URL base de marketing para rutas `#advertising`, `/create-socials` y `${SUPPORT_MARKETING_URL}/my-orders`)
- `SUPPORT_USER_URL_PREFIX` (prefijo de URL habitual del usuario para no pedir contrato duplicado)

Campos obligatorios para detección/regeneración:

- `EMAIL_OPENAI_API_KEY`
- `EMAIL_IMAP_EMAIL`
- `EMAIL_IMAP_PASSWORD`

Campos recomendados para envío SMTP desde UI/API:

- `EMAIL_SMTP_EMAIL`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT`

Firma con imágenes inline (opcional):

- Configura `EMAIL_SIGNATURE_ASSETS_DIR` y guarda imágenes PNG con estos nombres:
  - `logo.png`, `linkedin.png`, `tiktok.png`, `instagram.png`, `twitter.png`, `youtube.png`, `telegram.png`
- En la firma (`/email-agent/settings`, campo `signature`) usa placeholders:
  - `{{logo}}`, `{{linkedin}}`, `{{tiktok}}`, `{{instagram}}`, `{{twitter}}`, `{{youtube}}`, `{{telegram}}`
- En envío SMTP se renderiza versión HTML con imágenes inline por `cid`; texto plano se mantiene como fallback.

### Agente issues (`issue_agent`)

- `ISSUE_TARGET_WEB_URL`
- `ISSUE_OPENAI_API_KEY` (legacy: `OPENAI_API_KEY`)
- `ISSUE_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-4o-mini`)
- `ISSUE_OPENAI_STYLE_LAW` (ley/estilo para que escriba issues como tú)
- `ISSUE_WEBHOOK_URL` (legacy: `HASS_WEBHOOK_URL_ISSUE`; por defecto reutiliza `WORKDAY_WEBHOOK_START_URL`)
- `ISSUE_REPO_FRONTEND` / `ISSUE_BUG_PARENT_ISSUE_FRONTEND` (opcional; aliases legacy: `ISSUE_BUG_PARENT_REPO_FRONTEND`, `ISSUE_BUG_PARENT_REPO_FRONT`)
- `ISSUE_REPO_BACKEND` / `ISSUE_BUG_PARENT_ISSUE_BACKEND` (opcional; aliases legacy: `ISSUE_BUG_PARENT_REPO_BACKEND`, `ISSUE_BUG_PARENT_REPO_BACK`)
- `ISSUE_REPO_MANAGEMENT` / `ISSUE_BUG_PARENT_ISSUE_MANAGEMENT` (opcional; alias legacy: `ISSUE_BUG_PARENT_REPO_MANAGEMENT`)

Campos obligatorios para que `issue_agent` pueda generar/rellenar issues:

- `ISSUE_TARGET_WEB_URL`
- `ISSUE_OPENAI_API_KEY`

Ejemplo mínimo para correo (IMAP):

```json
{
  "email_imap_email": "usuario@example.com",
  "email_imap_password": "tu-password-imap",
  "email_imap_host": "imap.example.com",
  "email_openai_api_key": "sk-...",
  "email_openai_model": "gpt-4o-mini"
}
```

Ejemplo recomendado para correo (IMAP + SMTP + firma/CC):

```json
{
  "email_imap_email": "usuario@example.com",
  "email_imap_password": "tu-password-imap",
  "email_imap_host": "imap.example.com",
  "email_smtp_email": "usuario@example.com",
  "email_smtp_password": "tu-password-smtp",
  "email_smtp_host": "smtp.example.com",
  "email_smtp_port": 465,
  "email_default_from": "soporte@example.com",
  "email_default_cc": "ops@example.com, audit@example.com",
  "email_signature_assets_dir": "/config/media/signature",
  "email_openai_api_key": "sk-...",
  "email_openai_model": "gpt-4o-mini"
}
```

## Ejecución local

```bash
python -m pip install -r requirements.txt
```

Modo desarrollo con recarga automática al detectar cambios:

```bash
./scripts/dev_local.sh
```

Alternativa equivalente (sin script):

```bash
python -m uvicorn main:APP --host 0.0.0.0 --port 8099 --reload
```

Modo normal (sin autoreload):

```bash
python -m uvicorn main:APP --host 0.0.0.0 --port 8099
```

## Endpoints

### Base

- `GET /health`
- `GET /ui`

### Agente web

- `POST /run/{job_name}`
- `GET /jobs`
- `GET /status`
- `GET /settings`
- `POST /settings`
- `GET /events`
- `GET /history`
- `POST /retry-failed`

Notas:

- El scheduler interno lanza `workday_flow` automáticamente en weekdays cuando la config obligatoria está completa.
- La ventana de arranque automático se evalúa entre `06:57` y `09:30` (hora local de `WORKDAY_TIMEZONE`).
- Entre `08:31` y `09:30` usa modo rescate para ejecutar el primer click de forma inmediata.
- `GET /settings` y `POST /settings` permiten definir un rango (`blocked_start_date`, `blocked_end_date`) en el que no se inicia automáticamente, igual que fines de semana.
- Si falta configuración obligatoria, el scheduler no ejecuta y `POST /run/{job_name}` devuelve `400`.
- El estado runtime de `workday_agent` se persiste en `/data/workday_runtime_state.json`.
- Los eventos runtime se registran en `/data/workday_runtime_events.jsonl`.
- La configuración editable de bloqueo por fechas se persiste en `/data/workday_agent_config.json`.
- Si el proceso se reinicia durante una ejecución activa, al arrancar intenta reanudar desde la fase guardada.

### Agente de correo

- `POST /email-agent/check-new`
- `GET /email-agent/suggestions`
- `POST /email-agent/suggestions/{suggestion_id}/regenerate`
- `POST /email-agent/suggestions/{suggestion_id}/status`
- `POST /email-agent/suggestions/{suggestion_id}/send`
- `POST /email-agent/suggestions/manual`
- `GET /email-agent/settings`
- `POST /email-agent/settings`
- `GET /email-agent/ui` (legacy, redirige a `/ui`)

Control de acceso básico:

- Si `JOB_SECRET` está definido, los endpoints protegidos exigen secreto.
- Se acepta por header `X-Job-Secret` o por query string `?secret=...`.
- En `POST /run/{job_name}` también se acepta en body JSON como `payload.secret` (retrocompatibilidad).

### Agente de issues

- `GET /issue-agent/status`
- `GET /issue-agent/events`
- `POST /issue-agent/generate`
- `POST /issue-agent/submit`
- `POST /issue-agent/report`

Notas:

- El flujo de Playwright está preparado para modo no-headless y login manual.
- Puede rellenar `title`, `description`, `comment` (opcional), clickar desplegables y pulsar botón submit según selectores enviados.
- Genera enlace a partir de `ISSUE_TARGET_WEB_URL` + input de usuario.
- Incluye scheduler diario para enviar estado a webhook configurado.
- La UI integrada (`/ui`) incluye pestaña para generar y enviar issues.

## Flujo issue recomendado

1. Llama `POST /issue-agent/generate` con tu contexto de issue.
2. Revisa el resultado (`title`, `description`, `comment`, `generated_link`).
3. Llama `POST /issue-agent/submit` con selectores del formulario destino.
4. Usa `POST /issue-agent/report` para notificar manualmente incidencias al webhook destino.

## Flujo correo recomendado

1. Llamar `POST /email-agent/check-new` desde una automatización programada.
2. El agente detecta nuevos correos y genera borradores.
3. Opcionalmente dispara notificación por webhook por cada sugerencia nueva.
4. Abrir `GET /ui` para revisar cada propuesta.
5. Pedir ajustes con “Suggest changes”.
6. Enviar desde la propia UI (To/CC/Subject/Body) con `Send email`.

Notas:

- Además de llamadas manuales, el servicio ejecuta chequeo automático cada `EMAIL_BACKGROUND_INTERVAL_HOURS`.
- Solo se generan sugerencias para remitentes en `EMAIL_ALLOWED_FROM_WHITELIST`.

## Contexto y memoria del agente de correo

- Config: `/data/email_agent_config.json`
- Memoria de respuestas: `/data/email_agent_memory.jsonl`
- Bandeja local de propuestas: `/data/email_agent_suggestions.json`
