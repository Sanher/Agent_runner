# Agent Runner

Servicio Python (FastAPI + Playwright) para ejecutar automatizaciones web y exponerlas por API HTTP.

Este repositorio contiene **la app**. El empaquetado como add-on de Home Assistant vive en:

- `https://github.com/Sanher/sanher-ha-addons`
- carpeta del add-on: `agent_runner`

## Requisitos

- Python 3.11+
- Dependencias en `requirements.txt`

## Configuracion

La app admite configuracion por variables de entorno y, cuando corre dentro del add-on, tambien lee `/data/options.json`.

Variables relevantes:

- `JOB_SECRET`
- `HASS_WEBHOOK_URL_STATUS`
- `HASS_WEBHOOK_URL_FINAL`
- `SSO_EMAIL`
- `TARGET_URL`
- `TIMEZONE` (por defecto `Europe/Madrid`)

## Ejecucion local

```bash
pip install -r requirements.txt
uvicorn main:APP --host 0.0.0.0 --port 8099
```

## Endpoints

- `GET /health`
- `GET /jobs`
- `POST /run/{job_name}`

## Persistencia

- En add-on de Home Assistant: `/data`
- Local: depende de permisos/ruta montada para `/data`

## Notas

- El flujo `workday_flow` utiliza ventanas horarias locales segun `TIMEZONE`.
- Los artefactos (capturas/html) se guardan por `run_id` en el arbol de `runs`.
