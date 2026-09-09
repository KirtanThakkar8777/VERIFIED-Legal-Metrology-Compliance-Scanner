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


async def fetch_rendered_page(url: str, timeout_s: float = 30.0) -> dict:
    """
    Launch headless Chromium, navigate to `url`, wait for product gallery
    to render, then extract all product image URLs from the live DOM.

    Returns:
        {
          "html": str,           # full rendered HTML
          "images": list[dict],  # [{url, alt, score, source}, ...]
          "strategy": "browser"
        }

    Raises ValueError if Playwright is not installed.
    Raises TimeoutError if the page doesn't load within timeout_s.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise ValueError(
            "Playwright is not installed. Run: pip install playwright && "
            "python -m playwright install chromium"
        )

    images: list[dict] = []
    seen_urls: set[str] = set()

    def _add(url: str, alt: str = "", source: str = "browser_dom") -> None:
        url = _normalize_img_url(url, base_url=final_url)
        if url and url not in seen_urls and _is_useful_image(url):
            seen_urls.add(url)
            score = 15
            # Boost known product CDN URLs
            if any(cdn in url for cdn in ["rukminim", "meeshocdn", "bigbasket", "nykaa"]):
                score = 20
            # Boost if URL indicates high resolution
            if re.search(r"832|640|400|500|1000|1500", url):
                score += 5
            images.append({"url": url, "alt": alt, "score": score, "source": source})

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
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},   # iPhone 12 viewport
            locale="en-IN",
        )

        page = await context.new_page()

        # Block unnecessary resources to speed up loading
        await page.route(
            "**/*.{woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )

        final_url = url
        rendered_html = ""

        try:
            await page.goto(url, timeout=int(timeout_s * 1000), wait_until="domcontentloaded")
            final_url = page.url

            # Wait for product images to appear
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass  # Proceed even if not fully idle

            # Small delay to allow lazy-load images to start loading
            await asyncio.sleep(1.5)

            # Scroll down a bit to trigger lazy loading on gallery
            await page.evaluate("window.scrollBy(0, 400)")
            await asyncio.sleep(0.8)
            await page.evaluate("window.scrollTo(0, 0)")

            # Get fully rendered HTML
            rendered_html = await page.content()

            # ── Extract images from live DOM ──────────────────────────────────
            img_elements = await page.query_selector_all("img")
            for el in img_elements:
                src     = await el.get_attribute("src") or ""
                srcset  = await el.get_attribute("srcset") or ""
                datasrc = await el.get_attribute("data-src") or ""
                alt     = await el.get_attribute("alt") or ""

                # Pick best URL from srcset if available
                best = _parse_srcset(srcset) or datasrc or src
                if best:
                    _add(best, alt, "browser_img")

            # ── Also check <picture><source> ──────────────────────────────────
            source_els = await page.query_selector_all("picture source")
            for el in source_els:
                srcset = await el.get_attribute("srcset") or ""
                best = _parse_srcset(srcset)
                if best:
                    _add(best, "", "browser_picture")

        except PWTimeout:
            raise TimeoutError(f"Browser timed out loading {url}")

        # ── Gallery thumbnail interaction — trigger lazy-loaded images ─────────
        # Flipkart and many other platforms only load high-res gallery images
        # when the user clicks each thumbnail. We simulate this to discover all
        # product images, especially back/side packaging images.
        try:
            # Common gallery thumbnail selectors across major e-commerce platforms
            GALLERY_SELECTORS = [
                # Flipkart
                "._2KpZ6l img",             # Flipkart thumbnail strip
                "._3BTv9X img",             # Flipkart alt thumbnail
                "li._1l-4KG img",           # Flipkart list item thumb
                # Amazon
                "#altImages li img",        # Amazon alt images
                ".imageThumbnail img",
                # Generic
                "[data-thumbnail] img",
                ".gallery-thumb img",
                ".product-thumb img",
                ".thumbnail-image img",
                ".thumb-gallery img",
                ".image-gallery-thumbnail img",
                "ul.pdp-thumbnails li img",
            ]

            thumb_count = 0
            for selector in GALLERY_SELECTORS:
                thumbs = await page.query_selector_all(selector)
                if thumbs:
                    for thumb in thumbs[:8]:   # click up to 8 thumbnails max
                        try:
                            await thumb.click(timeout=1500)
                            await asyncio.sleep(0.4)   # brief wait for image network req
                            thumb_count += 1
                        except Exception:
                            continue
                    if thumb_count > 0:
                        break  # found working selector — stop trying others

            # After clicks, collect any newly loaded images
            if thumb_count > 0:
                await asyncio.sleep(0.8)  # allow batch of image requests to settle
                new_imgs = await page.query_selector_all("img")
                for el in new_imgs:
                    src     = await el.get_attribute("src") or ""
                    srcset  = await el.get_attribute("srcset") or ""
                    datasrc = await el.get_attribute("data-src") or ""
                    alt     = await el.get_attribute("alt") or ""
                    best = _parse_srcset(srcset) or datasrc or src
                    if best:
                        _add(best, alt, "browser_gallery_click")

                # Also grab updated rendered HTML for state extraction
                rendered_html = await page.content()

        except Exception:
            pass  # Gallery interaction is best-effort — never crash the main fetch

        finally:
            await browser.close()



    # ── Extract from embedded application state ───────────────────────────────
    state_images = _extract_images_from_state(rendered_html, final_url)
    for img in state_images:
        if img["url"] not in seen_urls:
            seen_urls.add(img["url"])
            images.append(img)

    # Sort by score
    images.sort(key=lambda x: -x["score"])

    return {
        "html": rendered_html,
        "images": images,
        "strategy": "browser",
        "final_url": final_url,
    }
