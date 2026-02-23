import json
import subprocess
import random
import threading
import sys
import time
from datetime import date, datetime
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.sync_api import sync_playwright


AGENT_NAME = "workday_agent"


class WorkdayAgentService:
    """Agent for phased web automation."""
    ACTIVE_PHASES = {"waiting_start", "working_before_break", "on_break", "working_after_break"}

    def __init__(
        self,
        data_dir: Path,
        target_url: str,
        sso_email: str,
        webhook_start_url: str,
        webhook_final_url: str,
        webhook_start_break_url: str,
        webhook_stop_break_url: str,
        logger,
    ) -> None:
        self.data_dir = data_dir
        self.target_url = target_url
        self.sso_email = sso_email
        self.webhook_start_url = webhook_start_url
        self.webhook_final_url = webhook_final_url
        self.webhook_start_break_url = webhook_start_break_url
        self.webhook_stop_break_url = webhook_stop_break_url
        self.logger = logger
        self._run_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self.config_path = self.data_dir / "workday_agent_config.json"
        self.runtime_state_path = self.data_dir / "workday_runtime_state.json"
        self.runtime_events_path = self.data_dir / "workday_runtime_events.jsonl"
        self._events_retention_days = 30
        self._last_runtime_events_prune_day = ""
        self._settings = self._load_settings()
        self._runtime_state: Dict[str, Any] = self._load_runtime_state()
        self._debug("Service initialized", phase=self._runtime_state.get("phase", "before_start"))
        self._maybe_prune_runtime_events()

    @staticmethod
    def _default_runtime_state() -> Dict[str, Any]:
        return {
            "phase": "before_start",
            "message": "Pending start",
            "run_id": "",
            "job": "workday_flow",
            "updated_at": datetime.now().isoformat(),
            "ok": None,
        }

    def _load_runtime_state(self) -> Dict[str, Any]:
        if not self.runtime_state_path.exists():
            return self._default_runtime_state()
        try:
            data = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = self._default_runtime_state()
                return {**base, **data}
        except Exception:
            self.logger.exception("Failed to read persisted runtime state")
        return self._default_runtime_state()

    def _persist_runtime_state(self, state: Dict[str, Any]) -> None:
        try:
            self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.runtime_state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            self.logger.exception("Failed to persist runtime state")

    def _append_runtime_event(self, event: str, **meta: Any) -> None:
        item = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "phase": meta.get("phase"),
            "run_id": meta.get("run_id"),
            "job": meta.get("job"),
            "meta": meta,
        }
        try:
            self.runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            self._maybe_prune_runtime_events()
        except Exception:
            self.logger.exception("Failed to store runtime event")

    @staticmethod
    def _safe_parse_iso_datetime(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            return None

    def _maybe_prune_runtime_events(self) -> None:
        today = date.today().isoformat()
        if self._last_runtime_events_prune_day == today:
            return
        self._prune_runtime_events(retention_days=self._events_retention_days)
        self._last_runtime_events_prune_day = today

    def _prune_runtime_events(self, retention_days: int = 30) -> None:
        if not self.runtime_events_path.exists():
            return
        try:
            cutoff = datetime.now() - timedelta(days=max(1, int(retention_days)))
            lines = self.runtime_events_path.read_text(encoding="utf-8").splitlines()
            kept_lines: list[str] = []
            removed = 0

            for line in lines:
                if not line.strip():
                    continue
                keep = True
                try:
                    item = json.loads(line)
                    ts = self._safe_parse_iso_datetime(item.get("ts", ""))
                    if ts is not None and ts < cutoff:
                        keep = False
                except Exception:
                    keep = True

                if keep:
                    kept_lines.append(line)
                else:
                    removed += 1

            if removed <= 0:
                return

            payload = "\n".join(kept_lines)
            if payload:
                payload += "\n"
            self.runtime_events_path.write_text(payload, encoding="utf-8")
            self.logger.info(
                "Runtime events pruned: removed=%s retained=%s retention_days=%s",
                removed,
                len(kept_lines),
                retention_days,
            )
        except Exception:
            self.logger.exception("Failed to prune runtime events")

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _debug(self, message: str, **meta: Any) -> None:
        suffix = " | "+", ".join(f"{k}={v}" for k,v in meta.items()) if meta else ""
        self.logger.debug(f"[DEBUG][{AGENT_NAME}] {message} | hora_texto={self._now_text()}{suffix}")

    @staticmethod
    def _sanitize_url_for_log(raw_url: str) -> str:
        if not raw_url:
            return raw_url
        try:
            parts = urlsplit(raw_url)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except Exception:
            return raw_url

    @staticmethod
    def now_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S")

    def list_jobs(self) -> Dict[str, Any]:
        return {"workday_flow": self.run_workday_flow}

    def _set_runtime_state(self, phase: str, message: str, **meta: Any) -> None:
        with self._status_lock:
            self._runtime_state = {
                "phase": phase,
                "message": message,
                "updated_at": datetime.now().isoformat(),
                **meta,
            }
            state_copy = dict(self._runtime_state)
        self._persist_runtime_state(state_copy)
        self._append_runtime_event(
            "state_transition",
            phase=phase,
            message=message,
            run_id=state_copy.get("run_id", ""),
            job=state_copy.get("job", "workday_flow"),
            ok=state_copy.get("ok"),
        )

    def _get_runtime_state(self) -> Dict[str, Any]:
        with self._status_lock:
            return dict(self._runtime_state)

    @staticmethod
    def _runtime_resume_fields(state: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "planned_first_ts",
            "first_click_ts",
            "planned_start_break_ts",
            "start_break_ts",
            "planned_stop_break_ts",
            "stop_break_ts",
            "planned_final_ts",
            "final_click_ts",
        )
        return {key: state.get(key) for key in keys}

    def _artifact_dir(self, job: str, run_id: str) -> Path:
        d = self.data_dir / "runs" / job / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _normalize_iso_date(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError as exc:
            raise RuntimeError("Invalid date format. Use YYYY-MM-DD") from exc

    def _load_settings(self) -> Dict[str, str]:
        default_settings = {"blocked_start_date": "", "blocked_end_date": ""}
        if not self.config_path.exists():
            return default_settings
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return default_settings
            blocked_start_date = self._normalize_iso_date(raw.get("blocked_start_date", ""))
            blocked_end_date = self._normalize_iso_date(raw.get("blocked_end_date", ""))
            if bool(blocked_start_date) != bool(blocked_end_date):
                self.logger.warning(
                    "Incomplete workday configuration: blocked_start_date and blocked_end_date must be set together"
                )
                return default_settings
            if blocked_start_date and blocked_end_date and blocked_start_date > blocked_end_date:
                self.logger.warning("Invalid workday configuration: blocked_start_date > blocked_end_date")
                return default_settings
            return {
                "blocked_start_date": blocked_start_date,
                "blocked_end_date": blocked_end_date,
            }
        except Exception:
            self.logger.exception("Failed to load editable workday configuration")
            return default_settings

    def _persist_settings(self, settings: Dict[str, str]) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            raise RuntimeError("Failed to save workday configuration") from exc

    def get_settings(self) -> Dict[str, str]:
        with self._config_lock:
            return dict(self._settings)

    def update_settings(self, blocked_start_date: str, blocked_end_date: str) -> Dict[str, str]:
        start = self._normalize_iso_date(blocked_start_date)
        end = self._normalize_iso_date(blocked_end_date)
        if bool(start) != bool(end):
            raise RuntimeError("You must provide both dates: start and end")
        if start and end and start > end:
            raise RuntimeError("Start date cannot be later than end date")
        updated = {
            "blocked_start_date": start,
            "blocked_end_date": end,
        }
        with self._config_lock:
            self._persist_settings(updated)
            self._settings = dict(updated)
        self._debug(
            "Workday configuration updated",
            blocked_start_date=updated["blocked_start_date"],
            blocked_end_date=updated["blocked_end_date"],
        )
        return dict(updated)

    def is_automatic_start_blocked_for_day(self, day_iso: str) -> bool:
        try:
            day = date.fromisoformat(str(day_iso)).isoformat()
        except Exception:
            return False
        settings = self.get_settings()
        start = settings.get("blocked_start_date", "")
        end = settings.get("blocked_end_date", "")
        return bool(start and end and start <= day <= end)

    def _ensure_playwright_browsers(self, run_id: str, job_name: str) -> bool:
        command = [sys.executable, "-m", "playwright", "install", "chromium"]
        self.logger.warning(
            "Chromium not found; attempting automatic install for run_id=%s job=%s",
            run_id,
            job_name,
        )
        try:
            subprocess.run(
                command,
                check=True,
                timeout=900,
                text=True,
                capture_output=True,
            )
            self.logger.info("Automatic Chromium install completed for run_id=%s", run_id)
            return True
        except Exception:
            self.logger.exception(
                "Could not install Chromium at runtime for run_id=%s",
                run_id,
            )
            return False

    @staticmethod
    def _is_playwright_executable_error(error: Exception) -> bool:
        msg = str(error)
        return "Executable doesn't exist" in msg

    def _launch_browser(self, playwright, run_id: str, job_name: str, *, headless: bool = True):
        try:
            return playwright.chromium.launch(headless=headless)
        except Exception as err:
            if not self._is_playwright_executable_error(err):
                raise
            if not self._ensure_playwright_browsers(run_id=run_id, job_name=job_name):
                raise
            return playwright.chromium.launch(headless=headless)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _build_planned_clicks(
        self,
        first_click_ts: float,
        planned_start_break_ts: float = 0.0,
        planned_stop_break_ts: float = 0.0,
        planned_final_ts: float = 0.0,
        stop_break_base_ts: float = 0.0,
    ) -> Dict[str, float]:
        start_ts = self._safe_float(planned_start_break_ts)
        stop_ts = self._safe_float(planned_stop_break_ts)
        final_ts = self._safe_float(planned_final_ts)

        if start_ts <= 0:
            start_min = first_click_ts + (4 * 3600)
            start_max = first_click_ts + (4 * 3600) + (45 * 60)
            start_ts = random.uniform(start_min, start_max)

        if stop_ts <= 0:
            stop_base = stop_break_base_ts if stop_break_base_ts > 0 else start_ts
            stop_min = stop_base + (14 * 60) + 30
            stop_max = stop_base + (15 * 60) + 59
            stop_ts = random.uniform(stop_min, stop_max)

        if final_ts <= 0:
            final_earliest = first_click_ts + (7 * 3600) + (45 * 60)
            final_latest = final_earliest + 59
            final_ts = random.uniform(final_earliest, final_latest)

        return {
            "planned_start_break_ts": start_ts,
            "planned_stop_break_ts": stop_ts,
            "planned_final_ts": final_ts,
        }

    @staticmethod
    def _same_local_day(ts_a: float, ts_b: float) -> bool:
        try:
            return datetime.fromtimestamp(ts_a).date() == datetime.fromtimestamp(ts_b).date()
        except Exception:
            return False

    def has_active_run(self) -> bool:
        phase = str(self._get_runtime_state().get("phase", "before_start"))
        return phase in self.ACTIVE_PHASES

    def get_runtime_events(self, limit: int = 200, day: str = "") -> Dict[str, Any]:
        # Returns recent runtime events from the jsonl file for UI/diagnostics.
        if not self.runtime_events_path.exists():
            return {"ok": True, "count": 0, "items": []}
        try:
            lines = self.runtime_events_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            self.logger.exception("Failed to read runtime events")
            return {"ok": False, "count": 0, "items": []}

        items: list[Dict[str, Any]] = []
        day_prefix = (day or "").strip()
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if day_prefix:
                ts = str(item.get("ts", ""))
                if not ts.startswith(day_prefix):
                    continue
            items.append(item)

        items = items[-max(1, min(limit, 1000)) :]
        return {"ok": True, "count": len(items), "items": items}

    def _infer_click_ts_from_events(self, run_id: str, click_name: str) -> float:
        events = self.get_runtime_events(limit=1000)
        if not events.get("ok"):
            return 0.0
        items = events.get("items", [])
        if not isinstance(items, list):
            return 0.0

        for item in reversed(items):
            if str(item.get("event", "")) != "click_webhook_sent":
                continue
            if run_id and str(item.get("run_id", "")) != run_id:
                continue
            meta = item.get("meta", {})
            if not isinstance(meta, dict):
                continue
            if str(meta.get("click_name", "")) != click_name:
                continue
            payload_meta = meta.get("meta", {})
            executed_at = ""
            if isinstance(payload_meta, dict):
                executed_at = str(payload_meta.get("executed_at", "")).strip()
            if not executed_at:
                executed_at = str(item.get("ts", "")).strip()
            parsed = self._safe_parse_iso_datetime(executed_at)
            if parsed is not None:
                return float(parsed.timestamp())
        return 0.0

    def get_daily_click_history(self, day: str = "") -> Dict[str, Any]:
        # Filters click webhook events to build the daily click history.
        target_day = day.strip() or datetime.now().strftime("%Y-%m-%d")
        events = self.get_runtime_events(limit=1000, day=target_day)
        if not events.get("ok"):
            return {"ok": False, "day": target_day, "count": 0, "items": []}

        clicks: list[Dict[str, Any]] = []
        for item in events.get("items", []):
            if item.get("event") != "click_webhook_sent":
                continue
            meta = item.get("meta", {})
            payload_meta = meta.get("meta", {}) if isinstance(meta, dict) else {}
            clicks.append(
                {
                    "ts": item.get("ts"),
                    "run_id": item.get("run_id"),
                    "phase": item.get("phase"),
                    "click_name": meta.get("click_name"),
                    "ok": meta.get("ok"),
                    "executed_at": payload_meta.get("executed_at", ""),
                    "scheduled_at": payload_meta.get("scheduled_at", ""),
                    "recovered": bool(payload_meta.get("recovered", False)),
                }
            )

        # End-of-workday click is persisted in runtime state (final_click_ts),
        # so include it in history when the run is completed on target_day.
        state = self._get_runtime_state()
        phase = str(state.get("phase", ""))
        final_click_ts = self._safe_float(state.get("final_click_ts"), 0.0)
        if phase == "completed" and final_click_ts > 0:
            try:
                final_day = datetime.fromtimestamp(final_click_ts).date().isoformat()
            except Exception:
                final_day = ""
            if final_day == target_day:
                has_final = any(str(item.get("click_name", "")) == "final_click" for item in clicks)
                if not has_final:
                    final_iso = datetime.fromtimestamp(final_click_ts).isoformat()
                    clicks.append(
                        {
                            "ts": final_iso,
                            "run_id": state.get("run_id", ""),
                            "phase": phase,
                            "click_name": "final_click",
                            "ok": bool(state.get("ok", True)),
                            "executed_at": final_iso,
                            "scheduled_at": "",
                            "recovered": bool(state.get("recovered", False)),
                        }
                    )

        return {"ok": True, "day": target_day, "count": len(clicks), "items": clicks}

    def retry_failed_action(self) -> Dict[str, Any]:
        # Retries the last failed state by restoring the active phase before the error.
        state = self._get_runtime_state()
        if str(state.get("phase", "")) != "failed":
            raise RuntimeError("There is no failed run to retry")

        failed_phase = str(state.get("failed_phase", "")).strip()
        if failed_phase not in self.ACTIVE_PHASES:
            raise RuntimeError("The failure cannot be retried automatically")

        run_id = str(state.get("run_id", "")).strip()
        first_click_ts = state.get("first_click_ts")
        start_break_ts = state.get("start_break_ts")
        stop_break_ts = state.get("stop_break_ts")
        inferred_fields: list[str] = []

        if self._safe_float(first_click_ts) <= 0:
            inferred = self._infer_click_ts_from_events(run_id=run_id, click_name="start_click")
            if inferred > 0:
                first_click_ts = inferred
                inferred_fields.append("first_click_ts")
        if self._safe_float(start_break_ts) <= 0:
            inferred = self._infer_click_ts_from_events(run_id=run_id, click_name="start_break_click")
            if inferred > 0:
                start_break_ts = inferred
                inferred_fields.append("start_break_ts")
        if self._safe_float(stop_break_ts) <= 0:
            inferred = self._infer_click_ts_from_events(run_id=run_id, click_name="stop_break_click")
            if inferred > 0:
                stop_break_ts = inferred
                inferred_fields.append("stop_break_ts")

        if inferred_fields:
            self.logger.info(
                "Retry inferred missing timestamps from events run_id=%s fields=%s",
                run_id or "-",
                ",".join(inferred_fields),
            )

        self._set_runtime_state(
            failed_phase,
            "Manual retry requested",
            run_id=run_id,
            job=state.get("job", "workday_flow"),
            ok=None,
            planned_first_ts=state.get("planned_first_ts"),
            first_click_ts=first_click_ts,
            planned_start_break_ts=state.get("planned_start_break_ts"),
            start_break_ts=start_break_ts,
            planned_stop_break_ts=state.get("planned_stop_break_ts"),
            stop_break_ts=stop_break_ts,
            planned_final_ts=state.get("planned_final_ts"),
            retry_requested_at=datetime.now().isoformat(),
        )
        return self.resume_pending_flow()

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
            self.logger.info("Webhook skipped: URL not configured")
            return
        sanitized_url = self._sanitize_url_for_log(url)
        self._debug("Sending webhook", url=sanitized_url)
        try:
            httpx.post(url, json=payload, timeout=15)
            self._debug("Webhook sent", url=sanitized_url)
        except Exception:
            self.logger.exception("Webhook send failed")

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
        # Step-by-step details stay in logs; webhooks are sent per event.

    def send_final(self, job_name: str, run_id: str, result: Dict[str, Any]):
        payload = {
            "ok": result.get("ok", False),
            "job": job_name,
            "run_id": run_id,
            "message": f"[{job_name}] {'OK' if result.get('ok') else 'ERROR'}",
            "meta": result,
        }
        log_fn = self.logger.info if result.get("ok") else self.logger.error
        log_fn("Final result %s/%s: %s", job_name, run_id, payload["message"])
        self._post_webhook(self.webhook_final_url, payload)
        self._append_runtime_event(
            "final_webhook_sent",
            phase=self._get_runtime_state().get("phase"),
            run_id=run_id,
            job=job_name,
            ok=payload["ok"],
            message=payload["message"],
        )

    def send_click_webhook(
        self,
        url: str,
        job_name: str,
        run_id: str,
        click_name: str,
        ok: bool,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "ok": ok,
            "event": f"workday_{click_name}",
            "job": job_name,
            "run_id": run_id,
            "ts": datetime.now().isoformat(),
            "meta": meta or {},
        }
        self._post_webhook(url, payload)
        self._append_runtime_event(
            "click_webhook_sent",
            phase=self._get_runtime_state().get("phase"),
            run_id=run_id,
            job=job_name,
            ok=ok,
            click_name=click_name,
            meta=meta or {},
        )

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        sec = max(0, int(seconds))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    @staticmethod
    def _fmt_clock(ts: Optional[float]) -> str:
        if not ts:
            return ""
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")

    def get_status(self) -> Dict[str, Any]:
        state = self._get_runtime_state()
        now_ts = time.time()
        phase = str(state.get("phase", "before_start"))
        settings = self.get_settings()
        today = datetime.now().date().isoformat()
        state["blocked_start_date"] = settings.get("blocked_start_date", "")
        state["blocked_end_date"] = settings.get("blocked_end_date", "")
        state["blocked_today"] = self.is_automatic_start_blocked_for_day(today)

        if phase == "waiting_start":
            planned = float(state.get("planned_first_ts", 0))
            remaining = max(0, int(planned - now_ts))
            state["message"] = f"Waiting to start, {self._fmt_duration(remaining)} remaining"
            state["remaining_seconds"] = remaining
            return state

        if phase == "working_before_break":
            first_ts = float(state.get("first_click_ts", now_ts))
            elapsed = max(0, int(now_ts - first_ts))
            state["message"] = f"Workday started, running for {self._fmt_duration(elapsed)}"
            state["elapsed_seconds"] = elapsed
            return state

        if phase == "on_break":
            planned = float(state.get("planned_stop_break_ts", 0))
            if planned <= 0:
                # Break is confirmed, but remaining time cannot be inferred reliably.
                state["message"] = "On break (remaining time unknown)"
                state.pop("remaining_seconds", None)
                return state
            remaining = max(0, int(planned - now_ts))
            state["message"] = f"On break, {self._fmt_duration(remaining)} remaining"
            state["remaining_seconds"] = remaining
            return state

        if phase == "working_after_break":
            planned = float(state.get("planned_final_ts", 0))
            if planned <= 0:
                state["message"] = "After break (remaining time unknown)"
                state.pop("remaining_seconds", None)
                return state
            remaining = max(0, int(planned - now_ts))
            state["message"] = f"After break, {self._fmt_duration(remaining)} remaining"
            state["remaining_seconds"] = remaining
            return state

        if phase == "completed":
            if state.get("ok"):
                state["message"] = (
                    "Workday completed successfully. "
                    f"Start {self._fmt_clock(state.get('first_click_ts'))}, "
                    f"break start {self._fmt_clock(state.get('start_break_ts'))}, "
                    f"break end {self._fmt_clock(state.get('stop_break_ts'))}, "
                    f"end {self._fmt_clock(state.get('final_click_ts'))}."
                )
            return state

        if phase == "failed":
            state["message"] = f"Run failed: {state.get('error', 'unknown')}"
            return state

        # before_start o cualquier valor no esperado
        first_start = self._today_at(6, 58).timestamp()
        rescue_end = self._today_at(9, 30).timestamp()
        if state.get("blocked_today"):
            start_text = state.get("blocked_start_date", "")
            end_text = state.get("blocked_end_date", "")
            state["message"] = (
                f"Day blocked by configuration ({start_text} to {end_text}). "
                "Automatic start is disabled."
            )
            return state
        if now_ts < first_start:
            state["message"] = (
                f"Before start, {self._fmt_duration(int(first_start - now_ts))} "
                "until the start window."
            )
        elif now_ts <= rescue_end:
            state["message"] = "Start window open, waiting for flow start."
        else:
            state["message"] = "Outside start window for the first click."
        return state

    @staticmethod
    def _today_at(hour: int, minute: int, second: int = 0) -> datetime:
        now = datetime.now()
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    @staticmethod
    def _human_pause(min_ms: int = 120, max_ms: int = 320) -> None:
        if max_ms < min_ms:
            max_ms = min_ms
        time.sleep(random.uniform(min_ms, max_ms) / 1000.0)

    def _capture_click_failure_snapshot(self, page, context_label: str) -> None:
        try:
            state = self._get_runtime_state()
            run_id = str(state.get("run_id", "")).strip() or f"manual-{self.now_id()}"
            job_name = str(state.get("job", "workday_flow") or "workday_flow")
            run_dir = self._artifact_dir(job_name, run_id)
            safe_label = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in str(context_label or "click"))
            safe_label = safe_label.strip("_") or "click"
            ts = self.now_id()
            png_path = run_dir / f"click_failed_{safe_label}_{ts}.png"
            html_path = run_dir / f"click_failed_{safe_label}_{ts}.html"
            page.screenshot(path=str(png_path), full_page=True)
            html_path.write_text(page.content(), encoding="utf-8")
            self.logger.warning("Click failure snapshot saved: %s", png_path)
        except Exception:
            self.logger.exception("Could not save click failure snapshot")

    @staticmethod
    def _pick_largest_visible_locator(page, selector: str, timeout_ms: int = 15_000):
        page.wait_for_selector(selector, timeout=timeout_ms)
        group = page.locator(selector)
        count = group.count()
        best = None
        best_area = -1.0

        # Some views expose duplicate icon buttons; pick the largest visible
        # candidate to target the primary control.
        for idx in range(count):
            loc = group.nth(idx)
            try:
                if not loc.is_visible():
                    continue
                box = loc.bounding_box()
                if not box:
                    continue
                area = float(box.get("width", 0.0)) * float(box.get("height", 0.0))
                if area > best_area:
                    best = loc
                    best_area = area
            except Exception:
                continue

        return best if best is not None else group.first

    def _is_selector_visible(self, page, selector: str, timeout_ms: int = 0) -> bool:
        if timeout_ms > 0:
            try:
                page.wait_for_selector(selector, timeout=timeout_ms)
            except Exception:
                pass
        group = page.locator(selector)
        count = group.count()
        for idx in range(count):
            try:
                if group.nth(idx).is_visible():
                    return True
            except Exception:
                continue
        return False

    def _is_icon_visible(self, page, icon_label: str, timeout_ms: int = 0) -> bool:
        selector = f"button:has(svg[aria-label='{icon_label}'])"
        return self._is_selector_visible(page, selector, timeout_ms=timeout_ms)

    def _humanized_click(self, page, selector: str, timeout_ms: int = 15_000, context_label: str = "click") -> None:
        try:
            page.wait_for_selector(selector, timeout=timeout_ms)
            locator = self._pick_largest_visible_locator(page, selector, timeout_ms=timeout_ms)
            try:
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
            except Exception:
                pass
            try:
                box = locator.bounding_box()
                if box:
                    cx = float(box["x"]) + (float(box["width"]) / 2.0)
                    cy = float(box["y"]) + (float(box["height"]) / 2.0)
                    page.mouse.move(
                        cx + random.uniform(-36.0, 36.0),
                        cy + random.uniform(-18.0, 18.0),
                        steps=random.randint(6, 14),
                    )
                    page.mouse.move(
                        cx + random.uniform(-2.0, 2.0),
                        cy + random.uniform(-2.0, 2.0),
                        steps=random.randint(8, 20),
                    )
            except Exception:
                pass
            try:
                locator.hover(timeout=timeout_ms)
            except Exception:
                pass
            self._human_pause(120, 420)
            locator.click(timeout=timeout_ms, delay=random.randint(70, 220))
            self._human_pause(80, 220)
            return
        except Exception as human_err:
            self.logger.warning(
                "Humanized click failed for %s; retrying direct click. error=%s",
                context_label,
                human_err,
            )
            try:
                page.wait_for_selector(selector, timeout=timeout_ms)
                page.click(selector, timeout=timeout_ms)
                self._human_pause(40, 120)
                return
            except Exception as direct_err:
                self._capture_click_failure_snapshot(page, context_label)
                raise RuntimeError(
                    f"Could not click target ({context_label}) with humanized or direct click"
                ) from direct_err

    def _click_icon_button(self, page, icon_label: str, timeout_ms: int = 15_000):
        selector = f"button:has(svg[aria-label='{icon_label}'])"
        self._humanized_click(page, selector, timeout_ms=timeout_ms, context_label=f"icon_{icon_label}")

    def _click_and_confirm_transition(
        self,
        page,
        click_icon_label: str,
        expected_icon_label: str,
        action_label: str,
        timeout_ms: int = 15_000,
    ) -> None:
        click_selector = f"button:has(svg[aria-label='{click_icon_label}'])"
        self._click_icon_button(page, click_icon_label, timeout_ms=timeout_ms)
        expected_selector = f"button:has(svg[aria-label='{expected_icon_label}'])"
        if self._is_selector_visible(page, expected_selector, timeout_ms=timeout_ms):
            return

        self.logger.warning(
            "Transition not confirmed for %s on first attempt; reloading and retrying",
            action_label,
        )
        try:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            self._dismiss_cookie_popup(page)
            self._dismiss_location_prompt(page)
        except Exception:
            self.logger.exception("Failed to reload page during transition retry (%s)", action_label)

        if self._is_selector_visible(page, expected_selector, timeout_ms=4_000):
            self.logger.info("Transition confirmed after reload for %s", action_label)
            return

        if self._is_selector_visible(page, click_selector, timeout_ms=4_000):
            self._click_icon_button(page, click_icon_label, timeout_ms=timeout_ms)
            if self._is_selector_visible(page, expected_selector, timeout_ms=timeout_ms):
                self.logger.info("Transition confirmed on second click for %s", action_label)
                return

        raise RuntimeError(
            f"Could not confirm {action_label}: {expected_icon_label} did not appear after clicking {click_icon_label}"
        )


    def _confirm_end_of_day_modal(self, page, timeout_ms: int = 15_000) -> None:
        # Some interfaces show an additional modal after clicking "Icon-stop".
        # End-of-day is only considered valid after confirming that modal.
        time.sleep(2)
        modal_selector = "button:has-text('Sí, he terminado')"
        fallback_selector = "button:has-text('Si, he terminado')"
        try:
            self._humanized_click(page, modal_selector, timeout_ms=timeout_ms, context_label="end_of_day_modal_primary")
        except Exception:
            try:
                self._humanized_click(page, fallback_selector, timeout_ms=timeout_ms, context_label="end_of_day_modal_fallback")
            except Exception as exc:
                raise RuntimeError(
                    "Could not confirm end of day: button 'Sí, he terminado' did not appear"
                ) from exc

    def _complete_end_of_day(self, page, timeout_ms: int = 15_000) -> None:
        self._click_icon_button(page, "Icon-stop", timeout_ms=timeout_ms)
        self._confirm_end_of_day_modal(page, timeout_ms=timeout_ms)
        try:
            page.wait_for_selector("button:has(svg[aria-label='Icon-play'])", timeout=timeout_ms)
        except Exception as exc:
            raise RuntimeError(
                "Could not confirm end of day: Icon-play did not appear after modal confirmation"
            ) from exc

    def _dismiss_cookie_popup(self, page):
        try:
            page.locator("#onetrust-reject-all-handler").first.click(timeout=5_000)
            self.logger.info("Consent banner dismissed")
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
                self.logger.info("Geolocation modal dismissed with selector: %s", sel)
                return True
            except Exception:
                continue
        return False

    def resume_pending_flow(self) -> Dict[str, Any]:
        """Resume an active run using persisted state."""
        state = self._get_runtime_state()
        phase = str(state.get("phase", "before_start"))
        if phase not in self.ACTIVE_PHASES:
            return {"ok": True, "resumed": False, "phase": phase, "reason": "phase_not_active"}

        job_name = str(state.get("job", "workday_flow") or "workday_flow")
        run_id = str(state.get("run_id", "") or f"recover-{self.now_id()}")

        if not self._run_lock.acquire(blocking=False):
            return {"ok": False, "resumed": False, "phase": phase, "reason": "busy"}

        self._debug("Resuming persisted flow", phase=phase, run_id=run_id, job_name=job_name)
        run_dir = self._artifact_dir(job_name, run_id)
        storage_path = self.data_dir / "storage" / f"{job_name}.json"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._append_runtime_event(
            "resume_start",
            phase=phase,
            run_id=run_id,
            job=job_name,
            planned_from_state=True,
        )
        start_deadline_ts = self._today_at(9, 30).timestamp()

        browser = None
        context = None
        page = None

        try:
            now_ts = time.time()
            first_click_ts = self._safe_float(state.get("first_click_ts"))
            planned_first_ts = self._safe_float(state.get("planned_first_ts"))
            start_break_ts = self._safe_float(state.get("start_break_ts"))
            stop_break_ts = self._safe_float(state.get("stop_break_ts"))

            anchor_ts = first_click_ts if first_click_ts > 0 else planned_first_ts
            if anchor_ts > 0 and not self._same_local_day(anchor_ts, now_ts):
                raise RuntimeError("Persisted state is stale: it belongs to another day")

            if phase == "waiting_start":
                if planned_first_ts <= 0:
                    raise RuntimeError("Invalid persisted state: missing planned_first_ts")
                if planned_first_ts > start_deadline_ts + 300:
                    raise RuntimeError("Invalid persisted state: planned_first_ts is outside the allowed window")
                if now_ts > start_deadline_ts + 300:
                    raise RuntimeError("Start window expired; automatic resume is disabled")

            with sync_playwright() as p:
                browser = self._launch_browser(p, run_id=run_id, job_name=job_name, headless=True)
                context_kwargs: Dict[str, Any] = {}
                if storage_path.exists():
                    context_kwargs["storage_state"] = str(storage_path)
                    self.logger.info("Resume: reusing storage_state from %s", storage_path)

                context = browser.new_context(**context_kwargs)
                page = context.new_page()

                def snap(tag: str):
                    page.screenshot(path=str(run_dir / f"{tag}.png"), full_page=True)
                    (run_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
                    self.logger.info("Snapshot saved: %s", tag)

                def open_target():
                    if not self.target_url:
                        raise RuntimeError("Missing target_url in configuration")
                    page.goto(self.target_url, wait_until="domcontentloaded", timeout=60_000)
                    self._debug("Target page opened", url=self._sanitize_url_for_log(page.url))
                    self._dismiss_cookie_popup(page)
                    self._dismiss_location_prompt(page)

                if phase == "waiting_start":
                    self._sleep_until(planned_first_ts)
                    if time.time() > start_deadline_ts + 300:
                        raise RuntimeError("Resume is outside the start window")
                    open_target()
                    context.storage_state(path=str(storage_path))
                    self.logger.info("Resume: storage_state updated at %s", storage_path)
                    self._click_and_confirm_transition(page, "Icon-play", "Icon-pause", "start of workday")
                    first_click_ts = time.time()
                    executed_at = datetime.now().isoformat()
                    self.send_status(job_name, run_id, "first_click", "Resume: clicked start (Icon-play)")
                    self.send_click_webhook(
                        self.webhook_start_url,
                        job_name=job_name,
                        run_id=run_id,
                        click_name="start_click",
                        ok=True,
                        meta={"executed_at": executed_at, "recovered": True},
                    )
                    snap("recovered_first_click")
                    plans = self._build_planned_clicks(
                        first_click_ts=first_click_ts,
                        planned_start_break_ts=self._safe_float(state.get("planned_start_break_ts")),
                        planned_stop_break_ts=self._safe_float(state.get("planned_stop_break_ts")),
                        planned_final_ts=self._safe_float(state.get("planned_final_ts")),
                    )
                    self._set_runtime_state(
                        "working_before_break",
                        "Workday started (resumed)",
                        run_id=run_id,
                        job=job_name,
                        ok=None,
                        first_click_ts=first_click_ts,
                        planned_start_break_ts=plans["planned_start_break_ts"],
                        planned_stop_break_ts=plans["planned_stop_break_ts"],
                        planned_final_ts=plans["planned_final_ts"],
                    )
                    phase = "working_before_break"

                if phase == "working_before_break":
                    if first_click_ts <= 0:
                        raise RuntimeError("Missing first_click_ts to resume break start")
                    latest_state = self._get_runtime_state()
                    plans = self._build_planned_clicks(
                        first_click_ts=first_click_ts,
                        planned_start_break_ts=self._safe_float(latest_state.get("planned_start_break_ts")),
                        planned_stop_break_ts=self._safe_float(latest_state.get("planned_stop_break_ts")),
                        planned_final_ts=self._safe_float(latest_state.get("planned_final_ts")),
                    )
                    second_click_ts = plans["planned_start_break_ts"]
                    self._sleep_until(second_click_ts)
                    open_target()
                    if self._is_icon_visible(page, "Icon-play", timeout_ms=2_000):
                        inferred_start_break_ts = self._infer_click_ts_from_events(
                            run_id=run_id,
                            click_name="start_break_click",
                        )
                        if inferred_start_break_ts <= 0:
                            self._set_runtime_state(
                                "on_break",
                                "On break detected from UI (manual state, unknown remaining time)",
                                run_id=run_id,
                                job=job_name,
                                ok=None,
                                first_click_ts=first_click_ts,
                                planned_start_break_ts=plans["planned_start_break_ts"],
                                planned_stop_break_ts=0.0,
                                planned_final_ts=plans["planned_final_ts"],
                                manual_state_detected=True,
                            )
                            self._append_runtime_event(
                                "manual_state_detected",
                                phase="on_break",
                                run_id=run_id,
                                job=job_name,
                                reason="break_start_detected_without_timestamp",
                            )
                            self.logger.info(
                                "Manual break detected without timing reference run_id=%s",
                                run_id,
                            )
                            snap("recovered_manual_on_break")
                            return {
                                "ok": True,
                                "resumed": False,
                                "phase": "on_break",
                                "run_id": run_id,
                                "reason": "manual_break_unknown_timing",
                            }
                        start_break_ts = inferred_start_break_ts
                        self._set_runtime_state(
                            "on_break",
                            "On break detected from UI (manual state)",
                            run_id=run_id,
                            job=job_name,
                            ok=None,
                            first_click_ts=first_click_ts,
                            start_break_ts=start_break_ts,
                            planned_start_break_ts=plans["planned_start_break_ts"],
                            planned_stop_break_ts=plans["planned_stop_break_ts"],
                            planned_final_ts=plans["planned_final_ts"],
                            manual_state_detected=True,
                        )
                        phase = "on_break"
                        self._append_runtime_event(
                            "manual_state_detected",
                            phase=phase,
                            run_id=run_id,
                            job=job_name,
                            reason="break_start_detected",
                        )
                        self.logger.info(
                            "Manual break detected and reconciled run_id=%s",
                            run_id,
                        )
                        snap("recovered_manual_on_break")
                    if phase == "working_before_break":
                        self._click_and_confirm_transition(page, "Icon-pause", "Icon-play", "break start")
                        start_break_at = datetime.now().isoformat()
                        self.send_status(
                            job_name,
                            run_id,
                            "start_break_click",
                            "Resume: clicked break start",
                        )
                        self.send_click_webhook(
                            self.webhook_start_break_url,
                            job_name=job_name,
                            run_id=run_id,
                            click_name="start_break_click",
                            ok=True,
                            meta={
                                "scheduled_at": datetime.fromtimestamp(second_click_ts).isoformat(),
                                "executed_at": start_break_at,
                                "recovered": True,
                            },
                        )
                        snap("recovered_start_break_click")
                        start_break_ts = datetime.fromisoformat(start_break_at).timestamp()
                        self._set_runtime_state(
                            "on_break",
                            "On break (resumed)",
                            run_id=run_id,
                            job=job_name,
                            ok=None,
                            first_click_ts=first_click_ts,
                            start_break_ts=start_break_ts,
                            planned_stop_break_ts=plans["planned_stop_break_ts"],
                            planned_final_ts=plans["planned_final_ts"],
                        )
                        phase = "on_break"

                if phase == "on_break":
                    if first_click_ts <= 0 or start_break_ts <= 0:
                        raise RuntimeError("Missing previous timestamps to resume break end")
                    latest_state = self._get_runtime_state()
                    plans = self._build_planned_clicks(
                        first_click_ts=first_click_ts,
                        planned_start_break_ts=self._safe_float(latest_state.get("planned_start_break_ts")),
                        planned_stop_break_ts=self._safe_float(latest_state.get("planned_stop_break_ts")),
                        planned_final_ts=self._safe_float(latest_state.get("planned_final_ts")),
                        stop_break_base_ts=start_break_ts,
                    )
                    third_click_ts = plans["planned_stop_break_ts"]
                    self._sleep_until(third_click_ts)
                    open_target()
                    self._click_and_confirm_transition(page, "Icon-play", "Icon-stop", "break end")
                    stop_break_at = datetime.now().isoformat()
                    break_gap_seconds = max(
                        0,
                        int(datetime.fromisoformat(stop_break_at).timestamp() - start_break_ts),
                    )
                    self.send_status(
                        job_name,
                        run_id,
                        "stop_break_click",
                        "Resume: clicked break end",
                    )
                    self.send_click_webhook(
                        self.webhook_stop_break_url,
                        job_name=job_name,
                        run_id=run_id,
                        click_name="stop_break_click",
                        ok=True,
                        meta={
                            "scheduled_at": datetime.fromtimestamp(third_click_ts).isoformat(),
                            "executed_at": stop_break_at,
                            "gap_seconds_from_start_break": break_gap_seconds,
                            "gap_minutes_from_start_break": round(break_gap_seconds / 60, 2),
                            "recovered": True,
                        },
                    )
                    snap("recovered_stop_break_click")
                    stop_break_ts = datetime.fromisoformat(stop_break_at).timestamp()
                    self._set_runtime_state(
                        "working_after_break",
                        "Final segment (resumed)",
                        run_id=run_id,
                        job=job_name,
                        ok=None,
                        first_click_ts=first_click_ts,
                        start_break_ts=start_break_ts,
                        stop_break_ts=stop_break_ts,
                        planned_final_ts=plans["planned_final_ts"],
                    )
                    phase = "working_after_break"

                if phase == "working_after_break":
                    if first_click_ts <= 0:
                        raise RuntimeError("Missing first_click_ts to resume final click")
                    latest_state = self._get_runtime_state()
                    plans = self._build_planned_clicks(
                        first_click_ts=first_click_ts,
                        planned_start_break_ts=self._safe_float(latest_state.get("planned_start_break_ts")),
                        planned_stop_break_ts=self._safe_float(latest_state.get("planned_stop_break_ts")),
                        planned_final_ts=self._safe_float(latest_state.get("planned_final_ts")),
                        stop_break_base_ts=start_break_ts,
                    )
                    final_ts = plans["planned_final_ts"]
                    self._sleep_until(final_ts)
                    open_target()
                    self._complete_end_of_day(page)
                    self.send_status(job_name, run_id, "final_click", "Resume: clicked end of workday")
                    snap("recovered_final_click")
                    final_click_ts = time.time()
                    result = {
                        "ok": True,
                        "job": job_name,
                        "run_id": run_id,
                        "url": page.url,
                        "data_dir": str(self.data_dir),
                        "recovered": True,
                    }
                    self._set_runtime_state(
                        "completed",
                        "Workday completed (resumed)",
                        run_id=run_id,
                        job=job_name,
                        ok=True,
                        first_click_ts=first_click_ts,
                        start_break_ts=start_break_ts,
                        stop_break_ts=stop_break_ts,
                        final_click_ts=final_click_ts,
                    )
                    self.send_final(job_name, run_id, result)
                    self._append_runtime_event(
                        "resume_completed",
                        phase="completed",
                        run_id=run_id,
                        job=job_name,
                        ok=True,
                    )
                    return {"ok": True, "resumed": True, "phase": "completed", "run_id": run_id}

                return {"ok": True, "resumed": False, "phase": phase, "run_id": run_id}

        except Exception as err:
            self.logger.exception("Error resuming job=%s run_id=%s", job_name, run_id)
            latest_state = self._get_runtime_state()
            prev_phase = str(latest_state.get("phase", ""))
            retry_phase = prev_phase if prev_phase in self.ACTIVE_PHASES else ""
            if page is not None:
                try:
                    page.screenshot(path=str(run_dir / "recovered_failed.png"), full_page=True)
                    (run_dir / "recovered_failed.html").write_text(page.content(), encoding="utf-8")
                    self.logger.info("Snapshot saved: recovered_failed")
                except Exception:
                    self.logger.exception("Could not save snapshot during failed resume")
            result = {
                "ok": False,
                "job": job_name,
                "run_id": run_id,
                "error": str(err),
                "url": page.url if page is not None else "",
                "recovered": True,
            }
            self._set_runtime_state(
                "failed",
                "Workday failed during resume",
                run_id=run_id,
                job=job_name,
                ok=False,
                error=str(err),
                failed_phase=retry_phase,
                **self._runtime_resume_fields(latest_state),
            )
            self.send_status(job_name, run_id, "error", f"Resume error: {err}", ok=False)
            self.send_final(job_name, run_id, result)
            return {"ok": False, "resumed": True, "phase": "failed", "run_id": run_id, "error": str(err)}

        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    self.logger.exception("Error closing Playwright context during resume")
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    self.logger.exception("Error closing Playwright browser during resume")
            self.logger.info("Playwright resources closed after resume job=%s run_id=%s", job_name, run_id)
            self._run_lock.release()

    def run_workday_flow(self, job_name: str, supervision: bool, run_id: str) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            result = {
                "ok": False,
                "job": job_name,
                "run_id": run_id,
                "error": "There is already an active run for workday_flow",
            }
            self._set_runtime_state(
                "failed",
                "Run rejected due to concurrency",
                run_id=run_id,
                job=job_name,
                ok=False,
                error=result["error"],
            )
            self.send_status(job_name, run_id, "busy", result["error"], ok=False)
            self.send_final(job_name, run_id, result)
            return result

        self._debug("Starting run_workday_flow", job_name=job_name, run_id=run_id, supervision=supervision)
        run_dir = self._artifact_dir(job_name, run_id)
        storage_path = self.data_dir / "storage" / f"{job_name}.json"
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Start job=%s run_id=%s supervision=%s artifacts=%s",
            job_name,
            run_id,
            supervision,
            run_dir,
        )

        first_start = self._today_at(6, 58)
        first_end = self._today_at(8, 31)
        rescue_end = self._today_at(9, 30)

        with sync_playwright() as p:
            browser = self._launch_browser(p, run_id=run_id, job_name=job_name, headless=True)
            context_kwargs: Dict[str, Any] = {}
            if storage_path.exists():
                context_kwargs["storage_state"] = str(storage_path)
                self.logger.info("Reutilizando storage_state desde %s", storage_path)

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            def snap(tag: str):
                page.screenshot(path=str(run_dir / f"{tag}.png"), full_page=True)
                (run_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
                self.logger.info("Snapshot saved: %s", tag)

            try:
                now = datetime.now()
                rescue_mode = now > first_end
                if now > rescue_end:
                    raise RuntimeError("Execution started after 09:30 for the first click")

                if rescue_mode:
                    random_first = time.time()
                    scheduled_message = "Normal window expired: first click (Icon-play) in immediate recovery mode"
                else:
                    random_first = random.uniform(first_start.timestamp(), first_end.timestamp())
                    scheduled_message = "First click (Icon-play) planned randomly"

                self._set_runtime_state(
                    "waiting_start",
                    "Waiting to start",
                    run_id=run_id,
                    job=job_name,
                    ok=None,
                    planned_first_ts=random_first,
                )
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_first",
                    scheduled_message,
                    extra={
                        "at": datetime.fromtimestamp(random_first).isoformat(),
                        "rescue_mode": rescue_mode,
                    },
                )
                self._debug(
                    "Scheduled wait for first click",
                    run_id=run_id,
                    planned_at=datetime.fromtimestamp(random_first).isoformat(),
                    rescue_mode=rescue_mode,
                )
                self._sleep_until(random_first)

                if not self.target_url:
                    raise RuntimeError("Missing target_url in configuration")

                self.logger.info("Opening target URL: %s", self._sanitize_url_for_log(self.target_url))
                page.goto(self.target_url, wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)

                url = page.url.lower()
                # Generic heuristic to detect authentication screens from different providers.
                auth_markers = ("login", "signin", "sso", "auth")
                if any(marker in url for marker in auth_markers):
                    self.logger.warning(
                        "Authentication flow detected at URL: %s",
                        self._sanitize_url_for_log(page.url),
                    )
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
                            self.logger.info("Sign-in identifier auto-filled")
                        except Exception:
                            self.logger.exception(
                                "Could not auto-fill sign-in identifier"
                            )
                    if supervision:
                        snap("sso_required")
                        raise RuntimeError(
                            "An authentication screen was detected. Complete login manually and run again"
                        )

                context.storage_state(path=str(storage_path))
                self.logger.info("storage_state updated at %s", storage_path)

                self._click_and_confirm_transition(page, "Icon-play", "Icon-pause", "start of workday")
                self.send_status(job_name, run_id, "first_click", "Clicked start button (Icon-play)")
                self.send_click_webhook(
                    self.webhook_start_url,
                    job_name=job_name,
                    run_id=run_id,
                    click_name="start_click",
                    ok=True,
                    meta={"executed_at": datetime.now().isoformat()},
                )
                snap("first_click")
                first_click_ts = time.time()

                plans = self._build_planned_clicks(first_click_ts=first_click_ts)
                second_click_ts = plans["planned_start_break_ts"]
                third_click_ts = plans["planned_stop_break_ts"]
                final_ts = plans["planned_final_ts"]
                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_start_break",
                    "Break start (Icon-pause) planned",
                    extra={"at": datetime.fromtimestamp(second_click_ts).isoformat()},
                )
                self._debug(
                    "Scheduled wait for break start",
                    run_id=run_id,
                    planned_at=datetime.fromtimestamp(second_click_ts).isoformat(),
                )
                self._set_runtime_state(
                    "working_before_break",
                    "Workday started",
                    run_id=run_id,
                    job=job_name,
                    ok=None,
                    first_click_ts=first_click_ts,
                    planned_start_break_ts=second_click_ts,
                    planned_stop_break_ts=third_click_ts,
                    planned_final_ts=final_ts,
                )
                self._sleep_until(second_click_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._click_and_confirm_transition(page, "Icon-pause", "Icon-play", "break start")
                start_break_at = datetime.now().isoformat()
                self.send_status(
                    job_name,
                    run_id,
                    "start_break_click",
                    "Clicked break start (Icon-pause)",
                )
                self.send_click_webhook(
                    self.webhook_start_break_url,
                    job_name=job_name,
                    run_id=run_id,
                    click_name="start_break_click",
                    ok=True,
                    meta={
                        "scheduled_at": datetime.fromtimestamp(second_click_ts).isoformat(),
                        "executed_at": start_break_at,
                    },
                )
                snap("start_break_click")
                start_break_ts = datetime.fromisoformat(start_break_at).timestamp()

                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_stop_break",
                    "Break end (Icon-play) planned",
                    extra={"at": datetime.fromtimestamp(third_click_ts).isoformat()},
                )
                self._debug(
                    "Scheduled wait for break end",
                    run_id=run_id,
                    planned_at=datetime.fromtimestamp(third_click_ts).isoformat(),
                )
                self._set_runtime_state(
                    "on_break",
                    "On break",
                    run_id=run_id,
                    job=job_name,
                    ok=None,
                    first_click_ts=first_click_ts,
                    start_break_ts=start_break_ts,
                    planned_stop_break_ts=third_click_ts,
                    planned_final_ts=final_ts,
                )
                self._sleep_until(third_click_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._click_and_confirm_transition(page, "Icon-play", "Icon-stop", "break end")
                stop_break_at = datetime.now().isoformat()
                self.send_status(
                    job_name,
                    run_id,
                    "stop_break_click",
                    "Clicked break end (Icon-play)",
                )
                break_gap_seconds = max(0, int(datetime.fromisoformat(stop_break_at).timestamp() - datetime.fromisoformat(start_break_at).timestamp()))
                self.send_click_webhook(
                    self.webhook_stop_break_url,
                    job_name=job_name,
                    run_id=run_id,
                    click_name="stop_break_click",
                    ok=True,
                    meta={
                        "scheduled_at": datetime.fromtimestamp(third_click_ts).isoformat(),
                        "executed_at": stop_break_at,
                        "gap_seconds_from_start_break": break_gap_seconds,
                        "gap_minutes_from_start_break": round(break_gap_seconds / 60, 2),
                    },
                )
                snap("stop_break_click")
                stop_break_ts = datetime.fromisoformat(stop_break_at).timestamp()

                self.send_status(
                    job_name,
                    run_id,
                    "scheduled_final",
                    "Final click (Icon-stop) planned",
                    extra={"at": datetime.fromtimestamp(final_ts).isoformat()},
                )
                self._debug(
                    "Scheduled wait for final click",
                    run_id=run_id,
                    planned_at=datetime.fromtimestamp(final_ts).isoformat(),
                )
                self._set_runtime_state(
                    "working_after_break",
                    "Final segment",
                    run_id=run_id,
                    job=job_name,
                    ok=None,
                    first_click_ts=first_click_ts,
                    start_break_ts=start_break_ts,
                    stop_break_ts=stop_break_ts,
                    planned_final_ts=final_ts,
                )
                self._sleep_until(final_ts)
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                self._dismiss_cookie_popup(page)
                self._dismiss_location_prompt(page)
                self._complete_end_of_day(page)
                self.send_status(job_name, run_id, "final_click", "Clicked end of workday (Icon-stop)")
                snap("final_click")
                final_click_ts = time.time()

                result = {
                    "ok": True,
                    "job": job_name,
                    "run_id": run_id,
                    "url": page.url,
                    "data_dir": str(self.data_dir),
                }
                self._set_runtime_state(
                    "completed",
                    "Workday completed",
                    run_id=run_id,
                    job=job_name,
                    ok=True,
                    first_click_ts=first_click_ts,
                    start_break_ts=start_break_ts,
                    stop_break_ts=stop_break_ts,
                    final_click_ts=final_click_ts,
                )
                self.send_final(job_name, run_id, result)
                self._debug("Run completed OK", job_name=job_name, run_id=run_id)
                return result

            except Exception as err:
                self.logger.exception("Execution error job=%s run_id=%s", job_name, run_id)
                latest_state = self._get_runtime_state()
                prev_phase = str(latest_state.get("phase", ""))
                retry_phase = prev_phase if prev_phase in self.ACTIVE_PHASES else ""
                try:
                    snap("failed")
                except Exception:
                    self.logger.exception("Could not save error snapshot")
                result = {
                    "ok": False,
                    "job": job_name,
                    "run_id": run_id,
                    "error": str(err),
                    "url": page.url if "page" in locals() else "",
                }
                self._set_runtime_state(
                    "failed",
                    "Workday failed",
                    run_id=run_id,
                    job=job_name,
                    ok=False,
                    error=str(err),
                    failed_phase=retry_phase,
                    **self._runtime_resume_fields(latest_state),
                )
                self.send_status(job_name, run_id, "error", f"Execution error: {err}", ok=False)
                self.send_final(job_name, run_id, result)
                self._debug("Run finished with error", job_name=job_name, run_id=run_id, error=str(err))
                return result

            finally:
                context.close()
                browser.close()
                self.logger.info("Playwright resources closed job=%s run_id=%s", job_name, run_id)
                self._run_lock.release()
