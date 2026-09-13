"""
url_scanner/adapters/generic.py
Generic fallback adapter for any e-commerce site.
Works for JioMart, BigBasket, Blinkit, Zepto, Snapdeal, Ajio, TataCliq,
Nykaa, HealthKart, and any other product page.
"""
from __future__ import annotations
import json
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "mrp", "maximum retail",
    "best before", "expiry", "consumer care", "contact", "address",
    "item weight", "ingredients", "allergen", "nutritional", "storage",
    "legal", "declaration", "batch", "lot",
]


def _is_compliance(key: str) -> bool:
    kl = key.lower()
    return any(c in kl for c in _COMPLIANCE_KEYS)


def _table_rows(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            k = cells[0].get_text(" ", strip=True).strip(":")
            v = cells[1].get_text(" ", strip=True)
            if k and v:
                data[k] = v
    return data


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    result: dict = {"source": "Generic"}

    # Product name from h1
    h1 = soup.find("h1")
    if h1:
        result["product_name"] = h1.get_text(" ", strip=True)

    # Try Next.js / embedded JSON data
    for script in soup.find_all("script", id=re.compile(r"__NEXT_DATA__|__NUXT_DATA__")):
        try:
            data = json.loads(script.string or "")
            def _find_product_name(obj, depth=0):
                if depth > 4:
                    return
                if isinstance(obj, dict):
                    if "productName" in obj:
                        result["product_name"] = result.get("product_name") or str(obj["productName"])
                    if "name" in obj and isinstance(obj["name"], str) and len(obj["name"]) > 5:
                        result.setdefault("product_name", obj["name"])
                    if "mrp" in obj:
                        result["mrp"] = str(obj["mrp"])
                    if "brand" in obj and isinstance(obj["brand"], str):
                        result["brand"] = obj["brand"]
                    for v in obj.values():
                        _find_product_name(v, depth + 1)
                elif isinstance(obj, list):
                    for item in obj[:10]:
                        _find_product_name(item, depth + 1)
            _find_product_name(data)
        except Exception:
            pass

    # Try JSON-LD offers.price for MRP
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                offers = data.get("offers", {})
                price = (offers.get("price") if isinstance(offers, dict) else None)
                if price and not result.get("mrp"):
                    result["mrp"] = str(price)
                result.setdefault("product_name", data.get("name", ""))
        except Exception:
            pass

    # Table rows with compliance content
    rows = _table_rows(soup)
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # Map common table row keys to standard fields
    for mfr_key in ["Manufacturer", "Marketed by", "Manufactured by", "Packer", "Manufacturer Name"]:
        if rows.get(mfr_key) and not result.get("manufacturer_raw"):
            result["manufacturer_raw"] = rows[mfr_key][:300]
            break
    for qty_key in ["Net Quantity", "Net Weight", "Net Content", "Item Weight", "Unit Count"]:
        if rows.get(qty_key) and not result.get("net_quantity"):
            result["net_quantity"] = rows[qty_key][:80]
            break
    for coo_key in ["Country of Origin", "Country Of Origin", "Made In"]:
        if rows.get(coo_key) and not result.get("country_of_origin"):
            result["country_of_origin"] = rows[coo_key][:50]
            break

    # Remove scripts/styles for clean text extraction
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # Extract compliance-relevant paragraph and list content
    compliance_paragraphs = []
    for el in soup.find_all(["p", "li", "div", "span"]):
        t = el.get_text(" ", strip=True)
        if len(t) < 20 or len(t) > 600:
            continue
        if any(kw in t.lower() for kw in _COMPLIANCE_KEYS):
            compliance_paragraphs.append(t)
    result["compliance_text"] = "\n".join(compliance_paragraphs[:20])

    # MRP — try explicit label first, then ₹ symbol
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s₹Rs.]*\s*([\d,]+\.?\d{0,2})", full_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")
    elif not result.get("mrp"):
        rupee_m = re.search(r"₹\s*([\d,]+\.?\d{0,2})", full_text)
        if rupee_m:
            candidate = rupee_m.group(1).replace(",", "")
            try:
                if 1 <= float(candidate) <= 100000:
                    result["mrp"] = candidate
                    result["price_block"] = f"₹{candidate}"
            except ValueError:
                pass

    # Net Quantity
    if not result.get("net_quantity"):
        qty = re.search(
            r"Net\s*(?:Quantity|Weight|Content|Vol(?:ume)?)\s*[:\-]?\s*([\d.,]+\s*(?:kg|g|ml|l(?:iter|itre)?|gm|gms)\b[^,\n]{0,30})",
            full_text, re.IGNORECASE
        )
        if qty:
            result["net_quantity"] = qty.group(1).strip()

    # Country of Origin
    if not result.get("country_of_origin"):
        coo = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|$|\||,)",
                        full_text, re.IGNORECASE)
        if coo:
            result["country_of_origin"] = coo.group(1).strip()

    # FSSAI (14-digit number)
    fssai_m = re.search(
        r"(?:fssai|lic(?:ence|ense)?\s*no)[^0-9]{0,30}([1-9]\d{13})",
        full_text, re.IGNORECASE
    )
    if fssai_m:
        result["fssai"] = fssai_m.group(1)
    else:
        bare = re.search(r"\b([1-9]\d{13})\b", full_text)
        if bare:
            result["fssai"] = bare.group(1)

    # Manufacturer
    if not result.get("manufacturer_raw"):
        mfr = re.search(
            r"(?:Manufactured|Marketed|Packed|Processed)\s*(?:and\s+\w+\s*)*[Bb]y\s*[:\-]?\s*([^\n\.]{5,120})",
            full_text
        )
        if mfr:
            result["manufacturer_raw"] = mfr.group(1).strip()

    # Best before
    bb = re.search(r"(?:best\s*before|shelf\s*life|expiry)[:\s]*([^\n|]{4,60})", full_text, re.IGNORECASE)
    if bb:
        result["best_before"] = bb.group(1).strip()

    # Consumer care phone + email
    phone = re.search(r"(?:1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10}|0\d{9,10})", full_text)
    if phone:
        result["consumer_care_phone"] = phone.group(0).strip()
    email = re.search(r"[\w.+\-]+@[\w\-]+\.[\w.]+", full_text)
    if email:
        result["consumer_care_email"] = email.group(0)

    return result
