"""
Pinterest session auth helper.

Launches a visible Chromium browser so the user can log in manually.
Once logged in, the session state (cookies) is saved to disk and
reused by the ImageScraper for all future requests.
"""

import asyncio
import sys
import logging
from pathlib import Path

STATE_PATH = Path("data/pinterest_session.json")
log = logging.getLogger(__name__)


async def _launch_login_browser():
    from playwright.async_api import async_playwright

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await page.goto("https://www.pinterest.com/login/", wait_until="domcontentloaded")

        print("\n[Pinterest Auth] A browser window has opened.")
        print("[Pinterest Auth] Please log in to Pinterest.")
        print("[Pinterest Auth] Waiting for login to complete... (URL change)")
        
        # Streamlit swallows stdin, so input() returns instantly. 
        # Instead, wait infinitely until the URL proves we are no longer on the login page.
        try:
            await page.wait_for_url(lambda url: "login" not in url.lower(), timeout=0)
            # Give it a couple of seconds to ensure storage state cookies are finalized
            await page.wait_for_timeout(3000)
        except Exception as e:
            log.warning(f"Error waiting for auth: {e}")

        # Save cookies / storage state
        await ctx.storage_state(path=str(STATE_PATH))
        log.info(f"[Pinterest Auth] Session saved to {STATE_PATH}")
        await browser.close()


def run_login_flow():
    """Blocking entry point — call from Streamlit button handler."""
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_launch_login_browser())
        finally:
            loop.close()
    else:
        asyncio.run(_launch_login_browser())


def session_exists() -> bool:
    return STATE_PATH.exists() and STATE_PATH.stat().st_size > 10
