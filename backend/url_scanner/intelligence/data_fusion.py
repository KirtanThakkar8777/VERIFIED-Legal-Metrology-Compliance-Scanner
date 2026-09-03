"""
url_scanner/intelligence/data_fusion.py
Merge webpage adapter data + OCR text into a single normalized product model.
OCR text takes priority for label-specific fields.
Webpage data takes priority for commerce fields.
"""
from __future__ import annotations
import re
from .address_parser import parse_address
from .country_detector import detect_country, classify_product_origin
from .data_normalizer import normalize_quantity, normalize_price


_MFR_PATTERNS = [
    re.compile(
        r"(?:Manufactured|Marketed|Packed|Processed|Imported|Distributed)\s*"
        r"(?:and\s+\w+(?:\s+\w+)?\s*)?(?:by|for)\s*[:\-]?\s*([^\n\.]{5,150})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Manufacturer|Packer|Importer|Marketer)\s*[:\-]\s*([^\n\.]{5,150})",
        re.IGNORECASE,
    ),
    re.compile(
        r"Manufacturer\s+Contact\s+Information\s*[:\-]?\s*([^\n]{10,200})",
        re.IGNORECASE,
    ),
]

_PACKER_PATTERNS = [
    re.compile(r"(?:Packed|Packer)\s*(?:and\s+\w+)?\s*[Bb]y\s*[:\-]?\s*([^\n\.]{5,120})", re.IGNORECASE),
    re.compile(r"Packer\s+Contact\s+Information\s*[:\-]?\s*([^\n]{10,200})", re.IGNORECASE),
]

_IMPORTER_PATTERNS = [
    re.compile(r"(?:Imported|Importer)\s*(?:by|for)?\s*[:\-]?\s*([^\n\.]{5,120})", re.IGNORECASE),
]

_FSSAI_PATTERN = re.compile(r"\b([1-9]\d{13})\b")
_BARCODE_PATTERN = re.compile(r"\b(\d{12,14})\b")
_BATCH_PATTERN = re.compile(r"(?:Batch|Lot|Batch\s*No\.?|Lot\s*No\.?)\s*[:\-#]?\s*([A-Z0-9\-/]{3,20})", re.IGNORECASE)
_EXPIRY_PATTERN = re.compile(
    r"(?:Best\s*Before|Expiry|Exp\.?|Use\s*By|BBD)\s*[:\-]?\s*([^\n|]{3,40})",
    re.IGNORECASE,
)
_MFG_DATE_PATTERN = re.compile(
    r"(?:Mfg\.?\s*Date?|Date\s*of\s*Manufacture?|Manufactured\s*On)\s*[:\-]?\s*([^\n|]{3,30})",
    re.IGNORECASE,
)
_CONSUMER_CARE_PATTERN = re.compile(
    r"(?:Consumer\s*Care|Customer\s*Care|Helpline|Toll[\s\-]*Free)\s*[:\-]?\s*([^\n]{5,120})",
    re.IGNORECASE,
)


def _first_match(text: str, patterns: list) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()[:200]
    return ""


