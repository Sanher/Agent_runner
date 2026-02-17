# Agent Runner

Servicio Python (FastAPI + Playwright) para ejecutar automatizaciones web y exponerlas por API HTTP.

## Estructura (agentes por carpeta)

Ahora hay dos agentes separados por carpeta y `main.py` actúa como **compositor**:

- `agents/workday_agent/service.py`: lógica del agente de interacción web (workday flow).
- `routers/workday_agent.py`: endpoints del agente web (`/run/{job_name}`, `/jobs`).
- `agents/email_agent/service.py`: lógica del agente de correo (Gmail + OpenAI + memoria + webhook).
- `routers/email_agent.py`: endpoints y UI del agente de correo.
- `agents/issue_agent/service.py`: lógica del agente de issues (OpenAI + Playwright + memoria + webhook).
- `routers/issue_agent.py`: endpoints del agente de issues (`/issue-agent/*`).
- `main.py`: carga configuración, instancia servicios y monta routers.

## Requisitos

- Python 3.11+
- Dependencias en `requirements.txt`

## Configuracion por agente

La app admite configuración por variables de entorno y, cuando corre dentro del add-on, también lee `/data/options.json`.

`main.py` carga claves nuevas separadas por agente y mantiene compatibilidad con las antiguas.

### Compartido

- `JOB_SECRET`

### Agente web (`workday_agent`)

- `WORKDAY_TARGET_URL` (legacy: `TARGET_URL`)
- `WORKDAY_SSO_EMAIL` (legacy: `SSO_EMAIL`)
- `WORKDAY_TIMEZONE` (legacy: `TIMEZONE`, por defecto `Europe/Madrid`)
- `WORKDAY_WEBHOOK_START_URL` (legacy: `WORKDAY_WEBHOOK_STATUS_URL` / `HASS_WEBHOOK_URL_STATUS`)
- `WORKDAY_WEBHOOK_FINAL_URL` (legacy: `HASS_WEBHOOK_URL_FINAL`)
- `WORKDAY_WEBHOOK_START_BREAK_URL` (nuevo, webhook dedicado al click `start_break`)
- `WORKDAY_WEBHOOK_STOP_BREAK_URL` (nuevo, webhook dedicado al click `stop_break`)

Campos obligatorios para que `workday_agent` se considere válido y arranque automático:

- `JOB_SECRET`
- `WORKDAY_TARGET_URL`
- `WORKDAY_WEBHOOK_START_URL`
- `WORKDAY_WEBHOOK_FINAL_URL`
- `WORKDAY_WEBHOOK_START_BREAK_URL`
- `WORKDAY_WEBHOOK_STOP_BREAK_URL`

`WORKDAY_SSO_EMAIL` sigue siendo opcional.

### Agente correo (`email_agent`)

- `EMAIL_OPENAI_API_KEY` (legacy: `OPENAI_API_KEY`)
- `EMAIL_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-4o-mini`)
- `EMAIL_IMAP_EMAIL` (legacy: `GMAIL_EMAIL`)
- `EMAIL_IMAP_PASSWORD` (legacy: `GMAIL_APP_PASSWORD`, app password de Gmail)
- `EMAIL_IMAP_HOST` (legacy: `GMAIL_IMAP_HOST`, por defecto `imap.gmail.com`)
- `EMAIL_WEBHOOK_NOTIFY_URL` (legacy: `EMAIL_AGENT_WEBHOOK_NOTIFY`; por defecto reutiliza `WORKDAY_WEBHOOK_START_URL`)
- `EMAIL_ALLOWED_FROM_WHITELIST` (array; solo se generan sugerencias de estos remitentes, ej. `["info@dextools.io"]`)
- `EMAIL_BACKGROUND_INTERVAL_HOURS` (por defecto `4`; chequeo automático en segundo plano)

Campos obligatorios para que `email_agent` pueda ejecutar detección/regeneración:

- `EMAIL_OPENAI_API_KEY`
- `EMAIL_IMAP_EMAIL`
- `EMAIL_IMAP_PASSWORD`

### Agente issues (`issue_agent`)

