"""
url_scanner/image_classifier.py
Legal Metrology Compliance Image Classifier

ARCHITECTURE: Two-stage selection
  Stage 1 — URL/metadata signal scoring (fast, always runs)
  Stage 2 — Visual content analysis via PIL (downloads thumbnail for each candidate)
  Stage 3 — Diversity/duplicate filter (maximise compliance info coverage)

DESIGN GOAL:
  Select images that contain the MOST USEFUL REAL PACKAGING INFORMATION for
  Legal Metrology compliance extraction — not just pretty or "relevant" product shots.

  GOOD: front/back/side of actual physical package, label panels, declaration panels
  BAD:  marketing graphics, lifestyle shots, brand logos, Amazon UI images, infographics

No trained ML model is required. The combination of:
  - Strong URL/alt signal blocklists and allowlists
  - PIL-based visual metrics (texture variance, aspect ratio, colour histogram)
  - Compliance-keyword matching on alt text
  - Duplicate similarity detection via image hash
produces accurate compliance-focused selection.
"""
from __future__ import annotations

import re
import io
import hashlib
import asyncio
from typing import Optional


# ── Image type classification ──────────────────────────────────────────────────
# Legal Metrology Relevance Score: how valuable is this image type for LM extraction?
# Scale 0–100: 100 = absolutely critical, 0 = completely useless

IMAGE_TYPES = {
    # High priority: contain the actual legal declarations
    "BACK_PACKAGE":         {"lm_relevance": 99, "is_packaging": True},
    "MANUFACTURER_LABEL":   {"lm_relevance": 98, "is_packaging": True},
    "MRP_LABEL":            {"lm_relevance": 97, "is_packaging": True},
    "REGULATORY_LABEL":     {"lm_relevance": 95, "is_packaging": True},
    "SIDE_LABEL":           {"lm_relevance": 94, "is_packaging": True},
    "INGREDIENT_PANEL":     {"lm_relevance": 90, "is_packaging": True},   # NEW — ingredient list panel
    "INGREDIENT_LABEL":     {"lm_relevance": 88, "is_packaging": True},
    "NUTRITION_LABEL":      {"lm_relevance": 85, "is_packaging": True},
    "BARCODE":              {"lm_relevance": 80, "is_packaging": True},
    "FRONT_PACKAGE":        {"lm_relevance": 75, "is_packaging": True},
    # Low priority: not relevant for legal declarations
    "PRODUCT_INFO":         {"lm_relevance": 40, "is_packaging": False},
    "PRODUCT_USAGE":        {"lm_relevance": 20, "is_packaging": False},
    "PROMOTIONAL_GRAPHIC":  {"lm_relevance": 8,  "is_packaging": False},
    "LIFESTYLE":            {"lm_relevance": 7,  "is_packaging": False},
    "PACKAGING_VARIATION":  {"lm_relevance": 4,  "is_packaging": False},
    "ADVERTISEMENT":        {"lm_relevance": 3,  "is_packaging": False},
    "BRAND_GRAPHIC":        {"lm_relevance": 3,  "is_packaging": False},
    "UNKNOWN":              {"lm_relevance": 30, "is_packaging": False},
}


# Legacy CATEGORIES kept for backwards compatibility with classify_image()
CATEGORIES = {
    "front_package": [
        "front", "main", "primary", "_SL1500_", "_SL1000_", "front-view",
        "pack-front", "_AC_SL", "product-image", "pdp-",
    ],
    "back_package": [
        "back", "rear", "reverse", "back-view", "pack-back",
        "ingredients", "nutrition", "nutrition-label",
    ],
    "side_label": [
        "side", "label", "detail", "spec", "specification",
        "manufacturer", "mfg", "barcode", "qr", "declaration",
    ],
    "nutrition": [
        "nutrition", "nutritional", "allergen",
        "supplement-facts", "facts-panel",
    ],
    # Dedicated ingredient panel — URL contains these keywords → high ingredient priority
    "ingredient_panel": [
        "ingredient", "ingredients", "composition", "made-from",
        "made-with", "prepared-from", "content-list",
    ],
    "lifestyle": [
        "lifestyle", "model", "person", "happy", "banner",
        "hero", "mood", "scene", "background",
    ],
}



# ── Field → ImageType routing (spec §9) ───────────────────────────────────────
# Maps a missing LM field name → ordered list of image classification categories
# most likely to contain that field.  Used by rank_for_missing_fields() to
# re-rank remaining candidates when the adaptive OCR loop needs more images.

_FIELD_TO_PREFERRED_TYPES: dict[str, list[str]] = {
    # Critical fields
    "manufacturer":          ["back_package", "side_label", "non_packaging"],   # non_packaging = MANUFACTURER_LABEL
    "manufacturer_address":  ["back_package", "side_label"],
    "mrp":                   ["back_package", "side_label", "front_package"],
    "net_qty":               ["front_package", "back_package", "side_label"],
    "country":               ["back_package", "side_label"],
    "fssai":                 ["back_package", "side_label"],
    # High priority
    "consumer_care":         ["back_package", "side_label"],
    "barcode":               ["back_package", "side_label"],
    "batch":                 ["back_package", "side_label"],
    "expiry":                ["back_package", "side_label"],
    "dates":                 ["back_package", "side_label"],
    # Medium priority — ingredient/food specific
    "ingredients":           ["ingredient_panel", "nutrition", "back_package", "side_label"],
    "nutrition":             ["nutrition", "back_package"],
    "allergen":              ["nutrition", "ingredient_panel", "back_package"],
    "storage":               ["back_package", "side_label"],
    # OCR signal fields (match keys in ocr_signals dict)
    "has_fssai":             ["back_package", "side_label"],
    "has_mrp":               ["back_package", "side_label", "front_package"],
    "has_manufacturer":      ["back_package", "side_label"],
    "has_net_qty":           ["front_package", "back_package", "side_label"],
    "has_consumer_care":     ["back_package", "side_label"],
    "has_date_batch":        ["back_package", "side_label"],
    "has_country":           ["back_package", "side_label"],
    "has_ingredients":       ["ingredient_panel", "nutrition", "back_package", "side_label"],
}

# OCR signal → field name mapping (for adaptive loop to know which signals cover which fields)
_OCR_SIGNAL_TO_FIELD: dict[str, str] = {
    "has_fssai":        "fssai",
    "has_mrp":          "mrp",
    "has_manufacturer": "manufacturer",
    "has_net_qty":      "net_qty",
    "has_consumer_care":"consumer_care",
    "has_date_batch":   "dates",
    "has_country":      "country",
    "has_ingredients":  "ingredients",   # NEW — ingredient signal maps to ingredients field
}



