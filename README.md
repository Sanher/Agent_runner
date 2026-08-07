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
- `agents/discord_agent/service.py`: lector de canales Discord, resúmenes IA y propuestas de tareas en modo solo lectura.
- `routers/discord_agent.py`: endpoints del agente Discord (`/discord-agent/*`).
- `agents/telegram_reader/service.py`: lector Telegram alimentado por el fan-out del webhook de Answers, con resúmenes IA y propuestas de tareas en modo solo lectura.
- `routers/telegram_reader.py`: endpoints del lector Telegram (`/telegram-reader/*`).
- `runners/intake_local.py`: consola local aislada para revisar Discord y datos Telegram de prueba, sin iniciar el resto de agentes ni tomar el webhook compartido.
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
- `EMAIL_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-5-mini`)
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
- `ISSUE_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-5-mini`)
- `ISSUE_OPENAI_STYLE_LAW` (ley/estilo para que escriba issues como tú)
- `ISSUE_WEBHOOK_URL` (legacy: `HASS_WEBHOOK_URL_ISSUE`; por defecto reutiliza `WORKDAY_WEBHOOK_START_URL`)
- `ISSUE_REPO_FRONTEND` / `ISSUE_BUG_PARENT_ISSUE_FRONTEND` (opcional; aliases legacy: `ISSUE_BUG_PARENT_REPO_FRONTEND`, `ISSUE_BUG_PARENT_REPO_FRONT`)
- `ISSUE_REPO_BACKEND` / `ISSUE_BUG_PARENT_ISSUE_BACKEND` (opcional; aliases legacy: `ISSUE_BUG_PARENT_REPO_BACKEND`, `ISSUE_BUG_PARENT_REPO_BACK`)
- `ISSUE_REPO_MANAGEMENT` / `ISSUE_BUG_PARENT_ISSUE_MANAGEMENT` (opcional; alias legacy: `ISSUE_BUG_PARENT_REPO_MANAGEMENT`)

Campos obligatorios para que `issue_agent` pueda generar/rellenar issues:

- `ISSUE_TARGET_WEB_URL`
- `ISSUE_OPENAI_API_KEY`

### Agente Discord (`discord_agent`)

- `DISCORD_ENABLED` (por defecto `false`; debe activarse explícitamente)
- `DISCORD_BOT_TOKEN` (secreto del bot de Discord)
- `DISCORD_OPENAI_API_KEY` (clave de OpenAI compartida por los lectores de Discord y Telegram)
- `DISCORD_OPENAI_MODEL` (por defecto `gpt-5-mini`)
- `DISCORD_CHANNEL_IDS` (CSV en variables de entorno; lista JSON en `options.json`)
- `DISCORD_POLL_INTERVAL_MINUTES` (por defecto `15`)
- `DISCORD_SUMMARY_MIN_MESSAGES` (por defecto `5`; rango `1`–`100`)
- `DISCORD_RETENTION_DAYS` (por defecto `14`)

En Home Assistant las opciones canónicas se llaman igual en minúsculas (`discord_enabled`, `discord_bot_token`, etc.) y se guardan en `/data/options.json`; las variables `DISCORD_*` se reservan para entornos locales. Después de modificar cualquiera de estas opciones en Home Assistant, reinicia el add-on para que recargue la configuración.

Con `DISCORD_ENABLED=false`, el agente no inicia ningún planificador ni contacta Discord. Cuando está activo, solo realiza lecturas de los canales incluidos en `DISCORD_CHANNEL_IDS`; no implementa operaciones para enviar, editar, reaccionar ni borrar mensajes.

Antes de invitar el bot al servidor de pruebas, activa el intent privilegiado **Message Content** en el apartado *Bot* del portal de desarrolladores de Discord. En el rol del bot concede solo `View Channel` y `Read Message History` sobre los canales que vayas a autorizar; deja sin conceder `Send Messages`, `Manage Messages` y permisos de administración. Discord devuelve el contenido de los mensajes vacío sin ese intent y exige visibilidad e historial para recuperar los mensajes del canal. Si el agente recibe cualquier mensaje no-bot sin texto legible, señala la lectura como parcial y no avanza el cursor para reintentarlo después de corregir el intent o los permisos.

