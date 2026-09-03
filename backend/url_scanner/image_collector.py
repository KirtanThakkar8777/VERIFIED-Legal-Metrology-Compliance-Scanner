"""
url_scanner/image_collector.py
Collect product image URLs from a product page HTML.
"""
from __future__ import annotations
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


# Patterns that suggest a URL is a UI/nav/icon image (skip these)
_SKIP_PATTERNS = re.compile(
    r"(logo|icon|banner|arrow|star|rating|flag|spinner|favicon|"
    r"cart|wishlist|share|social|badge|tag|nav|menu|button|"
    r"placeholder|blank|spacer|pixel|ad\b|advertisement)",
    re.IGNORECASE,
)

# Patterns that suggest packaging images
_PACKAGING_HINTS = re.compile(
    r"(product|pack|label|bottle|box|front|back|side|item|main|"
    r"thumb|large|zoom|detail|image|img|photo|picture|gallery)",
    re.IGNORECASE,
)

MIN_IMG_URL_LEN = 20
MAX_IMAGES = 15


def _is_valid_image_url(url: str) -> bool:
    if not url or len(url) < MIN_IMG_URL_LEN:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", ""):
        return False
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")) or \
           "image" in url.lower() or "img" in url.lower()


def _score_image_url(url: str, alt: str = "", context: str = "") -> int:
    """Higher score = more likely to be a useful product image."""
    score = 0
    combined = (url + " " + alt + " " + context).lower()
    if _SKIP_PATTERNS.search(combined):
        return -100
    if _PACKAGING_HINTS.search(combined):
        score += 10
    # Larger resolution hints in URL
    for res in ("_SL1500_", "_SL1000_", "_SX679_", "large", "zoom", "1200x", "800x"):
        if res.lower() in url.lower():
            score += 5
    # Amazon specific high-res pattern
    if re.search(r"_SL\d{3,4}_|_AC_SL\d+", url):
        score += 8
    return score


def collect_images(html: str, base_url: str) -> list[dict]:
    """
    Collect product image URLs from page HTML.

    Returns list of:
    { url: str, alt: str, score: int, source: str }
    ordered by score descending, deduplicated, max MAX_IMAGES.
    """
    soup = BeautifulSoup(html, "lxml")
    seen_urls: set[str] = set()
    images: list[dict] = []

    def _add(url: str, alt: str = "", source: str = "img_tag") -> None:
        url = url.strip()
        if not url:
            return
        # Make absolute
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(base_url, url)
        if url in seen_urls:
            return
        if not _is_valid_image_url(url):
            return
        score = _score_image_url(url, alt)
        if score < -50:  # skip obvious non-product images
            return
        seen_urls.add(url)
        images.append({"url": url, "alt": alt, "score": score, "source": source})

    # ── Standard <img> tags ───────────────────────────────────────────────────
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy-src", "")
        # Amazon stores high-res as data-old-hires or data-a-dynamic-image JSON
        hires = img.get("data-old-hires", "")
        if hires:
            _add(hires, img.get("alt", ""), "amazon_hires")
        dyn = img.get("data-a-dynamic-image", "")
        if dyn:
            try:
                d = json.loads(dyn)
                for u in d.keys():
                    _add(u, img.get("alt", ""), "amazon_dynamic")
            except Exception:
                pass
        _add(src, img.get("alt", ""), "img_tag")

    # ── Amazon image block (altImages) ───────────────────────────────────────
    img_block = soup.find(id="imageBlock") or soup.find(id="altImages")
    if img_block:
        for img in img_block.find_all("img"):
            src = img.get("src", "")
            # Upgrade Amazon thumbnail URLs to full-size
            full = re.sub(r"\._[A-Z]{2}\d+_\.", "._SL1500_.", src)
            _add(full, img.get("alt", ""), "amazon_gallery")

    # ── Flipkart image gallery ────────────────────────────────────────────────
    for div in soup.find_all("div", {"class": re.compile(r"_396cs4|_3BTv9X|CXW8mj")}):
        for img in div.find_all("img"):
            _add(img.get("src", ""), img.get("alt", ""), "flipkart_gallery")

    # ── JSON-LD image references ──────────────────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                imgs = data.get("image", [])
                if isinstance(imgs, str):
                    imgs = [imgs]
                for img_url in imgs:
                    if isinstance(img_url, str):
                        _add(img_url, "", "jsonld")
        except Exception:
            pass

    # Sort by score, return top MAX_IMAGES
    images.sort(key=lambda x: x["score"], reverse=True)
    return images[:MAX_IMAGES]
