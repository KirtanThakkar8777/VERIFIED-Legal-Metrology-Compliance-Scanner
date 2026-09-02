"""
scraper/service.py — HTTP + BeautifulSoup4 product text extractor.
Uses mobile User-Agent to bypass Amazon anti-bot detection.
Supports Amazon.in, Flipkart, Meesho, Myntra, and generic pages.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

# Mobile UA bypasses Amazon's bot detection (desktop UA gets blocked)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

TIMEOUT = 20.0

# Compliance-relevant table key fragments (case-insensitive match)
COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "net content",
    "mrp", "maximum retail", "price", "best before", "expiry",
    "consumer care", "contact information", "address", "legal",
    "item weight", "item form", "package weight", "size",
    "number of items", "unit count", "tablets", "capsules",
]


def _is_compliance_key(key: str) -> bool:
    kl = key.lower()
    return any(kw in kl for kw in COMPLIANCE_KEYS)


def _detect_marketplace(url: str) -> str:
    ul = url.lower()
    if "amazon" in ul:
        return "Amazon"
    if "flipkart" in ul:
        return "Flipkart"
    if "meesho" in ul:
        return "Meesho"
    if "myntra" in ul:
        return "Myntra"
    if "nykaa" in ul:
        return "Nykaa"
    if "bigbasket" in ul:
        return "BigBasket"
    return "Unknown"


def _clean_asin_url(url: str) -> str:
    """Normalise Amazon URL to clean /dp/ASIN form to avoid tracking params."""
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        return f"https://www.amazon.in/dp/{m.group(1)}?th=1&psc=1"
    return url


# ── Table/list row extraction ─────────────────────────────────────────────────

def _extract_table_rows(soup: BeautifulSoup) -> dict[str, str]:
    """Extract key-value pairs from ALL tables on the page."""
    data: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            k = cells[0].get_text(" ", strip=True).strip(":")
            v = cells[1].get_text(" ", strip=True)
            if k and v:
                data[k] = v
    return data


def _extract_detail_bullets(soup: BeautifulSoup) -> dict[str, str]:
    """Extract key:value pairs from detail bullet lists (Amazon detailBullets)."""
    data: dict[str, str] = {}
    for el_id in [
        "detailBullets_feature_div",
        "productDetails_detailBullets_sections1",
        "productDetails_techSpec_section_1",
    ]:
        el = soup.find(id=el_id)
        if not el:
            continue
        for li in el.find_all("li"):
            text = li.get_text(" ", strip=True)
            if ":" in text:
                k, _, v = text.partition(":")
                data[k.strip()] = v.strip()
    return data


# ── Amazon extractor ──────────────────────────────────────────────────────────

def _extract_amazon(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (product_name, compliance_text) from an Amazon product page."""

    # Product title
    product_name = ""
    for sel in [("span", {"id": "productTitle"}), ("h1", {}), ("span", {"class": "a-size-large"})]:
        el = soup.find(sel[0], sel[1])
        if el:
            product_name = el.get_text(" ", strip=True)
            break

    # Gather all table rows
    all_rows = _extract_table_rows(soup)
    all_rows.update(_extract_detail_bullets(soup))

    # Feature bullets (product highlights)
    bullets_text = ""
    bullets = soup.find(id="feature-bullets")
    if bullets:
        lines = [li.get_text(" ", strip=True) for li in bullets.find_all("li")]
        bullets_text = "\n".join(lines[:8])

    # Product description
    desc_text = ""
    desc = soup.find(id="productDescription")
    if desc:
        desc_text = desc.get_text("\n", strip=True)[:800]

    # MRP / price
    price_text = ""
    for price_id in [
        "corePriceDisplay_desktop_feature_div",
        "apex_desktop_newAccordionRow_priceBlock_id",
        "priceblock_ourprice",
        "priceblock_dealprice",
    ]:
        el = soup.find(id=price_id)
        if el:
            price_text = el.get_text(" ", strip=True)[:200]
            break

    # Also scan all text for price patterns if not found via ID
    if not price_text:
        full = soup.get_text(" ", strip=True)
        m = re.search(
            r"M\.?R\.?P\.?\s*[:\s₹Rs.]*\s*([\d,]+\.?\d{0,2})", full, re.IGNORECASE
        )
        if m:
            price_text = f"MRP: Rs. {m.group(1)}"

    # ── Scan full page text for fields Amazon hides in JS-rendered sections ───
    full_text = soup.get_text(" ", strip=True)

    # Country of Origin (often in product details or A+ content)
    coo_match = re.search(
        r"Country\s+of\s+Origin\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s*\n|\s{2,}|$|\|)",
        full_text, re.IGNORECASE
    )
    if coo_match:
        all_rows["Country of Origin"] = coo_match.group(1).strip()

    # FSSAI — 14-digit number anywhere on page
    fssai_match = re.search(r"\b([1-9]\d{13})\b", full_text)
    if fssai_match:
        all_rows["FSSAI Lic No"] = fssai_match.group(1)

    # Best Before / Shelf Life
    shelf_match = re.search(
        r"(?:shelf\s*life|best\s*before|expiry)[:\s]*([^\n\|]{4,60})",
        full_text, re.IGNORECASE
    )
    if shelf_match:
        all_rows["Best Before"] = shelf_match.group(1).strip()

    # Mfg Date
    mfg_match = re.search(
        r"(?:Mfg\.?\s*Date|Date\s*of\s*Manufacture|Manufacturing\s*Date)[:\s]+([^\n\|]{4,30})",
        full_text, re.IGNORECASE
    )
    if mfg_match:
        all_rows["Mfg Date"] = mfg_match.group(1).strip()

    # ── Build compliance-only text (no marketing fluff) ──────────────────────
    lines = [f"Product: {product_name}"] if product_name else []

    # Add only compliance-relevant table rows — skip generic marketing fields
    SKIP_MARKETING = {
        "asin", "best sellers rank", "customer reviews", "date first available",
        "feedback", "department", "colour", "color", "flavour", "flavor",
        "material", "style", "pattern", "finish", "brand"
    }
    for k, v in all_rows.items():
        kl = k.lower().strip()
        if any(skip in kl for skip in SKIP_MARKETING):
            continue
        if _is_compliance_key(k) or k in ("Country of Origin", "FSSAI Lic No", "Best Before", "Mfg Date"):
            # Cap each value at 300 chars
            lines.append(f"{k}: {v[:300]}")

    if price_text:
        lines.append(f"\nMRP: {price_text[:200]}")

    # Source context so compliance engine knows this is an e-commerce listing
    lines.append(f"\nSource: Amazon.in e-commerce listing (online marketplace)")
    lines.append("Note: Manufacturing date, expiry, and FSSAI number may only appear on physical packaging — verify with seller for full compliance.")

    compliance_text = "\n".join(lines)

    # ── Fallback: if we got almost nothing, search full text briefly ──────────
    if len(compliance_text) < 200:
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        compliance_text = soup.get_text("\n", strip=True)[:5000]

    return product_name, compliance_text


