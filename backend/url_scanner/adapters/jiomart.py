"""
url_scanner/adapters/jiomart.py - JioMart product data extractor.

JioMart is a React/Next.js SPA. Static HTML has no product fields.
Browser-rendered HTML has all fields in a structured spec table.

Key extraction sources:
  1. Product spec table / key-value pairs (Manufacturer, FSSAI, Net Qty, etc.)
  2. JSON-LD structured data
  3. Full-page regex fallbacks on visible text
"""
from __future__ import annotations
import json
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "net content", "mrp", "maximum retail",
    "best before", "expiry", "shelf life", "consumer care", "contact", "address",
    "item weight", "ingredients", "allergen", "nutritional", "storage", "legal",
    "unit count", "batch",
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


def _extract_jiomart_spec_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """
    JioMart renders specs as definition-list style divs or labeled spans.
    Finds all key:value pairs in the page body.
    """
    pairs: dict[str, str] = {}

    # Method 1: Look for divs where first child is a label and second is a value
    for div in soup.find_all(["div", "li", "p"]):
        children = [c for c in div.children if hasattr(c, "get_text")]
        if len(children) == 2:
            k = children[0].get_text(" ", strip=True).strip(": ")
            v = children[1].get_text(" ", strip=True)
            if k and v and len(k) < 60 and k not in pairs:
                pairs[k] = v

    # Method 2: Find strong/b tags followed by sibling text (label: value pattern)
    for el in soup.find_all(["strong", "b", "span", "dt"]):
        key_text = el.get_text(" ", strip=True).rstrip(":")
        if not key_text or len(key_text) > 60:
            continue
        # Get adjacent text (next sibling)
        sibling = el.next_sibling
        while sibling and isinstance(sibling, str) and not sibling.strip():
            sibling = sibling.next_sibling
        if sibling:
            val = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            if val and key_text not in pairs:
                pairs[key_text] = val

    return pairs


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    """
    Return normalized product dict for JioMart page.
    Works on browser-rendered HTML (static has no product data).
    """
    result: dict = {"source": "JioMart"}
    html = str(soup)

    # Product name
    for sel in [
        ("h1", {}),
        ("span", {"class": re.compile(r"product.title|product.name|pdp.title", re.I)}),
    ]:
        el = soup.find(sel[0], sel[1])
        if el:
            result["product_name"] = el.get_text(" ", strip=True)
            break

    # JSON-LD structured data
    json_ld_text = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                if data.get("@type") in ("Product", "ItemPage", "FoodProduct"):
                    result.setdefault("product_name", data.get("name", ""))
                    result.setdefault("brand", (data.get("brand") or {}).get("name", "") if isinstance(data.get("brand"), dict) else str(data.get("brand", "")))
                    result.setdefault("description", str(data.get("description", ""))[:400])
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        result.setdefault("mrp", str(offers.get("price", "")))
                json_ld_text += " " + json.dumps(data)
        except Exception:
            pass

    # Table rows
    rows = _table_rows(soup)

    # JioMart spec key-value pairs
    spec_pairs = _extract_jiomart_spec_pairs(soup)
    rows.update(spec_pairs)  # merge (table rows win for same key)

    # Add compliance rows to result
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # Combined text for regex fallbacks
    all_text = full_text + "\n" + json_ld_text

    # ── MAP FIELDS ─────────────────────────────────────────────────────────────

    # Manufacturer / Packer / Importer
    for mfr_key in ["Manufacturer Name", "Manufacturer", "Marketed by", "Manufactured by",
                     "Manufacturer Details", "Packer", "Packed by", "Manufacturer Address"]:
        val = rows.get(mfr_key, "")
        if val and not result.get("manufacturer_raw"):
            # Combine name + address if both available
            addr_key = "Manufacturer Address" if "Name" in mfr_key else mfr_key + " Address"
            addr = rows.get(addr_key, "") or rows.get("Manufacturer Address", "")
            result["manufacturer_raw"] = (val + (", " + addr if addr and addr not in val else ""))[:300]
            break
    if not result.get("manufacturer_raw"):
        mfr = re.search(
            r"(?:Manufacturer(?:\s+Name)?|Manufactured\s+by|Marketed\s+by|Packed\s+by)\s*[:\-]?\s*([^\n]{5,150})",
            all_text
        )
        if mfr:
            result["manufacturer_raw"] = mfr.group(1).strip()[:300]

    for pkr_key in ["Packer", "Packed by", "Packer Name"]:
        val = rows.get(pkr_key, "")
        if val and not result.get("packer_raw"):
            result["packer_raw"] = val[:300]
            break

    for imp_key in ["Importer", "Imported by", "Importer Name"]:
        val = rows.get(imp_key, "")
        if val and not result.get("importer_raw"):
            result["importer_raw"] = val[:300]
            break

    # Net Quantity
    for qty_key in ["Net Quantity", "Net Weight", "Net Content", "Item Weight",
                     "Unit Count", "Net Vol", "Net Volume", "Qty"]:
        val = rows.get(qty_key, "")
        if val and not result.get("net_quantity"):
            result["net_quantity"] = val[:80]
            break
    if not result.get("net_quantity"):
        qty = re.search(
            r"Net\s*(?:Quantity|Weight|Content|Vol(?:ume)?)\s*[:\-]?\s*([\d.,]+\s*(?:kg|g|ml|l(?:iter|itre)?|gm|gms)\b[^,\n]{0,30})",
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
                       "Fssai Lic No", "FSSAI Lic No", "Licence No"]:
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
    for shelf_key in ["Best Before", "Shelf Life", "Expiry", "Best Before (From Mfg Date)",
                       "Best Before Date"]:
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

    # MRP — JioMart shows MRP as selling price with ₹ symbol, not explicit "MRP" label
    # Try table rows first
    for mrp_key in ["MRP", "Maximum Retail Price", "Price", "Selling Price"]:
        val = rows.get(mrp_key, "")
        if val:
            m = re.search(r"[\d,]+\.?\d{0,2}", val)
            if m:
                result["mrp"] = m.group(0).replace(",", "")
                break

    # Try JSON-LD offers.price
    if not result.get("mrp"):
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                offers = data.get("offers", {}) if isinstance(data, dict) else {}
                price = offers.get("price") if isinstance(offers, dict) else None
                if price and str(price).replace(".", "").isdigit():
                    result["mrp"] = str(price)
                    break
            except Exception:
                pass

    # Try ₹ price from visible text (JioMart shows "₹104" prominently)
    if not result.get("mrp"):
        price_m = re.search(
            r"(?:M\.?R\.?P\.?|Price|only)\s*[:\s]*[₹Rs.]*\s*([\d,]+\.?\d{0,2})",
            all_text, re.IGNORECASE
        )
        if price_m:
            result["mrp"] = price_m.group(1).replace(",", "")
        else:
            # Last resort: first ₹ amount in text
            rupee_m = re.search(r"₹\s*([\d,]+\.?\d{0,2})", all_text)
            if rupee_m:
                candidate = rupee_m.group(1).replace(",", "")
                # Sanity check: plausible product price 1 to 100000
                try:
                    if 1 <= float(candidate) <= 100000:
                        result["mrp"] = candidate
                        result["price_block"] = f"₹{candidate}"
                except ValueError:
                    pass

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

    # Ingredients — require explicit heading to avoid matching product descriptions
    ing_m = re.search(
        r"(?:^|\n)\s*(?:Ingredients?|Composition)\s*[:\-]\s*(.{20,600}?)(?:\n\n|\n[A-Z]|\Z)",
        all_text, re.IGNORECASE | re.DOTALL
    )
    if ing_m:
        result["ingredients"] = ing_m.group(1).strip()[:500]

    # JioMart CDN images from rendered HTML
    # Filter: only keep product images (jio-pd or images paths), skip theme/icon assets
    cdn_imgs = re.findall(
        r"https?://(?:cdn\d*\.jiomartjcp\.com|cdn\.jiomart\.com|jiostatic\.com)"
        r"/[^\s\"'<>\\]+\.(?:jpg|jpeg|png|webp)",
        html, re.IGNORECASE
    )
    if cdn_imgs:
        seen_jio: set[str] = set()
        upgraded: list[str] = []
        for u in cdn_imgs:
            # Skip theme/icon assets (not product images)
            if "/theme/assets/" in u or "/icons/" in u or "/logo" in u.lower():
                continue
            # Get original quality image
            orig = re.sub(r"/t\.\w+\([^)]*\)/", "/original/", u)
            orig = re.sub(r"\?.*$", "", orig)
            if orig not in seen_jio:
                seen_jio.add(orig)
                upgraded.append(orig)
        result["product_image_urls"] = upgraded[:20]

    return result

