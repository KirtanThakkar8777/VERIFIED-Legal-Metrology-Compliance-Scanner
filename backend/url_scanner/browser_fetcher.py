"""
url_scanner/browser_fetcher.py
Playwright-based headless browser fetcher for JavaScript-rendered e-commerce pages.

Called ONLY when static HTML fetch yields 0 product images.
Runs Chromium in headless mode, waits for the product gallery to render,
then extracts all image URLs from the live DOM and embedded application state.

This is the fallback for: Flipkart, Meesho, JioMart, Nykaa, BigBasket, etc.
"""
from __future__ import annotations
import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

# ── Image URL patterns ─────────────────────────────────────────────────────────
_IMG_SKIP = re.compile(
    r"(logo|icon|banner|arrow|star|rating|spinner|favicon|cart|wishlist|"
    r"share|badge|nav|menu|button|placeholder|blank|spacer|pixel|advertisement|"
    r"loader|shimmer|skeleton|retaillabs)",
    re.IGNORECASE,
)
_IMG_EXTENSIONS = re.compile(
    r"\.(jpe?g|png|webp|avif|gif)(\?|$)", re.IGNORECASE
)
_CDN_HOSTS = re.compile(
    r"(rukminim|img-f\.scribdassets|fk-p-l\.justdial|"
    r"cf\.shopify|images-na\.ssl-images-amazon|m\.media-amazon|"
    r"media\.flipkart|img-f\.meesho|assets\.myntassets|"
    r"bigbasket\.com/media|grofers|blinkit|zepto|magicpin)",
    re.IGNORECASE,
)

# Embedded state key patterns that contain image arrays
_STATE_IMAGE_KEYS = re.compile(
    r'"(?:imageUrl|image_url|images|imageUrls|media|gallery|'
    r'productImages|mediaGallery|imageList|imageData|photos|'
    r'primaryImageUrl|imageUrlWebp|thumbnailUrl)":\s*"?(https?://[^">\s]+\.(?:jpe?g|png|webp))',
    re.IGNORECASE,
)


def _is_useful_image(url: str) -> bool:
    """Quick check if an image URL is likely a product image."""
    if not url or len(url) < 15:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    # Skip obvious UI images
    if _IMG_SKIP.search(url):
        return False
    # Must look like an image
    if not (_IMG_EXTENSIONS.search(url) or _CDN_HOSTS.search(url) or
            "image" in url.lower() or "img" in url.lower()):
        return False
    return True


def _normalize_img_url(url: str, base_url: str) -> str:
    """Make URL absolute and upgrade to high-res where possible."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = urljoin(base_url, url)
    # Flipkart: upgrade to high-res
    url = re.sub(r"/\d{2,3}/\d{2,3}/", "/832/832/", url)
    return url


def _parse_srcset(srcset: str) -> str:
    """Extract highest-resolution URL from a srcset attribute."""
    if not srcset:
        return ""
    best_url = ""
    best_size = 0
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        url = tokens[0]
        size = 0
        if len(tokens) > 1:
            w_desc = tokens[-1].rstrip("w")
            try:
                size = int(w_desc)
            except ValueError:
                size = 0
        if size > best_size or (size == 0 and not best_url):
            best_size = size
            best_url = url
    return best_url


def _extract_images_from_state(page_content: str, base_url: str) -> list[dict]:
    """Extract product image URLs from embedded application state JSON."""
    found: list[dict] = []
    seen: set[str] = set()

    # Direct regex over the entire page source for image URLs in JSON values
    for m in _STATE_IMAGE_KEYS.finditer(page_content):
        url = m.group(1)
        url = _normalize_img_url(url, base_url)
        if url and url not in seen and _is_useful_image(url):
            seen.add(url)
            found.append({"url": url, "alt": "product", "score": 15, "source": "browser_state"})

    # Also scan for bare image URL strings in JSON
    bare_img_pattern = re.compile(
        r'"(https?://[^"]+\.(?:jpe?g|png|webp)(?:\?[^"]*)?)"',
        re.IGNORECASE,
    )
    for m in bare_img_pattern.finditer(page_content):
        url = m.group(1)
        if url and url not in seen and _is_useful_image(url):
            # Flipkart CDN specifically
            if "rukminim" in url or "meeshocdn" in url or "bigbasket" in url:
                seen.add(url)
                found.append({"url": url, "alt": "product", "score": 18, "source": "browser_cdn"})

    return found


async def fetch_rendered_page(url: str, timeout_s: float = 60.0) -> dict:
    """
    Launch headless Chromium and extract product images from the rendered page.

    Runs Playwright in a **dedicated thread with its own event loop** so it is
    fully isolated from FastAPI/uvicorn's event loop.  This is the only reliable
    way to use Playwright inside a long-running FastAPI process — sharing the
    same event loop causes silent failures on the 2nd+ call.

    Returns:
        { "html": str, "images": list[dict], "strategy": "browser", "final_url": str }
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_playwright_fetch, url, timeout_s)