def fuse(adapter_data: dict, ocr_text: str = "", structured: dict | None = None) -> dict:
    """
    Merge all data sources into normalized product model.

    Priority:
    - OCR text > adapter data for label fields (manufacturer, FSSAI, dates)
    - Adapter data > OCR for commerce fields (price, platform, seller)
    - structured (JSON-LD) used as supplement
    """
    structured = structured or {}

    # Combine all text sources for regex extraction
    all_text_parts = []
    for k, v in adapter_data.items():
        if isinstance(v, str) and v:
            all_text_parts.append(v)
        elif isinstance(v, list):
            all_text_parts.extend([str(x) for x in v if x])
    all_text_parts.append(ocr_text)
    combined = "\n".join(all_text_parts)

    model = {
        "product": {
            "name": (adapter_data.get("product_name") or
                     structured.get("name") or
                     structured.get("og_title") or ""),
            "brand": (adapter_data.get("brand") or structured.get("brand") or
                      _extract_brand(combined) or ""),
            "category": adapter_data.get("category", ""),
            "variant": adapter_data.get("variant", ""),
            "description": (adapter_data.get("description") or
                            structured.get("og_description") or "")[:400],
            "sku": adapter_data.get("sku") or structured.get("sku") or "",
        },
        "commerce": {
            "platform": adapter_data.get("source", "Unknown"),
            "seller": (adapter_data.get("seller") or structured.get("seller") or ""),
            "mrp_raw": (adapter_data.get("mrp") or structured.get("price") or ""),
            "selling_price_raw": adapter_data.get("selling_price", ""),
            "currency": "INR",
        },
        "manufacturer": _build_entity("manufacturer", combined, adapter_data),
        "packer": _build_entity("packer", combined, adapter_data),
        "importer": _build_entity("importer", combined, adapter_data),
        "origin": {
            "declared_country": (adapter_data.get("country_of_origin") or
                                 _extract_country_of_origin(combined) or ""),
            "detected_country": "",
            "confidence": 0,
        },
        "quantity": {
            "website_raw": adapter_data.get("Unit Count") or adapter_data.get("Item Weight") or adapter_data.get("net_quantity", ""),
            "package_raw": _extract_from_ocr(ocr_text, r"Net\s*(?:Quantity|Weight|Content)\s*[:\-]?\s*([^\n|]{2,30})"),
            "normalized": None,
        },
        "dates": {
            "mfg_date": (adapter_data.get("mfg_date") or
                         _first_match(combined, [_MFG_DATE_PATTERN]) or ""),
            "packing_date": "",
            "expiry_date": (adapter_data.get("best_before") or
                            _first_match(combined, [_EXPIRY_PATTERN]) or ""),
            "best_before": adapter_data.get("best_before", ""),
        },
        "consumer_care": {
            "raw": _first_match(combined, [_CONSUMER_CARE_PATTERN]),
            "phone": adapter_data.get("consumer_care_phone") or _extract_phone(combined),
            "email": _extract_email(combined),
        },
        "regulatory": {
            "fssai": (adapter_data.get("fssai") or
                      adapter_data.get("FSSAI Lic No") or
                      _first_match(combined, [_FSSAI_PATTERN])),
            "barcode": _extract_barcode(combined),
            "batch_no": _first_match(combined, [_BATCH_PATTERN]),
            "declarations": _extract_declarations(combined),
        },
        "images": adapter_data.get("images", []),
        "ocr_text": ocr_text,
        "adapter_data": adapter_data,
    }

    # ── Post-process: normalize quantities ────────────────────────────────────
    qty_raw = model["quantity"]["website_raw"]
    if qty_raw:
        model["quantity"]["normalized"] = normalize_quantity(qty_raw)

    # ── Post-process: detect manufacturer country ─────────────────────────────
    mfr_addr = model["manufacturer"]["address_raw"]
    if mfr_addr:
        cd = detect_country(mfr_addr)
        model["manufacturer"]["country"] = cd["country"]
        model["manufacturer"]["country_confidence"] = cd["confidence"]
        model["manufacturer"]["country_signals"] = cd["signals"]

    # ── Post-process: declared country of origin ──────────────────────────────
    declared = model["origin"]["declared_country"]
    if declared:
        cd = detect_country(declared + " " + (mfr_addr or ""))
        model["origin"]["detected_country"] = cd["country"]
        model["origin"]["confidence"] = cd["confidence"]
    elif mfr_addr:
        cd = detect_country(mfr_addr)
        model["origin"]["detected_country"] = cd["country"]
        model["origin"]["confidence"] = cd["confidence"]

    # ── Post-process: product classification ─────────────────────────────────
    model["product_classification"] = classify_product_origin(
        manufacturer_country=model["manufacturer"].get("country", ""),
        importer_country=model["importer"].get("country", ""),
        declared_country=model["origin"].get("declared_country", ""),
    )

    return model


def _build_entity(role: str, combined: str, adapter_data: dict) -> dict:
    """Build manufacturer/packer/importer entity dict."""
    patterns_map = {
        "manufacturer": _MFR_PATTERNS,
        "packer": _PACKER_PATTERNS,
        "importer": _IMPORTER_PATTERNS,
    }
    raw_key = f"{role}_raw"
    patterns = patterns_map.get(role, _MFR_PATTERNS)

    raw = adapter_data.get(raw_key) or _first_match(combined, patterns)

    if raw:
        parsed = parse_address(raw)
    else:
        parsed = {}

    return {
        "name": parsed.get("company", ""),
        "address_raw": raw,
        "parsed": parsed,
        "country": parsed.get("country", ""),
        "country_confidence": parsed.get("confidence", 0),
        "country_signals": [],
        "source": "webpage" if adapter_data.get(raw_key) else "regex",
    }


def _extract_country_of_origin(text: str) -> str:
    m = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|$|\||\,)",
                  text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_brand(text: str) -> str:
    m = re.search(r"\bBrand\s*[:\-]\s*([A-Za-z][A-Za-z\s&]{2,40}?)(?:\n|$|\|)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_phone(text: str) -> str:
    m = re.search(r"(?:1800[\s\-]?[\d\s\-]{7,12}|\+91[\s\-]?\d{10}|0\d{10})", text)
    return m.group(0).strip() if m else ""


def _extract_email(text: str) -> str:
    m = re.search(r"[\w.\-+]+@[\w\-]+\.[\w.]+", text)
    return m.group(0) if m else ""


def _extract_barcode(text: str) -> str:
    # EAN-13 / UPC-A (12-13 digits) but not FSSAI (14 digits)
    m = re.search(r"\b(\d{12,13})\b", text)
    return m.group(1) if m else ""


def _extract_from_ocr(ocr_text: str, pattern: str) -> str:
    m = re.search(pattern, ocr_text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_declarations(text: str) -> list[str]:
    """Extract Legal Metrology style declarations from text."""
    decl_patterns = [
        r"(?:All\s+weights[^\n.]{5,100})",
        r"(?:Weigh\s+before\s+buying[^\n.]{0,60})",
        r"(?:Statutory\s+warning[^\n.]{5,100})",
        r"(?:FSSAI[^\n.]{5,80})",
        r"(?:Vegetarian|Non[\s\-]?Vegetarian)[^\n.]{0,60}",
        r"(?:Certified\s+Organic[^\n.]{0,60})",
        r"(?:Lic\.\s*No\.[^\n.]{5,40})",
    ]
    results = []
    for pat in decl_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            results.append(m.group(0).strip())
    return results[:5]
