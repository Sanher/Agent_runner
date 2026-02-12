# Agent Runner (Home Assistant add-on)

Este repositorio está preparado para ejecutarse como add-on de Home Assistant.

## Variables desde configuración del add-on

Se inyectan a través de `options`/`schema` en `config.yaml`:

- `job_secret`
- `hass_webhook_url_status` (feedback por paso; útil para Telegram vía automatización HA)
- `hass_webhook_url_final` (resultado final)
- `sso_email`
- `target_url`
- `timezone` (zona horaria para calcular ventanas, p.ej. `Europe/Madrid`)

El directorio persistente siempre es `/data`.

Las ventanas horarias se calculan **dentro del contenedor** usando la hora local del servidor/add-on (configurable con `timezone`), por lo que no hacen falta llamadas externas para calcular horarios.

## Endpoints

- `GET /health`
- `GET /jobs`
- `POST /run/{job_name}`

## Flujo incluido

- `workday_flow`:
  - primer click (`Icon-play`) aleatorio entre 06:58 y 08:31,
  - segundo click (`Icon-pause`) tras 4h + ventana aleatoria de 45m,
  - tercer click (`Icon-play`) entre 14m30s y 15m59s después,
  - último click (`Icon-stop`) aleatorio entre 7h y 7h45 desde el primero.
