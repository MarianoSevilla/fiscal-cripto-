"""Chromium E2E: CSV Binance sintético -> diagnóstico fiscal incompleto PDF.

Usa Flask real con SQLite temporal y usuario ficticio, sin proveedores externos
ni datos privados. La ruta fiscal debe seguir bloqueada en el caso incompleto.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


EARN_SYNTHETIC = (
    "Tiempo,Moneda,Cantidad,Tipo\n"
    "2025-06-10,ABC,0.125,Real-time APR Rewards\n"
).encode("utf-8-sig")


def allow_local(route):
    if urlsplit(route.request.url).hostname == "127.0.0.1":
        route.continue_()
    else:
        route.abort()


def run_binance_incomplete(origin, cookie_name, cookie_value):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (375, 1280):
                context = browser.new_context(
                    viewport={"width": width, "height": 812},
                    accept_downloads=True,
                )
                context.route("**/*", allow_local)
                context.add_cookies([{
                    "name": cookie_name, "value": cookie_value,
                    "url": origin, "httpOnly": True, "sameSite": "Lax",
                }])
                try:
                    page = context.new_page()
                    page.set_default_timeout(16000)
                    errors = []
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    response = page.goto(origin + "/binance", wait_until="domcontentloaded")
                    assert response and response.status == 200
                    page.locator("#csvInput").set_input_files({
                        "name": "Earn-(UTC+1).csv",
                        "mimeType": "text/csv", "buffer": EARN_SYNTHETIC,
                    })
                    page.locator("#binancePendientes").wait_for(state="visible")
                    page.locator('input[name="alcance_datos"][value="solo_binance"]').check()
                    assert "Vista previa del archivo" in page.locator("#binancePendientes").inner_text()
                    assert "Qué aportar:" not in page.locator("#binancePendientes").inner_text()
                    page.locator("#btnAnalizar").click()
                    page.locator("#binanceIncompleteState").wait_for(state="visible")
                    assert not page.locator("#errorState").is_visible()
                    assert "Resultado provisional" in page.locator(
                        "#binanceIncompleteTitle"
                    ).inner_text()
                    assert "No es válido para declarar" in page.locator(
                        ".binance-incomplete-notice"
                    ).inner_text()
                    assert "Earn-(UTC+1).csv" in page.locator(
                        "#binanceIncompleteFiles"
                    ).inner_text()
                    assert "candidatos" in page.locator(
                        "#binanceIncompleteFactsNote"
                    ).inner_text()
                    assert not page.locator("#btnDownload").is_visible()
                    Path("qa-artifacts").mkdir(parents=True, exist_ok=True)
                    page.locator("#binanceIncompleteState").screenshot(
                        path=f"qa-artifacts/home_binance_incomplete_{width}.png",
                        animations="disabled",
                    )
                    assert page.locator("#binanceIncompleteGroups details").count() >= 1
                    assert page.locator("#binancePdfFeedback").inner_text() == ""
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 2"
                    ), f"Overflow horizontal en Binance incompleto a {width}px"
                    with page.expect_download(timeout=16000) as download_info:
                        page.locator("#binanceDiagnosticoPdf").click()
                    download = download_info.value
                    assert "NO_FISCAL" in download.suggested_filename
                    assert Path(download.path()).read_bytes().startswith(b"%PDF-")
                    assert not errors, errors
                    print("BINANCE_INCOMPLETE_CHROMIUM_PASS", width, flush=True)
                finally:
                    context.close()
        finally:
            browser.close()


def run_binance_internal_error_ui(origin, cookie_name, cookie_value):
    """A server failure is not blamed on the upload; original files remain retryable."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (375, 1280):
                context = browser.new_context(viewport={"width": width, "height": 812})
                context.route("**/*", allow_local)
                context.add_cookies([{
                    "name": cookie_name, "value": cookie_value,
                    "url": origin, "httpOnly": True, "sameSite": "Lax",
                }])
                try:
                    page = context.new_page()
                    page.set_default_timeout(16000)
                    page.route("**/api/binance/analizar", lambda route: route.fulfill(
                        status=500,
                        content_type="application/json",
                        body=json.dumps({
                            "result_type": "technical_error",
                            "error": "PRIVATE traceback that must not be shown",
                        }),
                    ))
                    response = page.goto(origin + "/binance", wait_until="domcontentloaded")
                    assert response and response.status == 200
                    page.locator("#csvInput").set_input_files({
                        "name": "Earn-(UTC+1).csv",
                        "mimeType": "text/csv", "buffer": EARN_SYNTHETIC,
                    })
                    page.locator("#binancePendientes").wait_for(state="visible")
                    page.locator('input[name="alcance_datos"][value="solo_binance"]').check()
                    page.locator("#btnAnalizar").click()
                    page.locator("#errorState").wait_for(state="visible")
                    description = page.locator("#errorDesc").inner_text()
                    assert "problema técnico" in description
                    assert "tus archivos sean incorrectos" in description
                    assert "PRIVATE traceback" not in page.locator("#errorState").inner_text()
                    assert page.locator("#errorSupportLink a[href='/contacto']").is_visible()
                    page.locator("#btnRetry").click()
                    assert page.locator("#btnAnalizar").is_enabled()
                    print("BINANCE_INTERNAL_ERROR_RETRY_CHROMIUM_PASS", width, flush=True)
                finally:
                    context.close()
        finally:
            browser.close()