Al añadir un canal nuevo, el primer ciclo fija un punto de inicio **desde ahora** con una lectura mínima del identificador del último mensaje. No crea un resumen ni envía el contenido anterior a OpenAI; a partir de ese punto solo procesa mensajes posteriores. La UI también permite iniciar ese punto de forma explícita. Si el canal estaba vacío, el marcador se conserva igualmente para que su primer mensaje futuro no active una lectura retrospectiva.

Cuando haya trabajo concreto, pendiente y respaldado por mensajes, la IA puede separar incidencias independientes en varias sugerencias de tipo `bug` o `task`. Los mensajes informativos, pruebas, duplicados, elementos resueltos y conversaciones sin acción no deben generar una sugerencia. Toda clasificación requiere revisión humana: cada tarjeta puede trasladarse solo como borrador al formulario de Issues o descartarse localmente con motivo (`created`, `duplicate`, `not_actionable` u `other`). El descarte es reversible mientras el resumen se conserve; no crea, envía ni modifica ningún issue ni mensaje de Discord.

Si un canal acumula un atraso superior a la ventana segura de recuperación después de su punto de inicio, el agente procesa la parte más reciente, registra el aviso en el resumen y evita quedar bloqueado repitiendo la misma consulta. Los resúmenes derivados pueden contener información sensible: accede a la app mediante el ingress de Home Assistant y no expongas su puerto directamente. El acceso directo requiere siempre `JOB_SECRET`; una cabecera `X-Ingress-Path` enviada por un cliente no la sustituye.

Campos obligatorios con el agente activado:

- `DISCORD_BOT_TOKEN`
- `DISCORD_OPENAI_API_KEY`
- `DISCORD_CHANNEL_IDS`

### Lector de Telegram (`telegram_reader`)

- `TELEGRAM_READER_ENABLED` (por defecto `false`; debe activarse explícitamente)
- `TELEGRAM_READER_CHAT_IDS` (CSV en variables de entorno; lista JSON en `options.json`)
- `TELEGRAM_READER_SUMMARY_MIN_MESSAGES` (por defecto `5`; rango `1`–`100`)
- `TELEGRAM_READER_RETENTION_DAYS` (por defecto `14`)
- `DISCORD_OPENAI_API_KEY` y `DISCORD_OPENAI_MODEL` (credencial y modelo compartidos; no existe una segunda clave de OpenAI para Telegram)

En la configuración del add-on, los nombres canónicos equivalentes son `telegram_reader_enabled`, `telegram_reader_chat_ids`, `telegram_reader_summary_min_messages` y `telegram_reader_retention_days`. Mantén cada chat ID como texto, no como número, para no perder precisión. Al activarlo también deben seguir configurados `answers_telegram_bot_token`, `answers_webhook_secret` y `discord_openai_api_key`; `discord_openai_model` conserva el valor por defecto `gpt-5-mini`. Reinicia el add-on después de cambiar cualquiera de esos valores.

El lector reutiliza indirectamente el bot Business de Answers, pero no su servicio de respuesta ni sus operaciones de escritura. El token y el webhook se configuran **una sola vez** en `answers_agent`; el webhook autenticado entrega una copia interna del update a Answers y, cuando `TELEGRAM_READER_ENABLED=true`, al lector. No existe una credencial de bot propia del lector.

