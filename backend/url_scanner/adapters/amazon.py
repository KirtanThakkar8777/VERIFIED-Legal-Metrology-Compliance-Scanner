"""
url_scanner/adapters/amazon.py — Amazon.in product data extractor.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "net content",
    "mrp", "maximum retail", "best before", "expiry", "shelf life",
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

    # Amazon detail bullets — all known section IDs
    for el_id in [
        "detailBullets_feature_div",
        "productDetails_detailBullets_sections1",
        "productDetails_techSpec_section_1",
        "productDetails_feature_div",
        "productDetails_db_sections",
    ]:
        el = soup.find(id=el_id)
        if el:
            for li in el.find_all("li"):
                t = li.get_text(" ", strip=True)
                if ":" in t:
                    k, _, v = t.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if k and v and k not in rows:
                        rows[k] = v

    # Keep only compliance-relevant rows (stored as-is for reference)
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # ── Map Amazon-specific fields to standard keys ───────────────────────────

    # Manufacturer
    for mfr_key in ["Manufacturer", "Manufacturer Contact Information", "Brand Contact"]:
        val = rows.get(mfr_key, "")
        if val and not result.get("manufacturer_raw"):
            result["manufacturer_raw"] = val[:300]
            break

    # Packer
    for packer_key in ["Packer Contact Information", "Packer", "Packer Contact"]:
        val = rows.get(packer_key, "")
        if val and not result.get("packer_raw"):
            result["packer_raw"] = val[:300]
            break

    # Importer
    for imp_key in ["Importer", "Importer Contact Information"]:
        val = rows.get(imp_key, "")
        if val and not result.get("importer_raw"):
            result["importer_raw"] = val[:300]
            break

    # Brand
    for brand_key in ["Brand", "Item model number"]:
        val = rows.get(brand_key, "")
        if val and not result.get("brand"):
            result["brand"] = val[:100]
            break

    # Country of Origin — from table rows first, then regex fallback
    for coo_key in ["Country of Origin", "Country Of Origin", "Origin", "Made in"]:
        val = rows.get(coo_key, "")
        if val:
            result["country_of_origin"] = val.strip()[:50]
            break
    if not result.get("country_of_origin"):
        coo = re.search(
            r"Country\s+of\s+Origin\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s{2,}|\||$|\n)",
            full_text, re.IGNORECASE
        )
        if coo:
            result["country_of_origin"] = coo.group(1).strip()

    # Net Quantity
    for qty_key in ["Net Quantity", "Net Weight", "Net Content", "Item Weight", "Unit Count"]:
        val = rows.get(qty_key, "")
        if val:
            result["net_quantity"] = val.strip()[:60]
            break

    # Best Before / Shelf Life
    for shelf_key in ["Best Before", "Shelf Life", "Expiry"]:
        val = rows.get(shelf_key, "")
        if val:
            result["best_before"] = val.strip()[:80]
            break
    if not result.get("best_before"):
        shelf = re.search(
            r"(?:shelf\s*life|best\s*before|expiry)[:\s]*([^\n|]{4,60})",
            full_text, re.IGNORECASE
        )
        if shelf:
            result["best_before"] = shelf.group(1).strip()

    # FSSAI — from table rows first, then regex on full_text
    for fssai_key in ["FSSAI Lic. No", "FSSAI", "FSSAI Licence No", "Fssai Lic No"]:
        val = rows.get(fssai_key, "")
        if val:
            m = re.search(r"[1-9]\d{13}", re.sub(r"\s", "", val))
            if m:
                result["fssai"] = m.group(0)
                break
    if not result.get("fssai"):
        # 14-digit number near FSSAI/LIC.NO keyword
        fssai_m = re.search(
            r"(?:fssai|lic(?:ence|ense)?\s*no|lic\.\s*no)[^0-9]{0,30}([1-9]\d{13})",
            full_text, re.IGNORECASE
        )
        if fssai_m:
            result["fssai"] = fssai_m.group(1)
        else:
            # Standalone 14-digit number (last resort — very likely FSSAI on food product pages)
            fssai_bare = re.search(r"\b([1-9]\d{13})\b", full_text)
            if fssai_bare:
                result["fssai"] = fssai_bare.group(1)

    # ── Feature bullets ───────────────────────────────────────────────────────
    bullets = soup.find(id="feature-bullets")
    if bullets:
        result["feature_bullets"] = [
            li.get_text(" ", strip=True) for li in bullets.find_all("li")
        ][:8]
    # Scan feature bullets for compliance fields not in table
    for bullet in result.get("feature_bullets", []):
        bl_lower = bullet.lower()
        if not result.get("manufacturer_raw") and any(k in bl_lower for k in ("mfg.", "manufactured by", "mkt. by", "marketed by")):
            result["manufacturer_raw"] = bullet[:300]
        if not result.get("packer_raw") and "packed by" in bl_lower:
            result["packer_raw"] = bullet[:300]
        if not result.get("country_of_origin") and ("made in" in bl_lower or "country of origin" in bl_lower):
            m = re.search(r"(?:made in|country of origin)[:\s]+([A-Za-z]{3,30})", bullet, re.IGNORECASE)
            if m:
                result["country_of_origin"] = m.group(1).strip()

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

    # MRP regex fallback on full_text
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s\u20b9Rs.]*\s*([\d,]+\.?\d{0,2})", full_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")

    # ── Mfg Date ──────────────────────────────────────────────────────────────
    mfg = re.search(r"(?:Mfg\.?\s*Date|Date\s*of\s*Manufacture)[:\s]+([^\n|]{4,30})", full_text, re.IGNORECASE)
    if mfg:
        result["mfg_date"] = mfg.group(1).strip()

    # ── Consumer care phone ───────────────────────────────────────────────────
    # Amazon packer_raw often contains toll-free number e.g. "...India, 18002027080"
    for src_field in ["packer_raw", "manufacturer_raw", "importer_raw"]:
        src = result.get(src_field, "")
        phone_m = re.search(r"(1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10})", src)
        if phone_m and not result.get("consumer_care_phone"):
            result["consumer_care_phone"] = phone_m.group(0).strip()
            break
    if not result.get("consumer_care_phone"):
        phone = re.search(r"(1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10})", full_text)
        if phone:
            result["consumer_care_phone"] = phone.group(0).strip()

    return result
