"""
url_scanner/image_collector.py
Collect product image URLs from a product page HTML.

KEY DESIGN CHANGE:
  BEFORE: collected img tags from entire page (picked up UI icons, Amazon branding,
          customer review images, related product images)
  AFTER:  scopes collection to the PRODUCT GALLERY CONTAINER only (the main image
          block that shows front/back/side of the actual product being viewed).
          Falls back to curated full-page scan only when no gallery is found.

Supported platforms: Amazon, Flipkart, Meesho, Myntra, Generic
"""
from __future__ import annotations
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


# ── Hard-reject patterns (never collect these) ─────────────────────────────────
# Amazon and other e-commerce sites embed many UI elements as images.
# These MUST be filtered at collection time.

_SKIP_URL = re.compile(
    r"""(
        # Amazon UI icons
        amazon-logo | amzn-logo | sprite[_/] | ic_[a-z] | btmbar |
        nav[_-]icon | \/nav\/ | \/icons\/ |
        [/_-]icon[/_-] | [/_-]badge[/_-] | [/_-]star[/_.-] |
        [/_-]rating[/_-] | [/_-]arrow[/_-] |
        [/_-]cart[/_-] | [/_-]wishlist[/_-] |
        [/_-]share[/_-] | [/_-]social[/_-] |
        [/_-]button[/_-] | [/_-]widget[/_-] |
        [/_-]flag[/_-] | [/_-]spinner[/_.-] | [/_-]loader[/_.-] |
        [/_-]shimmer | [/_-]skeleton | [/_-]placeholder |

        # Amazon specific UI
        transparent-pixel | amazon_pay | pay_icon |
        prime[_-]logo | \/gp\/aw\/ | pdp_loader |
        customer[_-]image | review[_-]image | review_img |

        # Generic UI junk
        favicon | spacer | pixel | blank | retaillabs |
        watermark | overlay | social-icon |
        facebook\.com | twitter\.com | instagram\.com | youtube\.com |

        # Hard brand/logo strings (not product)
        \/logo\/ | [/_-]logo\.(?:png|jpg|svg|webp) |

        # Amazon gray placeholder box/camera icons (base64-like tiny images)
        data:image
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_SKIP_ALT = re.compile(
    r"""(
        amazon\s*logo | brand\s*logo | promotional | lifestyle |
        marketing | banner | offer | discount | sale |
        buy\s*now | add\s*to\s*cart | free\s*delivery | prime |
        serving\s*suggestion | packaging\s*may\s*vary |
        image\s*for\s*representation | for\s*illustration |
        customer\s*image | customer\s*review |
        related\s*product | similar\s*product |
        # Amazon Fresh / Amazon branding
        amazon\s*fresh | amazon\s*basics | ^\s*fresh\s*$
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# ── Amazon product gallery container IDs / classes ─────────────────────────────
# These are the ONLY containers we collect images from on Amazon pages.
# Order matters: most specific → least specific.
_AMAZON_GALLERY_IDS = [
    "imageBlock",          # Main image block (desktop)
    "altImages",           # Thumbnail strip (01, 02, 03...)
    "main-image-container",# Alternative
    "imageBlockThumbs",    # Thumbnail container
    "dp-container",        # Full product container (fallback, scoped)
    "ppd",                 # Product page detail (wide fallback)
]

_AMAZON_GALLERY_CLASSES = [
    "imgTagWrapper",       # High-res main image wrapper
    "a-dynamic-image",     # Amazon dynamic image class
    "selected-image",      # Selected gallery image
]

# ── Flipkart product gallery containers ────────────────────────────────────────
_FLIPKART_GALLERY_CLASSES = [
    "_396cs4", "_3BTv9X", "CXW8mj", "q6DClP",  # Image gallery classes
    "_2r_T1I",  # Image block
    "IIioX1",   # Full image
]

# ── Minimum and maximum image counts per source ────────────────────────────────
MAX_IMAGES = 25   # collect more, filter later


def _is_valid_image_url(url: str) -> bool:
    if not url or len(url) < 20:
        return False
    # Reject data: URIs (inline base64 = tiny placeholder or UI element)
    if url.startswith("data:"):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", ""):
        return False
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")):
        return True
    # Cloudinary CDN (Myntra, Meesho, Nykaa)
    if any(cdn in url for cdn in ("myntassets.com", "cloudinary.com", "media.meesho.com")):
        if any(ext in url for ext in (".jpg", ".jpeg", ".png", ".webp")):
            return True
    # Flipkart CDN
    if "rukminim" in url and any(ext in url for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return True
    # Amazon image CDN (no extension but known pattern)
    if re.search(r"images-amazon\.com|m\.media-amazon\.com|i\.imgur\.com", url):
        return True
    return False


def _should_skip(url: str, alt: str = "") -> bool:
    """Return True if this image should definitely be rejected."""
    if _SKIP_URL.search(url):
        return True
    if alt and _SKIP_ALT.search(alt):
        return True
    # Amazon gray placeholder icons (very small SVG-sized images)
    if re.search(r"_SX\d{1,2}_|_SY\d{1,2}_|_SS\d{2}_", url):
        return True   # tiny thumbnail = UI element
    return False


def _score_image_url(url: str, alt: str = "") -> int:
    """Score how likely this image is to be a useful product packaging image."""
    score = 0
    combined = (url + " " + alt).lower()

    # High-res size signals (Amazon)
    m = re.search(r"_SL(\d{3,4})_|_AC_SL(\d{3,4})|_SX(\d{3,4})", url)
    if m:
        sz = int(next(g for g in m.groups() if g) or 0)
        if sz >= 1000:
            score += 25
        elif sz >= 500:
            score += 12

    # Amazon image index: 01=front, 02-06=back/side/detail (best), 07+=promo
    idx_m = re.search(r"\.(\d{2})\.", url)
    if idx_m:
        idx = int(idx_m.group(1))
        if idx == 1:
            score += 5    # front view
        elif 2 <= idx <= 6:
            score += 20   # back/side/detail panels
        elif 7 <= idx <= 9:
            score -= 10   # lifestyle/promo range
        else:
            score -= 20   # brand graphics

    # Flipkart CDN (high-res)
    if "rukminim" in url:
        if "/832/" in url or "/1664/" in url:
            score += 20
        else:
            score += 10

    # Cloudinary high-res transforms
    if re.search(r"h_\d{4}|w_\d{4}|q_\d{2,3}", url):
        score += 15

    # Source preference: from gallery block = very high confidence
    if "amazon_gallery" in url or "adapter" in url:
        score += 20

    # Alt text contains compliance-related words = packaging image
    if re.search(r"back|rear|label|ingredient|nutrition|fssai|manufacturer|barcode|declaration", combined):
        score += 15

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


def _extract_amazon_gallery_images(html_raw: str, soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Extract ONLY product gallery images from an Amazon page.

    STRATEGY — strict whitelist (3 sources):
      1. colorImages JS variable  ← only official gallery images, NEVER review photos
      2. altImages DOM div        ← only gallery thumbnail strip, NEVER reviews
      3. #landingImage element    ← main image with data-old-hires / data-a-dynamic-image

    WHY the raw-HTML CDN scan failed:
      Customer review images use the SAME CDN as product gallery images.
      Scanning all raw HTML always picks up review photos.

    WHY colorImages is review-free:
      colorImages is populated EXCLUSIVELY by the seller's uploads.
      Amazon never puts customer review photos in colorImages.
    """
    results: list[dict] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    def _upgrade(url: str) -> str:
        """
        Upgrade any Amazon CDN image URL to _SL1500_ max resolution.

        Handles all known Amazon transform suffixes:
          ._SL500_.          → simple size
          ._AC_SL500_.       → auto-crop + size
          ._SS40_.           → thumbnail strip size
          ._SX679_.          → width-based size
          ._AC_UF350,350_QL50_.  → UGC format with dimensions and quality
          ._FMwebp_QL65_.    → WebP format with quality
          ._AC_UY218_.       → auto-crop + height
        """
        # Remove ANY Amazon transform segment: starts with ._ and ends with _.
        # Handles multi-segment transforms like ._AC_UF350,350_QL50_. by
        # collapsing everything between the first ._ and the last _. into one step.
        #
        # Strategy: find the FIRST ._ after the image ID, and replace everything
        # up to (and including) the extension dot with ._SL1500_.
        #
        # We split on /images/I/<ID> to isolate the transform + extension part.
        m = re.match(
            r"(https?://[^/]+/images/I/[A-Za-z0-9+/]{8,25})"  # base up to ID
            r"(\._[^/]+?)"                                        # transform(s)
            r"(\.(jpg|jpeg|png|webp))",                           # extension
            url, re.IGNORECASE
        )
        if m:
            # Check it's not a video overlay (has PKmb = play-button overlay)
            if "PKmb" in m.group(2) or "play-button" in m.group(2).lower():
                return ""  # Signal: discard this URL (video thumbnail)
            return m.group(1) + "._SL1500_" + m.group(3)
        return url

    def _img_id(url: str) -> str:
        """Extract Amazon image ID from URL for deduplication."""
        m = re.search(r"/images/I/([A-Za-z0-9]{8,25})\.", url)
        return m.group(1) if m else url

    def _add(url: str, alt: str = "", source: str = "amazon_gallery") -> None:
        url = url.strip()
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url
        # Upgrade FIRST — converts thumbnails to full-res, returns "" for video overlays
        url_up = _upgrade(url)
        if not url_up:          # video overlay / unrecognized format → skip
            return
        if _should_skip(url_up, alt):
            return
        if not _is_valid_image_url(url_up):
            return
        img_id = _img_id(url_up)
        if img_id in seen_ids or url_up in seen_urls:
            return
        seen_ids.add(img_id)
        seen_urls.add(url_up)
        results.append({
            "url": url_up,
            "alt": alt,
            "score": _score_image_url(url_up, alt),
            "source": source,
        })

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 1: colorImages JS variable
    # ══════════════════════════════════════════════════════════════════════════
    # Matches both "hiRes":"URL" and 'hiRes':'URL' (Amazon uses both quote styles)
    _HIRES_RE = re.compile(
        r"""['"]hiRes['"]\s*:\s*['"]?(https?://[^'"<>\s]{20,})['"]?""", re.I
    )
    _LARGE_RE = re.compile(
        r"""['"]large['"]\s*:\s*['"]?(https?://[^'"<>\s]{20,})['"]?""", re.I
    )

    # Search both soup script tags AND raw html (covers scripts BeautifulSoup misses)
    # We search the raw HTML but ONLY in the portion before the reviews section
    # to guarantee we never touch review image data.
    _REV_SPLIT = re.compile(
        r'id=["\'](?:reviews|customer-reviews-content|cm_cr-review_list)["\']',
        re.IGNORECASE
    )
    split_match = _REV_SPLIT.search(html_raw)
    html_above_reviews = html_raw[:split_match.start()] if split_match else html_raw

    # Find all colorImages script blocks in the safe portion of HTML
    _CI_BLOCK_RE = re.compile(
        r'colorImages[\s\S]{0,50000}?(?=colorToAsin|imageReviewData|"reviews"|\'reviews\'|$)',
        re.IGNORECASE
    )
    ci_match = _CI_BLOCK_RE.search(html_above_reviews)
    search_text = ci_match.group(0) if ci_match else html_above_reviews

    hi_urls = _HIRES_RE.findall(search_text)
    lg_urls = _LARGE_RE.findall(search_text)
    use_urls = hi_urls if hi_urls else lg_urls
    for url in use_urls:
        _add(url, "", "colorImages_js")

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 2: altImages DOM div (gallery thumbnail strip)
    # ══════════════════════════════════════════════════════════════════════════
    # The altImages div ONLY contains the official gallery thumbnail strip.
    # Amazon NEVER puts customer review images in this div.
    alt_div = (
        soup.find(id="altImages") or
        soup.find(id="imageBlock_feature_div") or
        soup.find(id="imageBlock")
    )
    if alt_div:
        for img in alt_div.find_all("img"):
            src = img.get("src", "")
            if src:
                _add(src, img.get("alt", ""), "altImages_dom")

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 3: #landingImage — main product image element
    # ══════════════════════════════════════════════════════════════════════════
    main_img = soup.find("img", id=re.compile(r"landingImage|main-image|imgBlkFront", re.I))
    if main_img:
        alt_text = main_img.get("alt", "")

        # data-old-hires = direct max-res URL
        hires = main_img.get("data-old-hires", "")
        if hires:
            _add(hires, alt_text, "landingImage_hires")

        # data-a-dynamic-image = {url: [w, h]} — pick largest
        dyn = main_img.get("data-a-dynamic-image", "")
        if dyn:
            try:
                d = json.loads(dyn)
                best_url = max(d, key=lambda u: (d[u][0] * d[u][1] if len(d[u]) >= 2 else 0))
                _add(best_url, alt_text, "landingImage_dynamic")
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # FALLBACK: 0 images found — scan only the imageBlock container HTML
    # (scoped to the gallery div, so reviews are never included)
    # ══════════════════════════════════════════════════════════════════════════
    if not results:
        image_block = soup.find(id="imageBlock") or soup.find(id="dp-container")
        if image_block:
            block_html = str(image_block)
            _GALLERY_CDN = re.compile(
                r"https?://m\.media-amazon\.com/images/I/([A-Za-z0-9]{10,22})"
                r"\._SL(?:1500|1200|1000|832|679|500)_\.(?:jpg|jpeg|png|webp)",
                re.IGNORECASE,
            )
            for m in _GALLERY_CDN.finditer(block_html):
                _add(m.group(0), "", "imageBlock_fallback")

    results.sort(key=lambda x: -x["score"])
    return results


def collect_images(html: str, base_url: str) -> list[dict]:
    """
    Collect product image URLs from page HTML.

    STRATEGY (in priority order):
    1. Amazon: Extract exclusively from the product gallery JS data + altImages block
       (NOT the entire page — this avoids UI icons, review images, related products)
    2. Flipkart: Extract from gallery div containers only
    3. Myntra/Meesho: Extract from CDN URL patterns in page scripts
    4. Generic: OpenGraph/JSON-LD/srcset from the page, with strict filtering

    Returns list of { url, alt, score, source } ordered by score, max MAX_IMAGES.
    """
    soup = BeautifulSoup(html, "lxml")
    is_amazon   = bool(re.search(r"amazon\.(in|com|co\.uk|de|fr|ca|com\.br)", base_url, re.I))
    is_flipkart = "flipkart.com" in base_url.lower()
    is_myntra   = "myntra.com" in base_url.lower()
    is_meesho   = "meesho.com" in base_url.lower()

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
        if _should_skip(url, alt):
            return
        seen_urls.add(url)
        images.append({"url": url, "alt": alt, "score": _score_image_url(url, alt), "source": source})

    # ════════════════════════════════════════════════════════════════════════════
    # AMAZON — scoped gallery extraction only
    # ════════════════════════════════════════════════════════════════════════════
    if is_amazon:
        gallery_images = _extract_amazon_gallery_images(html, soup, base_url)
        for img in gallery_images:
            if img["url"] not in seen_urls:
                seen_urls.add(img["url"])
                images.append(img)

        # OpenGraph image as additional source (usually front-of-pack)
        for meta in soup.find_all("meta", property="og:image"):
            _add(meta.get("content", ""), "", "og_image")

        images.sort(key=lambda x: -x["score"])
        return images[:MAX_IMAGES]

    # ════════════════════════════════════════════════════════════════════════════
    # FLIPKART — gallery div containers only
    # ════════════════════════════════════════════════════════════════════════════
    if is_flipkart:
        # Flipkart CDN URLs (high-res) — most reliable source
        flipkart_imgs = re.findall(
            r'"(https?://rukminim\d*\.flixcart\.com/image/[^"?]+\.(?:jpg|jpeg|png|webp))',
            html, re.IGNORECASE,
        )
        for fk_url in flipkart_imgs:
            upgraded = re.sub(r"/\d+/\d+/", "/832/832/", fk_url)
            _add(upgraded, "product", "flipkart_cdn")

        # Gallery div containers
        for cls in _FLIPKART_GALLERY_CLASSES:
            for div in soup.find_all("div", class_=re.compile(cls, re.I)):
                for img in div.find_all("img"):
                    src = img.get("src", "") or img.get("data-src", "")
                    _add(src, img.get("alt", ""), "flipkart_gallery")

        images.sort(key=lambda x: -x["score"])
        return images[:MAX_IMAGES]

    # ════════════════════════════════════════════════════════════════════════════
    # MYNTRA — CDN script extraction
    # ════════════════════════════════════════════════════════════════════════════
    if is_myntra:
        myntra_imgs = re.findall(
            r"https?://(?:assets\.myntassets\.com|assets\.myntra\.com)/assets/images/"
            r"(\d{4}/\w+/\d+/[A-Za-z0-9_]+\.(?:jpg|jpeg|png|webp))",
            html, re.IGNORECASE,
        )
        seen_myntra: set[str] = set()
        for asset_path in myntra_imgs:
            if "retaillabs" in asset_path:
                continue
            hires_url = f"https://assets.myntassets.com/h_1440,q_75,w_1080/v1/assets/images/{asset_path}"
            if hires_url not in seen_myntra:
                seen_myntra.add(hires_url)
                _add(hires_url, "product", "myntra_script")

        images.sort(key=lambda x: -x["score"])
        return images[:MAX_IMAGES]

    # ════════════════════════════════════════════════════════════════════════════
    # MEESHO — CDN extraction
    # ════════════════════════════════════════════════════════════════════════════
    if is_meesho:
        meesho_imgs = re.findall(
            r"https?://media\.meesho\.com/images/products/[^\s\"']+\.(?:jpg|jpeg|png|webp)",
            html, re.IGNORECASE,
        )
        for url in set(meesho_imgs):
            # Upgrade to high-res (replace /256/256 → /1080/1080)
            high = re.sub(r"/\d+/\d+", "/1080/1080", url)
            _add(high, "product", "meesho_cdn")

        images.sort(key=lambda x: -x["score"])
        return images[:MAX_IMAGES]

    # ════════════════════════════════════════════════════════════════════════════
    # GENERIC — curated full-page scan with strict filtering
    # ════════════════════════════════════════════════════════════════════════════

    # OpenGraph / Twitter card (most reliable for generic sites)
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        content = meta.get("content", "")
        if prop in ("og:image", "og:image:secure_url") and content:
            _add(content, "", "og_image")
        elif prop in ("twitter:image", "twitter:image:src") and content:
            _add(content, "", "twitter_image")

    # JSON-LD product images
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") in ("Product", "ItemPage"):
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

    # <img> tags from the page — but ONLY from product-related containers
    # Look for main content / product container first
    product_container = (
        soup.find(id=re.compile(r"product|item|pdp|detail|main.content|content.main", re.I)) or
        soup.find(class_=re.compile(r"product.detail|pdp.container|item.detail|product.page", re.I)) or
        soup.find("main") or
        soup.body
    )

    if product_container:
        for img in product_container.find_all("img"):
            alt = img.get("alt", "")
            # Skip clearly non-product images
            if _should_skip(img.get("src", ""), alt):
                continue

            # Try high-res attributes first
            for attr in ("data-zoom-image", "data-src", "data-original", "data-large", "data-full"):
                val = img.get(attr, "")
                if val:
                    _add(val, alt, f"generic_{attr}")

            # srcset
            srcset = img.get("srcset", "")
            if srcset:
                best = _parse_srcset_best(srcset)
                if best:
                    _add(best, alt, "generic_srcset")

            src = img.get("src", "")
            _add(src, alt, "img_tag")

    images.sort(key=lambda x: -x["score"])
    return images[:MAX_IMAGES]
