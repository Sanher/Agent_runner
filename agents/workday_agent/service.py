import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from playwright.sync_api import sync_playwright


AGENT_NAME = "workday_agent"


class WorkdayAgentService:
    """Agente para automatización web de fichaje en jornada laboral."""

    def __init__(
        self,
        data_dir: Path,
        target_url: str,
        sso_email: str,
        webhook_status_url: str,
        webhook_final_url: str,
        logger,
    ) -> None:
        self.data_dir = data_dir
        self.target_url = target_url
        self.sso_email = sso_email
        self.webhook_status_url = webhook_status_url
        self.webhook_final_url = webhook_final_url
        self.logger = logger
        self._debug("Servicio inicializado")

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _debug(self, message: str, **meta: Any) -> None:
        suffix = " | "+", ".join(f"{k}={v}" for k,v in meta.items()) if meta else ""
        self.logger.info(f"[DEBUG][{AGENT_NAME}] {message} | hora_texto={self._now_text()}{suffix}")

    @staticmethod
    def now_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    def list_jobs(self) -> Dict[str, Any]:
        return {"workday_flow": self.run_workday_flow}

    def _artifact_dir(self, job: str, run_id: str) -> Path:
        d = self.data_dir / "runs" / job / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _sleep_until(target_ts: float):
        remaining_log = None
        while True:
            now = time.time()
            remaining = target_ts - now
            if remaining <= 0:
                return
            remaining_int = int(remaining)
            if remaining_log != remaining_int and remaining_int % 900 == 0:
                remaining_log = remaining_int
            time.sleep(min(remaining, 30))

    def _post_webhook(self, url: str, payload: Dict[str, Any]):
        if not url:
            self.logger.info("Webhook omitido: URL no configurada")
            return
        try:
            httpx.post(url, json=payload, timeout=15)
        except Exception:
            self.logger.exception("Fallo enviando webhook")

    def send_status(
        self,
        job_name: str,
        run_id: str,
        step: str,
        message: str,
        ok: bool = True,
        extra: Optional[Dict[str, Any]] = None,
    ):
        payload = {
            "ok": ok,
            "job": job_name,
            "run_id": run_id,
            "step": step,
            "message": message,
            "ts": datetime.now().isoformat(),
            "meta": extra or {},
        }
        log_fn = self.logger.info if ok else self.logger.error
        log_fn("[%s:%s] %s - %s", job_name, run_id, step, message)
        self._post_webhook(self.webhook_status_url, payload)

    def send_final(self, job_name: str, run_id: str, result: Dict[str, Any]):
        payload = {
            "ok": result.get("ok", False),
            "job": job_name,
            "run_id": run_id,
            "message": f"[{job_name}] {'OK' if result.get('ok') else 'ERROR'}",
            "meta": result,
        }
        log_fn = self.logger.info if result.get("ok") else self.logger.error
        log_fn("Resultado final %s/%s: %s", job_name, run_id, payload["message"])
        self._post_webhook(self.webhook_final_url, payload)

    @staticmethod
    def _today_at(hour: int, minute: int, second: int = 0) -> datetime:
        now = datetime.now()
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    @staticmethod
    def _click_icon_button(page, icon_label: str, timeout_ms: int = 15_000):
        selector = f"button:has(svg[aria-label='{icon_label}'])"
        page.wait_for_selector(selector, timeout=timeout_ms)
        page.click(selector)

    def _dismiss_cookie_popup(self, page):
        try:
            page.locator("#onetrust-reject-all-handler").first.click(timeout=5_000)
            self.logger.info("Popup de cookies descartado")
            return True
        except Exception:
            return False

    def _dismiss_location_prompt(self, page):
        candidates = [
            "button:has-text('Deny')",
            "button:has-text('Block')",
            "button:has-text('No permitir')",
            "button:has-text('Rechazar')",
        ]
        for sel in candidates:
            try:
                page.locator(sel).first.click(timeout=1_500)
                self.logger.info("Modal de geolocalización descartado con selector: %s", sel)
                return True
            except Exception:
                continue
        return False

    def run_workday_flow(self, job_name: str, supervision: bool, run_id: str) -> Dict[str, Any]:
        self._debug("Inicio run_workday_flow", job_name=job_name, run_id=run_id, supervision=supervision)
        run_dir = self._artifact_dir(job_name, run_id)
        storage_path = self.data_dir / "storage" / f"{job_name}.json"
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Inicio job=%s run_id=%s supervision=%s artifacts=%s",
            job_name,
            run_id,
            supervision,
            run_dir,
        )

        first_start = self._today_at(6, 58)
        first_end = self._today_at(8, 31)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_kwargs: Dict[str, Any] = {}
            if storage_path.exists():
                context_kwargs["storage_state"] = str(storage_path)
                self.logger.info("Reutilizando storage_state desde %s", storage_path)

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            def snap(tag: str):
                page.screenshot(path=str(run_dir / f"{tag}.png"), full_page=True)
                (run_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
                self.logger.info("Snapshot guardado: %s", tag)

            try:
                now = datetime.now()
                if now > first_end:
                    raise RuntimeError("La ejecución empezó después de las 08:31 para el primer click")

                random_first = random.uniform(first_start.timestamp(), first_end.timestamp())
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_first",
                    "Primer click (Icon-play) planificado aleatoriamente",
                    extra={"at": datetime.fromtimestamp(random_first).isoformat()},
                )
                self._sleep_until(random_first)

                if not self.target_url:
                    raise RuntimeError("Falta target_url en la configuración del add-on")

                self.logger.info("Abriendo URL objetivo: %s", self.target_url)
                page.goto(self.target_url, wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)

                url = page.url.lower()
                if "login" in url or "sso" in url or "accounts.google" in url:
                    self.logger.warning("Detectado flujo de login/SSO en URL: %s", page.url)
                    if self.sso_email:
                        try:
                            page.wait_for_selector(
                                "input[type='email'], input[name='identifier'], input[name='email']",
                                timeout=15_000,
                            )
                            page.fill(
                                "input[type='email'], input[name='identifier'], input[name='email']",
                                self.sso_email,
                            )
                            page.keyboard.press("Enter")
                            self.logger.info("Email SSO rellenado automáticamente")
                        except Exception:
                            self.logger.exception("No se pudo completar el email SSO automáticamente")
                    if supervision:
                        snap("sso_required")
                        raise RuntimeError(
                            "Detectado flujo SSO/login. Completa login manual inicial y vuelve a lanzar"
                        )

                context.storage_state(path=str(storage_path))
                self.logger.info("storage_state actualizado en %s", storage_path)

                self._click_icon_button(page, "Icon-play")
                self.send_status(job_name, run_id, "first_click", "Pulsado botón de inicio (Icon-play)")
                snap("first_click")
                first_click_ts = time.time()

                second_min = first_click_ts + (4 * 3600)
                second_max = first_click_ts + (4 * 3600) + (45 * 60)
                second_click_ts = random.uniform(second_min, second_max)
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_start_break",
                    "Start break (Icon-pause) planificado",
                    extra={"at": datetime.fromtimestamp(second_click_ts).isoformat()},
                )
                self._sleep_until(second_click_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._click_icon_button(page, "Icon-pause")
                self.send_status(job_name, run_id, "start_break_click", "Pulsado start break (Icon-pause)")
                snap("start_break_click")

                third_min = time.time() + (14 * 60) + 30
                third_max = time.time() + (15 * 60) + 59
                third_click_ts = random.uniform(third_min, third_max)
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_stop_break",
                    "Stop break (Icon-play) planificado",
                    extra={"at": datetime.fromtimestamp(third_click_ts).isoformat()},
                )
                self._sleep_until(third_click_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._click_icon_button(page, "Icon-play")
                self.send_status(job_name, run_id, "stop_break_click", "Pulsado stop break (Icon-play)")
                snap("stop_break_click")

                final_latest = first_click_ts + (7 * 3600) + (45 * 60)
                final_earliest = first_click_ts + (7 * 3600)
                final_ts = random.uniform(final_earliest, final_latest)
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_final",
                    "Click final (Icon-stop) planificado",
                    extra={"at": datetime.fromtimestamp(final_ts).isoformat()},
                )
                self._sleep_until(final_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._click_icon_button(page, "Icon-stop")
                self.send_status(job_name, run_id, "final_click", "Pulsado fin de jornada (Icon-stop)")
                snap("final_click")

                result = {
                    "ok": True,
                    "job": job_name,
                    "run_id": run_id,
                    "url": page.url,
                    "data_dir": str(self.data_dir),
                }
                self.send_final(job_name, run_id, result)
                self._debug("Run completado OK", job_name=job_name, run_id=run_id)
                return result

            except Exception as err:
                self.logger.exception("Error en ejecución job=%s run_id=%s", job_name, run_id)
                try:
                    snap("failed")
                except Exception:
                    self.logger.exception("No se pudo guardar snapshot de error")
                result = {
                    "ok": False,
                    "job": job_name,
                    "run_id": run_id,
                    "error": str(err),
                    "url": page.url if "page" in locals() else "",
                }
                self.send_status(job_name, run_id, "error", f"Error en ejecución: {err}", ok=False)
                self.send_final(job_name, run_id, result)
                self._debug("Run finalizado con error", job_name=job_name, run_id=run_id, error=str(err))
                return result

            finally:
                context.close()
                browser.close()
                self.logger.info("Recursos Playwright cerrados job=%s run_id=%s", job_name, run_id)
