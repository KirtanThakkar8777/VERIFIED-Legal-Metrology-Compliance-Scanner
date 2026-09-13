"""
url_scanner/adapters/flipkart.py — Flipkart product data extractor.

Flipkart is a fully JS-rendered React app. The static HTML has almost no
product data. Key data sources (in priority order):
  1. window.__PRELOADED_STATE__ / pageDataV4 JSON blobs (embedded in <script>)
  2. <table> rows in the product specifications section
  3. Regex on full_text + json_text as final fallback

All 8 mandatory PCR 2011 §6 fields are targeted:
  manufacturer/importer, net_quantity, mfg_date, expiry_date,
  mrp, consumer_care, country_of_origin, fssai
"""
from __future__ import annotations
import json
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "net content", "mrp", "maximum retail",
    "best before", "expiry", "shelf life", "consumer care", "contact", "address",
    "item weight", "ingredients", "allergen", "nutritional", "storage",
    "legal", "size", "unit count",
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


def _extract_balanced_json(s: str) -> str:
    """Extract a balanced JSON object from the start of string s."""
    depth = 0
    in_string = False
    escape = False
    for i, c in enumerate(s):
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[: i + 1]
    return ""


def _extract_json_blobs(html: str) -> list[dict]:
    """Extract all JSON objects from <script> tags that contain product data."""
    results = []
    script_pattern = re.compile(r"<script[^>]*>([\s\S]*?)</script>", re.IGNORECASE)
    for m in script_pattern.finditer(html):
        content = m.group(1).strip()
        if not content or len(content) < 100:
            continue
        for prefix in [
            r"window\.__PRELOADED_STATE__\s*=\s*",
            r"window\.pageDataV4\s*=\s*",
            r"window\._fn\s*=\s*",
        ]:
            pm = re.search(prefix + r"(\{[\s\S]+)", content)
            if pm:
                try:
                    json_str = _extract_balanced_json(pm.group(1))
                    if json_str:
                        obj = json.loads(json_str)
                        results.append(obj)
                except Exception:
                    pass
        if content.startswith("{") and len(content) > 200:
            try:
                obj = json.loads(content)
                if isinstance(obj, dict) and len(obj) > 3:
                    results.append(obj)
            except Exception:
                pass
    return results


