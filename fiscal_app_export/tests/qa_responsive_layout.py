"""Run the approved responsive browser suites with bounded, visible progress.

Each suite retains its existing assertions. Running suites in separate processes
prevents a stuck Playwright page/cleanup from hiding the failing module or
holding the entire required CI job indefinitely.
"""
import os
import signal
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright
from qa_responsive_nav import server
from qa_home_redesign import run_home_redesign
from qa_herramientas_redesign import run_herramientas_apple
from qa_como_funciona_apple import run_como_funciona_apple
from qa_recursos_apple import run_recursos_apple
from qa_faq_apple import run_faq_apple
from qa_privacidad_apple import run_privacidad_apple
from qa_terminos_apple import run_terminos_apple
from qa_contacto_apple import run_contacto_apple
from qa_exchanges_apple import run_exchanges_apple
from qa_about_apple import run_about_apple
from qa_auth_apple import run_auth_apple
from qa_dashboard_apple import run_dashboard_apple


# Keep the original coverage and order, but identify the module if it stalls.
SUITES = {
    "dashboard": run_dashboard_apple,
    "auth": run_auth_apple,
    "about": run_about_apple,
    "exchanges": run_exchanges_apple,
    "contacto": run_contacto_apple,
    "terminos": run_terminos_apple,
    "privacidad": run_privacidad_apple,
    "faq": run_faq_apple,
    "home": run_home_redesign,
    "herramientas": run_herramientas_apple,
    "como_funciona": run_como_funciona_apple,
    "recursos": run_recursos_apple,
}
SUITE_TIMEOUT_SECONDS = 180


def _run_suite(name):
    if name not in SUITES:
        raise ValueError(f"Unknown responsive suite: {name}")
    with server() as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            SUITES[name](browser, origin)
        finally:
            browser.close()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--suite":
        name = sys.argv[2]
        print(f"[responsive] Running {name}", flush=True)
        _run_suite(name)
        print(f"[responsive] Finished {name}", flush=True)
        return

    if len(sys.argv) != 1:
        raise SystemExit("Usage: qa_responsive_layout.py [--suite SUITE_NAME]")

    for name in SUITES:
        print(f"[responsive] START {name} (timeout {SUITE_TIMEOUT_SECONDS}s)", flush=True)
        start = time.monotonic()
        process = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--suite", name],
            start_new_session=(os.name == "posix"),
        )
        try:
            code = process.wait(timeout=SUITE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            raise SystemExit(
                f"[responsive] TIMEOUT {name} after {SUITE_TIMEOUT_SECONDS}s"
            )
        if code != 0:
            raise SystemExit(f"[responsive] FAIL {name} (exit {code})")
        print(f"[responsive] PASS {name} ({time.monotonic()-start:.1f}s)", flush=True)

    print(f"[responsive] PASS all {len(SUITES)} suites", flush=True)


if __name__ == "__main__":
    main()