# ── Flipkart extractor ────────────────────────────────────────────────────────

def _extract_flipkart(soup: BeautifulSoup) -> tuple[str, str]:
    product_name = ""
    h1 = soup.find("h1")
    if h1:
        product_name = h1.get_text(" ", strip=True)

    text_parts = [product_name]

    all_rows = _extract_table_rows(soup)
    for k, v in all_rows.items():
        if _is_compliance_key(k):
            text_parts.append(f"{k}: {v}")

    for cls in ["X3BRps", "_2o-xpa", "_1mXcCf", "rgWa7D", "dGKuTl", "_14cfVK"]:
        for el in soup.find_all("div", class_=cls):
            text_parts.append(el.get_text("\n", strip=True))

    return product_name, "\n\n".join(filter(None, text_parts))


# ── Generic extractor ────────────────────────────────────────────────────────

def _extract_generic(soup: BeautifulSoup) -> tuple[str, str]:
    product_name = ""
    h1 = soup.find("h1")
    if h1:
        product_name = h1.get_text(" ", strip=True)

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text_parts = [product_name]
    all_rows = _extract_table_rows(soup)
    for k, v in all_rows.items():
        if _is_compliance_key(k):
            text_parts.append(f"{k}: {v}")

    main = soup.find("main") or soup.find("article") or soup.body
    page_text = main.get_text("\n", strip=True) if main else soup.get_text("\n", strip=True)
    text_parts.append(page_text[:5000])

    return product_name, "\n\n".join(filter(None, text_parts))


# ── Public API ─────────────────────────────────────────────────────────────────

async def fetch_and_extract(url: str) -> dict:
    """
    Fetch URL and extract product compliance text.
    Returns: {extracted_text, product_name, marketplace, raw_html_length}
    """
    marketplace = _detect_marketplace(url)

    # Clean Amazon URLs to avoid tracking params that trigger bot detection
    if marketplace == "Amazon":
        url = _clean_asin_url(url)

    async with httpx.AsyncClient(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    raw_html = resp.text

    if len(raw_html) < 5000:
        raise ValueError(
            f"Page returned only {len(raw_html)} bytes — likely bot-blocked. "
            "Try opening the URL in your browser first, then paste the text manually."
        )

    soup = BeautifulSoup(raw_html, "lxml")

    if marketplace == "Amazon":
        product_name, text = _extract_amazon(soup)
    elif marketplace == "Flipkart":
        product_name, text = _extract_flipkart(soup)
    else:
        product_name, text = _extract_generic(soup)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return {
        "extracted_text": text,
        "product_name": product_name,
        "marketplace": marketplace,
        "raw_html_length": len(raw_html),
    }
