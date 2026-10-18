"""Audit the approved Home at the actual / URL, with synthetic data only.

The redesign uses local system fonts, native table scrolling and the shared
session renderer. The previous audit assumed the replaced hero structure and
required external Syne/DM Sans fonts; these assumptions no longer apply.
The replacement exercises 13 widths, document overflow, keyboard, roles,
delayed sessions, 200% text and native no-JavaScript navigation.
"""
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


def main():
    with server() as origin, sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            run_dashboard_apple(browser,origin)
            run_auth_apple(browser,origin)
            run_about_apple(browser,origin)
            run_exchanges_apple(browser,origin)
            run_contacto_apple(browser,origin)
            run_terminos_apple(browser,origin)
            run_privacidad_apple(browser,origin)
            run_faq_apple(browser,origin)
            run_home_redesign(browser,origin)
            run_herramientas_apple(browser,origin)
            run_como_funciona_apple(browser,origin)
            run_recursos_apple(browser,origin)
        finally:
            browser.close()


if __name__=='__main__':
    main()