def rank_for_missing_fields(
    candidates: list[dict],
    missing_fields: list[str],
    already_processed_urls: set[str] | None = None,
) -> list[dict]:
    """
    Re-rank remaining candidate images based on which LM fields are still missing.

    For each candidate, computes a "field-match boost" based on:
      1. Whether its thumbnail OCR signals directly cover a missing field (+60 per field)
      2. Whether its classification category is preferred for a missing field (+25 per field)
      3. Its existing compliance_score (base)

    Returns candidates sorted by this composite score (highest first),
    filtered to exclude already-processed URLs.

    Example:
        missing_fields = ["manufacturer", "fssai"]
        → Image classified as back_package with has_manufacturer=True
          gets +60 (OCR signal) + +25 (category match for manufacturer)
          + +25 (category match for fssai) = +110 field-match boost
        → Image classified as front_package with no signals gets 0 boost
    """
    if already_processed_urls is None:
        already_processed_urls = set()

    # Build preferred-type set for all currently missing fields
    preferred_type_scores: dict[str, int] = {}
    for field in missing_fields:
        preferred_types = _FIELD_TO_PREFERRED_TYPES.get(field, [])
        for rank, cat in enumerate(preferred_types):
            # First preferred type = +25, second = +15, third = +8
            boost = [25, 15, 8][min(rank, 2)]
            preferred_type_scores[cat] = preferred_type_scores.get(cat, 0) + boost

    scored: list[tuple[int, dict]] = []
    for img in candidates:
        url = img.get("url", "")
        if url in already_processed_urls:
            continue

        base = img.get("compliance_score", 0)
        field_boost = 0

        # Boost 1: thumbnail OCR signals directly cover missing fields
        sigs = img.get("ocr_signals", {})
        for sig, field in _OCR_SIGNAL_TO_FIELD.items():
            if sigs.get(sig) and field in missing_fields:
                field_boost += 60  # direct evidence — very high boost

        # Boost 2: classification category matches preferred types for missing fields
        cat = img.get("classification", {}).get("category", "unknown")
        field_boost += preferred_type_scores.get(cat, 0)

        # Boost 3: thumbnail OCR preview text contains field keywords (if available)
        preview = img.get("ocr_preview_text", "")
        if preview:
            if "manufacturer" in missing_fields and any(
                kw in preview.lower() for kw in ("manufactur", "mfg by", "packed by", "marketed by")
            ):
                field_boost += 20
            if "fssai" in missing_fields and any(
                kw in preview.lower() for kw in ("fssai", "licence no", "license no")
            ):
                field_boost += 20
            if "mrp" in missing_fields and any(
                kw in preview.lower() for kw in ("mrp", "maximum retail", "₹")
            ):
                field_boost += 20

        scored.append((base + field_boost, img))

    # Sort by composite score (highest first)
    scored.sort(key=lambda x: -x[0])
    return [img for _, img in scored]



# Images matching these are marketing/UI/icon/non-packaging — strongly penalise

_REJECT_URL = re.compile(
    r"(amazon-logo|amzn-logo|sprite[_/]|ic_|btmbar|nav-icon|"
    # Use word boundaries / separators to avoid matching CDN hostnames
    # e.g. 'cart' in 'flipcart', 'star' in 'myntastar', 'icon' in domain
    r"[/_-]icon[/_-]|[/_-]badge[/_-]|[/_-]star[/_-]|[/_-]review[/_-]|"
    r"[/_-]cart[/_-]|[/_-]wishlist[/_-]|[/_-]checkout[/_-]|"
    r"[/_-]offer[/_-]|[/_-]deal[/_-]|[/_-]payment[/_-]|"
    r"[/_-]widget[/_-]|[/_-]share[/_-]|"
    # Longer distinctive strings safe to match without boundaries
    r"watermark|overlay|retaillabs|placeholder|spacer|pixel|"
    r"pdp_loader|favicon|"
    r"[/_-]banner[/_-]|[/_-]hero[/_-]|[/_-]model[/_-]|"
    r"background|bg-|_bg\.|"
    r"social-icon|facebook\.com|twitter\.com|instagram\.com|"
    r"logo(?!.*product)|"
    # Lifestyle / promotional / variation patterns (KEY FIX)
    r"lifestyle|howto|how-to|how_to|"
    r"serving[_-]?suggestion|serving[_-]?size[_-]?image|"
    r"benefit[_-]image|claim[_-]image|feature[_-]image|infographic[_-]|"
    r"step[_-]?\d[_-]|steps[_-]?to|usage[_-]?image|"
    r"packaging[_-]?may[_-]?vary|may[_-]?vary|for[_-]?illustration|"
    r"representat|for[_-]?represent|image[_-]?purpose|"
    r"[/_-]promo[/_-]|promotional[/_-]|[/_-]sale[/_-]|"
    r"[/_-]ad[/_-]|advertisement)",
    re.IGNORECASE,
)

_REJECT_ALT = re.compile(
    r"(amazon logo|brand logo|promotional|lifestyle|"
    r"marketing|banner|offer|discount|sale|"
    r"buy now|add to cart|free delivery|prime|"
    r"icon|graphic|illustration|"
    r"serving suggestion|packaging may vary|"
    r"image for representation|for illustration)",
    re.IGNORECASE,
)

# ── Strong PREFER patterns (URL / alt text) ────────────────────────────────────
# Known high-value signals that suggest actual packaging

_PREFER_URL = re.compile(
    r"(back|rear|side|label|nutrition|ingredient|allergen|"
    r"declaration|compliance|specification|spec-|"
    r"manufacturer|mfg|barcode|qrcode|"
    r"_SL1500_|_SL1000_|_SL500_|_SX679_|_SX466_|"
    r"h_1440|h_2000|q_90|w_1500|"         # high-res Cloudinary
    r"large|zoom|hires|hi-res|full|"
    r"/p/\d|/product/\d|/dp/)",
    re.IGNORECASE,
)


_PREFER_ALT = re.compile(
    r"(back|reverse|label|ingredient|nutrition|allergen|"
    r"manufacturer|packer|importer|fssai|"
    r"net.?weight|net.?qty|net.?quantity|mrp|"
    r"country.?of.?origin|consumer.?care|"
    r"best.?before|expiry|batch|lot.?no|"
    r"barcode|qr.?code|declaration|statutory|"
    r"packaging|package)",
    re.IGNORECASE,
)

# ── Compliance keyword scoring on alt text ─────────────────────────────────────
_COMPLIANCE_ALT_KEYWORDS = [
    # High-value compliance fields
    ("net.?weight|net.?qty|net.?quantity|net.?content",         25),
    (r"mrp|maximum.?retail.?price|price.?per",                  25),
    ("manufacturer|mfg.?by|marketed.?by|packed.?by|packer",     25),
    ("importer|imported.?by",                                   25),
    ("fssai|lic.?no|licence|license",                           20),
    ("country.?of.?origin",                                     15),
    ("consumer.?care|customer.?care|helpline",                   15),
    ("best.?before|expiry|exp.?date|use.?by",                   15),
    ("batch|lot.?no|b.?no",                                     10),
    ("ingredients|allergen|nutritional",                        10),
    ("back|rear|reverse",                                       20),
    ("side|label|declaration|statutory",                        15),
    ("front|main|primary",                                       8),
]

# ── Amazon-specific URL patterns ───────────────────────────────────────────────
_AMAZON_HIRES = re.compile(r"_SL(\d{3,4})_|_AC_SL(\d{3,4})|_SX(\d{3,4})", re.IGNORECASE)
_AMAZON_THUMB = re.compile(r"_SS(\d{2,3})_|_SX(\d{2})_|_UX(\d{2,3})_", re.IGNORECASE)
_AMAZON_IMAGE_INDEX = re.compile(r"\.(\d{2})\.", )  # e.g. .02.  .03.  in Amazon image URLs