def _flatten_json_text(obj, depth: int = 0) -> str:
    """Flatten all string values from nested JSON into a single text blob."""
    if depth > 10:
        return ""
    parts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            parts.append(str(k))
            parts.append(_flatten_json_text(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            parts.append(_flatten_json_text(item, depth + 1))
    elif isinstance(obj, str):
        return obj
    elif isinstance(obj, (int, float)):
        return str(obj)
    return " ".join(filter(None, parts))


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    """
    Return normalized product dict for Flipkart page.
    Works on BOTH static HTML and browser-rendered HTML.
    """
    result: dict = {"source": "Flipkart"}
    html = str(soup)

    # ── Product name ──────────────────────────────────────────────────────────
    for sel in [
        ("span", {"class": re.compile(r"B_NuCI|yhB1nd|VU-ZEz|x-product-title", re.I)}),
        ("h1", {}),
    ]:
        el = soup.find(sel[0], sel[1])
        if el:
            result["product_name"] = el.get_text(" ", strip=True)
            break

    # ── Embedded JSON blobs ────────────────────────────────────────────────────
    json_blobs = _extract_json_blobs(html)
    json_text = ""
    for blob in json_blobs:
        json_text += " " + _flatten_json_text(blob)

    # Combined text corpus
    all_text = full_text + "\n" + json_text

    # ── Table rows ─────────────────────────────────────────────────────────────
    rows = _table_rows(soup)
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # ── Flipkart spec / description section divs ───────────────────────────────
    spec_texts: list[str] = []
    # Flipkart uses many div class patterns for specs (they change with releases)
    for div in soup.find_all("div", class_=re.compile(
        r"_2RngUh|_1s_Smc|_25bRXJ|_1UhVsV|_3Fm-hO|_1YokD2|_3-wDH0|"
        r"X3BRps|_2o-xpa|_1mXcCf|rgWa7D|pqs9Lf|Izz52n|col-9-12|_2b00jl|_1fgeW|_3l-3pn",
        re.I
    )):
        text = div.get_text("\n", strip=True)
        if any(kw in text.lower() for kw in _COMPLIANCE_KEYS):
            spec_texts.append(text[:600])

    # Also check sections/articles
    for section in soup.find_all(["section", "article"]):
        text = section.get_text("\n", strip=True)
        if any(kw in text.lower() for kw in ["manufacturer", "fssai", "country of origin", "net quantity"]):
            spec_texts.append(text[:800])

    spec_combined = "\n".join(spec_texts)
    all_text = all_text + "\n" + spec_combined

    # ── MAP FIELDS ─────────────────────────────────────────────────────────────

    # Manufacturer / Packer / Importer — table first then regex
    for mfr_key in ["Manufacturer", "Marketed by", "Manufactured by", "Manufacturer Name",
                     "Manufacturer Details", "Packer", "Packed by", "Importer"]:
        val = rows.get(mfr_key, "")
        if val and not result.get("manufacturer_raw"):
            result["manufacturer_raw"] = val[:300]
            break
    if not result.get("manufacturer_raw"):
        mfr = re.search(
            r"(?:Manufactured|Marketed|Packed|Imported)\s*(?:and\s+\w+\s*)?[Bb]y\s*[:\-]?\s*([^\n]{5,150})",
            all_text
        )
        if mfr:
            result["manufacturer_raw"] = mfr.group(1).strip()[:300]

    for pkr_key in ["Packer", "Packed by", "Packer Contact Information"]:
        val = rows.get(pkr_key, "")
        if val and not result.get("packer_raw"):
            result["packer_raw"] = val[:300]
            break

    for imp_key in ["Importer", "Imported by", "Importer Details"]:
        val = rows.get(imp_key, "")
        if val and not result.get("importer_raw"):
            result["importer_raw"] = val[:300]
            break

    # Net Quantity
    for qty_key in ["Net Quantity", "Net Weight", "Net Content", "Item Weight",
                     "Unit Count", "Net Vol", "Net Volume"]:
        val = rows.get(qty_key, "")
        if val and not result.get("net_quantity"):
            result["net_quantity"] = val[:80]
            break
    if not result.get("net_quantity"):
        qty = re.search(
            r"Net\s*(?:Quantity|Weight|Content|Vol(?:ume)?)\s*[:\-]?\s*"
            r"([\d.,]+\s*(?:kg|g|ml|l(?:iter|itre)?|gm|gms)\b[^,\n]{0,30})",
            all_text, re.IGNORECASE
        )
        if qty:
            result["net_quantity"] = qty.group(1).strip()

    # Country of Origin
    for coo_key in ["Country of Origin", "Country Of Origin", "Origin", "Made In"]:
        val = rows.get(coo_key, "")
        if val:
            result["country_of_origin"] = val.strip()[:50]
            break
    if not result.get("country_of_origin"):
        coo = re.search(
            r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s{2,}|\||$|\n)",
            all_text, re.IGNORECASE
        )
        if coo:
            result["country_of_origin"] = coo.group(1).strip()

    # FSSAI
    for fssai_key in ["FSSAI Lic. No", "FSSAI", "FSSAI Licence No", "FSSAI License No",
                       "Fssai Lic No"]:
        val = rows.get(fssai_key, "")
        if val:
            m = re.search(r"[1-9]\d{13}", re.sub(r"\s", "", val))
            if m:
                result["fssai"] = m.group(0)
                break
    if not result.get("fssai"):
        fssai_m = re.search(
            r"(?:fssai|lic(?:ence|ense)?\s*no|lic\.\s*no)[^0-9]{0,30}([1-9]\d{13})",
            all_text, re.IGNORECASE
        )
        if fssai_m:
            result["fssai"] = fssai_m.group(1)
        else:
            bare = re.search(r"\b([1-9]\d{13})\b", all_text)
            if bare:
                result["fssai"] = bare.group(1)

    # Best Before / Shelf Life
    for shelf_key in ["Best Before", "Shelf Life", "Expiry", "Best Before (From Mfg Date)"]:
        val = rows.get(shelf_key, "")
        if val:
            result["best_before"] = val.strip()[:80]
            break
    if not result.get("best_before"):
        shelf = re.search(
            r"(?:shelf\s*life|best\s*before|expiry)[:\s]*([^\n|]{4,80})",
            all_text, re.IGNORECASE
        )
        if shelf:
            result["best_before"] = shelf.group(1).strip()

    # MRP
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s]*(?:Rs\.?|INR)?\s*([\d,]+\.?\d{0,2})",
                       all_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")

    # Mfg Date
    mfg = re.search(
        r"(?:Mfg\.?\s*Date?|Date\s*of\s*Manufacture?|Manufactured\s*On)\s*[:\-]?\s*([^\n|]{4,30})",
        all_text, re.IGNORECASE
    )
    if mfg:
        result["mfg_date"] = mfg.group(1).strip()

    # Consumer Care
    phone_m = re.search(r"(1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10}|0\d{9,10})", all_text)
    if phone_m:
        result["consumer_care_phone"] = phone_m.group(0).strip()
    email_m = re.search(r"[\w.+\-]+@[\w\-]+\.[\w.]+", all_text)
    if email_m:
        result["consumer_care_email"] = email_m.group(0)

    # ── Flipkart CDN images ────────────────────────────────────────────────────
    # Flipkart uses rukminim CDN; URLs appear in both static and rendered HTML
    cdn_imgs = re.findall(
        r"https?://rukminim\d*\.flixcart\.com/image/[^\s\"'<>\\]+\.(?:jpg|jpeg|png|webp)",
        html, re.IGNORECASE
    )
    # Also check JSON text (Flipkart embeds image URLs in JSON state)
    if not cdn_imgs:
        cdn_imgs = re.findall(
            r"https?://rukminim\d*\.flixcart\.com/image/[^\s\"'<>\\]+\.(?:jpg|jpeg|png|webp)",
            json_text, re.IGNORECASE
        )
    if cdn_imgs:
        seen_imgs: set[str] = set()
        upgraded: list[str] = []
        for u in cdn_imgs:
            # Upgrade to 832px resolution
            u_up = re.sub(r"/\d{2,4}/\d{2,4}/", "/832/832/", u)
            if u_up not in seen_imgs:
                seen_imgs.add(u_up)
                upgraded.append(u_up)
        result["product_image_urls"] = upgraded[:20]

    return result
