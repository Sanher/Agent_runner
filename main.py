import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

APP = FastAPI(title="Agent Runner")

# === Directorios ===
DATA_DIR = Path(os.getenv("AGENT_DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# === Seguridad ===
JOB_SECRET = os.getenv("JOB_SECRET", "")

# === Webhooks HA ===
HASS_WEBHOOK_URL_START = os.getenv("HASS_WEBHOOK_URL_START", "")
HASS_WEBHOOK_URL_END = os.getenv("HASS_WEBHOOK_URL_END", "")

# === Holded ===
HOLDED_EMAIL = os.getenv("HOLDED_EMAIL", "")
HOLDED_PASSWORD = os.getenv("HOLDED_PASSWORD", "")  # opcional

HOLDED_URL = "https://app.holded.com/myzone"
HOLDED_URL = "" # REMOVE IT


class RunRequest(BaseModel):
    supervision: bool = True
    run_id: Optional[str] = None
    # para futuro: parámetros por job
    payload: Optional[Dict[str, Any]] = None

def _now_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def _artifact_dir(job: str, run_id: str) -> Path:
    d = DATA_DIR / "runs" / job / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def send_ha_webhook(job_name: str, ok: bool, message: str, meta: dict):
    if job_name == "holded_click_morning":
        url = HASS_WEBHOOK_URL_START
    elif job_name == "holded_click_evening":
        url = HASS_WEBHOOK_URL_END
    else:
        return  # job desconocido

    if not url:
        return

    payload = {
        "ok": ok,
        "job": job_name,
        "message": message,
        "meta": meta,
    }

    try:
        httpx.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[WARN] Webhook HA falló: {e}")

def _guard_auth():
    if JOB_SECRET:
        pass

def run_holded_click(job_name: str, supervision: bool, run_id: str) -> Dict[str, Any]:
    """
    job_name: holded_click_morning / holded_click_evening
    supervision:
      - True: guarda artefactos y corta pronto si algo no cuadra
      - False: reintenta alguna vez y asume autonomía
    """

    run_dir = _artifact_dir(job_name, run_id)
    storage_path = DATA_DIR / "storage" / f"{job_name}.json"
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    # TODO: Ajusta estos selectores cuando me confirmes qué botón es
    # IMPORTANTE: para la 2ª ejecución (estilo distinto), usa un selector robusto
    # (por texto, aria-label, data-testid, etc.)
    BUTTON_SELECTORS = [
        "button:has-text('...')",         # opción 1 (texto)
        "[data-testid='...']",            # opción 2 (ideal si existe)
        "css=button.my-button-class",      # opción 3 (fallback)
    ]

    # <button class="MuiButtonBase-root MuiIconButton-root MuiIconButton-sizeLarge css-1aome1q" tabindex="0" type="button"><div class="Icon-root MuiBox-root css-1bj0bvd"><svg class="MuiSvgIcon-root MuiSvgIcon-fontSizeExtraLarge css-zcd73j" focusable="false" aria-hidden="true" viewBox="0 0 448 512" aria-label="Icon-play"><path d="M91.2 36.9c-12.4-6.8-27.4-6.5-39.6 .7S32 57.9 32 72l0 368c0 14.1 7.5 27.2 19.6 34.4s27.2 7.5 39.6 .7l336-184c12.8-7 20.8-20.5 20.8-35.1s-8-28.1-20.8-35.1l-336-184z"></path></svg></div></button>

    # Detectores de error típicos (ajústalos a lo que veas en Holded)
    ERROR_SELECTORS = [
        "text=/error/i",
        "text=/algo ha ido mal/i",
        "[role='alert']",
        ".toast--error, .notification--error",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # si quieres depurar: False
        context_kwargs = {}
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def snap(tag: str):
            # artefactos para depuración
            page.screenshot(path=str(run_dir / f"{tag}.png"), full_page=True)
            (run_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")

        try:
            page.goto(HOLDED_URL, wait_until="domcontentloaded", timeout=60_000)

            # 1) Comprobar si ya está logueado
            # Heurística: si te manda a login/SSO o aparece un input de email
            url = page.url
            if "login" in url or "sso" in url:
                # 2) Login (SSO por email) - aquí hay que afinar según UI real
                # De momento lo dejamos como esqueleto robusto:
                # - buscar input de email
                # - continuar
                # - completar SSO si aparece pantalla del proveedor
                # Si no lo ves viable, usamos correo+pass (fallback)
                try:
                    # intenta email
                    page.wait_for_selector("input[type='email'], input[name='email']", timeout=15_000)
                    email = HOLDED_EMAIL
                    if not email:
                        raise RuntimeError("Falta HOLDED_EMAIL en env")
                    if not email:
                        raise RuntimeError("Falta HOLDED_EMAIL en env")
                    page.fill("input[type='email'], input[name='email']", email)
                    page.keyboard.press("Enter")
                except PWTimeoutError:
                    # puede que ya esté en un SSO provider o en otra pantalla
                    pass

                # En modo supervisado, si no vemos avance claro, paramos con artefactos
                try:
                    page.wait_for_load_state("networkidle", timeout=40_000)
                except PWTimeoutError:
                    if supervision:
                        snap("login_timeout")
                        raise RuntimeError("Timeout esperando carga tras login/SSO")

            # 3) Guardar estado de sesión (si ya estás dentro)
            # (aunque no haya cambiado, no pasa nada)
            context.storage_state(path=str(storage_path))

            # 4) Acción: pulsar botón y verificar cambio mínimo de UI
            # Estrategia: antes/después capturar un “estado” (DOM marker, URL, o texto)
            before_url = page.url
            before_dom = page.inner_text("body")[:2000]  # heurística simple

            clicked = False
            for sel in BUTTON_SELECTORS:
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    page.click(sel)
                    clicked = True
                    break
                except PWTimeoutError:
                    continue

            if not clicked:
                snap("button_not_found")
                raise RuntimeError("No se encontró el botón objetivo con los selectores actuales")

            # Esperar cambio mínimo: load/networkidle o cambio de URL o cambio de DOM
            # (esto es conservador; lo refinamos cuando sepamos qué cambia)
            try:
                page.wait_for_timeout(1500)
                page.wait_for_load_state("networkidle", timeout=25_000)
            except PWTimeoutError:
                # no siempre habrá networkidle; seguimos con comprobación heurística
                pass

            after_url = page.url
            after_dom = page.inner_text("body")[:2000]

            # 5) Detectar mensajes de error
            for es in ERROR_SELECTORS:
                try:
                    loc = page.locator(es).first
                    if loc.count() > 0 and loc.is_visible():
                        snap("error_detected")
                        raise RuntimeError(f"Detectado posible error en UI: selector {es}")
                except Exception:
                    pass
            changed = (after_url != before_url) or (after_dom != before_dom)
            if not changed:
                # cambio mínimo no observado: en supervisión lo tratamos como fallo
                if supervision:
                    snap("no_ui_change")
                    raise RuntimeError("No se observó cambio mínimo de UI tras pulsar el botón")

            # OK
            snap("ok")  # útil para auditoría
            return {"ok": True, "job": job_name, "run_id": run_id, "url": page.url}

        except Exception as e:
            # artefacto final
            try:
                snap("failed")
            except Exception:
                pass
            return {"ok": False, "job": job_name, "run_id": run_id, "error": str(e), "url": page.url}

        finally:
            context.close()
            browser.close()

@APP.post("/run/{job_name}")
def run_job(job_name: str, req: RunRequest):

    if JOB_SECRET:
        provided = (req.payload or {}).get("secret", "")
        if provided != JOB_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized")

    run_id = req.run_id or _now_id()

    result = run_holded_click(
        job_name=job_name,
        supervision=req.supervision,
        run_id=run_id
    )

    msg = f"[{job_name}] {'OK' if result['ok'] else 'ERROR'} (run {run_id})"
    if not result["ok"]:
        msg += f" → {result.get('error', '')}"

    send_ha_webhook(
        job_name=job_name,
        ok=result["ok"],
        message=msg,
        meta=result
    )

    return result

@APP.get("/health")
def health():
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "has_job_secret": bool(JOB_SECRET),
        "has_webhook_start": bool(HASS_WEBHOOK_URL_START),
        "has_webhook_end": bool(HASS_WEBHOOK_URL_END),
        "holded_email_set": bool(HOLDED_EMAIL),
    }