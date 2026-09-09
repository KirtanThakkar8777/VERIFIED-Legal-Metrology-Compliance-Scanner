"""
url_scanner/adapters/myntra.py — Myntra product data extractor.

Myntra is a React/Redux app. Static HTML has almost nothing rendered —
all product data is in window.__REDUX_STATE__ and window.MYNTRA JavaScript
global variables. We parse those to extract all available structured data.

Image URLs are in the Redux state and img tags. Product images follow the
pattern: assets.myntassets.com/assets/images/YEAR/MONTH/DAY/hash.ext
"""
from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup


# Myntra CDN base for product images
_CDN_BASE = "https://assets.myntassets.com"


def _extract_redux_state(html: str) -> dict:
    """Parse window.__REDUX_STATE__ from Myntra page HTML."""
    m = re.search(r"window\.__REDUX_STATE__\s*=\s*(\{)", html)
    if not m:
        return {}

    start = m.start(1)
    depth = 0
    end = start
    in_string = False
    escape = False
    chunk = html[start: start + 250_000]  # 250KB max

    for i, ch in enumerate(chunk):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = start + i + 1
                break

    if end <= start:
        return {}

    try:
        return json.loads(html[start:end])
    except Exception:
        return {}


def _extract_product_images_from_html(html: str) -> list[str]:
    """
    Extract ONLY product packaging images from Myntra page.
    Product images are at: assets/images/YEAR/MONTH(name)/DAY/hash.ext
    UI icons are at: assets/images/retaillabs/... or have short hash IDs.
    """
    images: list[str] = []
    seen: set[str] = set()

    # Pattern for actual product images (date-based path, NOT retaillabs)
    product_img_pattern = re.compile(
        r"https?://(?:assets\.myntassets\.com|assets\.myntra\.com)/assets/images/"
        r"(\d{4})/(\w+)/(\d+)/([A-Za-z0-9_]+\.(?:jpg|jpeg|png|webp))",
        re.IGNORECASE,
    )

    for m in product_img_pattern.finditer(html):
        year, month, day, filename = m.group(1), m.group(2), m.group(3), m.group(4)
        # Skip retaillabs images (UI elements)
        if "retaillabs" in m.group(0):
            continue
        # Build high-res URL
        hires = f"{_CDN_BASE}/h_1440,q_75,w_1080/v1/assets/images/{year}/{month}/{day}/{filename}"
        if hires not in seen:
            seen.add(hires)
            images.append(hires)

    return images


