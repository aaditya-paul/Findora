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
import re
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

_PINIMG_LOW_RES_SEGMENT = re.compile(r"/(?:75x75|140x|170x|236x|280x280_RS|474x|564x|736x)/")
_PINIMG_SIZE_SEGMENT = re.compile(r"/(\d+)x(?:\d+_RS)?/")


def _promote_pinimg_url(url: str) -> str:
    if "pinimg.com" not in url:
        return url
    if "/originals/" in url:
        return url
    return _PINIMG_LOW_RES_SEGMENT.sub("/originals/", url)


def _url_quality_score(url: str) -> int:
    if not url or "pinimg.com" not in url:
        return -1
    if "/originals/" in url:
        return 1_000_000
    m = _PINIMG_SIZE_SEGMENT.search(url)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def _pick_best_from_srcset(srcset: str | None) -> tuple[str | None, str | None, float]:
    if not srcset:
        return None, None, -1.0

    best_url = None
    best_descriptor = None
    best_score = -1.0
    best_url_score = -1

    # Format: "url 1x, url 2x" or "url 236w, url 474w"
    for candidate in srcset.split(","):
        token = candidate.strip()
        if not token:
            continue

        parts = token.split()
        if not parts:
            continue

        url = parts[0].strip()
        descriptor = parts[1].strip() if len(parts) > 1 else ""

        score = 1.0
        if descriptor.endswith("x"):
            try:
                score = float(descriptor[:-1])
            except ValueError:
                score = 1.0
        elif descriptor.endswith("w"):
            try:
                score = float(descriptor[:-1])
            except ValueError:
                score = 1.0

        url_score = _url_quality_score(url)
        if score > best_score or (score == best_score and url_score > best_url_score):
            best_score = score
            best_url = url
            best_descriptor = descriptor or None
            best_url_score = url_score

    return best_url, best_descriptor, best_score

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
                "img",
                "els => els.map(e => { const pic = e.closest('picture'); const srcset = e.srcset || e.getAttribute('srcset') || ''; const dataSrcset = e.getAttribute('data-srcset') || ''; const dataSrc = e.getAttribute('data-src') || ''; const sourceSrcset = pic ? Array.from(pic.querySelectorAll('source')).map(s => s.srcset || s.getAttribute('srcset') || '').join(', ') : ''; return ({src: e.src || '', currentSrc: e.currentSrc || '', srcset, dataSrcset, dataSrc, sourceSrcset, alt: e.alt || '', nw: e.naturalWidth || 0, nh: e.naturalHeight || 0}); })"
            )
            log.info(f"[SCRAPER] Found {len(imgs)} raw images")
            await ctx.close()
            await browser.close()

        seen = set()
        quality = []
        for i in imgs:
            srcset_blob = ", ".join(
                part for part in [
                    i.get("srcset", ""),
                    i.get("dataSrcset", ""),
                    i.get("sourceSrcset", ""),
                ] if part
            )
            best_srcset_url, best_descriptor, best_score = _pick_best_from_srcset(srcset_blob)

            raw_candidates = [
                best_srcset_url,
                i.get("currentSrc", ""),
                i.get("dataSrc", ""),
                i.get("src", ""),
            ]
            raw_candidates = [c for c in raw_candidates if c and "pinimg.com" in c and len(c) > 30]
            if not raw_candidates:
                continue

            promoted_candidates = [_promote_pinimg_url(c) for c in raw_candidates]
            promoted = max(promoted_candidates, key=_url_quality_score)

            nw = int(i.get("nw", 0) or 0)
            nh = int(i.get("nh", 0) or 0)
            if nw > 0 and nh > 0 and max(nw, nh) < 220 and _url_quality_score(promoted) < 700:
                continue

            if promoted in seen:
                continue
            seen.add(promoted)

            if best_srcset_url:
                log.debug(
                    "[SCRAPER] srcset winner descriptor=%s score=%s url=%s",
                    best_descriptor,
                    best_score,
                    promoted,
                )

            quality.append({"src": promoted, "alt": i.get("alt", "")})

        return quality[:n]
