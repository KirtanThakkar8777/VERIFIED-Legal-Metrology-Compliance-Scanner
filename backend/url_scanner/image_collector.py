"""
url_scanner/image_collector.py
Collect product image URLs from a product page HTML.
Supports: img src/srcset/data-src, picture/source, OpenGraph, Twitter meta,
          JSON-LD, Amazon dynamic, Myntra CDN, Flipkart CDN, embedded app state.
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
    r"placeholder|blank|spacer|pixel|ad\b|advertisement|"
    r"loader|shimmer|skeleton|retaillabs)",
    re.IGNORECASE,
)

# Patterns that suggest packaging images
_PACKAGING_HINTS = re.compile(
    r"(product|pack|label|bottle|box|front|back|side|item|main|"
    r"thumb|large|zoom|detail|image|img|photo|picture|gallery)",
    re.IGNORECASE,
)

MIN_IMG_URL_LEN = 20
MAX_IMAGES = 20   # raised from 15


def _is_valid_image_url(url: str) -> bool:
    if not url or len(url) < MIN_IMG_URL_LEN:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", ""):
        return False
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")):
        return True
    # Cloudinary CDN
    if "myntassets.com" in url or "cloudinary.com" in url:
        if any(ext in url for ext in (".jpg", ".jpeg", ".png", ".webp")):
            return True
    # Flipkart CDN
    if "rukminim" in url and any(ext in url for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return True
    # Generic image hint
    if "image" in url.lower() or "img" in url.lower():
        return True
    return False


def _score_image_url(url: str, alt: str = "", context: str = "") -> int:
    """Higher score = more likely to be a useful product image."""
    score = 0
    combined = (url + " " + alt + " " + context).lower()
    if _SKIP_PATTERNS.search(combined):
        return -100
    if _PACKAGING_HINTS.search(combined):
        score += 10
    for res in ("_SL1500_", "_SL1000_", "_SX679_", "large", "zoom", "1200x", "800x", "832"):
        if res.lower() in url.lower():
            score += 5
    if re.search(r"_SL\d{3,4}_|_AC_SL\d+", url):
        score += 8
    # Flipkart CDN = likely product image
    if "rukminim" in url:
        score += 12
    return score


def _parse_srcset_best(srcset: str) -> str:
    """Return the highest-resolution URL from a srcset string."""
    if not srcset:
        return ""
    best_url = ""
    best_size = 0
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        url = tokens[0]
        size = 0
        if len(tokens) > 1:
            try:
                size = int(tokens[-1].rstrip("w").rstrip("x"))
            except ValueError:
                size = 0
        if size > best_size or (size == 0 and not best_url):
            best_size = size
            best_url = url
    return best_url


def collect_images(html: str, base_url: str) -> list[dict]:
    """
    Collect product image URLs from page HTML.

    Sources searched:
    1. <img src / srcset / data-src / data-lazy-src / data-original>
    2. <picture><source srcset>
    3. Amazon data-old-hires and data-a-dynamic-image JSON
    4. Myntra CDN URLs from JS scripts
    5. Flipkart CDN URLs from raw HTML (rukminim)
    6. Amazon gallery block
    7. OpenGraph og:image + Twitter twitter:image
    8. JSON-LD image references

    Returns list of { url, alt, score, source } ordered by score, max MAX_IMAGES.
    """
    soup = BeautifulSoup(html, "lxml")
    seen_urls: set[str] = set()
    images: list[dict] = []

    def _add(url: str, alt: str = "", source: str = "img_tag") -> None:
        url = url.strip()
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(base_url, url)
        if url in seen_urls:
            return
        if not _is_valid_image_url(url):
            return
        score = _score_image_url(url, alt)
        if score < -50:
            return
        seen_urls.add(url)
        images.append({"url": url, "alt": alt, "score": score, "source": source})

    # ── 1. Standard <img> tags ────────────────────────────────────────────────
    for img in soup.find_all("img"):
        alt = img.get("alt", "")

        # Amazon high-res attributes
        hires = img.get("data-old-hires", "")
        if hires:
            _add(hires, alt, "amazon_hires")

        dyn = img.get("data-a-dynamic-image", "")
        if dyn:
            try:
                d = json.loads(dyn)
                for u in d.keys():
                    _add(u, alt, "amazon_dynamic")
            except Exception:
                pass

        # Srcset — pick highest resolution
        srcset = img.get("srcset", "")
        if srcset:
            best = _parse_srcset_best(srcset)
            if best:
                _add(best, alt, "img_srcset")

        # Lazy loading attributes
        for attr in ("data-src", "data-lazy-src", "data-original", "data-image",
                     "data-zoom-image", "data-full-size-src"):
            dsrc = img.get(attr, "")
            if dsrc:
                _add(dsrc, alt, f"img_{attr.replace('-', '_')}")

        # Regular src
        src = img.get("src", "")

        # Myntra partial CDN URL
        if src and not src.startswith("http") and "assets/images/" in src:
            asset_match = re.search(
                r"(assets/images/\d{4}/\w+/\d+/[A-Za-z0-9_]+\.(?:jpg|jpeg|png|webp))",
                src, re.IGNORECASE,
            )
            if asset_match:
                src = f"https://assets.myntassets.com/h_1440,q_75,w_1080/v1/{asset_match.group(1)}"
            else:
                src = "https://assets.myntassets.com/" + src.lstrip("/")

        _add(src, alt, "img_tag")

    # ── 2. <picture><source srcset> ───────────────────────────────────────────
    for picture in soup.find_all("picture"):
        for source in picture.find_all("source"):
            srcset = source.get("srcset", "")
            if srcset:
                best = _parse_srcset_best(srcset)
                if best:
                    _add(best, "", "picture_source")

    # ── 3. OpenGraph + Twitter meta images ───────────────────────────────────
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        content = meta.get("content", "")
        if prop in ("og:image", "og:image:secure_url") and content:
            _add(content, "", "og_image")
        elif prop in ("twitter:image", "twitter:image:src") and content:
            _add(content, "", "twitter_image")

    # ── 4. Myntra product images from page HTML scripts ───────────────────────
    myntra_product_imgs = re.findall(
        r"https?://(?:assets\.myntassets\.com|assets\.myntra\.com)/assets/images/"
        r"(\d{4}/\w+/\d+/[A-Za-z0-9_]+\.(?:jpg|jpeg|png|webp))",
        html, re.IGNORECASE,
    )
    seen_myntra: set[str] = set()
    for asset_path in myntra_product_imgs:
        if "retaillabs" in asset_path:
            continue
        hires_url = f"https://assets.myntassets.com/h_1440,q_75,w_1080/v1/assets/images/{asset_path}"
        if hires_url not in seen_myntra:
            seen_myntra.add(hires_url)
            _add(hires_url, "product", "myntra_script")

    # ── 5. Flipkart CDN URLs from raw HTML ───────────────────────────────────
    flipkart_imgs = re.findall(
        r'"(https?://rukminim\d*\.flixcart\.com/image/[^"?]+\.(?:jpg|jpeg|png|webp))',
        html, re.IGNORECASE,
    )
    for fk_url in flipkart_imgs:
        upgraded = re.sub(r"/\d+/\d+/", "/832/832/", fk_url)
        _add(upgraded, "product", "flipkart_cdn")

    # ── 6. Amazon image block (altImages) ────────────────────────────────────
    img_block = soup.find(id="imageBlock") or soup.find(id="altImages")
    if img_block:
        for img in img_block.find_all("img"):
            src = img.get("src", "")
            full = re.sub(r"\._[A-Z]{2}\d+_\.", "._SL1500_.", src)
            _add(full, img.get("alt", ""), "amazon_gallery")

    # ── 7. Flipkart gallery div classes ──────────────────────────────────────
    for div in soup.find_all("div", {"class": re.compile(r"_396cs4|_3BTv9X|CXW8mj|q6DClP")}):
        for img in div.find_all("img"):
            _add(img.get("src", ""), img.get("alt", ""), "flipkart_gallery")

    # ── 8. JSON-LD image references ──────────────────────────────────────────
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
                    elif isinstance(img_url, dict):
                        _add(img_url.get("url", ""), "", "jsonld")
        except Exception:
            pass

    images.sort(key=lambda x: x["score"], reverse=True)
    return images[:MAX_IMAGES]
