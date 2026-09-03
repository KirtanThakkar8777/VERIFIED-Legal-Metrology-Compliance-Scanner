"""
url_scanner/intelligence/data_fusion.py
Merge ALL sources into one normalized product model.

Source priority (highest to lowest):
  1. OCR entities from packaging images (physical label = ground truth)
  2. Webpage adapter data (HTML/JSON-LD from product page)
  3. Structured data (schema.org / OpenGraph)

RULE: Never overwrite a real value with "" or "Not Detected".
      Only fill missing fields — never replace present values.
"""
from __future__ import annotations
import re
from .address_parser import parse_address
from .country_detector import detect_country, classify_product_origin
from .data_normalizer import normalize_quantity, normalize_price


# ── Helper: pick first non-empty value ────────────────────────────────────────

def _first(*values) -> str:
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return ""


# ── Entity builders ────────────────────────────────────────────────────────────

def _build_entity_from_ocr(
    role: str,
    ocr_entities: dict,
    adapter_data: dict,
    combined_text: str,
) -> dict:
    """
    Build manufacturer/packer/importer entity, OCR-first.
    """
    from .address_parser import parse_address
    from .country_detector import detect_country

    # OCR entity keys
    name_key = f"{role}_name"
    addr_key = f"{role}_address"
    raw_key = f"{role}_raw"

    # Get from OCR entities first
    ocr_name = ocr_entities.get(name_key, "")
    ocr_addr = ocr_entities.get(addr_key, "")
    ocr_raw = ocr_entities.get(raw_key, "")

    # Fallback to adapter data
    web_raw = adapter_data.get(raw_key, "")

    # Determine best raw text
    raw = _first(ocr_raw, web_raw)
    name = _first(ocr_name, adapter_data.get(name_key, ""))
    address = _first(ocr_addr, adapter_data.get(addr_key, ""))

    # If we have name+address but no raw, compose raw
    if not raw and (name or address):
        raw = "\n".join(filter(None, [name, address]))

    # Parse address for structured fields
    if raw:
        parsed = parse_address(raw)
        if not name:
            name = parsed.get("company", "")
        if not address:
            lines = [
                parsed.get("address_line1", ""),
                parsed.get("address_line2", ""),
                parsed.get("city", ""),
                f"{parsed.get('state', '')} - {parsed.get('pincode', '')}".strip(" -"),
                parsed.get("country", ""),
            ]
            address = "\n".join(l for l in lines if l)
    else:
        parsed = {}

    # Country detection
    detect_text = raw or address or ""
    if detect_text:
        cd = detect_country(detect_text)
    else:
        cd = {"country": "", "confidence": 0, "signals": []}

    source = "ocr" if (ocr_name or ocr_addr or ocr_raw) else ("webpage" if web_raw else "none")

    return {
        "name": name,
        "address_raw": raw,
        "address_structured": address,
        "parsed": parsed,
        "country": cd["country"],
        "country_confidence": cd["confidence"],
        "country_signals": cd["signals"],
        "source": source,
    }


def _extract_regex_fields(text: str) -> dict:
    """Extract fields from combined text that adapters may have missed."""
    result = {}

    # Country of origin
    coo = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|$|\||\,)", text, re.IGNORECASE)
    if coo:
        result["country_of_origin"] = coo.group(1).strip()

    # FSSAI
    fssai = re.search(r"\b([1-9]\d{13})\b", text)
    if fssai:
        result["fssai"] = fssai.group(1)

    # Brand
    brand = re.search(r"\bBrand\s*[:\-]\s*([A-Za-z][A-Za-z\s&]{2,40}?)(?:\n|$|\|)", text, re.IGNORECASE)
    if brand:
        result["brand"] = brand.group(1).strip()

    # Consumer care phone
    phone = re.search(r"(?:1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10})", text)
    if phone:
        result["consumer_care_phone"] = phone.group(0).strip()

    # Email
    email = re.search(r"[\w.+\-]+@[\w\-]+\.[\w.]+", text)
    if email:
        result["consumer_care_email"] = email.group(0)

    # Best before / Expiry
    bb = re.search(r"(?:best\s*before|shelf\s*life|expiry)[:\s]*([^\n|]{4,60})", text, re.IGNORECASE)
    if bb:
        result["best_before"] = bb.group(1).strip()

    # Mfg date
    mfg = re.search(r"(?:Mfg\.?\s*Date?|Date\s*of\s*Manufacture?|Manufactured\s*On)\s*[:\-]?\s*([^\n|]{4,30})", text, re.IGNORECASE)
    if mfg:
        result["mfg_date"] = mfg.group(1).strip()

    return result


