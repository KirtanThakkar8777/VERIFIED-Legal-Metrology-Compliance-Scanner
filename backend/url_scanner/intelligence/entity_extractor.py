"""
url_scanner/intelligence/entity_extractor.py
Extract Legal Metrology entities from raw OCR text.

Handles all manufacturer phrase variants, address parsing,
FSSAI, MRP, dates, ingredients, allergens, barcode/QR text.

Returns a structured dict ready for data_fusion.
"""
from __future__ import annotations
import re
from typing import Optional


# ── Manufacturer / Packer / Importer phrase variants ──────────────────────────

# Each tuple: (pattern, role_tags)
# role_tags can be: "manufacturer", "marketer", "packer", "importer", "distributor"
_MFR_ROLE_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    # Combined roles (most specific first)
    (re.compile(
        r"(?:Manufactured|Mfg\.?)\s*[,&]+\s*(?:Marketed|Market\.?)\s*[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer", "marketer"]),
    (re.compile(
        r"(?:Manufactured|Mfg\.?)\s*[,&]+\s*Packed\s*[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer", "packer"]),
    (re.compile(
        r"Processed[\s,]+[Pp]acked\s*(?:and\s+)?(?:[Mm]arketed\s*)?[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer", "packer", "marketer"]),
    # Single roles
    (re.compile(
        r"Manufactured\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer"]),
    (re.compile(
        r"(?:Mfd\.?|Mfg\.?)\s*[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer"]),
    (re.compile(
        r"Marketed\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["marketer"]),
    (re.compile(
        r"Packed\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["packer"]),
    (re.compile(
        r"Imported\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["importer"]),
    (re.compile(
        r"Distributed\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["distributor"]),
    # Label format: "MANUFACTURER:" or "Manufacturer :"
    (re.compile(
        r"^MANUFACTURER\s*:\s*(.+?)(?=\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ), ["manufacturer"]),
    (re.compile(
        r"^PACKER\s*:\s*(.+?)(?=\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ), ["packer"]),
    (re.compile(
        r"^IMPORTER\s*:\s*(.+?)(?=\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ), ["importer"]),
    # Contact information (Amazon table format)
    (re.compile(
        r"Manufacturer\s+Contact\s+Information\s*[:\-]?\s*(.+?)(?=\n\n|\n[A-Z][a-z]+\s+Contact|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer"]),
    (re.compile(
        r"Packer\s+Contact\s+Information\s*[:\-]?\s*(.+?)(?=\n\n|\n[A-Z][a-z]+\s+Contact|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["packer"]),
]


def _clean_entity_text(raw: str, max_len: int = 400) -> str:
    """Clean and limit extracted entity text."""
    # Remove excessive whitespace
    text = re.sub(r"\s{3,}", "\n", raw.strip())
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:max_len].strip()


def _split_company_and_address(raw: str) -> tuple[str, str]:
    """
    Split raw OCR block into company name and address.
    Company name is usually the first 1-2 lines; rest is address.
    """
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    if not lines:
        return "", ""

    company_lines = []
    address_lines = []
    company_done = False

    for line in lines:
        if company_done:
            address_lines.append(line)
            continue
        # Heuristic: if line contains PIN/street indicators, it's address
        if re.search(r"\b\d{6}\b|Survey|No\.|Plot|Street|Road|Lane|Phase|Sector|Village|Gram|Nagar|Industrial", line, re.IGNORECASE):
            company_done = True
            address_lines.append(line)
        elif re.search(r"Pvt\.?|Ltd\.?|Private|Limited|LLP|Industries|Enterprises|Solutions|Foods|Wellness|Pharma", line, re.IGNORECASE):
            company_lines.append(line)
            company_done = True
        elif len(company_lines) >= 2:
            company_done = True
            address_lines.append(line)
        else:
            company_lines.append(line)

    company = " ".join(company_lines).strip()
    address = "\n".join(address_lines).strip()

    # If no split was possible, first line is company, rest is address
    if not company and lines:
        company = lines[0]
        address = "\n".join(lines[1:])

    return company, address


# ── Net Quantity patterns ──────────────────────────────────────────────────────

_QTY_PATTERNS = [
    re.compile(r"NET\s*(?:WEIGHT|WT\.?|QUANTITY|QTY\.?|CONTENT|VOL(?:UME)?)\s*[:\-]?\s*([\d.,]+\s*(?:kg|g|gm|gms|L|litre|liter|ml|oz|lb))", re.IGNORECASE),
    re.compile(r"NET\s+WT\s*[:\-]?\s*([\d.,]+\s*(?:kg|g|gm|gms|L|ml|oz|lb))", re.IGNORECASE),
    re.compile(r"Nett?\s*(?:Weight|Wt\.?)\s*[:\-]?\s*([\d.,]+\s*(?:kg|g|gm|gms|L|ml))", re.IGNORECASE),
    re.compile(r"([\d.,]+\s*(?:kg|Kg|KG))\s*(?:\||$|\n)", re.MULTILINE),
    re.compile(r"WEIGHT\s*[:\-]\s*([\d.,]+\s*(?:kg|g|gm|gms|L|ml))", re.IGNORECASE),
    re.compile(r"(?:Weight|Quantity)\s*[:\-]\s*([\d.,]+\s*(?:kg|g|gm|L|ml|pcs|units|tablets?|capsules?))", re.IGNORECASE),
]

# ── MRP patterns ──────────────────────────────────────────────────────────────

_MRP_PATTERNS = [
    re.compile(r"M\.?R\.?P\.?\s*(?:Incl\.?\s*of\s*all\s*taxes?)?\s*[:\-₹Rs.]*\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
    re.compile(r"(?:MRP|M\.R\.P)\s*[:\-]?\s*(?:Rs\.?|₹|INR)?\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
    re.compile(r"(?:Rs\.?|₹)\s*([\d,]+\.?\d{0,2})\s*/?\s*-?\s*(?:MRP|M\.R\.P)", re.IGNORECASE),
    re.compile(r"(?:Retail\s*Price|Maximum\s*Retail\s*Price)\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
]

# ── FSSAI patterns ────────────────────────────────────────────────────────────

_FSSAI_PATTERNS = [
    re.compile(r"FSSAI\s*(?:Lic(?:ence|ense)?\.?\s*No\.?|License\s*No\.?|Lic\.?\s*No\.?|#)?\s*[:\-]?\s*([1-9]\d{13})", re.IGNORECASE),
    re.compile(r"(?:Lic(?:ence)?\.?\s*No\.?)\s*([1-9]\d{13})", re.IGNORECASE),
    re.compile(r"\b([1-9]\d{13})\b"),  # Raw 14-digit number
]

# ── Date patterns ─────────────────────────────────────────────────────────────

_DATE_RE = r"(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[-/\s]?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/\s]?\d{2,4}|\d{4})"

_MFG_DATE_PATTERNS = [
    re.compile(r"(?:Mfg\.?\s*Date|MFG\.?\s*DATE|Date\s*of\s*Mfg\.?|Manufacturing\s*Date|Manufactured\s*On)\s*[:\-]?\s*(" + _DATE_RE + r")", re.IGNORECASE),
    re.compile(r"Mfg\s*[:\-]\s*(" + _DATE_RE + r")", re.IGNORECASE),
]

_EXP_DATE_PATTERNS = [
    re.compile(r"(?:Exp(?:iry)?\.?\s*Date|EXP\.?\s*DATE|Best\s*Before|BBE|Use\s*By|Expiry|Best\s*Before\s*(?:End)?|BB[D:]?)\s*[:\-]?\s*(" + _DATE_RE + r")", re.IGNORECASE),
    re.compile(r"(?:Use\s*Before|Consume\s*Before)\s*[:\-]?\s*(" + _DATE_RE + r")", re.IGNORECASE),
]

_BATCH_PATTERNS = [
    re.compile(r"(?:Batch\s*(?:No\.?|Code)?|Lot\s*(?:No\.?|#)?|Batch/Lot|B\.?\s*No\.?)\s*[:\-#]?\s*([A-Z0-9/\-]{3,25})", re.IGNORECASE),
]

# ── Consumer care patterns ────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"(?:1800[\s\-]?[\d\s\-]{6,12}|\+91[\s\-]?\d{10}|0\d{10})")
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.]+")
_CONSUMER_CARE_PATTERNS = [
    re.compile(r"(?:Consumer\s*Care|Customer\s*Care|Helpline|Care\s*Line|Toll[\s\-]*Free)\s*[:\-]?\s*(.{5,120})", re.IGNORECASE | re.DOTALL),
]

# ── Ingredients patterns ──────────────────────────────────────────────────────

_INGREDIENTS_PATTERNS = [
    re.compile(r"INGREDIENTS?\s*[:\-]?\s*(.{20,1000}?)(?=\n\n|\nALLERGEN|\nNUTRITION|\nSTORAGE|$)", re.IGNORECASE | re.DOTALL),
    re.compile(r"CONTAINS?\s*[:\-]\s*(.{10,400}?)(?=\n\n|\nALLERGEN|$)", re.IGNORECASE | re.DOTALL),
]

_ALLERGEN_PATTERNS = [
    re.compile(r"ALLERGEN\s*(?:INFORMATION|INFO\.?)?\s*[:\-]?\s*(.{5,300}?)(?=\n\n|\nSTORAGE|\nNUTRITION|$)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:Contains|Allergy\s*Advice)\s*[:\-]\s*(.{5,200}?)(?:\.|$|\n)", re.IGNORECASE),
    re.compile(r"(?:May\s+Contain|Contains\s+traces?\s+of)\s*[:\-]?\s*(.{5,150}?)(?:\.|$|\n)", re.IGNORECASE),
]

_STORAGE_PATTERNS = [
    re.compile(r"STORAGE\s*(?:INSTRUCTIONS?|CONDITIONS?|INFO\.?)?\s*[:\-]?\s*(.{5,300}?)(?=\n\n|\nNUTRITION|\nALLERGEN|$)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:Store|Keep)\s+(?:in|at|away)\s+(.{5,150}?)(?:\.|$|\n)", re.IGNORECASE),
]

# ── Country of Origin ─────────────────────────────────────────────────────────

_COO_PATTERNS = [
    re.compile(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30}?)(?:\n|$|\||,)", re.IGNORECASE),
    re.compile(r"Made\s+in\s+([A-Za-z\s]{3,25}?)(?:\n|$|\||\.|,)", re.IGNORECASE),
    re.compile(r"Product\s+of\s+([A-Za-z\s]{3,25}?)(?:\n|$|\||\.|,)", re.IGNORECASE),
]

# ── Barcode / GTIN ────────────────────────────────────────────────────────────

_BARCODE_OCR_PATTERN = re.compile(r"\b(\d{8}|\d{12}|\d{13}|\d{14})\b")


def _first_match(text: str, patterns: list[re.Pattern], group: int = 1) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            try:
                return _clean_entity_text(m.group(group))
            except IndexError:
                pass
    return ""


# ── Main extraction function ──────────────────────────────────────────────────

def extract_entities(ocr_text: str) -> dict:
    """
    Extract all Legal Metrology entities from raw OCR text.

    Returns dict with all detected entities and their values.
    Empty string means "not detected" — never returns placeholder text.
    """
    if not ocr_text:
        return {}

    text = ocr_text
    entities: dict = {}

    # ── Manufacturer / Packer / Importer ─────────────────────────────────────
    manufacturer_raw = ""
    packer_raw = ""
    importer_raw = ""
    marketer_raw = ""

    for pat, roles in _MFR_ROLE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        raw = _clean_entity_text(m.group(1))
        if "manufacturer" in roles and not manufacturer_raw:
            manufacturer_raw = raw
        if "packer" in roles and not packer_raw:
            packer_raw = raw
        if "importer" in roles and not importer_raw:
            importer_raw = raw
        if "marketer" in roles and not marketer_raw:
            marketer_raw = raw

    # Parse company and address from each entity
    if manufacturer_raw:
        company, address = _split_company_and_address(manufacturer_raw)
        entities["manufacturer_name"] = company
        entities["manufacturer_address"] = address
        entities["manufacturer_raw"] = manufacturer_raw

    if packer_raw and packer_raw != manufacturer_raw:
        company, address = _split_company_and_address(packer_raw)
        entities["packer_name"] = company
        entities["packer_address"] = address
        entities["packer_raw"] = packer_raw

    if importer_raw:
        company, address = _split_company_and_address(importer_raw)
        entities["importer_name"] = company
        entities["importer_address"] = address
        entities["importer_raw"] = importer_raw

    if marketer_raw and marketer_raw != manufacturer_raw:
        company, address = _split_company_and_address(marketer_raw)
        entities["marketer_name"] = company
        entities["marketer_raw"] = marketer_raw

    # ── Net Quantity ──────────────────────────────────────────────────────────
    qty = _first_match(text, _QTY_PATTERNS)
    if qty:
        entities["net_quantity"] = qty.strip()

    # ── MRP ───────────────────────────────────────────────────────────────────
    mrp = _first_match(text, _MRP_PATTERNS)
    if mrp:
        entities["mrp"] = mrp.replace(",", "").strip()
        # Validate it's a plausible price
        try:
            val = float(entities["mrp"])
            if val <= 0 or val > 1000000:
                del entities["mrp"]
        except ValueError:
            del entities["mrp"]

    # ── FSSAI ─────────────────────────────────────────────────────────────────
    fssai = _first_match(text, _FSSAI_PATTERNS)
    if fssai and len(fssai) == 14:
        entities["fssai"] = fssai

    # ── Dates ─────────────────────────────────────────────────────────────────
    mfg_date = _first_match(text, _MFG_DATE_PATTERNS)
    if mfg_date:
        entities["mfg_date"] = mfg_date.strip()

    exp_date = _first_match(text, _EXP_DATE_PATTERNS)
    if exp_date:
        entities["expiry_date"] = exp_date.strip()

    batch = _first_match(text, _BATCH_PATTERNS)
    if batch:
        entities["batch_no"] = batch.strip()

    # ── Country of Origin ─────────────────────────────────────────────────────
    coo = _first_match(text, _COO_PATTERNS)
    if coo:
        entities["country_of_origin"] = coo.strip()

    # ── Ingredients ───────────────────────────────────────────────────────────
    ingredients = _first_match(text, _INGREDIENTS_PATTERNS)
    if ingredients:
        entities["ingredients"] = _clean_entity_text(ingredients, max_len=1000)

    # ── Allergens ─────────────────────────────────────────────────────────────
    allergens = _first_match(text, _ALLERGEN_PATTERNS)
    if allergens:
        entities["allergen_info"] = _clean_entity_text(allergens, max_len=300)

    # ── Storage ───────────────────────────────────────────────────────────────
    storage = _first_match(text, _STORAGE_PATTERNS)
    if storage:
        entities["storage_instructions"] = _clean_entity_text(storage, max_len=200)

    # ── Consumer Care ─────────────────────────────────────────────────────────
    care_raw = _first_match(text, _CONSUMER_CARE_PATTERNS)
    if care_raw:
        entities["consumer_care_raw"] = _clean_entity_text(care_raw)

    phone = _PHONE_RE.search(text)
    if phone:
        entities["consumer_care_phone"] = phone.group(0).strip()

    email = _EMAIL_RE.search(text)
    if email:
        entities["consumer_care_email"] = email.group(0)

    # ── Barcode from OCR text ─────────────────────────────────────────────────
    # (actual barcode decoding happens in image_processor via pyzbar)
    # Exclude FSSAI number (also 14 digits) from being treated as barcode
    fssai_val = entities.get("fssai", "")
    barcode_ocr = _BARCODE_OCR_PATTERN.search(text)
    if barcode_ocr:
        val = barcode_ocr.group(1)
        # Must be EAN-8, UPC-A (12), or EAN-13 — FSSAI is 14 digits so won't match
        if len(val) in (8, 12, 13) and val != fssai_val:
            entities["barcode_ocr"] = val

    # ── Brand detection ───────────────────────────────────────────────────────
    brand_m = re.search(r"\bBrand\s*[:\-]\s*([A-Za-z][A-Za-z\s&]{2,40}?)(?:\n|$|\|)", text, re.IGNORECASE)
    if brand_m:
        entities["brand"] = brand_m.group(1).strip()

    # ── Vegetarian / Non-Vegetarian ───────────────────────────────────────────
    if re.search(r"\bnon[\s\-]?vegetarian\b|\bnon[\s\-]?veg\b", text, re.IGNORECASE):
        entities["veg_status"] = "Non-Vegetarian"
    elif re.search(r"\bvegetarian\b|\bpure\s*veg\b|\bveg\b", text, re.IGNORECASE):
        entities["veg_status"] = "Vegetarian"

    return entities
