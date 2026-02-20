# Answers Agent

Servidor FastAPI para recibir mensajes de Telegram y responder con API de ChatGPT, con memoria local y flujos de escalado/manual review.

## Características implementadas

- Webhook de Telegram para mensajes de texto.
- Respuesta con OpenAI (`/v1/responses`) con prompt de seguridad.
- Retraso configurable antes de responder (`BOT_RESPONSE_DELAY_SECONDS`) para evitar respuesta instantánea.
- Historial local de conversación en `answers_agent/data/conversations.json`.
- Si el usuario repite la misma pregunta: respuesta fija `The dev team is checking.`
- Fallback cuando no sabe responder: `Dame un segundo para mirarlo.`
- Detección inicial de spam con intento de bloqueo; si falla, crea tarea manual.
- Registro de issues pendientes con contexto en `answers_agent/data/pending_issues.json`.
- Endpoint para respuesta manual y edición de mensaje previo en Telegram.

## Variables de entorno

- `TELEGRAM_BOT_TOKEN`: token del bot.
- `TELEGRAM_WEHBOOK_SECRET` (opcional, recomendado): secreto para validar `X-Telegram-Bot-Api-Secret-Token` en el webhook.
- `OPENAI_API_KEY`: API key de OpenAI.
- `OPENAI_MODEL` (opcional, default: `gpt-4o-mini`).
- `BOT_RESPONSE_DELAY_SECONDS` (opcional, default: `8`).
- `REQUEST_TIMEOUT_SECONDS` (opcional, default: `30`).
- `LOG_LEVEL` (opcional): usa `DEBUG` para ver trazas de diagnóstico del webhook en logs de HA.
- `SUPPORT_TELEGRAM_URL` (opcional): grupo de soporte al que se redirige en casos de updates/listings/socials.
- `SUPPORT_MARKETING_URL` (opcional): URL base para flujos de marketing/publicidad.
- `SUPPORT_USER_URL_PREFIX` (opcional): prefijo de URLs compartidas por usuarios (evita pedir contrato dos veces cuando ya comparten URL).

También se aceptan por compatibilidad `ANSWERS_WEBHOOK_SECRET` y `TELEGRAM_WEBHOOK_SECRET`.

## Reglas de soporte (resumen)

- Nunca pedir información personal sensible ni clave privada.
- Si llega solo un saludo sin contexto (`hello`, `hola`, etc.), no se responde ni se guarda conversación.
- Si parece spam/promoción prehecha, se bloquea y reporta sin gastar respuesta de IA.
- Para casos de soporte frecuentes (refunds, locks, audits, exchange/blockchain integration, score, ads, etc.) aplica workflow específico antes de usar OpenAI.

## Ejecutar

```bash
uvicorn answers_agent.server:APP --host 0.0.0.0 --port 8100 --reload
```

## Endpoints

- `GET /answers_agent/health`
- `GET /answers_agent/guidelines`
- `POST /answers_agent/webhook/telegram`
- `POST /answers_agent/manual/respond`
- `GET /answers_agent/pending-issues`
- `GET /answers_agent/manual-actions`

## Privacidad

El historial se guarda **solo en local** dentro de `answers_agent/data/` para análisis interno y mejora manual.
No hay envío automático de este historial a servicios externos.