# ── Main fusion function ───────────────────────────────────────────────────────

def fuse(
    adapter_data: dict,
    ocr_text: str = "",
    structured: dict | None = None,
    ocr_entities: dict | None = None,
) -> dict:
    """
    Merge all sources into a normalized product model.

    Parameters:
        adapter_data: Platform-specific extracted data (webpage)
        ocr_text: Raw combined OCR text from all packaging images
        structured: JSON-LD / OpenGraph structured data
        ocr_entities: Pre-parsed entities from entity_extractor (highest priority)
    """
    structured = structured or {}
    ocr_entities = ocr_entities or {}

    # ── Build combined text for regex fallbacks ────────────────────────────────
    web_text_parts = []
    for k, v in adapter_data.items():
        if isinstance(v, str) and v:
            web_text_parts.append(v)
        elif isinstance(v, list):
            web_text_parts.extend([str(x) for x in v if x])
    web_combined = "\n".join(web_text_parts)

    # All text combined (OCR takes priority in entity extraction,
    # but combined is used for regex fallbacks on web data)
    all_text = "\n".join(filter(None, [web_combined, ocr_text]))

    # Regex fallbacks on web text
    web_regex = _extract_regex_fields(web_combined)
    ocr_regex = _extract_regex_fields(ocr_text) if ocr_text else {}

    # ── Product fields ─────────────────────────────────────────────────────────
    product_name = _first(
        adapter_data.get("product_name"),
        structured.get("name"),
        structured.get("og_title"),
    )
    brand = _first(
        ocr_entities.get("brand"),
        adapter_data.get("brand"),
        web_regex.get("brand"),
        structured.get("brand"),
    )

    # ── Commerce fields (webpage is authoritative) ─────────────────────────────
    mrp_raw = _first(
        adapter_data.get("mrp"),
        structured.get("price"),
        ocr_entities.get("mrp"),
    )
    selling_price_raw = adapter_data.get("selling_price", "")
    seller = _first(adapter_data.get("seller"), structured.get("seller"))

    # ── Quantity (OCR package > webpage) ──────────────────────────────────────
    website_qty = _first(
        adapter_data.get("Unit Count"),
        adapter_data.get("Item Weight"),
        adapter_data.get("net_quantity"),
        adapter_data.get("quantity"),
        adapter_data.get("Selected Quantity"),
    )
    package_qty = _first(
        ocr_entities.get("net_quantity"),
        ocr_regex.get("net_quantity"),
    )

    # ── Build manufacturer/packer/importer entities ────────────────────────────
    manufacturer = _build_entity_from_ocr("manufacturer", ocr_entities, adapter_data, all_text)
    packer = _build_entity_from_ocr("packer", ocr_entities, adapter_data, all_text)
    importer = _build_entity_from_ocr("importer", ocr_entities, adapter_data, all_text)

    # ── Country of Origin ──────────────────────────────────────────────────────
    declared_coo = _first(
        ocr_entities.get("country_of_origin"),
        adapter_data.get("country_of_origin"),
        ocr_regex.get("country_of_origin"),
        web_regex.get("country_of_origin"),
    )

    # Detect country from manufacturer address if declared not found
    origin_detected = ""
    origin_conf = 0
    if manufacturer["country"] and manufacturer["country"] != "Unknown":
        origin_detected = manufacturer["country"]
        origin_conf = manufacturer["country_confidence"]
    elif declared_coo:
        cd = detect_country(declared_coo)
        origin_detected = cd["country"]
        origin_conf = cd["confidence"]

    # ── Regulatory ────────────────────────────────────────────────────────────
    fssai = _first(
        ocr_entities.get("fssai"),
        adapter_data.get("fssai"),
        ocr_regex.get("fssai"),
        web_regex.get("fssai"),
    )
    barcode = _first(
        ocr_entities.get("barcode"),
        ocr_entities.get("barcode_ocr"),
    )
    barcode_type = ocr_entities.get("barcode_type", "")
    qr_code = ocr_entities.get("qr_code", "")
    batch_no = _first(ocr_entities.get("batch_no"), adapter_data.get("batch_no"))

    # ── Dates ─────────────────────────────────────────────────────────────────
    mfg_date = _first(
        ocr_entities.get("mfg_date"),
        adapter_data.get("mfg_date"),
        ocr_regex.get("mfg_date"),
        web_regex.get("mfg_date"),
    )
    expiry_date = _first(
        ocr_entities.get("expiry_date"),
        adapter_data.get("best_before"),
        ocr_regex.get("best_before"),
        web_regex.get("best_before"),
    )

    # ── Consumer care ─────────────────────────────────────────────────────────
    cc_raw = _first(ocr_entities.get("consumer_care_raw"), adapter_data.get("consumer_care"))
    cc_phone = _first(
        ocr_entities.get("consumer_care_phone"),
        adapter_data.get("consumer_care_phone"),
        web_regex.get("consumer_care_phone"),
    )
    cc_email = _first(
        ocr_entities.get("consumer_care_email"),
        web_regex.get("consumer_care_email"),
    )

    # ── Food-specific ─────────────────────────────────────────────────────────
    ingredients = _first(ocr_entities.get("ingredients"), adapter_data.get("ingredients", ""))
    allergen_info = _first(ocr_entities.get("allergen_info"), adapter_data.get("allergen_info", ""))
    storage_instructions = _first(
        ocr_entities.get("storage_instructions"),
        adapter_data.get("storage_instructions", ""),
    )
    veg_status = ocr_entities.get("veg_status", "")

    # ── Normalize quantity ─────────────────────────────────────────────────────
    qty_for_norm = package_qty or website_qty
    qty_normalized = normalize_quantity(qty_for_norm) if qty_for_norm else None

    # ── Normalize MRP ─────────────────────────────────────────────────────────
    mrp_normalized = normalize_price(mrp_raw) if mrp_raw else None

    # ── Build final model ──────────────────────────────────────────────────────
    model = {
        "product": {
            "name": product_name,
            "brand": brand,
            "category": adapter_data.get("category", ""),
            "variant": adapter_data.get("variant", ""),
            "description": _first(
                adapter_data.get("description"),
                structured.get("og_description"),
            )[:400] if (adapter_data.get("description") or structured.get("og_description")) else "",
            "sku": _first(adapter_data.get("sku"), structured.get("sku")),
            "veg_status": veg_status,
        },
        "commerce": {
            "platform": adapter_data.get("source", "Unknown"),
            "seller": seller,
            "mrp_raw": mrp_raw,
            "mrp_normalized": mrp_normalized,
            "selling_price_raw": selling_price_raw,
            "currency": "INR",
        },
        "manufacturer": manufacturer,
        "packer": packer,
        "importer": importer,
        "origin": {
            "declared_country": declared_coo,
            "detected_country": origin_detected,
            "confidence": origin_conf,
        },
        "quantity": {
            "website_raw": website_qty,
            "package_raw": package_qty,
            "normalized": qty_normalized,
        },
        "dates": {
            "mfg_date": mfg_date,
            "packing_date": "",
            "expiry_date": expiry_date,
        },
        "consumer_care": {
            "raw": cc_raw,
            "phone": cc_phone,
            "email": cc_email,
        },
        "regulatory": {
            "fssai": fssai,
            "barcode": barcode,
            "barcode_type": barcode_type,
            "qr_code": qr_code,
            "batch_no": batch_no,
            "declarations": _extract_declarations(all_text),
        },
        "ingredients": ingredients,
        "allergen_info": allergen_info,
        "storage_instructions": storage_instructions,
        "images": adapter_data.get("images", []),
        "ocr_text": ocr_text,
        "adapter_data": adapter_data,
        "structured": structured,
        "ocr_entities": ocr_entities,
    }

    # ── Product classification (Domestic / Imported) ───────────────────────────
    model["product_classification"] = classify_product_origin(
        manufacturer_country=model["manufacturer"].get("country", ""),
        importer_country=model["importer"].get("country", ""),
        declared_country=model["origin"].get("declared_country", ""),
    )

    return model


def _extract_declarations(text: str) -> list[str]:
    patterns = [
        r"(?:Statutory\s+warning[^\n.]{5,100})",
        r"(?:FSSAI[^\n.]{5,80})",
        r"(?:Vegetarian|Non[\s\-]?Vegetarian)[^\n.]{0,60}",
        r"(?:Certified\s+Organic[^\n.]{0,60})",
        r"(?:Lic\.?\s*No\.[^\n.]{5,40})",
        r"(?:All\s+weights[^\n.]{5,100})",
        r"(?:Weigh\s+before\s+buying[^\n.]{0,60})",
    ]
    results = []
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            results.append(m.group(0).strip())
    return results[:5]
