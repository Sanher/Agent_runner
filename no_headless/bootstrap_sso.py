#!/usr/bin/env python3
"""
Bootstrap manual de sesión SSO en modo headed para reutilizar storage_state.

Uso:
  TARGET_URL="https://tu-url" python3 no_headless/bootstrap_sso.py

Opcional:
  OUT_FILE="/ruta/workday_flow.json"
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    target_url = os.getenv("TARGET_URL", "").strip()
    if not target_url:
        raise SystemExit("Falta TARGET_URL. Ejemplo: TARGET_URL='https://tu-url' python3 no_headless/bootstrap_sso.py")

    out_file = os.getenv("OUT_FILE", "no_headless/workday_flow.json").strip()
    out_path = Path(out_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=120_000)

        print("Completa el SSO/cookies manualmente en la ventana del navegador.")
        input("Cuando termines, pulsa ENTER aquí para guardar la sesión... ")

        context.storage_state(path=str(out_path))
        print(f"Storage state guardado en: {out_path}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
