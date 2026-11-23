"""Synthetic Chromium checks for definitive, error and provisional UI results."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


SYNTHETIC_CSV = b"Date,Coin,Amount\n2025-01-01,BTC,0.01\n"
SYNTHETIC_PDF = b"%PDF-1.4\n% synthetic browser fixture\n%%EOF\n"


def _local_only(route):
    if urlsplit(route.request.url).hostname == "127.0.0.1":
        route.continue_()
    else:
        route.abort()


def run_fifo_results_browser(origin, cookie_name, cookie_value):
    provisional = {
        "no_es_informe_fiscal": True,
        "exchange_nombre": "Bitvavo",
        "alcance_descripcion": "El usuario declara actividad en otros exchanges o wallets.",
        "pendientes": [{"descripcion": "Faltan historiales de otras fuentes."}],
        "siguiente_paso": "Aporta historiales originales y repite el análisis.",
        "operaciones_detectadas": {"compraventas_candidatas": 1},
    }
    outcomes = {
        "definitive": (200, {"ok": True, "result_type": "definitive", "token": "synthetic.pdf",
                             "resumen": {"resultado_neto": 10}, "operaciones": [],
                             "posicion": [], "rendimientos": [], "advertencias": []}),
        "error": (500, {"ok": False, "result_type": "processing_error", "error": "PRIVATE traceback"}),
        "provisional": (422, {"ok": False, "result_type": "provisional", "error": "No definitivo",
                               "borrador_fifo": provisional, "token_pdf_diagnostico_fifo": "signed.synthetic.token"}),
    }
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        # Optional local override for environments with system Chromium but no Playwright download.
        if os.environ.get("FIFO_CHROMIUM_EXECUTABLE_PATH"):
            launch_options["executable_path"] = os.environ["FIFO_CHROMIUM_EXECUTABLE_PATH"]
        browser = playwright.chromium.launch(**launch_options)
        try:
            for width in (375, 1280):
                for outcome, (status, body) in outcomes.items():
                    context = browser.new_context(
                        viewport={"width": width, "height": 812}, accept_downloads=True,
                    )
                    context.route("**/*", _local_only)
                    context.add_cookies([{
                        "name": cookie_name, "value": cookie_value,
                        "url": origin, "httpOnly": True, "sameSite": "Lax",
                    }])
                    try:
                        page = context.new_page()
                        page.set_default_timeout(16000)
                        page.route("**/api/analizar", lambda route, _request, s=status, b=body: route.fulfill(
                            status=s, content_type="application/json", body=json.dumps(b),
                        ))
                        page.route("**/api/fifo/diagnostico-pdf", lambda route, _request: route.fulfill(
                            status=200, content_type="application/pdf",
                            headers={"Content-Disposition": 'attachment; filename="Bitvavo_diagnostico_INCOMPLETO_NO_FISCAL.pdf"'},
                            body=SYNTHETIC_PDF,
                        ))
                        page.route("**/api/descargar/synthetic.pdf**", lambda route, _request: route.fulfill(
                            status=200, content_type="application/pdf",
                            headers={"Content-Disposition": 'attachment; filename="informe_FIFO.pdf"'},
                            body=SYNTHETIC_PDF,
                        ))
                        page.goto(origin + "/bitvavo", wait_until="domcontentloaded")
                        page.locator("#csvInput").set_input_files({
                            "name": "synthetic.csv", "mimeType": "text/csv", "buffer": SYNTHETIC_CSV,
                        })
                        page.locator('input[name="alcance_datos"][value="solo_exchange"]').check()
                        page.locator("#btnAnalizar").click()
                        if outcome == "definitive":
                            page.locator("#resultsContent").wait_for(state="visible")
                            assert page.locator("#btnDownload").is_visible()
                            with page.expect_download(timeout=16000) as info:
                                page.locator("#btnDownload").click()
                            assert Path(info.value.path()).read_bytes().startswith(b"%PDF-")
                        elif outcome == "error":
                            page.locator("#errorState").wait_for(state="visible")
                            assert "problema técnico" in page.locator("#errorDesc").inner_text()
                            assert "PRIVATE traceback" not in page.locator("#errorState").inner_text()
                            page.locator("#btnRetry").click()
                            assert page.locator("#btnAnalizar").is_enabled()
                        else:
                            page.locator("#fifoProvisionalState").wait_for(state="visible")
                            assert "No es válido para declarar" in page.locator("#fifoProvisionalState").inner_text()
                            assert not page.locator("#btnDownload").is_visible()
                            with page.expect_download(timeout=16000) as info:
                                page.locator("#fifoProvisionalPdf").click()
                            assert "NO_FISCAL" in info.value.suggested_filename
                            assert Path(info.value.path()).read_bytes().startswith(b"%PDF-")
                        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 2")
                        print("FIFO_RESULTS_CHROMIUM_PASS", outcome, width, flush=True)
                    finally:
                        context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit("Import run_fifo_results_browser from qa_flask_navigation.py")