# ── Non-product tiny image sizes ──────────────────────────────────────────────
_TINY_SIZE_PAT = re.compile(r"[_-](\d{2,3})x\1[_-]|/(\d{2})x(\d{2})/", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 — URL/metadata scoring (no downloads needed)
# ──────────────────────────────────────────────────────────────────────────────

def _url_metadata_score(url: str, alt: str, source: str, collector_score: int) -> tuple[int, list[str]]:
    """
    Fast scoring based purely on URL, alt text, and collection metadata.
    Returns (score, [reason strings]).
    """
    combined_url = url.lower()
    combined_alt = alt.lower()
    reasons: list[str] = []
    score = 0

    # Hard reject: UI elements, icons, logos
    if _REJECT_URL.search(combined_url):
        score -= 120
        reasons.append("URL matches non-packaging pattern (icon/logo/UI/promotional)")
        return score, reasons

    if _REJECT_ALT.search(combined_alt):
        score -= 60
        reasons.append("Alt text matches promotional/marketing content")

    # Tiny thumbnail — useless for OCR
    if _TINY_SIZE_PAT.search(combined_url):
        score -= 40
        reasons.append("Appears to be a tiny thumbnail")

    # Amazon-specific thumbnail patterns
    if _AMAZON_THUMB.search(combined_url):
        score -= 50
        reasons.append("Amazon small thumbnail URL")

    # Source trust (adapter-provided images are actual product images)
    if source == "adapter":
        score += 30
        reasons.append("Adapter-provided product image (+30)")
    elif source in ("amazon_hires", "amazon_dynamic"):
        score += 25
        reasons.append("Amazon high-resolution image source (+25)")
    elif source == "amazon_gallery":
        score += 15
        reasons.append("Amazon gallery image (+15)")
    elif source in ("myntra_script",):
        score += 20
        reasons.append("Myntra product image (+20)")
    elif source == "jsonld":
        score += 10
        reasons.append("JSON-LD structured data image (+10)")

    # High-res URL signals
    if _PREFER_URL.search(combined_url):
        score += 20
        reasons.append("URL matches high-res/packaging pattern (+20)")

    # Amazon high-res size in URL
    m = _AMAZON_HIRES.search(combined_url)
    if m:
        size_val = int(m.group(1) or m.group(2) or m.group(3) or 0)
        if size_val >= 1000:
            score += 25
            reasons.append(f"Amazon high-res image {size_val}px (+25)")
        elif size_val >= 500:
            score += 12
            reasons.append(f"Amazon medium-res image {size_val}px (+12)")

    # Cloudinary high-res transforms (Myntra / Nykaa / Meesho)
    if re.search(r"h_\d{4}|w_\d{4}|q_\d{2,3}", combined_url):
        score += 18
        reasons.append("Cloudinary high-res transform (+18)")

    # Amazon image index (01, 02, 03 etc) — later indices often show back/side
    idx_m = _AMAZON_IMAGE_INDEX.search(url)
    if idx_m:
        idx = int(idx_m.group(1))
        if idx == 1:
            score += 5
            reasons.append("Amazon primary image index 01 (+5)")
        elif 2 <= idx <= 5:
            score += 18  # back/side/detail panels typically appear here
            reasons.append(f"Amazon image index {idx:02d} (back/side/detail range, +18)")
        elif 6 <= idx <= 9:
            # Amazon gallery 6-9: lifestyle shots, benefits infographics, range shots
            score -= 15
            reasons.append(f"Amazon image index {idx:02d} (likely lifestyle/promo, -15)")
        elif idx >= 10:
            # Index 10+: almost always brand graphic or lifestyle
            score -= 25
            reasons.append(f"Amazon image index {idx:02d} (very likely brand/lifestyle, -25)")


    # Alt text — compliance keyword matching
    if _PREFER_ALT.search(combined_alt):
        score += 18
        reasons.append("Alt text suggests compliance-relevant content (+18)")

    for pattern, pts in _COMPLIANCE_ALT_KEYWORDS:
        if re.search(pattern, combined_alt, re.IGNORECASE):
            score += pts
            reasons.append(f"Alt text: '{pattern}' compliance field (+{pts})")
            break  # only take the highest match per image

    # URL compliance keywords
    for kw in ("back", "rear", "reverse", "side", "label", "nutrition",
                "ingredient", "manufacturer", "declaration", "barcode"):
        if kw in combined_url:
            score += 12
            reasons.append(f"URL contains '{kw}' (+12)")
            break

    # Pass-through the original collector score (general image quality signal)
    if collector_score > 0:
        score += min(collector_score, 15)  # cap collector contribution

    return score, reasons


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 — Visual scoring via PIL (thumbnail download)
# ──────────────────────────────────────────────────────────────────────────────

def _visual_score_sync(image_bytes: bytes) -> tuple[int, str, str]:
    """
    Analyse image bytes with PIL to compute a compliance-focused visual score.
    Returns (visual_score, reason, image_hash).

    Metrics used:
      - Aspect ratio  (packaging is usually portrait or square, not ultra-wide banners)
      - Pixel variance (high variance = photo/text; low variance = flat graphic)
      - Edge density — primary proxy for text density
      - Colour histogram entropy (photos have diverse colours; logos/graphics are flat)
      - Text density ratio (% of image covered by text-like dark pixels on light bg)
      - Barcode detection (thin vertical lines on white bg = barcode image)
      - FSSAI certificate detector (small logo + text on white = FSSAI cert image)
      - Image size (larger = higher quality for OCR)
    """
    try:
        from PIL import Image, ImageFilter, ImageStat
        import struct

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size

        score = 0
        reasons = []

        # ── Size check ────────────────────────────────────────────────────────
        if w < 80 or h < 80:
            return -80, "Too small to contain useful packaging info", ""

        # Image hash (for duplicate detection) — use thumbnail hash
        thumb = img.resize((16, 16), Image.LANCZOS).convert("L")
        phash = hashlib.md5(thumb.tobytes()).hexdigest()

        # ── Aspect ratio ──────────────────────────────────────────────────────
        ratio = w / h if h > 0 else 1.0
        if 0.5 <= ratio <= 2.0:
            # Portrait/square/slight landscape → typical packaging image
            score += 15
            reasons.append("Good aspect ratio (packaging-like)")
        elif ratio > 3.0 or ratio < 0.3:
            # Ultra-wide or ultra-tall → likely a banner or icon strip
            score -= 25
            reasons.append("Extreme aspect ratio (likely banner/icon strip)")

        # ── Resolution quality ────────────────────────────────────────────────
        pixels = w * h
        if pixels >= 500_000:   # >= 500K px (e.g. 707×707)
            score += 20
            reasons.append("High resolution (>500K px)")
        elif pixels >= 100_000:  # >= 100K px
            score += 10
            reasons.append("Medium resolution (>100K px)")
        elif pixels < 20_000:
            score -= 20
            reasons.append("Very low resolution (<20K px)")

        # ── Edge density — primary proxy for text density ─────────────────────
        # Back-of-pack labels have MANY edges (text characters = edges).
        # Lifestyle/marketing photos have far fewer edges per area unit.
        gray = img.convert("L").resize((200, 200), Image.LANCZOS)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_mean = edge_stat.mean[0]

        # ── Colour diversity — combined with edge for image type classification
        small = img.resize((64, 64), Image.LANCZOS)
        unique_colours = len(set(small.getdata()))

        # ── Text density ratio ────────────────────────────────────────────────
        # Count pixels that look like dark text on a light background.
        # Binarize gray image: pixels darker than 140 on a mostly-light image = text
        gray_small = img.convert("L").resize((100, 100), Image.LANCZOS)
        pixels_data = list(gray_small.getdata())
        total_px = len(pixels_data)
        dark_px  = sum(1 for p in pixels_data if p < 140)
        light_px = sum(1 for p in pixels_data if p > 180)
        text_density  = dark_px / total_px      # fraction of image that is dark text
        bg_light_frac = light_px / total_px     # fraction that is white/light background

        # ── Barcode detector ──────────────────────────────────────────────────
        # A barcode image is: mostly white background + thin dense vertical dark lines
        # Signature: bg_light_frac > 0.55, text_density 0.05–0.30, portrait/square ratio
        # AND very regular edge pattern in horizontal direction (stripes)
        is_barcode = False
        if bg_light_frac > 0.55 and 0.05 < text_density < 0.35 and ratio <= 2.5:
            # Check horizontal stripe regularity: sample a thin band across the center
            # A barcode has alternating dark/light columns = many zero-crossings
            center_row = [gray_small.getpixel((x, 50)) for x in range(100)]
            crossings = sum(
                1 for i in range(1, len(center_row))
                if (center_row[i - 1] < 128) != (center_row[i] < 128)
            )
            if crossings >= 20:   # 20+ dark/light transitions across the center = barcode pattern
                is_barcode = True
                score += 55
                reasons.append(
                    f"BARCODE: {crossings} horizontal stripe transitions, "
                    f"{text_density*100:.0f}% dark px on light bg (+55)"
                )

        # ── FSSAI Certificate / Declaration Panel detector ────────────────────
        # FSSAI logo cards and regulatory declaration images are:
        # small square/portrait, mostly white, small amount of dark text + logo
        # text_density 0.02–0.12, very high light bg fraction > 0.70
        is_fssai_cert = False
        if (not is_barcode and bg_light_frac > 0.70
                and 0.02 < text_density < 0.15
                and 0.4 <= ratio <= 2.0
                and pixels < 300_000):   # Usually small images
            is_fssai_cert = True
            score += 40
            reasons.append(
                f"REGULATORY CERT: high white bg ({bg_light_frac*100:.0f}%), "
                f"low text density ({text_density*100:.0f}%) — FSSAI/cert image (+40)"
            )

        # ── Back label / declaration panel detector ───────────────────────────
        # Back labels: high edge density + mostly white/light bg + medium text density
        # This is stronger evidence than just "high edges" because it filters out
        # colourful front packaging with graphics that also have high edges.
        is_text_label = False
        if (not is_barcode and not is_fssai_cert
                and edge_mean > 18 and bg_light_frac > 0.35 and text_density > 0.08):
            is_text_label = True
            score += 45
            reasons.append(
                f"BACK/DECLARATION LABEL: edges={edge_mean:.0f}, "
                f"light-bg={bg_light_frac*100:.0f}%, text-density={text_density*100:.0f}% (+45)"
            )

        # ── Combined classifier: KEY FIX ──────────────────────────────────────
        if not is_barcode and not is_fssai_cert and not is_text_label:
            # ── Colored-background compliance label ─────────────────────────
            # Cadbury purple, green Amul, red Maggi etc. — compliance text printed
            # in WHITE on a COLORED (non-white) background.
            # In grayscale: the colored background is DARK (gray 50-130), so
            # text_density is very HIGH.  bg_light_frac is LOW (only white text).
            # These images look like "lifestyle" to the old detector → wrongly penalized.
            # Key signature: high text_density + at least some light pixels (the text)
            #   + some edge activity from the text characters.
            is_colored_label = False
            if (text_density > 0.40            # colored bg = lots of "dark" pixels
                    and bg_light_frac > 0.01   # at least 1% white/light (text area)
                    and edge_mean > 6          # some edges = text present
                    and 0.4 <= ratio <= 2.5):  # reasonable packaging aspect ratio
                is_colored_label = True
                score += 35
                reasons.append(
                    f"COLORED-BG COMPLIANCE LABEL: dark-bg={text_density*100:.0f}%, "
                    f"light-text={bg_light_frac*100:.1f}%, edges={edge_mean:.0f} (+35)"
                )

            if not is_colored_label:
                # High edge + low-medium colour = TEXT LABEL (back/declaration/nutrition)
                if edge_mean > 20 and unique_colours < 1800:
                    score += 40
                    reasons.append(
                        f"TEXT LABEL: high edges ({edge_mean:.0f}) + limited colours "
                        f"({unique_colours}) — back/declaration label"
                    )
                # High edge + high colour = text on colourful packaging (front or back)
                elif edge_mean > 20 and unique_colours >= 1800:
                    score += 18
                    reasons.append(
                        f"Colourful text-rich: edges ({edge_mean:.0f}), colours ({unique_colours})"
                    )
                # Low edge + high colour = lifestyle photo / marketing image (KEY PENALIZE)
                elif edge_mean < 12 and unique_colours > 2000:
                    score -= 30
                    reasons.append(
                        f"LIFESTYLE/PHOTO: low edges ({edge_mean:.0f}) + high colour "
                        f"diversity ({unique_colours}) — penalized"
                    )
                # Low edge + low colour = flat graphic / icon
                elif edge_mean < 12 and unique_colours < 500:
                    score -= 25
                    reasons.append(
                        f"FLAT GRAPHIC: edges ({edge_mean:.0f}), colours ({unique_colours})"
                    )
                else:
                    score += 5
                    reasons.append(
                        f"Medium visual complexity (edges={edge_mean:.0f}, colours={unique_colours})"
                    )

        # ── Pixel variance: only penalize truly uniform images ────────────────
        stat = ImageStat.Stat(img)
        avg_std = sum(stat.stddev) / 3
        if avg_std < 10:
            score -= 15
            reasons.append(f"Very low variance ({avg_std:.0f}) — blank/uniform image")

        # ── Product-range / lifestyle-scene detection ─────────────────────────
        # "Product range" shots (e.g. showing 6 different flavours in a row) are
        # always WIDE (landscape > 1.4:1) AND have multiple equally-spaced vertical
        # edge peaks — one per product.  These contain ZERO compliance information.
        # Detection: sample 8 vertical strips; count those with high edge density.
        # If most vertical strips have high edges = multiple distinct objects = range shot.
        if ratio > 1.2 and w >= 200 and not is_barcode:
            strip_w = max(1, w // 8)
            high_edge_strips = 0
            for s in range(8):
                x0 = s * strip_w
                x1 = min(x0 + strip_w, w)
                strip = gray.crop((
                    int(x0 * 200 / w), 0,
                    int(x1 * 200 / w), 200,
                ))
                strip_edges = strip.filter(ImageFilter.FIND_EDGES)
                if ImageStat.Stat(strip_edges).mean[0] > 15:
                    high_edge_strips += 1
            if high_edge_strips >= 6:
                # 6+ out of 8 strips are edge-dense = evenly distributed objects
                # = very likely a product-range / lifestyle-scene shot
                score -= 25
                reasons.append(
                    f"RANGE SHOT: {high_edge_strips}/8 vertical strips edge-dense "
                    f"(likely multi-product range or lifestyle scene, -25)"
                )

        reason_str = "; ".join(reasons)
        return score, reason_str, phash


    except Exception as e:
        return 0, f"Visual analysis failed: {e}", ""


async def _download_and_score_visual(session: "httpx.AsyncClient", url: str) -> tuple[int, str, str]:
    """Download thumbnail and return (visual_score, reason, phash)."""
    try:
        # Download a thumbnail version for analysis — use smaller size for speed
        thumb_url = url
        # Amazon: replace with 300px version for fast analysis
        thumb_url = re.sub(r"_SL\d{3,4}_", "_SL300_", thumb_url)
        thumb_url = re.sub(r"h_\d{4},q_\d+,w_\d{4}", "h_300,q_50,w_300", thumb_url)

        r = await session.get(thumb_url, timeout=6.0)
        if r.status_code == 200 and len(r.content) > 1000:
            loop = asyncio.get_event_loop()
            score, reason, phash = await loop.run_in_executor(
                None, _visual_score_sync, r.content
            )
            return score, reason, phash
    except Exception:
        pass
    return 0, "Visual analysis skipped (download failed)", ""


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3 — Coverage-Optimized Selection
# ──────────────────────────────────────────────────────────────────────────────
# Compliance field weights — used to calculate "marginal gain" of each image
# (how many NEW legal fields would this image contribute to the selected set?)
_FIELD_WEIGHTS = {
    "has_fssai_with_number": 120,  # FSSAI + 14-digit licence number — absolute top priority
    "has_fssai":              80,   # FSSAI text present — regulatory licence
    "has_dense_text":         60,   # 40+ OCR words — back label / ingredient panel
    "has_mrp":                35,   # Mandatory declaration
    "has_manufacturer":       35,   # Mandatory declaration
    "has_net_qty":            30,   # Mandatory declaration
    "has_ingredients":        30,   # Ingredient list (Food items — back/side label)
    "has_consumer_care":      20,   # Consumer care details
    "has_date_batch":         20,   # Mfg/Expiry/Batch dates
    "has_country":            15,   # Country of origin
    "has_nutrition_only":     10,   # Nutrition facts table (lower than ingredients)
}


def _marginal_gain(img: dict, covered: set[str]) -> int:
    """Return the total weight of NEW compliance fields this image would add."""
    signals = img.get("ocr_signals", {})
    gain = 0
    for field, weight in _FIELD_WEIGHTS.items():
        if signals.get(field) and field not in covered:
            gain += weight
    return gain


def _is_near_duplicate(img_a: dict, img_b: dict) -> bool:
    """Return True if two images appear to be near-duplicates.

    An image is NOT a near-duplicate if it carries unique compliance signals
    (FSSAI, dense text, manufacturer) that the other image doesn't have.
    We only suppress truly redundant images.
    """
    # Exact phash match — identical images regardless of signals
    pa = img_a.get("phash", "")
    pb = img_b.get("phash", "")
    if pa and pb and pa == pb:
        return True

    # Same category AND very close score — but only if NEITHER carries unique compliance signals
    cat_a = img_a.get("classification", {}).get("category", "")
    cat_b = img_b.get("classification", {}).get("category", "")
    if cat_a == cat_b and cat_a in ("front_package", "back_package") and cat_a != "unknown":
        score_diff = abs(img_a.get("compliance_score", 0) - img_b.get("compliance_score", 0))
        if score_diff <= 15:
            # Don't suppress if either image has unique compliance signals
            sigs_a = img_a.get("ocr_signals", {})
            sigs_b = img_b.get("ocr_signals", {})
            _UNIQUE = ("has_fssai_with_number", "has_fssai", "has_dense_text",
                       "has_manufacturer", "has_mrp")
            a_has = any(sigs_a.get(s) for s in _UNIQUE)
            b_has = any(sigs_b.get(s) for s in _UNIQUE)
            if a_has or b_has:
                return False  # keep both — they may carry different compliance data
            return True
    return False


def _coverage_optimized_select(
    scored: list[dict],
    max_for_ocr: int = 4,
) -> list[dict]:
    """
    Greedy compliance coverage selection.

    ALGORITHM:
    1. Hard-reject: marketing-only (confirmed by thumbnail OCR), score < -50
    2. FSSAI mandate: if any candidate has FSSAI signal, it MUST be included
    3. Greedy: for each slot, pick the image with highest (base_score + marginal_gain)
       where marginal_gain = weight of NEW compliance fields not yet covered
    4. Near-duplicate filter: after picking an image, suppress similar images
    5. Category cap: max 1 front_package per selection (front packaging is easy to find;
       back/side/declaration panels are more valuable)
    6. Never fill a slot with an image scoring below threshold

    Returns selected images (possibly fewer than max_for_ocr if good ones are scarce).
    """
    MIN_SCORE = -30

    # --- Step 1: Filter out clearly bad images ---
    candidates = []
    for img in scored:
        if img.get("compliance_score", 0) < MIN_SCORE:
            img.setdefault("skip_reason", f"Score {img['compliance_score']} below threshold")
            continue
        sigs = img.get("ocr_signals", {})
        if sigs.get("is_marketing_only"):
            img.setdefault("skip_reason", "Confirmed marketing-only by thumbnail OCR")
            continue
        candidates.append(img)

    if not candidates:
        return []

    # ── Step 2: Priority pre-selection ───────────────────────────────────────
    # RANK 1: Image with FSSAI + 14-digit licence number (highest value possible)
    # RANK 2: Dense-text image (back label / ingredient panel, 40+ OCR words)
    # RANK 3: Front-of-product image (only ONE ever selected)
    # These are force-inserted as the first slots before the greedy loop starts.

    fssai_number_images = [
        img for img in candidates
        if img.get("ocr_signals", {}).get("has_fssai_with_number")
    ]
    fssai_images = [
        img for img in candidates
        if img.get("ocr_signals", {}).get("has_fssai") and img not in fssai_number_images
    ]
    dense_text_images = [
        img for img in candidates
        if img.get("ocr_signals", {}).get("has_dense_text") and img not in fssai_number_images
    ]

    # --- Step 3: Greedy set-cover selection ---
    selected: list[dict] = []
    suppressed: set[int] = set()   # indexes into `candidates`
    covered_fields: set[str] = set()
    front_pkg_count = 0            # max 1 front_package ever selected

    def _commit(img: dict) -> None:
        """Add img to selected set, mark its fields as covered, suppress near-dupes."""
        nonlocal front_pkg_count
        selected.append(img)
        for field in _FIELD_WEIGHTS:
            if img.get("ocr_signals", {}).get(field):
                covered_fields.add(field)
        if img.get("classification", {}).get("category") == "front_package":
            front_pkg_count += 1
        idx = candidates.index(img)
        for j, c in enumerate(candidates):
            if j != idx and _is_near_duplicate(img, c):
                c.setdefault("skip_reason", "Near-duplicate of selected image")
                suppressed.add(j)

    # RANK 1 slot — best FSSAI+licence-number image
    if fssai_number_images and len(selected) < max_for_ocr:
        best = max(fssai_number_images, key=lambda x: x.get("compliance_score", 0))
        _commit(best)

    # Also include best plain-FSSAI image if not already covered
    if fssai_images and len(selected) < max_for_ocr:
        best_fssai = max(fssai_images, key=lambda x: x.get("compliance_score", 0))
        if best_fssai not in selected:
            _commit(best_fssai)

    # RANK 2 slot — best dense-text image (if not already selected)
    if dense_text_images and len(selected) < max_for_ocr:
        best_dense = max(dense_text_images, key=lambda x: x.get("compliance_score", 0))
        if best_dense not in selected:
            _commit(best_dense)

    # Fill remaining slots greedily (coverage-optimized)
    for _ in range(max_for_ocr - len(selected)):
        best_img = None
        best_effective_score = -9999

        for j, img in enumerate(candidates):
            if j in suppressed or img in selected:
                continue

            cat = img.get("classification", {}).get("category", "unknown")

            # FRONT PACKAGE CAP: once a front image is selected, never pick another.
            # Even if no other type exists — we'd rather select unknown than a 2nd front.
            if cat == "front_package" and front_pkg_count >= 1:
                img.setdefault("skip_reason", "Front-package already selected (cap=1)")
                continue

            # Effective score = base + marginal coverage gain + OCR-confirmed bonus
            base  = img.get("compliance_score", 0)
            gain  = _marginal_gain(img, covered_fields)
            # Extra bonus for dense-text (many OCR words = rich info content)
            text_bonus = 30 if img.get("ocr_signals", {}).get("has_dense_text") else 0
            ocr_bonus  = 20 if img.get("ocr_signals") else 0
            effective  = base + gain + text_bonus + ocr_bonus

            if effective > best_effective_score:
                best_effective_score = effective
                best_img = img

        if best_img is None:
            break

        _commit(best_img)

    return selected



# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def classify_image(url: str, alt: str = "") -> dict:
    """
    Classify a single image by URL/alt heuristics only (fast, no download).
    Returns: { category, confidence, is_packaging }
    """
    combined = (url + " " + alt).lower()
    scores: dict[str, int] = {cat: 0 for cat in CATEGORIES}

    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in combined:
                scores[cat] += 1

    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    if best_score == 0:
        if re.search(r"_SL\d{3,4}_|_AC_SL\d+|_SX\d+", url):
            best_cat = "front_package"
            best_score = 1
        else:
            best_cat = "unknown"

    # Hard reject patterns → not packaging
    if _REJECT_URL.search(url.lower()):
        best_cat = "non_packaging"
        best_score = 0

    confidence = min(0.5 + best_score * 0.1, 0.95)
    is_packaging = best_cat in ("front_package", "back_package", "side_label", "nutrition")

    return {
        "category": best_cat,
        "confidence": round(confidence, 2),
        "is_packaging": is_packaging,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2.5 — Thumbnail OCR pre-scan
# ──────────────────────────────────────────────────────────────────────────────
# FSSAI compliance signal patterns — searched in thumbnail OCR text

_FSSAI_OCR_SIGNAL = re.compile(
    r"FSSAI|F\.?S\.?S\.?A\.?I|Lic(?:ence|ense)?\.?\s*No\.?|"
    r"License\s*No|Licence\s*No|[1-9]\d{13}",
    re.IGNORECASE,
)
_MRP_OCR_SIGNAL = re.compile(
    r"M\.?R\.?P\.?|Maximum\s*Retail\s*Price|Rs\.?\s*\d|₹\s*\d",
    re.IGNORECASE,
)
_MFR_OCR_SIGNAL = re.compile(
    r"Manufactur|Mfg\.?\s*[Bb]y|Packed\s*[Bb]y|Marketed\s*[Bb]y|"
    r"Imported\s*[Bb]y|MANUFACTURER|PACKER|IMPORTER",
    re.IGNORECASE,
)
_NET_QTY_OCR_SIGNAL = re.compile(
    r"Net\s*(?:Weight|Wt\.?|Quantity|Qty\.?|Content|Vol)|"
    r"NET\s*WT|Nett?\s*Wt|Net\s+Content|\d+\s*(?:kg|g|ml|litre|liter|L)\b",
    re.IGNORECASE,
)
_CONSUMER_CARE_OCR_SIGNAL = re.compile(
    r"Consumer\s*Care|Customer\s*Care|Helpline|Toll[\s-]*Free|1800[\s-]\d",
    re.IGNORECASE,
)
_DATE_BATCH_OCR_SIGNAL = re.compile(
    r"Batch|Lot\s*No|Mfg\s*Date|Best\s*Before|Expiry|BBE|Use\s*By",
    re.IGNORECASE,
)
_COUNTRY_OCR_SIGNAL = re.compile(
    r"Country\s*of\s*Origin|Made\s*in\s*India|Product\s*of",
    re.IGNORECASE,
)
# Ingredient panel signals — detects heading variants including common OCR errors.
# OCR commonly substitutes: uppercase I ↔ lowercase l ↔ digit 1
# This pattern uses a broad INGRED[...] match to catch all misspelling permutations.
_INGREDIENTS_OCR_SIGNAL = re.compile(
    # Broad INGRED* — covers INGREDIENTS, INGREDIENT, INGREDIANTS, INGREDlENTS,
    # INGRED1ENTS, INGREDEENTS and any other 2-7-char suffix after "INGRED"
    r"INGRED[A-Za-z1l]{2,7}[S]?\s*[:\-.]?"
    r"|COMPOSITION\s*[:\-.]?"              # COMPOSITION:
    r"|MADE\s+(?:FROM|WITH)\s*[:\-.]?"    # MADE FROM / MADE WITH
    r"|PREPARED\s+FROM\s*[:\-.]?"          # PREPARED FROM
    r"|CONTAINS\s*[:\-]\s*[A-Z]"           # CONTAINS: (uppercase letter = ingredient list, not allergen)
    r"|CONTENT\s*[:\-]\s*[A-Z]",           # CONTENT: ingredient list heading
    re.IGNORECASE,
)

# Nutrition panel specific — helps distinguish ingredient panel from nutrition table
_NUTRITION_ONLY_SIGNAL = re.compile(
    r"NUTRITION\s*(?:FACTS?|INFORMATION|VALUE|PER\s+\d+)"
    r"|(?:CALORIES?|ENERGY)\s*[:\-]?\s*\d"
    r"|TOTAL\s+(?:FAT|CARB|PROTEIN)\s*[:\-]?\s*\d"
    r"|AMOUNT\s+PER\s+SERVING",
    re.IGNORECASE,
)
# Marketing-only signals — if ONLY these appear (no compliance), penalise
_MARKETING_OCR_ONLY = re.compile(
    r"100%\s*(?:Pure|Natural|Organic)|No\s*Preservatives|"
    r"(?:Free\s*from|Contains\s*no)\s+(?:artificial|added)|"
    r"Loved\s*by|Trusted\s*by|Award\s*winning|Best\s*seller|"
    r"Clinically\s*(?:proven|tested)|Dermatologist|Satisfaction\s*Guaranteed",
    re.IGNORECASE,
)




def _ocr_thumbnail_sync(image_bytes: bytes) -> str:
    """
    Run fast EasyOCR on a thumbnail image.
    Preserves line structure (groups by Y-band) so compliance patterns work.
    Returns extracted text or empty string.

    Size: up to 800px — larger than before so small text strips (e.g. the
    compliance line at the bottom of a Cadbury pack) are readable at thumbnail size.
    Contrast boost: colored backgrounds (purple, green, red) are enhanced so
    white text stands out for OCR.
    """
    try:
        import numpy as np
        from PIL import Image, ImageEnhance, ImageOps
        from ocr.service import _get_reader

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size

        # Resize: use 800px for OCR — larger thumbnail = readable small text
        long_side = max(w, h)
        if long_side > 800:
            scale = 800 / long_side
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        elif long_side < 200:
            # Very small image — upscale for OCR
            scale = 200 / long_side
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # ── Contrast enhancement for colored backgrounds ──────────────────────
        # Images with dark colored backgrounds (purple Cadbury, green Amul, etc.)
        # have low average grayscale → white compliance text needs boosting.
        gray_arr = np.array(img.convert("L"))
        mean_gray = float(gray_arr.mean())

        if mean_gray < 100:
            # Colored/dark background — boost contrast to make white text clearer
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.5)
            # Also slightly sharpen to improve OCR on small text
            enhancer2 = ImageEnhance.Sharpness(img)
            img = enhancer2.enhance(2.0)

        img_array = np.array(img)
        reader = _get_reader()
        results = reader.readtext(img_array, detail=1)
        if not results:
            return ""

        # Group into lines by Y-band (20px bands)
        line_groups: dict[int, list[tuple[float, str]]] = {}
        for bbox, text, _conf in results:
            cy = (bbox[0][1] + bbox[2][1]) / 2
            band = int(cy / 20)
            line_groups.setdefault(band, []).append((bbox[0][0], text))

        lines = []
        for band in sorted(line_groups.keys()):
            items = sorted(line_groups[band], key=lambda x: x[0])
            lines.append(" ".join(t for _, t in items))
        return "\n".join(lines)
    except Exception:
        return ""


def _score_ocr_signals(text: str) -> tuple[int, str, dict]:
    """
    Given thumbnail OCR text, return (score_boost, reason, signals_dict).
    signals_dict keys: has_fssai, has_mrp, has_manufacturer, has_net_qty,
                       has_consumer_care, has_date_batch, has_country,
                       has_ingredients, has_nutrition_only, is_marketing_only
    """
    if not text:
        return 0, "", {}

    has_ingredients_raw  = bool(_INGREDIENTS_OCR_SIGNAL.search(text))
    has_nutrition_only   = bool(_NUTRITION_ONLY_SIGNAL.search(text)) and not has_ingredients_raw

    signals = {
        "has_fssai":          bool(_FSSAI_OCR_SIGNAL.search(text)),
        "has_mrp":            bool(_MRP_OCR_SIGNAL.search(text)),
        "has_manufacturer":   bool(_MFR_OCR_SIGNAL.search(text)),
        "has_net_qty":        bool(_NET_QTY_OCR_SIGNAL.search(text)),
        "has_consumer_care":  bool(_CONSUMER_CARE_OCR_SIGNAL.search(text)),
        "has_date_batch":     bool(_DATE_BATCH_OCR_SIGNAL.search(text)),
        "has_country":        bool(_COUNTRY_OCR_SIGNAL.search(text)),
        "has_ingredients":    has_ingredients_raw,        # ingredient list heading detected
        "has_nutrition_only": has_nutrition_only,         # pure nutrition table (not ingredients)
        "is_marketing_only":  False,
    }

    # ── Text density signal ───────────────────────────────────────────────────
    word_count = len(text.split())
    has_dense_text = word_count >= 40
    signals["has_dense_text"] = has_dense_text
    signals["word_count"] = word_count

    # ── FSSAI + licence number combo ─────────────────────────────────────────
    # A 14-digit number near FSSAI/LIC.NO text = actual FSSAI licence number.
    # This is the most critical compliance datapoint → absolute highest priority.
    #
    # OCR quirks handled:
    #   • OCR reads "10014022002711" as "1001 4022 0027 11" (spaces between groups)
    #   • OCR reads "LIC. NO." as "LIC NO" or "LIC.NO." or "L1C. NO."
    #   • FSSAI logo may be unreadable cursive but LIC.NO is always printed clearly
    #
    # Strategy: check both strict (no spaces) AND relaxed (spaces/hyphens OK).
    #   Also: if LIC.NO is present even without the word FSSAI → set has_fssai=True.

    # Strict: 14 contiguous digits starting with non-zero
    _FSSAI_STRICT_RE  = re.compile(r"[1-9]\d{13}")
    # Relaxed: 14 digits with optional spaces/hyphens (OCR spacing artefacts)
    _FSSAI_SPACED_RE  = re.compile(
        r"[1-9]"                            # first digit (non-zero)
        r"(?:\d[\s\-]?){3}"                 # digits 2-4 (with optional gap)
        r"(?:\d[\s\-]?){4}"                 # digits 5-8
        r"(?:\d[\s\-]?){4}"                 # digits 9-12
        r"\d\d"                             # digits 13-14
    )
    # LIC.NO detector (even without word FSSAI in text)
    _LIC_NO_RE = re.compile(
        r"L\.?I\.?C\.?\s*N[O0]\.?|"
        r"LIC(?:ENCE|ENSE)?\s*N[O0]\.?|"
        r"LICENCE\s*N[O0]|LICENSE\s*N[O0]",
        re.IGNORECASE,
    )

    has_lic_no     = bool(_LIC_NO_RE.search(text))
    has_strict_num = bool(_FSSAI_STRICT_RE.search(text))
    has_spaced_num = bool(_FSSAI_SPACED_RE.search(text))
    has_any_num    = has_strict_num or has_spaced_num

    # If LIC.NO is present, treat as FSSAI even if the word FSSAI wasn't OCR'd
    if has_lic_no:
        signals["has_fssai"] = True

    has_fssai_with_number = signals["has_fssai"] and has_any_num
    # Also: LIC.NO + number alone is definitive (no need for the word FSSAI)
    if has_lic_no and has_any_num:
        has_fssai_with_number = True

    signals["has_fssai_with_number"] = has_fssai_with_number

    compliance_count = sum(
        1 for k, v in signals.items()
        if k not in ("is_marketing_only", "has_nutrition_only", "has_dense_text",
                     "word_count", "has_fssai_with_number") and v
    )

    # Mark as marketing-only if marketing patterns appear but zero compliance signals
    if compliance_count == 0 and bool(_MARKETING_OCR_ONLY.search(text)):
        signals["is_marketing_only"] = True

    boost = 0
    parts: list[str] = []

    # ── PRIORITY 1: FSSAI licence number visible ──────────────────────────────
    # Image shows "FSSAI Lic. No. 12345678901234" → absolute must-include.
    # Extra +70 on top of base FSSAI +80 = total +150 for FSSAI+number image.
    if has_fssai_with_number:
        boost += 150
        parts.append("FSSAI LICENCE NUMBER visible (+150) — HIGHEST PRIORITY")
    elif signals["has_fssai"]:
        boost += 80
        parts.append("FSSAI text detected (+80)")

    # ── PRIORITY 2: Dense text = back label / ingredient panel ───────────────
    # Images with 40+ OCR words are almost always back labels or ingredient lists.
    # These are more valuable than a front-of-pack image.
    if has_dense_text:
        boost += 60
        parts.append(f"DENSE TEXT: {word_count} words detected — back label/ingredient panel (+60)")
    elif word_count >= 20:
        boost += 25
        parts.append(f"MODERATE TEXT: {word_count} words detected (+25)")

    # Individual compliance signals
    if signals["has_mrp"]:
        boost += 35
        parts.append("MRP detected (+35)")
    if signals["has_manufacturer"]:
        boost += 35
        parts.append("Manufacturer/packer text (+35)")
    if signals["has_net_qty"]:
        boost += 30
        parts.append("Net quantity text (+30)")
    if signals["has_ingredients"]:
        boost += 45
        parts.append("Ingredient heading detected (+45)")
    if signals["has_consumer_care"]:
        boost += 20
        parts.append("Consumer care info (+20)")
    if signals["has_date_batch"]:
        boost += 20
        parts.append("Batch/date info (+20)")
    if signals["has_country"]:
        boost += 15
        parts.append("Country of origin (+15)")
    if signals["is_marketing_only"]:
        boost -= 40
        parts.append("Confirmed marketing-only content (-40)")

    reason = "; ".join(parts) if parts else ""
    return boost, reason, signals




async def _run_thumb_ocr_batch(candidates: list[dict]) -> None:
    """
    Download thumbnails for ALL candidates concurrently, then OCR in parallel.

    SPEED OPTIMIZATIONS vs old sequential version:
    1. Concurrent HTTP downloads (asyncio.gather) — all images download at once
    2. Parallel OCR via ThreadPoolExecutor (2 workers) — ~2x OCR throughput
    3. Smaller thumbnail (300px) — faster download + faster OCR, still detects signals
    4. Early-exit: once FSSAI+MRP+manufacturer+net_qty all confirmed, skip remaining OCR
    5. Cap at top-12 by compliance_score — bottom images very unlikely to be selected

    Mutates each image dict in-place with ocr_score, ocr_reason, ocr_signals,
    compliance_score.
    """
    import httpx
    from concurrent.futures import ThreadPoolExecutor

    _UA = (
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
    )

    # Cap candidates — bottom of list scored very low, not worth OCR'ing
    work_list = [c for c in candidates if c.get("compliance_score", 0) > -50][:12]
    if not work_list:
        return

    # ── Step 1: Build thumbnail URLs (300px — fast download, enough for signal detect) ──
    def _thumb_url(url: str) -> str:
        u = re.sub(r"_SL\d{3,4}_", "_SL300_", url)
        u = re.sub(r"_SS\d{2,3}_", "_SL300_", u)
        u = re.sub(r"h_\d{3,4},q_\d+,w_\d{3,4}", "h_300,q_75,w_300", u)
        return u

    # ── Step 2: Download ALL thumbnails concurrently ──────────────────────────
    async def _fetch(session: httpx.AsyncClient, img: dict) -> tuple[dict, bytes | None]:
        url = img.get("url", "")
        if not url:
            return img, None
        try:
            r = await session.get(_thumb_url(url), timeout=6.0)
            if r.status_code == 200 and len(r.content) >= 1500:
                return img, r.content
        except Exception:
            pass
        return img, None

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA},
        follow_redirects=True,
        timeout=8.0,
    ) as session:
        fetch_results: list[tuple[dict, bytes | None]] = await asyncio.gather(
            *[_fetch(session, img) for img in work_list],
            return_exceptions=False,
        )

    # ── Step 3: OCR downloaded thumbnails, in parallel, with early exit ───────
    # Track which compliance signals are already confirmed — once all found, stop
    ALL_SIGNALS = {"has_fssai", "has_mrp", "has_manufacturer", "has_net_qty"}
    found_signals: set[str] = set()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for img, content in fetch_results:
            # Early exit: all high-value signals already confirmed
            if found_signals >= ALL_SIGNALS:
                break

            if content is None:
                continue

            try:
                ocr_text = await loop.run_in_executor(
                    pool, _ocr_thumbnail_sync, content
                )
                if not ocr_text:
                    continue

                boost, reason, signals = _score_ocr_signals(ocr_text)

                img["ocr_score"] = boost
                img["ocr_reason"] = reason
                img["ocr_signals"] = signals
                img["ocr_preview_text"] = ocr_text[:300]
                img["compliance_score"] = (
                    img.get("url_score", 0)
                    + img.get("visual_score", 0)
                    + boost
                )

                # Track confirmed signals for early exit
                for sig in ALL_SIGNALS:
                    if signals.get(sig):
                        found_signals.add(sig)

            except Exception:
                continue



