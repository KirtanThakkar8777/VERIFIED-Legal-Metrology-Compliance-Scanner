"""
url_scanner/adapters/amazon.py — Amazon.in product data extractor.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "net content",
    "mrp", "maximum retail", "best before", "expiry",
    "consumer care", "contact information", "address", "legal",
    "item weight", "unit count", "number of items",
    "item form", "size", "tablets", "capsules", "ingredients",
    "allergen", "nutritional", "storage",
]

_SKIP_KEYS = {
    "asin", "best sellers rank", "customer reviews", "date first available",
    "feedback", "department", "colour", "color", "flavour", "flavor",
    "style", "pattern", "finish",
}


def _is_compliance(key: str) -> bool:
    kl = key.lower()
    if any(s in kl for s in _SKIP_KEYS):
        return False
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
    """
    Return normalized product dict for Amazon page.
    """
    result: dict = {"source": "Amazon"}

    # ── Product name ──────────────────────────────────────────────────────────
    for sel in [("span", {"id": "productTitle"}), ("h1", {}), ("span", {"class": "a-size-large"})]:
        el = soup.find(sel[0], sel[1])
        if el:
            result["product_name"] = el.get_text(" ", strip=True)
            break

    # ── All compliance table rows ─────────────────────────────────────────────
    rows = _table_rows(soup)

    # Amazon detail bullets (key: value in <li> elements)
    for el_id in ["detailBullets_feature_div", "productDetails_detailBullets_sections1",
                  "productDetails_techSpec_section_1"]:
        el = soup.find(id=el_id)
        if el:
            for li in el.find_all("li"):
                t = li.get_text(" ", strip=True)
                if ":" in t:
                    k, _, v = t.partition(":")
                    rows[k.strip()] = v.strip()

    # Keep only compliance-relevant rows
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # ── Map Amazon-specific fields to standard keys ───────────────────────────
    # Amazon stores manufacturer as "Manufacturer" or "Manufacturer Contact Information"
    for mfr_key in ["Manufacturer", "Manufacturer Contact Information"]:
        val = rows.get(mfr_key, "")
        if val and not result.get("manufacturer_raw"):
            result["manufacturer_raw"] = val[:300]

    for packer_key in ["Packer Contact Information", "Packer"]:
        val = rows.get(packer_key, "")
        if val and not result.get("packer_raw"):
            result["packer_raw"] = val[:300]

    for brand_key in ["Brand", "Item model number"]:
        val = rows.get(brand_key, "")
        if val and not result.get("brand"):
            result["brand"] = val[:100]

    # ── Feature bullets ───────────────────────────────────────────────────────
    bullets = soup.find(id="feature-bullets")
    if bullets:
        result["feature_bullets"] = [
            li.get_text(" ", strip=True) for li in bullets.find_all("li")
        ][:8]

    # ── Description ───────────────────────────────────────────────────────────
    desc = soup.find(id="productDescription")
    if desc:
        result["description"] = desc.get_text("\n", strip=True)[:600]

    # ── Price / MRP ───────────────────────────────────────────────────────────
    for pid in ["corePriceDisplay_desktop_feature_div", "priceblock_ourprice", "priceblock_dealprice"]:
        el = soup.find(id=pid)
        if el:
            result["price_block"] = el.get_text(" ", strip=True)[:200]
            break

    # MRP regex fallback
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s₹Rs.]*\s*([\d,]+\.?\d{0,2})", full_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")

    # ── Full-text hidden fields ───────────────────────────────────────────────
    # Country of Origin
    coo = re.search(
        r"Country\s+of\s+Origin\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s{2,}|\||$|\n)",
        full_text, re.IGNORECASE
    )
    if coo:
        result["country_of_origin"] = coo.group(1).strip()

    # FSSAI
    fssai = re.search(r"\b([1-9]\d{13})\b", full_text)
    if fssai:
        result["fssai"] = fssai.group(1)

    # Best Before / Shelf Life
    shelf = re.search(r"(?:shelf\s*life|best\s*before|expiry)[:\s]*([^\n|]{4,60})", full_text, re.IGNORECASE)
    if shelf:
        result["best_before"] = shelf.group(1).strip()

    # Mfg Date
    mfg = re.search(r"(?:Mfg\.?\s*Date|Date\s*of\s*Manufacture)[:\s]+([^\n|]{4,30})", full_text, re.IGNORECASE)
    if mfg:
        result["mfg_date"] = mfg.group(1).strip()

    # Consumer care phone
    phone = re.search(r"(?:1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10})", full_text)
    if phone:
        result["consumer_care_phone"] = phone.group(0).strip()

    return result