def run_binance_rate_limit_ui(origin, cookie_name, cookie_value):
    """Renderiza esperas 429 reales del servidor y fallback sin inventar plazos."""
    cases = (
        (600, "10 minutos"),
        (3600, "1 hora"),
        (86400, "1 día"),
        (None, None),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (375, 1280):
                for retry_after, expected_wait in cases:
                    context = browser.new_context(viewport={"width": width, "height": 812})
                    context.route("**/*", allow_local)
                    context.add_cookies([{
                        "name": cookie_name, "value": cookie_value,
                        "url": origin, "httpOnly": True, "sameSite": "Lax",
                    }])
                    try:
                        page = context.new_page()
                        page.set_default_timeout(16000)
                        payload = {
                            "error": "Has alcanzado un límite temporal de análisis. Espera antes de volver a intentarlo.",
                            "ok": False,
                        }
                        headers = {"content-type": "application/json"}
                        if retry_after is not None:
                            payload["retry_after_seconds"] = retry_after
                            payload["error"] = (
                                "Has alcanzado un límite temporal de análisis. "
                                f"Podrás volver a intentarlo en {expected_wait}."
                            )
                            headers["Retry-After"] = str(retry_after)
                        response_body = json.dumps(payload)

                        def fulfill_rate_limit(route, request=None):
                            return route.fulfill(
                                status=429, headers=headers, body=response_body
                            )

                        page.route("**/api/binance/analizar", fulfill_rate_limit)
                        response = page.goto(origin + "/binance", wait_until="domcontentloaded")
                        assert response and response.status == 200
                        page.locator("#csvInput").set_input_files({
                            "name": "Earn-(UTC+1).csv",
                            "mimeType": "text/csv", "buffer": EARN_SYNTHETIC,
                        })
                        page.locator("#binancePendientes").wait_for(state="visible")
                        page.locator("#btnAnalizar").click()
                        page.locator("#errorState").wait_for(state="visible")
                        description = page.locator("#errorDesc").inner_text()
                        assert "Has alcanzado temporalmente el límite de análisis." in description
                        if expected_wait:
                            assert f"Podrás volver a intentarlo en {expected_wait}." in description, (
                                width, expected_wait, description
                            )
                        else:
                            assert "Vuelve a intentarlo más tarde." in description
                            assert not any(value in description for value in (
                                "10 minutos", "1 hora", "1 día"
                            )), (width, description)
                        assert page.locator("#errorTitulo").inner_text() == "Límite de análisis alcanzado"
                        print("BINANCE_RATE_LIMIT_UI_PASS", width, retry_after, flush=True)
                    finally:
                        context.close()
        finally:
            browser.close()
