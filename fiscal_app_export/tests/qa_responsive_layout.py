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
from qa_herramientas_apple import run_herramientas_apple


def main():
    with server() as origin, sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            run_home_redesign(browser,origin)
            run_herramientas_apple(browser,origin)
        finally:
            browser.close()


if __name__=='__main__':
    main()