El lector no configura webhooks, no hace long polling, no llama a ninguna API de Telegram y no contiene métodos para enviar, editar, borrar o reaccionar a mensajes. Solo admite mensajes entrantes con texto, procedentes de un cliente, en chats privados incluidos en `TELEGRAM_READER_CHAT_IDS`; ignora mensajes salientes del bot, ediciones, grupos, adjuntos y otros tipos de update hasta que exista una ampliación explícita. Al resumir se envía a OpenAI únicamente el texto mínimo y sus IDs de evidencia; el identificador del chat se conserva solo localmente para el enrutamiento. Un fallo al resumir o al contactar OpenAI se aísla del flujo de Answers y no altera la respuesta del bot al usuario. Consulta la documentación oficial de [actualizaciones y webhooks de Telegram](https://core.telegram.org/bots/api#getting-updates).

Al iniciarse con una configuración válida, el lector fija automáticamente un punto de inicio por chat desde ahora. `POST /telegram-reader/baseline` es una operación local e idempotente que permite inicializar o confirmar ese límite de forma manual; no consulta Telegram ni convierte mensajes anteriores en análisis retrospectivo. Solo los mensajes posteriores, recibidos por el webhook compartido y pertenecientes a la lista autorizada, pueden formar resúmenes. Si se desactiva el lector, falta una credencial compartida, o se retira y vuelve a añadir un chat, se descarta el texto pendiente y la siguiente activación crea un límite nuevo para ese chat. Mientras un chat no alcanza el umbral de resumen, el lector conserva de forma temporal el mínimo texto pendiente en `/data/telegram_reader/state.json`; se elimina al resumir o al caducar `TELEGRAM_READER_RETENTION_DAYS`, incluso si después se desactiva el lector, y nunca se devuelve por sus endpoints.

Las tareas se generan únicamente como sugerencias separadas, con evidencia por mensaje, y se revisan de forma humana. Cada tarea puede descartarse localmente como `created`, `duplicate`, `not_actionable` u `other`, o restaurarse mientras se conserve el resumen. El lector nunca crea, envía ni modifica un issue automáticamente.

### Agente respuestas (`answers_agent`)

- `ANSWERS_DATA_DIR` (por defecto `/data/answers_agent`; persistencia de conversaciones/estado)
- `ANSWERS_TELEGRAM_BOT_TOKEN` (legacy: `TELEGRAM_BOT_TOKEN`; único token del bot Business y de su entrega webhook compartida con `telegram_reader`)
- `ANSWERS_OPENAI_API_KEY` (legacy: `OPENAI_API_KEY`)
- `ANSWERS_OPENAI_MODEL` (legacy: `OPENAI_MODEL`, por defecto `gpt-5-mini`)
- `ANSWERS_REQUEST_TIMEOUT_SECONDS` (por defecto `30`)
- `ANSWERS_WEBHOOK_SECRET` (legacy: `TELEGRAM_WEBHOOK_SECRET`; también acepta `telegram_wehbook_secret` en `options.json` por retrocompatibilidad)

Ejemplo mínimo para correo (IMAP):

```json
{
  "email_imap_email": "usuario@example.com",
  "email_imap_password": "tu-password-imap",
  "email_imap_host": "imap.example.com",
  "email_openai_api_key": "sk-...",
  "email_openai_model": "gpt-5-mini"
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
  "email_openai_model": "gpt-5-mini"
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
python -m uvicorn main:APP --host 0.0.0.0 --port 8099 --reload --no-proxy-headers
```

Modo normal (sin autoreload):

```bash
python -m uvicorn main:APP --host 0.0.0.0 --port 8099 --no-proxy-headers
```

### Consola local de intake (Discord y Telegram)

La consola aislada no importa `main.py`, no lee `/data/options.json` y no inicia Workday, Email, Answers ni Issue Agent. Solo construye el lector local de Discord, no inicia un scheduler automático y se enlaza exclusivamente a loopback. Telegram puede aparecer como fuente de revisión si se inyectan datos de prueba, pero la consola no recibe webhooks ni conecta con el bot Business compartido.

```bash
cp .env.example .env
# Edita .env con placeholders reales solo en tu Mac local.
set -a
source .env
set +a
python -m runners.intake_local
```

Por defecto escucha en `http://127.0.0.1:8098`. Abre `http://127.0.0.1:8098/#<JOB_SECRET>` para que el HTML autentique sus llamadas locales con `X-Job-Secret`: el fragmento no se envía al servidor y se elimina del historial visible al cargar. El antiguo formato `/?secret=<JOB_SECRET>` sigue funcionando de forma transitoria, pero también se limpia inmediatamente; sustitúyelo por el fragmento en tus marcadores. La página de arranque no contiene datos y las operaciones de datos permanecen autenticadas. No reenvíes ni expongas ese puerto; Ingress sigue siendo la vía recomendada para el add-on. La consola ofrece lectura y baseline manual solo para Discord, tarjetas de revisión y un borrador local de Issue: no llama a `issue-agent/submit`, no crea un issue y no publica en Discord o Telegram.

`JOB_SECRET` debe ser un secreto local único, no vacío y distinto de `false`, `none` o `null`. `INTAKE_LOCAL_DATA_DIR`, `INTAKE_LOCAL_HOST` e `INTAKE_LOCAL_PORT` son exclusivamente locales. El runner rechaza cualquier host distinto de loopback y cualquier directorio dentro de las raíces runtime habituales de Home Assistant (`/data`, `/config`, `/share`, `/media`, `/ssl` y `/backup`), para no reutilizar ni modificar el almacenamiento del add-on. No apuntes el bot Business ni su webhook compartido a esta consola: interrumpiría Answers. Una prueba Telegram realmente local requerirá en el futuro un bot de pruebas dedicado y un transporte explícito que se diseñe y apruebe por separado; no debe reutilizar el bot compartido.

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

- El ingress de Home Assistant se acepta solo desde su proxy interno documentado (`172.30.32.2`); fuera del ingress, los endpoints protegidos siempre exigen `JOB_SECRET`. El despliegue debe conservar esa IP de par TCP y no confiar en `X-Forwarded-For` enviado por clientes.
- Se acepta por header `X-Job-Secret` o por query string `?secret=...`.
- En `POST /run/{job_name}` también se acepta en body JSON como `payload.secret` (retrocompatibilidad).

### Agente de issues

- `GET /issue-agent/status`
- `GET /issue-agent/events`
- `POST /issue-agent/generate`
- `POST /issue-agent/submit`
- `POST /issue-agent/report`

### Agente Discord

- `GET /discord-agent/status`
- `POST /discord-agent/poll`
- `POST /discord-agent/channels/{channel_id}/baseline`
- `GET /discord-agent/summaries`
- `GET /discord-agent/summaries/{summary_id}`
- `POST /discord-agent/summaries/{summary_id}/tasks/{task_key}/dismiss`
- `DELETE /discord-agent/summaries/{summary_id}/tasks/{task_key}/dismiss`

`POST /discord-agent/poll` permite probar manualmente un ciclo de lectura; para un canal sin punto de inicio, ese ciclo lo establece sin resumir contenido anterior. La UI solo puede trasladar una tarea candidata al formulario de Issues; crear o enviar un issue siempre requiere la revisión manual existente. Los endpoints de descarte solo guardan una decisión local de revisión y siguen requiriendo autenticación incluso si la integración queda desactivada (`JOB_SECRET` en acceso directo).

### Lector de Telegram

- `GET /telegram-reader/status`
- `POST /telegram-reader/baseline`
- `POST /telegram-reader/process`
- `GET /telegram-reader/summaries`
- `GET /telegram-reader/summaries/{summary_id}`
- `POST /telegram-reader/summaries/{summary_id}/tasks/{task_key}/dismiss`
- `DELETE /telegram-reader/summaries/{summary_id}/tasks/{task_key}/dismiss`

`POST /telegram-reader/baseline` inicia el lector desde el momento actual sin consultar Telegram. `POST /telegram-reader/process` procesa mensajes que ya haya recibido el webhook compartido de Answers y que estén pendientes de resumen; tampoco consulta Telegram. Los endpoints no exponen operaciones de escritura de Telegram ni creación automática de Issues; al igual que Discord, el resultado es una sugerencia revisable y un borrador local. Todos requieren autenticación, incluso cuando el lector está desactivado.

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

## Contexto y memoria del agente de respuestas

- Conversaciones: `/data/answers_agent/conversations.json`
- Estado de revisión: `/data/answers_agent/review_state.json`
- Archivado: `/data/answers_agent/archived_chats.json`
- Pendientes: `/data/answers_agent/pending_issues.json`
- Usuarios bloqueados: `/data/answers_agent/blocked_users.json`
- Patrones spam: `/data/answers_agent/spam_patterns.json`

Notas:

- Si `ANSWERS_DATA_DIR` apunta fuera de `/data`, el endpoint `GET /health` marcará `data_dir_within_persistent_data_dir=false`.
- En despliegues dentro de Home Assistant/Supervisor conviene mantener `answers_agent` dentro de `/data` para no perder estado al recrear el contenedor.
