# Agent Runner

Servicio Python (FastAPI + Playwright) para ejecutar automatizaciones web y exponerlas por API HTTP.

## Estructura (agentes por carpeta)

Ahora hay dos agentes separados por carpeta y `main.py` actúa como **compositor**:

- `agents/workday_agent/service.py`: lógica del agente de interacción web (workday flow).
- `routers/workday_agent.py`: endpoints del agente web (`/run/{job_name}`, `/jobs`).
- `agents/email_agent/service.py`: lógica del agente de correo (Gmail + OpenAI + memoria + webhook).
- `routers/email_agent.py`: endpoints y UI del agente de correo.
- `main.py`: carga configuración, instancia servicios y monta routers.

## Requisitos

- Python 3.11+
- Dependencias en `requirements.txt`

## Configuracion

La app admite configuración por variables de entorno y, cuando corre dentro del add-on, también lee `/data/options.json`.

Variables relevantes:

- `JOB_SECRET`
- `HASS_WEBHOOK_URL_STATUS`
- `HASS_WEBHOOK_URL_FINAL`
- `SSO_EMAIL`
- `TARGET_URL`
- `TIMEZONE` (por defecto `Europe/Madrid`)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (por defecto `gpt-4o-mini`)
- `GMAIL_EMAIL`
- `GMAIL_APP_PASSWORD` (app password de Gmail)
- `GMAIL_IMAP_HOST` (por defecto `imap.gmail.com`)
- `EMAIL_AGENT_WEBHOOK_NOTIFY` (si no se define, reutiliza `HASS_WEBHOOK_URL_STATUS`)

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

### Agente de correo

- `POST /email-agent/check-new`
- `GET /email-agent/suggestions`
- `POST /email-agent/suggestions/{suggestion_id}/regenerate`
- `POST /email-agent/suggestions/{suggestion_id}/status`
- `GET /email-agent/ui`

## Flujo correo recomendado

1. Se llama `POST /email-agent/check-new` desde una automatización programada.
2. El agente detecta nuevos correos, genera borradores en inglés (por defecto).
3. Envía webhook para disparar una notificación de Telegram.
4. Abres `GET /email-agent/ui` para revisar cada propuesta.
5. Pides ajustes con “Suggest changes” y finalmente copias el texto para pegarlo manualmente en Gmail.

## Contexto y memoria del agente de correo

- Config: `/data/email_agent_config.json`
- Memoria de respuestas: `/data/email_agent_memory.jsonl`
- Bandeja local de propuestas: `/data/email_agent_suggestions.json`
