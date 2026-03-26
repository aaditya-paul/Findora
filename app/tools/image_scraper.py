"""
ImageScraper — anti-detection Pinterest scraper.

Strategy:
  - Uses a saved Pinterest session file (data/pinterest_session.json) for auth.
  - If no session file exists, falls back to a clean anonymous browser.
  - Run the one-time login flow from the Streamlit sidebar to generate the session file.

Anti-detection techniques:
  🥈  Human-like behaviour: random delays, natural mouse paths, scroll pauses
  🥉  Tracker / ad blocking to reduce detection surface
  🥇⭐ Manual CAPTCHA solve mode: pause, let user solve, resume
"""

import asyncio
import logging
import os
import random
import time
from pathlib import Path
from playwright.async_api import async_playwright, Page

log = logging.getLogger(__name__)

DEBUG_DIR   = Path("debug")
SESSION_FILE = Path("data/pinterest_session.json")

# Domains to block — reduces bot-detection surface
BLOCKED_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "connect.facebook.net",
    "facebook.com",
    "facebook.net",
    "scorecardresearch.com",
    "hotjar.com",
    "segment.io",
    "segment.com",
    "ads.pinterest.com",
    "recaptcha.net",          # block recaptcha probes (won't stop CAPTCHA page, but reduces fingerprint)
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Human-like helpers
# ---------------------------------------------------------------------------

async def _delay(min_ms=800, max_ms=2200):
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def _mouse_drift(page: Page):
    x = random.randint(200, 1000)
    y = random.randint(150, 700)
    await page.mouse.move(x, y, steps=random.randint(12, 25))


async def _human_scroll(page: Page, rounds=6):
    for _ in range(rounds):
        await page.mouse.wheel(0, random.randint(350, 850))
        await _delay(500, 1400)
        if random.random() < 0.3:
            await _delay(1200, 2800)   # occasional longer pause
        await _mouse_drift(page)


# ---------------------------------------------------------------------------
# Tracker blocking
# ---------------------------------------------------------------------------

async def _block_trackers(route, request):
    if any(d in request.url for d in BLOCKED_DOMAINS):
        await route.abort()
    else:
        await route.continue_()


# ---------------------------------------------------------------------------
# CAPTCHA handler — pause, let user solve, resume
# ---------------------------------------------------------------------------

async def _handle_captcha(page: Page) -> bool:
    sel = '[id*="captcha"], [class*="captcha"], [data-test-id*="captcha"], iframe[src*="recaptcha"]'
    
    # We only care if the CAPTCHA is actually VISIBLE on screen.
    # Pinterest often has hidden captcha elements in the DOM.
    try:
        await page.wait_for_selector(sel, state="visible", timeout=3000)
    except Exception:
        # No visible captcha appeared
        return False

    shot = DEBUG_DIR / "screenshots" / f"captcha_{int(time.time())}.png"
    await page.screenshot(path=str(shot))
    log.warning(f"[SCRAPER] ⚠️  CAPTCHA visible! Screenshot → {shot}")

    print("\n" + "=" * 60)
    print("⚠️  CAPTCHA DETECTED on Pinterest!")
    print("The browser window is open. Please solve the CAPTCHA manually.")
    print("The script will automatically resume once the CAPTCHA disappears.")
    print("=" * 60)

    # Automatically resume when the CAPTCHA element is no longer visible
    try:
        await page.wait_for_selector(sel, state="hidden", timeout=0)
    except Exception as e:
        log.warning(f"[SCRAPER] Error waiting for CAPTCHA to clear: {e}")

    log.info("[SCRAPER] CAPTCHA solved/cleared. Resuming...")
    return True


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

class ImageScraper:
    """Playwright Pinterest scraper with session auth and anti-detection."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        (DEBUG_DIR / "screenshots").mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / "videos").mkdir(parents=True, exist_ok=True)

    async def scrape_pinterest(self, query: str, n: int = 8) -> list[dict]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            ctx_kwargs: dict = dict(
                viewport={"width": 1280, "height": 900},
                user_agent=_USER_AGENT,
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )

            # Load saved session if available
            if SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 10:
                ctx_kwargs["storage_state"] = str(SESSION_FILE)
                log.info("[SCRAPER] Loaded Pinterest session from disk ✅")
            else:
                log.warning("[SCRAPER] No session file — using anonymous browser. Login via sidebar for best results.")

            ctx = await browser.new_context(**ctx_kwargs)

            # Block trackers across all pages in this context
            await ctx.route("**/*", _block_trackers)

            page = await ctx.new_page()
            page.on("pageerror",     lambda e: log.error(f"[PAGE ERROR] {e}"))
            page.on("requestfailed", lambda r: log.debug(f"[REQ FAILED] {r.url}"))

            url = f"https://www.pinterest.com/search/pins/?q={query.replace(' ', '+')}"
            log.info(f"[SCRAPER] Navigating → {url}")

            await _delay(400, 900)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log.warning(f"[SCRAPER] Page load timeout, continuing: {e}")

            await _delay(1200, 2500)

            # CAPTCHA check #1
            await _handle_captcha(page)

            # Human scroll
            await _human_scroll(page, rounds=random.randint(5, 8))

            # CAPTCHA check #2 (sometimes triggered post-scroll)
            await _handle_captcha(page)

            # If logged in, save refreshed session cookies
            if SESSION_FILE.exists():
                await ctx.storage_state(path=str(SESSION_FILE))

            await page.screenshot(
                path=str(DEBUG_DIR / "screenshots" / f"pinterest_{int(time.time())}.png")
            )

            imgs = await page.eval_on_selector_all(
                "img[src*='pinimg.com']",
                "els => els.map(e => ({src: e.src, alt: e.alt || ''}))"
            )
            log.info(f"[SCRAPER] Found {len(imgs)} raw images")
            await ctx.close()
            await browser.close()

        quality = [i for i in imgs if "236x" not in i["src"] and len(i["src"]) > 30]
        return quality[:n]