- `ISSUE_TARGET_WEB_URL`
- `ISSUE_OPENAI_API_KEY` (legacy: `OPENAI_API_KEY`)
- `ISSUE_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-4o-mini`)
- `ISSUE_OPENAI_STYLE_LAW` (ley/estilo para que escriba issues como tú)
- `ISSUE_WEBHOOK_URL` (legacy: `HASS_WEBHOOK_URL_ISSUE`; por defecto reutiliza `WORKDAY_WEBHOOK_START_URL`)

Campos obligatorios para que `issue_agent` pueda generar/rellenar issues:

- `ISSUE_TARGET_WEB_URL`
- `ISSUE_OPENAI_API_KEY`

Ejemplo mínimo para correo (Gmail IMAP):

```json
{
  "email_imap_email": "tu-cuenta@gmail.com",
  "email_imap_password": "tu-app-password-de-gmail",
  "email_imap_host": "imap.gmail.com",
  "email_openai_api_key": "sk-...",
  "email_openai_model": "gpt-4o-mini"
}
```

## Ejecucion local

```bash
pip install -r requirements.txt
uvicorn main:APP --host 0.0.0.0 --port 8099
```

## Endpoints

### Base

- `GET /health`

### Agente web (workday)

- `POST /run/{job_name}`
- `GET /jobs`
- `GET /status`

Notas:

- El scheduler interno lanza `workday_flow` automáticamente en weekdays cuando la config obligatoria está completa.
- La ventana de arranque automático se evalúa entre `06:57` y `08:31` (hora local de `WORKDAY_TIMEZONE`).
- Si falta configuración obligatoria, el scheduler no ejecuta y `POST /run/{job_name}` devuelve `400`.
- El estado runtime de `workday_agent` se persiste en `/data/workday_runtime_state.json`.
- Los eventos runtime se registran en `/data/workday_runtime_events.jsonl`.
- Si el add-on se reinicia durante una ejecución activa, al arrancar intenta reanudar desde la fase guardada.

### Agente de correo

- `POST /email-agent/check-new`
- `GET /email-agent/suggestions`
- `POST /email-agent/suggestions/{suggestion_id}/regenerate`
- `POST /email-agent/suggestions/{suggestion_id}/status`
- `POST /email-agent/suggestions/manual`
- `GET /email-agent/settings`
- `POST /email-agent/settings`
- `GET /email-agent/ui`

Seguridad:

- Si `JOB_SECRET` está definido, los endpoints de `email_agent` exigen secreto.
- Se puede enviar en header `X-Job-Secret` o en query string `?secret=...`.
- En `POST /run/{job_name}` también se acepta en body JSON como `payload.secret` (retrocompatibilidad).
- Para UI por navegador: `GET /email-agent/ui?secret=...`

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
- Incluye scheduler diario para enviar estado a webhook de HA.
- Emite logs de diagnóstico pensados para Home Assistant add-ons (auth, config y errores de ejecución).

## Flujo issue recomendado

1. Llama `POST /issue-agent/generate` con tu contexto de issue.
2. Revisa el resultado (`title`, `description`, `comment`, `generated_link`).
3. Llama `POST /issue-agent/submit` con selectores del formulario destino.
4. Usa `POST /issue-agent/report` para notificar manualmente incidencias a HA.

## Flujo correo recomendado

1. Se llama `POST /email-agent/check-new` desde una automatización programada.
2. El agente detecta nuevos correos, genera borradores en inglés (por defecto).
3. Envía webhook para disparar una notificación de Telegram.
4. Abres `GET /email-agent/ui` para revisar cada propuesta.
5. Pides ajustes con “Suggest changes” y finalmente copias el texto para pegarlo manualmente en Gmail.

Notas:

- Además de llamadas manuales, el servicio ejecuta chequeo automático en segundo plano cada `EMAIL_BACKGROUND_INTERVAL_HOURS`.
- Solo se generan sugerencias para emails cuyo remitente esté en `EMAIL_ALLOWED_FROM_WHITELIST`.

## Contexto y memoria del agente de correo

- Config: `/data/email_agent_config.json`
- Memoria de respuestas: `/data/email_agent_memory.jsonl`
- Bandeja local de propuestas: `/data/email_agent_suggestions.json`