def _extract_product_data_from_scripts(html: str) -> dict:
    """
    Extract product data from Myntra page scripts.
    Myntra stores product data in window.MYNTRA and embedded JSON.
    """
    result: dict = {}

    # Extract product name from og:title or twitter:title (most reliable)
    og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if og_title:
        name = og_title.group(1).strip()
        # Remove " | Myntra" suffix
        name = re.sub(r'\s*\|\s*Myntra\s*$', '', name, flags=re.IGNORECASE).strip()
        # Extract product part: "Buy XYZ from ABC at Rs..."  
        buy_m = re.match(r'Buy\s+(.+?)\s*(?:\s*-\s*\w+\s*for\s+|\s*from\s+|\s*at\s+Rs)', name, re.IGNORECASE)
        if buy_m:
            result['product_name'] = buy_m.group(1).strip()
        elif name and name.lower() not in ('default', ''):
            result['product_name'] = name

    # Twitter title fallback
    if not result.get('product_name'):
        tw_title = re.search(r'<meta[^>]+name="twitter:title"[^>]+content="([^"]+)"', html, re.IGNORECASE)
        if tw_title:
            name = tw_title.group(1).strip()
            name = re.sub(r'\s*\|\s*Myntra\s*$', '', name).strip()
            if name and name.lower() != 'default':
                result['product_name'] = name

    # Title tag fallback
    if not result.get('product_name'):
        title_m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if title_m:
            name = title_m.group(1).strip()
            buy_m = re.match(r'Buy\s+(.+?)\s*(?:\s*-\s*|\s*from\s+|\s*at\s+)', name, re.IGNORECASE)
            if buy_m:
                result['product_name'] = buy_m.group(1).strip()

    # Extract from scripts
    # Look for brand, mrp in the big script
    brand_m = re.search(r'"brandName"\s*:\s*"([^"]{2,100})"', html)
    if brand_m:
        result['brand'] = brand_m.group(1)

    mrp_m = re.search(r'"mrp"\s*:\s*"?(\d+)"?', html)
    if mrp_m:
        result['mrp'] = mrp_m.group(1)

    size_m = re.search(r'"brandSize"\s*:\s*"([^"]{1,50})"', html)
    if size_m:
        size_val = size_m.group(1).strip()
        result['brand_size'] = size_val
        # Parse net quantity from size
        qty_m = re.match(r'(\d+(?:\.\d+)?)\s*(g|gm|gram|kg|ml|l|litre|liter|count|pc|tab)', size_val, re.IGNORECASE)
        if qty_m:
            result['net_quantity'] = qty_m.group(0).lower()

    # Country of origin
    coo_m = re.search(r'"countryOfOrigin"\s*:\s*"([^"]{2,50})"', html)
    if coo_m:
        val = coo_m.group(1)
        if val.lower() not in ('country of origin', ''):
            result['country_of_origin'] = val

    # Manufacturer info from productDetails
    pd_matches = re.findall(
        r'"productDetails"\s*:\s*(\[[\s\S]{0,4000}?\])\s*,\s*"(?:styleId|productId|brand|name)"',
        html,
    )
    for pd_json in pd_matches:
        try:
            items = json.loads(pd_json)
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = (item.get('title') or '').strip().lower()
                content = (item.get('content') or '').strip()
                if not content or content.lower() in ('n/a', 'na', ''):
                    continue
                if 'manufacturer' in title:
                    result.setdefault('manufacturer_raw', content)
                elif 'packer' in title:
                    result.setdefault('packer_raw', content)
                elif 'importer' in title:
                    result.setdefault('importer_raw', content)
                elif 'country' in title and 'origin' in title:
                    result.setdefault('country_of_origin', content)
                elif 'fssai' in title or 'lic' in title:
                    result.setdefault('fssai', content)
                elif 'ingredient' in title:
                    result.setdefault('ingredients', content)
                elif 'allergen' in title:
                    result.setdefault('allergen_info', content)
                elif 'storage' in title:
                    result.setdefault('storage_instructions', content)
                elif 'net' in title and ('weight' in title or 'qty' in title or 'quantity' in title):
                    result.setdefault('net_quantity', content)
        except Exception:
            continue

    # Seller
    seller_m = re.search(r'"seller"\s*:\s*"([^"]{3,100})"', html)
    if seller_m:
        result['seller'] = seller_m.group(1)
    else:
        # Visible text fallback
        seller_v = re.search(r'Seller\s*:\s*([A-Z][A-Za-z\s&]{2,60})(?:$|\n|Add)', html)
        if seller_v:
            result['seller'] = seller_v.group(1).strip()

    # FSSAI from page text
    fssai_m = re.search(r'\b([1-9]\d{13})\b', html)
    if fssai_m:
        result.setdefault('fssai', fssai_m.group(1))

    return result


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    """
    Main Myntra adapter entry point.
    """
    result: dict = {"source": "Myntra"}

    html = str(soup)

    # 1. Extract product data from scripts (og:title, productDetails, scripts)
    script_data = _extract_product_data_from_scripts(html)
    result.update(script_data)

    # 2. Fallback product name from h1
    if not result.get("product_name") or result["product_name"].lower() == "default":
        h1 = soup.find("h1")
        if h1:
            result["product_name"] = h1.get_text(" ", strip=True)

    # 3. Extract product images (from HTML, not redux)
    product_images = _extract_product_images_from_html(html)
    if product_images:
        result["product_image_urls"] = product_images[:8]

    # 4. Additional data from visible text
    # MRP
    if not result.get("mrp"):
        mrp_m = re.search(r"MRP\s*[₹Rs.]*\s*(\d[\d,]*\.?\d{0,2})", full_text, re.IGNORECASE)
        if mrp_m:
            result["mrp"] = mrp_m.group(1).replace(",", "")

    # Country of origin fallback from text
    if not result.get("country_of_origin"):
        coo_m = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|$|\|)", full_text, re.IGNORECASE)
        if coo_m:
            result["country_of_origin"] = coo_m.group(1).strip()

    result["source"] = "Myntra"
    return result
