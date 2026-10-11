"""No live page/provider: real browser checks of static maintenance document."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from advisory_prefreeze import SUSPENSION_MESSAGE
html = (Path(__file__).resolve().parents[1] / 'static' / 'pagar.html').read_text()
with sync_playwright() as p:
    browser = p.chromium.launch()
    for javascript in (True, False):
        for width in (320, 375, 768, 1440):
            context = browser.new_context(viewport={'width': width, 'height': 900},
                                          java_script_enabled=javascript)
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_content(html)
            notice = page.locator('#financialSuspension')
            assert notice.is_visible()
            assert SUSPENSION_MESSAGE in notice.inner_text()
            assert page.locator('button, form, a[href*="paypal"], a[href*="stripe"]').count() == 0
            box = notice.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert page.locator('body').bounding_box()['width'] <= width
            context.close()
    browser.close()
print('PREFREEZE browser: 8 mobile/tablet/desktop + JS on/off cases PASS')