def _sync_playwright_fetch(url: str, timeout_s: float) -> dict:
    """
    Runs the Playwright coroutine in a brand-new event loop inside a thread.
    Called via run_in_executor — never call directly from async code.
    """
    import asyncio as _asyncio
    new_loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(_playwright_core(url, timeout_s))
    finally:
        try:
            new_loop.close()
        except Exception:
            pass


async def _playwright_core(url: str, timeout_s: float) -> dict:
    """
    Actual Playwright logic — runs inside a fresh dedicated event loop.
    Extracts product images from a fully-rendered page.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise ValueError(
            "Playwright not installed. Run: pip install playwright && "
            "python -m playwright install chromium"
        )

    import random as _rnd

    images: list[dict] = []
    seen_urls: set[str] = set()
    final_url = url
    rendered_html = ""

    # ── Randomize fingerprint so Amazon sees a different user each request ────
    _chrome_ver = _rnd.choice(["122", "123", "124", "125", "126"])
    _win_ver    = _rnd.choice(["10.0", "11.0"])
    _vp_w       = _rnd.randint(1260, 1400)
    _vp_h       = _rnd.randint(860, 960)
    _hw_conc    = _rnd.choice([4, 6, 8, 12])

    is_amazon = "amazon." in url.lower()

    if is_amazon:
        ctx_ua = (
            f"Mozilla/5.0 (Windows NT {_win_ver}; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{_chrome_ver}.0.0.0 Safari/537.36"
        )
        ctx_viewport = {"width": _vp_w, "height": _vp_h}
        # Strip tracking params — just /dp/ASIN
        _asin_m = re.search(r"/dp/([A-Z0-9]{10})", url)
        if _asin_m:
            _domain = "www.amazon.in" if "amazon.in" in url else "www.amazon.com"
            url = f"https://{_domain}/dp/{_asin_m.group(1)}?th=1&psc=1"
    else:
        _android_ver = _rnd.choice(["10", "11", "12", "13"])
        ctx_ua = (
            f"Mozilla/5.0 (Linux; Android {_android_ver}; SM-G981B) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{_chrome_ver}.0.6367.82 Mobile Safari/537.36"
        )
        ctx_viewport = {"width": 390, "height": _rnd.randint(820, 900)}

    def _add(img_url: str, alt: str = "", source: str = "browser_dom") -> None:
        img_url = _normalize_img_url(img_url, base_url=final_url)
        if img_url and img_url not in seen_urls and _is_useful_image(img_url):
            seen_urls.add(img_url)
            score = 15
            if any(cdn in img_url for cdn in [
                "rukminim", "meeshocdn", "bigbasket", "nykaa",
                "jiomartjcp.com", "jiostatic.com", "jiomart.com",
                "blinkit", "zeptonow",
            ]):
                score = 20
            if re.search(r"[_/](large|zoom|hires|hi-res|full|h_\d{3,4}|_SL\d{4}_|/original/)", img_url, re.I):
                score = 22
            images.append({"url": img_url, "alt": alt, "score": score, "source": source})

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
                "--mute-audio",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--lang=en-IN",
                "--window-size=1366,768",
            ],
        )

        try:
            context = await browser.new_context(
                user_agent=ctx_ua,
                viewport=ctx_viewport,
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Cache-Control": "max-age=0",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-CH-UA": f'"Chromium";v="{_chrome_ver}", "Google Chrome";v="{_chrome_ver}", "Not-A.Brand";v="99"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                    "Referer": "https://www.google.com/",
                },
            )

            # ── Stealth: mask all automation signals ──────────────────────────
            await context.add_init_script(f"""
                // Hide webdriver flag
                Object.defineProperty(navigator, 'webdriver',
                    {{ get: () => undefined }});
                // Fake plugins array (real Chrome has plugins)
                Object.defineProperty(navigator, 'plugins',
                    {{ get: () => [
                        {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' }},
                        {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' }},
                        {{ name: 'Native Client', filename: 'internal-nacl-plugin' }},
                    ] }});
                Object.defineProperty(navigator, 'languages',
                    {{ get: () => ['en-IN', 'en', 'en-US', 'hi'] }});
                Object.defineProperty(navigator, 'hardwareConcurrency',
                    {{ get: () => {_hw_conc} }});
                Object.defineProperty(navigator, 'deviceMemory',
                    {{ get: () => 8 }});
                Object.defineProperty(navigator, 'platform',
                    {{ get: () => 'Win32' }});
                // Chrome object (missing in headless)
                window.chrome = {{
                    runtime: {{}},
                    loadTimes: function() {{}},
                    csi: function() {{}},
                    app: {{}}
                }};
                // Screen dimensions
                Object.defineProperty(screen, 'width',  {{ get: () => {_vp_w} }});
                Object.defineProperty(screen, 'height', {{ get: () => {_vp_h} }});
                Object.defineProperty(screen, 'availWidth',  {{ get: () => {_vp_w} }});
                Object.defineProperty(screen, 'availHeight', {{ get: () => {_vp_h - 40} }});
                // WebGL renderer spoof
                const origGetParam = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(param) {{
                    if (param === 37446) return 'Intel Inc.';
                    if (param === 37445) return 'Intel Iris OpenGL Engine';
                    return origGetParam.call(this, param);
                }};
                // Notification permission (real browsers have this)
                if (window.Notification) {{
                    Object.defineProperty(Notification, 'permission', {{ get: () => 'default' }});
                }}
            """)

            page = await context.new_page()

            # Block fonts and analytics — speeds up load, doesn't affect images
            await page.route("**/*.{woff,woff2,ttf,otf}", lambda r: r.abort())
            await page.route("**/{analytics,beacon,tracking,pixel}**", lambda r: r.abort())

            # Small random delay — avoids Amazon rate-limit on rapid repeated requests
            import asyncio as _asyncio
            await _asyncio.sleep(_rnd.uniform(1.0, 2.5))

            # Use 'load' for Amazon so the colorImages JS block has time to execute
            wait_event = "load" if is_amazon else "domcontentloaded"
            await page.goto(url, timeout=int(timeout_s * 1000), wait_until=wait_event)
            final_url = page.url

            # For Amazon wait until colorImages JS is available
            if is_amazon:
                try:
                    await page.wait_for_function(
                        "() => document.documentElement.innerHTML.includes('colorImages')",
                        timeout=18000,
                    )
                except PWTimeout:
                    pass  # Proceed even if blocked (CAPTCHA page)

            # Wait for network to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PWTimeout:
                pass

            # JioMart-specific: wait for the product spec table to render
            # (the React app populates manufacturer/FSSAI/country after JS loads)
            is_jiomart = "jiomart.com" in url.lower()
            if is_jiomart:
                try:
                    await page.wait_for_function(
                        "() => document.body.innerText.includes('Manufacturer') || "
                        "document.body.innerText.includes('Net Quantity')",
                        timeout=15000,
                    )
                except PWTimeout:
                    pass  # proceed with whatever we have

            # Scroll to trigger lazy-loaded gallery thumbnails
            await _asyncio.sleep(1.5)
            await page.evaluate("window.scrollBy(0, 500)")
            await _asyncio.sleep(0.8)
            await page.evaluate("window.scrollTo(0, 0)")
            await _asyncio.sleep(0.5)

            rendered_html = await page.content()

            # ── Image extraction ─────────────────────────────────────────────
            if is_amazon:
                # Use strict whitelist extractor — colorImages JS + altImages DOM only
                from bs4 import BeautifulSoup
                from url_scanner.image_collector import _extract_amazon_gallery_images
                amz_soup = BeautifulSoup(rendered_html, "lxml")
                for img in _extract_amazon_gallery_images(rendered_html, amz_soup, final_url):
                    if img["url"] and img["url"] not in seen_urls:
                        seen_urls.add(img["url"])
                        images.append(img)
            else:
                # Non-Amazon: scan live DOM elements
                for el in await page.query_selector_all("img"):
                    src     = await el.get_attribute("src") or ""
                    srcset  = await el.get_attribute("srcset") or ""
                    datasrc = await el.get_attribute("data-src") or ""
                    alt     = await el.get_attribute("alt") or ""
                    best = _parse_srcset(srcset) or datasrc or src
                    if best:
                        _add(best, alt, "browser_img")

                # <picture><source> — skip for Amazon (review photos)
                for el in await page.query_selector_all("picture source"):
                    srcset = await el.get_attribute("srcset") or ""
                    best = _parse_srcset(srcset)
                    if best:
                        _add(best, "", "browser_picture")

                # Gallery thumbnail clicks for non-Amazon SPAs (Flipkart etc.)
                _GALLERY_SEL = [
                    "._2KpZ6l img", "._3BTv9X img", "li._1l-4KG img",
                    "[data-thumbnail] img", ".gallery-thumb img",
                    ".product-thumb img", ".thumbnail-image img",
                    ".image-gallery-thumbnail img", "ul.pdp-thumbnails li img",
                ]
                for selector in _GALLERY_SEL:
                    thumbs = await page.query_selector_all(selector)
                    if thumbs:
                        clicked = 0
                        for thumb in thumbs[:8]:
                            try:
                                await thumb.click(timeout=1500)
                                await _asyncio.sleep(0.35)
                                clicked += 1
                            except Exception:
                                continue
                        if clicked:
                            await _asyncio.sleep(0.8)
                            for el in await page.query_selector_all("img"):
                                src     = await el.get_attribute("src") or ""
                                srcset  = await el.get_attribute("srcset") or ""
                                datasrc = await el.get_attribute("data-src") or ""
                                alt     = await el.get_attribute("alt") or ""
                                best = _parse_srcset(srcset) or datasrc or src
                                if best:
                                    _add(best, alt, "browser_gallery_click")
                            rendered_html = await page.content()
                            break

                # Embedded state extraction
                for img in _extract_images_from_state(rendered_html, final_url):
                    if img["url"] not in seen_urls:
                        seen_urls.add(img["url"])
                        images.append(img)

        finally:
            # Always close browser — even on exception
            try:
                await browser.close()
            except Exception:
                pass

    images.sort(key=lambda x: -x["score"])
    return {
        "html": rendered_html,
        "images": images,
        "strategy": "browser",
        "final_url": final_url,
    }