async def score_and_select_images(
    images: list[dict],
    max_for_ocr: int = 4,
    enable_visual: bool = True,
    enable_thumb_ocr: bool = True,
) -> list[dict]:
    """
    Full three-stage compliance image selection pipeline.

    Stage 1  — URL/metadata scoring (ALL images, fast, no downloads)
    Stage 2  — PIL visual scoring (top-12 by URL score, downloads thumbnails)
    Stage 2.5— Thumbnail OCR pre-scan (top-8 by combined score)
               ** CORE FIX: actually reads text in images to find FSSAI before
               selecting the final set — not just URL/pixel heuristics **
    Stage 3  — Diversity/duplicate filter

    Each returned image has:
      compliance_score  (int)   — total weighted score
      score_reason      (str)   — human-readable explanation
      classification    (dict)  — category/confidence/is_packaging
      phash             (str)   — perceptual hash for duplicate detection
      ocr_signals       (dict)  — per-image compliance signals detected
    """
    import httpx

    if not images:
        return []

    # ── Stage 1: URL/metadata scoring (ALL images) ────────────────────────────
    for img in images:
        url = img.get("url", "")
        alt = img.get("alt", "")
        source = img.get("source", "")
        collector_score = img.get("score", 0)

        url_score, url_reasons = _url_metadata_score(url, alt, source, collector_score)
        clf = classify_image(url, alt)

        img["classification"] = clf
        img["url_score"] = url_score
        img["url_reasons"] = url_reasons
        img["visual_score"] = 0
        img["visual_reason"] = ""
        img["ocr_score"] = 0
        img["ocr_reason"] = ""
        img["ocr_signals"] = {}
        img["phash"] = ""
        img["compliance_score"] = url_score

    # Sort by URL score to identify top candidates for visual + OCR analysis
    images.sort(key=lambda x: -x["url_score"])

    # ── Stage 2: PIL visual scoring (thumbnails, concurrent) ─────────────────
    # Download thumbnail versions and run visual metrics (variance, edges, etc.)
    visual_candidates = [img for img in images if img["url_score"] > -50][:12]

    if enable_visual and visual_candidates:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; SM-G981B) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.6367.82 Mobile Safari/537.36"
                )},
                follow_redirects=True,
                timeout=8.0,
            ) as session:
                visual_tasks = [
                    _download_and_score_visual(session, img["url"])
                    for img in visual_candidates
                ]
                visual_results = await asyncio.gather(*visual_tasks, return_exceptions=True)

            for img, result in zip(visual_candidates, visual_results):
                if isinstance(result, tuple) and len(result) == 3:
                    v_score, v_reason, phash = result
                    img["visual_score"] = v_score
                    img["visual_reason"] = v_reason
                    img["phash"] = phash
                    img["compliance_score"] = img["url_score"] + v_score
        except Exception:
            pass

    # Re-sort by URL+visual combined score before OCR pre-scan
    images.sort(key=lambda x: -x["compliance_score"])

    # ── Stage 2.5: Thumbnail OCR pre-scan (ALL non-rejected candidates) ─────────
    # CORE FIX: Run fast EasyOCR on thumbnail of every non-hard-rejected candidate
    # BEFORE final selection. Images with FSSAI/compliance text get boosted scores.
    #
    # We scan ALL candidates (not just top-8) because a back-label containing FSSAI
    # may score low on URL heuristics alone and appear at position 10-15.
    # Missing it would defeat the entire purpose of this pipeline.
    if enable_thumb_ocr:
        thumb_ocr_candidates = [img for img in images if img["compliance_score"] > -50]
        if thumb_ocr_candidates:
            try:
                await _run_thumb_ocr_batch(thumb_ocr_candidates)
            except Exception:
                pass  # OCR pre-scan is best-effort — selection continues without it

    # Final sort: URL + visual + OCR signals combined
    images.sort(key=lambda x: -x["compliance_score"])

    # Build combined reason string for each image
    for img in images:
        reasons = []
        clf = img.get("classification", {})
        cat = clf.get("category", "unknown")
        if cat not in ("unknown", "non_packaging"):
            reasons.insert(0, f"Category: {cat}")
        if img.get("url_reasons"):
            reasons.extend(img["url_reasons"])
        if img.get("visual_reason"):
            reasons.append(img["visual_reason"])
        if img.get("ocr_reason"):
            reasons.append(img["ocr_reason"])
        img["score_reason"] = "; ".join(reasons) if reasons else "General product image"

    # ── Stage 3: Coverage-optimized selection ─────────────────────────────────
    # DEDUP FIRST: strip any images with duplicate URLs before selection.
    # This prevents the same image appearing twice (e.g. same URL from two
    # different collectors: colorImages_js and altImages_dom).
    seen_before_select: set[str] = set()
    deduped_images: list[dict] = []
    for img in images:
        url_key = img.get("url", "").split("?")[0]  # ignore query params
        if url_key and url_key not in seen_before_select:
            seen_before_select.add(url_key)
            deduped_images.append(img)

    # Greedy algorithm: maximises compliance coverage, FSSAI-first, front_package capped at 1
    selected = _coverage_optimized_select(deduped_images, max_for_ocr)

    # ── Guarantee exactly max_for_ocr images (if enough exist) ──────────────
    # If the greedy algorithm returned fewer images than requested (can happen
    # when many near-duplicates exist), fill remaining slots from the deduped
    # pool in score order.
    if len(selected) < max_for_ocr:
        selected_urls = {img.get("url", "") for img in selected}
        for img in deduped_images:
            if len(selected) >= max_for_ocr:
                break
            if img.get("url", "") not in selected_urls and img.get("compliance_score", 0) > -30:
                selected_urls.add(img["url"])
                selected.append(img)

    return selected[:max_for_ocr]  # hard cap — never return more than requested


def select_packaging_images(images: list[dict], max_for_ocr: int = 4) -> list[dict]:
    """
    SYNCHRONOUS wrapper — used for backwards compatibility when visual scoring
    is not needed (fast path, URL-only scoring).

    For the full async pipeline, call score_and_select_images() directly.
    """
    if not images:
        return []

    for img in images:
        url = img.get("url", "")
        alt = img.get("alt", "")
        source = img.get("source", "")
        collector_score = img.get("score", 0)

        url_score, url_reasons = _url_metadata_score(url, alt, source, collector_score)
        clf = classify_image(url, alt)
        img["classification"] = clf
        img["compliance_score"] = url_score
        img["url_score"] = url_score
        img["score_reason"] = "; ".join(url_reasons) if url_reasons else "General product image"
        img["phash"] = ""

    images.sort(key=lambda x: -x["compliance_score"])
    selected = _coverage_optimized_select(images, max_for_ocr)

    return selected
