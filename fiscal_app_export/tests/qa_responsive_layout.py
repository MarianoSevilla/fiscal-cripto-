"""Auditoría visual reproducible de la Home, sólo datos ficticios y HTTP local.

Se ejecuta independientemente de pytest: crea capturas y valida geometría.
No precisa Flask, acceso a Railway, credenciales ni CSV reales.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from qa_responsive_nav import server

WIDTHS = (320, 375, 390, 480, 768, 900, 901, 1024, 1200, 1201, 1280)
SELECTORS = (
    ".hero-wrap",
    ".hero-header",
    ".hero-body",
    ".hero-left",
    ".btn-primary",
    ".asistencia-block",
    ".btn-asistencia",
    ".authors",
    ".hero-right",
    ".device-frame",
    ".compatible-inner",
)
TEXT_ELEMENTS = ("h1", ".hero-desc", ".cta-micro", ".author-role")
ARTIFACTS = Path("qa-artifacts")


def audit_page(page, width):
    failures = []
    for selector in SELECTORS + TEXT_ELEMENTS:
        loc = page.locator(selector).first
        if not loc.count() or not loc.is_visible():
            continue
        result = loc.evaluate("""el => {
          const r = el.getBoundingClientRect();
          return {left:r.left, right:r.right, top:r.top,
                  scrollWidth:el.scrollWidth, clientWidth:el.clientWidth};
        }""")
        if result["left"] < -1 or result["right"] > width + 1:
            failures.append(f"{selector}: fuera de pantalla {result}")
        if selector in TEXT_ELEMENTS and result["scrollWidth"] > result["clientWidth"] + 1:
            failures.append(f"{selector}: texto desbordado {result}")

    # El overflow-x:hidden del body puede ocultar un ancho incorrecto:
    # inspeccionar todo el documento, no sólo el Hero.
    metrics = page.evaluate("""() => {
      const vw = document.documentElement.clientWidth;
      const root = document.documentElement.scrollWidth;
      const body = document.body.scrollWidth;
      const offenders = [...document.body.querySelectorAll('*')]
        .filter(el => {
          const st = getComputedStyle(el);
          if (st.display === 'none' || st.visibility === 'hidden') return false;
          const r = el.getBoundingClientRect();
          return r.width > 0 && (r.right > vw + 1 || r.left < -1);
        })
        .map(el => {
          const r = el.getBoundingClientRect();
          return {tag:el.tagName.toLowerCase(), id:el.id || '',
                  cls:String(el.className || '').slice(0,65),
                  left:Math.round(r.left),right:Math.round(r.right)};
        })
        .sort((a,b)=>b.right-a.right).slice(0,16);
      return {vw,root,body,offenders};
    }""")
    if metrics["root"] > width + 1 or metrics["body"] > width + 1:
        failures.append(f"desbordamiento global: {metrics}")

    nav = page.locator("#snavMenuToggle")
    if width <= 1200 and not nav.is_visible():
        failures.append("menú móvil no visible")
    if width > 1200 and nav.is_visible():
        failures.append("menú compacto visible en escritorio amplio")
    return failures


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    all_failures = []
    with server() as origin, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for width in WIDTHS:
                page = browser.new_page(viewport={"width":width, "height":812}, device_scale_factor=1)
                # Permitir únicamente los dos hosts de las fuentes reales del diseño.
                # Todos los demás recursos externos siguen bloqueados.
                def font_only(route):
                    host = urlsplit(route.request.url).hostname
                    if host in ("fonts.googleapis.com", "fonts.gstatic.com"):
                        route.continue_()
                    else:
                        route.abort()
                page.route("https://**/*", font_only)
                page.route("**/api/me", lambda route:route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"user":None}),
                ))
                try:
                    page.goto(origin + "/", wait_until="domcontentloaded", timeout=20000)
                    page.locator("#snavBtnSignup:not(.snav-hidden)").wait_for(state="attached", timeout=15000)
                    font_status = page.evaluate("""async () => {
                      await document.fonts.ready;
                      const loaded = [...document.fonts].filter(f => f.status === 'loaded')
                        .map(f => f.family.replace(/['"]/g,''));
                      return {syne: loaded.includes('Syne'), dm: loaded.includes('DM Sans'),
                              loadedFonts:loaded};
                    }""")
                    if not font_status["syne"] or not font_status["dm"]:
                        all_failures.append(
                            f"{width}px: no se cargaron fuentes reales: {font_status}"
                        )
                    image_path = ARTIFACTS / f"home_{width}px.png"
                    page.screenshot(path=str(image_path),
                                    full_page=True, animations="disabled")
                    # Leer el ancho del propio PNG evita falsos negativos por CSS clip.
                    with image_path.open("rb") as image_file:
                        image_file.seek(16)
                        png_width = int.from_bytes(image_file.read(4), "big")
                    issues = audit_page(page, width)
                    if png_width != width:
                        issues.append(f"captura PNG mide {png_width}px, viewport {width}px")
                    all_failures.extend(f"{width}px: {issue}" for issue in issues)
                    print(f"Home {width}px: {'PASS' if not issues else 'FAIL'} ({len(issues)} incidencias)")
                finally:
                    page.close()
        finally:
            browser.close()
    if all_failures:
        print("Incidencias de geometría detectadas:")
        for issue in all_failures:
            print("-",issue)
        raise AssertionError(f"{len(all_failures)} incidencias responsive")
    print(f"Home: {len(WIDTHS)} tamaños sin desbordamiento de elementos principales.")


if __name__ == "__main__":
    main()
