import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

APP = FastAPI(title="Agent Runner")


# Home Assistant add-ons siempre montan /data para persistencia.
DATA_DIR = Path("/data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_addon_options() -> Dict[str, Any]:
    options_path = DATA_DIR / "options.json"
    if not options_path.exists():
        return {}
    try:
        return json.loads(options_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


ADDON_OPTIONS = _load_addon_options()


def _setting(name: str, default: str = "") -> str:
    env_name = name.upper()
    if env_name in os.environ:
        return os.getenv(env_name, default)
    return str(ADDON_OPTIONS.get(name.lower(), default))


# === Seguridad ===
JOB_SECRET = _setting("job_secret", "")

# === Webhooks HA (usa automatizaciones de HA para Telegram) ===
HASS_WEBHOOK_URL_STATUS = _setting("hass_webhook_url_status", "")
HASS_WEBHOOK_URL_FINAL = _setting("hass_webhook_url_final", "")

# === Sitio objetivo ===
TARGET_URL = _setting("target_url", "")
SSO_EMAIL = _setting("sso_email", "")
TIMEZONE = _setting("timezone", "Europe/Madrid")


def _apply_timezone() -> None:
    os.environ["TZ"] = TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()


_apply_timezone()


class RunRequest(BaseModel):
    supervision: bool = True
    run_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


def _now_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _artifact_dir(job: str, run_id: str) -> Path:
    d = DATA_DIR / "runs" / job / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sleep_until(target_ts: float):
    while True:
        now = time.time()
        remaining = target_ts - now
        if remaining <= 0:
            return
        time.sleep(min(remaining, 30))


def _post_webhook(url: str, payload: Dict[str, Any]):
    if not url:
        return
    try:
        httpx.post(url, json=payload, timeout=15)
    except Exception as err:
        print(f"[WARN] fallo webhook: {err}")


def send_status(job_name: str, run_id: str, step: str, message: str, ok: bool = True, extra: Optional[Dict[str, Any]] = None):
    payload = {
        "ok": ok,
        "job": job_name,
        "run_id": run_id,
        "step": step,
        "message": message,
        "ts": datetime.now().isoformat(),
        "meta": extra or {},
    }
    _post_webhook(HASS_WEBHOOK_URL_STATUS, payload)


def send_final(job_name: str, run_id: str, result: Dict[str, Any]):
    payload = {
        "ok": result.get("ok", False),
        "job": job_name,
        "run_id": run_id,
        "message": f"[{job_name}] {'OK' if result.get('ok') else 'ERROR'}",
        "meta": result,
    }
    _post_webhook(HASS_WEBHOOK_URL_FINAL, payload)


def _today_at(hour: int, minute: int, second: int = 0) -> datetime:
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _click_icon_button(page, icon_label: str, timeout_ms: int = 15_000):
    selector = f"button:has(svg[aria-label='{icon_label}'])"
    page.wait_for_selector(selector, timeout=timeout_ms)
    page.click(selector)


def _dismiss_cookie_popup(page):
    try:
        page.locator("#onetrust-reject-all-handler").first.click(timeout=5_000)
        return True
    except Exception:
        return False


def _dismiss_location_prompt(page):
    # Permiso del navegador suele estar denegado por defecto en contexto limpio,
    # pero intentamos cerrar modales in-page típicos si aparecen.
    candidates = [
        "button:has-text('Deny')",
        "button:has-text('Block')",
        "button:has-text('No permitir')",
        "button:has-text('Rechazar')",
    ]
    for sel in candidates:
        try:
            page.locator(sel).first.click(timeout=1_500)
            return True
        except Exception:
            continue
    return False


def run_workday_flow(job_name: str, supervision: bool, run_id: str) -> Dict[str, Any]:
    run_dir = _artifact_dir(job_name, run_id)
    storage_path = DATA_DIR / "storage" / f"{job_name}.json"
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    # Ventanas temporales solicitadas
    first_start = _today_at(6, 58)
    first_end = _today_at(8, 31)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs: Dict[str, Any] = {}
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def snap(tag: str):
            page.screenshot(path=str(run_dir / f"{tag}.png"), full_page=True)
            (run_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")

        try:
            now = datetime.now()
            if now > first_end:
                raise RuntimeError("La ejecución empezó después de las 08:31 para el primer click")

            random_first = random.uniform(first_start.timestamp(), first_end.timestamp())
            send_status(job_name, run_id, "scheduled_first", "Primer click (Icon-play) planificado aleatoriamente", extra={"at": datetime.fromtimestamp(random_first).isoformat()})
            _sleep_until(random_first)

            if not TARGET_URL:
                raise RuntimeError("Falta target_url en la configuración del add-on")

            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
            _dismiss_cookie_popup(page)
            _dismiss_location_prompt(page)

            # Si está en pantalla de login/SSO, intenta completar email y deja margen a login manual.
            url = page.url.lower()
            if "login" in url or "sso" in url or "accounts.google" in url:
                if SSO_EMAIL:
                    try:
                        page.wait_for_selector("input[type='email'], input[name='identifier'], input[name='email']", timeout=15_000)
                        page.fill("input[type='email'], input[name='identifier'], input[name='email']", SSO_EMAIL)
                        page.keyboard.press("Enter")
                    except Exception:
                        pass
                if supervision:
                    snap("sso_required")
                    raise RuntimeError("Detectado flujo SSO/login. Completa login manual inicial y vuelve a lanzar")

            context.storage_state(path=str(storage_path))

            # 1) Primer botón (Icon-play)
            _click_icon_button(page, "Icon-play")
            send_status(job_name, run_id, "first_click", "Pulsado botón de inicio (Icon-play)")
            snap("first_click")
            first_click_ts = time.time()

            # 2) Start break: 4h + aleatorio en los siguientes 45 min
            second_min = first_click_ts + (4 * 3600)
            second_max = first_click_ts + (4 * 3600) + (45 * 60)
            second_click_ts = random.uniform(second_min, second_max)
            send_status(job_name, run_id, "scheduled_start_break", "Start break (Icon-pause) planificado", extra={"at": datetime.fromtimestamp(second_click_ts).isoformat()})
            _sleep_until(second_click_ts)
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            _dismiss_cookie_popup(page)
            _dismiss_location_prompt(page)
            _click_icon_button(page, "Icon-pause")
            send_status(job_name, run_id, "start_break_click", "Pulsado start break (Icon-pause)")
            snap("start_break_click")

            # 3) Stop break: no exacto 15m, y nunca 16m
            # Ventana: 14m30s .. 15m59s
            third_min = time.time() + (14 * 60) + 30
            third_max = time.time() + (15 * 60) + 59
            third_click_ts = random.uniform(third_min, third_max)
            send_status(job_name, run_id, "scheduled_stop_break", "Stop break (Icon-play) planificado", extra={"at": datetime.fromtimestamp(third_click_ts).isoformat()})
            _sleep_until(third_click_ts)
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            _dismiss_cookie_popup(page)
            _dismiss_location_prompt(page)
            _click_icon_button(page, "Icon-play")
            send_status(job_name, run_id, "stop_break_click", "Pulsado stop break (Icon-play)")
            snap("stop_break_click")

            # 4) Final (Icon-stop): aleatorio pero <= 7h45 desde el primero
            final_latest = first_click_ts + (7 * 3600) + (45 * 60)
            final_earliest = first_click_ts + (7 * 3600)
            final_ts = random.uniform(final_earliest, final_latest)
            send_status(job_name, run_id, "scheduled_final", "Click final (Icon-stop) planificado", extra={"at": datetime.fromtimestamp(final_ts).isoformat()})
            _sleep_until(final_ts)
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            _dismiss_cookie_popup(page)
            _dismiss_location_prompt(page)
            _click_icon_button(page, "Icon-stop")
            send_status(job_name, run_id, "final_click", "Pulsado fin de jornada (Icon-stop)")
            snap("final_click")

            result = {
                "ok": True,
                "job": job_name,
                "run_id": run_id,
                "url": page.url,
                "data_dir": str(DATA_DIR),
            }
            send_final(job_name, run_id, result)
            return result

        except Exception as err:
            try:
                snap("failed")
            except Exception:
                pass
            result = {
                "ok": False,
                "job": job_name,
                "run_id": run_id,
                "error": str(err),
                "url": page.url if "page" in locals() else "",
            }
            send_status(job_name, run_id, "error", f"Error en ejecución: {err}", ok=False)
            send_final(job_name, run_id, result)
            return result

        finally:
            context.close()
            browser.close()


RunnerFn = Callable[[str, bool, str], Dict[str, Any]]
JOB_RUNNERS: Dict[str, RunnerFn] = {
    "workday_flow": run_workday_flow,
}


@APP.post("/run/{job_name}")
def run_job(job_name: str, req: RunRequest):
    if JOB_SECRET:
        provided = (req.payload or {}).get("secret", "")
        if provided != JOB_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized")

    runner = JOB_RUNNERS.get(job_name)
    if not runner:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")

    run_id = req.run_id or _now_id()
    return runner(job_name=job_name, supervision=req.supervision, run_id=run_id)


@APP.get("/jobs")
def list_jobs():
    return {"jobs": sorted(JOB_RUNNERS.keys())}


@APP.get("/health")
def health():
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "has_job_secret": bool(JOB_SECRET),
        "has_webhook_status": bool(HASS_WEBHOOK_URL_STATUS),
        "has_webhook_final": bool(HASS_WEBHOOK_URL_FINAL),
        "has_sso_email": bool(SSO_EMAIL),
        "timezone": TIMEZONE,
        "jobs": sorted(JOB_RUNNERS.keys()),
    }
