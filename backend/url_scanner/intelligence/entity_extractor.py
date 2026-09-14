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

    # ── Importer variants (most common on imported packaged foods) ────────────
    # "IMPORTED IN INDIA BY: Ferrero India Pvt. Ltd..."
    (re.compile(
        r"Imported\s+in\s+India\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|PACKED\s+BY|MFD\s+BY|MANUFACTURED|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["importer"]),
    # "IMPORTED AND MARKETED BY:" or "IMPORTED & MARKETED BY:"
    (re.compile(
        r"Imported\s+(?:and|&)\s+(?:Marketed|Distributed|Sold)\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["importer", "marketer"]),
    # "SOLE IMPORTER:" or "AUTHORISED IMPORTER:"
    (re.compile(
        r"(?:Sole|Authoris[e]?d|Exclusive)\s+Importer\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["importer"]),
    # "IMPORTER:" standalone label
    (re.compile(
        r"^IMPORTER\s*[:\-]\s*(.+?)(?=\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ), ["importer"]),

    # ── Marketer / Distributor variants ───────────────────────────────────────
    # "MKT. BY:" or "MARKETED BY:" or "MARKETED AND DISTRIBUTED BY:"
    (re.compile(
        r"(?:Mkt\.?\s*[Bb]y|Marketed\s+[Bb]y|Marketed\s+(?:and|&)\s+Distributed\s+[Bb]y)\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["marketer"]),
    # "FOR SALE IN INDIA CONTACT:" / "INDIA CONTACT:"
    (re.compile(
        r"(?:For\s+Sale\s+in\s+India|India\s+Contact|India\s+Office)\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["importer"]),

    # ── Standard single-role patterns ─────────────────────────────────────────
    (re.compile(
        r"Manufactured\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer"]),
    (re.compile(
        r"(?:Mfd\.?|Mfg\.?)\s*[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
        re.IGNORECASE | re.DOTALL,
    ), ["manufacturer"]),
    # "MFD. IN ITALY BY:" (manufacturing in another country)
    (re.compile(
        r"Mf[gd]\.?\s+in\s+[A-Za-z\s]+\s+[Bb]y\s*[:\-]?\s*(.+?)(?=\n\n|\n(?:[A-Z]{{2,}}:)|$)",
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
# FSSAI licence numbers are always exactly 14 digits starting with 1-9.
# OCR may introduce spaces within the number or confuse O/0, I/1, l/1.
# NOTE: Use raw strings with SINGLE backslash escapes — double-backslash breaks them.

_FSSAI_PATTERNS = [
    # Pattern 1: "FSSAI Lic. No.: 12345678901234" — matches solid or spaced digits
    re.compile(
        r"FSSAI\s*(?:Lic(?:ence|ense)?\.?\s*No\.?|License\s*No\.?|Lic\.?\s*No\.?|"
        r"#|Reg\.?\s*No\.?|Licence\s*Number|License\s*Number)?\s*[:\-]?\s*"
        r"([1-9][\d\s\-]{12,17}\d)",
        re.IGNORECASE,
    ),
    # Pattern 2: "Lic. No. 12345678901234" (without explicit FSSAI keyword)
    re.compile(
        r"Lic(?:ence|ense)?\.?\s*No\.?\s*[:\-]?\s*([1-9][\d\s\-]{12,17}\d)",
        re.IGNORECASE,
    ),
    # Pattern 3: Licence Number label
    re.compile(
        r"Licen[sc]e\s*(?:No\.?|Number)\s*[:\-]?\s*([1-9][\d\s\-]{12,17}\d)",
        re.IGNORECASE,
    ),
    # Pattern 4: "FSSAI" keyword near a 14-digit number (solid or spaced, within 80 chars)
    re.compile(r"FSSAI[^\d]{0,60}([1-9][\d\s\-]{12,17}\d)", re.IGNORECASE | re.DOTALL),
    # Pattern 5: Raw 14-digit number on its own line (standalone licence number)
    re.compile(r"(?:^|\n)\s*([1-9]\d{13})\s*(?:\n|$)", re.MULTILINE),
    # Pattern 5b: Spaced 14-digit number on its own line e.g. "1001 4022 0027 11"
    re.compile(r"(?:^|\n)\s*([1-9]\d{3}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{2})\s*(?:\n|$)", re.MULTILINE),
    # Pattern 6: OCR with spaces — "1 1521 9980 0076 9" → compact
    re.compile(r"\b([1-9][\d\s]{14,20}\d)\b"),
    # Pattern 7: 14-digit block anywhere in text (last resort)
    re.compile(r"\b([1-9]\d{13})\b"),
]

# FSSAI signal words — text near these suggests nearby number is a licence number
_FSSAI_CONTEXT = re.compile(
    r"FSSAI|Lic(?:ence|ense)?\.?\s*No|Licence\s*Number|License\s*Number|"
    r"Food\s*Safety|FSSAI\s*Logo",
    re.IGNORECASE,
)


def _clean_fssai(raw: str) -> str:
    """Clean up an FSSAI number candidate — remove spaces/hyphens, validate length.
    Also fixes common OCR misreads: O→0, I→1, l→1.
    NOTE: Does NOT blindly replace S→5 — only in purely numeric context after stripping letters.
    """
    cleaned = raw.strip()
    # Only keep digits, O, I, l (common OCR misreads) and separators
    cleaned = re.sub(r"[^\dOIlS\s\-]", "", cleaned)
    cleaned = cleaned.replace("O", "0").replace("o", "0")
    cleaned = cleaned.replace("I", "1").replace("l", "1")
    # S→5 only if surrounded by digits (not at a letter/word boundary)
    cleaned = re.sub(r"(?<=\d)S(?=\d)", "5", cleaned)
    cleaned = re.sub(r"(?<=\d)s(?=\d)", "5", cleaned)
    cleaned = re.sub(r"[\s\-]", "", cleaned)  # collapse spaces and hyphens

    if len(cleaned) == 14 and cleaned[0] != "0":
        if cleaned[0] in "123456789":
            return cleaned
    return ""


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
# Heading variants (including common OCR errors and Indian packaging variants):
#   INGREDlENTS (l vs I), INGRED1ENTS (1 vs I), INGREDIANTS (misspelling)
#   COMPOSITION, MADE FROM, MADE WITH, PREPARED FROM, CONTENT
# The stop-group prevents the ingredient text from bleeding into a Nutrition section.
_STOP_GROUP = (
    r"(?=\n\n"
    r"|\nALLERGEN"
    r"|\nNUTRITION"
    r"|\nSTORAGE"
    r"|\nCALORIES?"
    r"|\nENERGY\s*[:\-]?"
    r"|\nTOTAL\s+(?:FAT|CARB|PROTEIN)"
    r"|\nAMOUNT\s+PER"
    r"|$)"
)

_INGREDIENTS_PATTERNS = [
    # Standard "INGREDIENTS:" heading (most common)
    re.compile(
        r"INGREDIENT[S]?\s*[:\-.]?\s*(.{20,2000}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
    # OCR fuzzy: INGREDIANTS / INGREDENTS / INGREDlENTS / INGRED1ENTS
    re.compile(
        r"INGRED(?:I[1lL]|IE|IA)ENTS?\s*[:\-.]?\s*(.{20,2000}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
    # COMPOSITION: (common on Indian and European packaging)
    re.compile(
        r"COMPOSITION\s*[:\-.]?\s*(.{20,2000}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
    # MADE FROM: / MADE WITH:
    re.compile(
        r"MADE\s+(?:FROM|WITH)\s*[:\-.]?\s*(.{20,2000}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
    # PREPARED FROM:
    re.compile(
        r"PREPARED\s+FROM\s*[:\-.]?\s*(.{20,2000}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
    # CONTAINS: followed by a food ingredient list (not "Contains Milk" allergen)
    re.compile(
        r"CONTAINS\s*[:\-]\s*((?:[A-Z][a-zA-Z\s,\(\)%\d\.]+){20,600}?)" + _STOP_GROUP,
        re.IGNORECASE | re.DOTALL,
    ),
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
# IMPORTANT: OCR from product labels often puts label and value on separate lines.
# Patterns must handle both same-line AND next-line value layouts.

_COO_PATTERNS = [
    # Same line: "Country of Origin: India" or "Country of Origin India"
    re.compile(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{2,29}?)(?:\n|$|\||,|\s{2,})", re.IGNORECASE),
    # Next line: "Country of Origin\nIndia" (very common in OCR of packaged labels)
    re.compile(r"Country\s*of\s*Origin\s*[:\-]?\s*\n\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\n|$|\||,)", re.IGNORECASE),
    # Short label "Origin: India"
    re.compile(r"\bOrigin\s*[:\-]\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\n|$|\||,|\s{2,})", re.IGNORECASE),
    # "Made in India" on same line or at line end
    re.compile(r"Made\s+in\s+([A-Za-z][A-Za-z\s]{2,25}?)(?:\n|$|\||\.|\,|\s{2,})", re.IGNORECASE),
    # "Product of India"
    re.compile(r"Product\s+of\s+([A-Za-z][A-Za-z\s]{2,25}?)(?:\n|$|\||\.|\,)", re.IGNORECASE),
    # "Produce of India"
    re.compile(r"Produce\s+of\s+([A-Za-z][A-Za-z\s]{2,25}?)(?:\n|$|\||\.|\,)", re.IGNORECASE),
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


# ── Ingredient completeness helper ───────────────────────────────────────────

_TRUNCATION_SIGNALS = re.compile(
    r"(?:,\s*$"              # ends with comma  -> "Oats, Wheat,"
    r"|\band\s*$"            # ends with "and"  -> "Oats and"
    r"|\(\s*$"               # ends with "("    -> "Oats (25"
    r"|\d+\.?\d*\s*%?\s*$"   # ends with a bare number/percentage
    r"|\d+\s*$)",            # ends with just digits
    re.IGNORECASE,
)


def _check_ingredient_completeness(ingredient_text: str) -> bool:
    """
    Return True if the ingredient list appears complete, False if truncated.

    A list is INCOMPLETE when it ends with:
    - A comma  ("Oats, Wheat, Millets,")
    - 'and'    ("Oats and")
    - Open parenthesis  ("Glucose (")
    - A bare number or percentage  ("25" or "25%")

    A list is COMPLETE when it ends with a full stop, closing parenthesis,
    or a recognisable ingredient word token.
    """
    if not ingredient_text:
        return False
    tail = ingredient_text.strip()[-80:]   # inspect last 80 chars
    return not bool(_TRUNCATION_SIGNALS.search(tail))


# ── Country inference from address ────────────────────────────────────────────

# Indian states, UTs, and major cities — if present in an address, country = India
_INDIA_GEO = re.compile(
    r"\b("
    # All 28 states
    r"Andhra\s*Pradesh|Arunachal\s*Pradesh|Assam|Bihar|Chhattisgarh|Goa|Gujarat|"
    r"Haryana|Himachal\s*Pradesh|Jharkhand|Karnataka|Kerala|Madhya\s*Pradesh|"
    r"Maharashtra|Manipur|Meghalaya|Mizoram|Nagaland|Odisha|Orissa|Punjab|"
    r"Rajasthan|Sikkim|Tamil\s*Nadu|Telangana|Tripura|Uttar\s*Pradesh|Uttarakhand|"
    r"West\s*Bengal|"
    # Union territories
    r"Andaman|Nicobar|Chandigarh|Dadra|Nagar\s*Haveli|Daman|Diu|Delhi|"
    r"Jammu|Kashmir|Ladakh|Lakshadweep|Puducherry|Pondicherry|"
    # Major cities
    r"Mumbai|Bombay|Delhi|Kolkata|Calcutta|Chennai|Madras|Bangalore|Bengaluru|"
    r"Hyderabad|Ahmedabad|Pune|Surat|Jaipur|Lucknow|Kanpur|Nagpur|Indore|"
    r"Thane|Bhopal|Visakhapatnam|Pimpri|Patna|Vadodara|Ghaziabad|Ludhiana|"
    r"Agra|Nashik|Faridabad|Meerut|Rajkot|Varanasi|Srinagar|Aurangabad|"
    r"Dhanbad|Amritsar|Navi\s*Mumbai|Allahabad|Howrah|Coimbatore|Jabalpur|"
    r"Gwalior|Vijayawada|Jodhpur|Madurai|Raipur|Kota|Guwahati|Chandigarh|"
    r"Solapur|Hubli|Baddi|Silvassa|Haridwar|Rishikesh|Noida|Gurugram|Gurgaon"
    r")\b",
    re.IGNORECASE
)

# 6-digit Indian PIN code pattern
_INDIA_PIN = re.compile(r"\b[1-9]\d{5}\b")

# Other countries — matched against full address text
_OTHER_COUNTRIES = [
    (re.compile(r"\bChina\b|\bPRC\b|\bPeople'?s\s*Republic\b", re.I), "China"),
    (re.compile(r"\bUSA\b|\bUnited\s*States\b|\bU\.S\.A\.?\b", re.I), "USA"),
    (re.compile(r"\bUnited\s*Kingdom\b|\bU\.K\.?\b|\bEngland\b|\bBritain\b", re.I), "United Kingdom"),
    (re.compile(r"\bGermany\b|\bDeutschland\b", re.I), "Germany"),
    (re.compile(r"\bFrance\b|\bFrench\b", re.I), "France"),
    (re.compile(r"\bItaly\b|\bItalia\b", re.I), "Italy"),
    (re.compile(r"\bJapan\b|\bJapanese\b", re.I), "Japan"),
    (re.compile(r"\bSri\s*Lanka\b", re.I), "Sri Lanka"),
    (re.compile(r"\bBangladesh\b", re.I), "Bangladesh"),
    (re.compile(r"\bPakistan\b", re.I), "Pakistan"),
    (re.compile(r"\bNepal\b", re.I), "Nepal"),
    (re.compile(r"\bAustralia\b", re.I), "Australia"),
    (re.compile(r"\bCanada\b", re.I), "Canada"),
    (re.compile(r"\bThailand\b", re.I), "Thailand"),
    (re.compile(r"\bVietnam\b", re.I), "Vietnam"),
    (re.compile(r"\bIndonesia\b", re.I), "Indonesia"),
    (re.compile(r"\bMalaysia\b", re.I), "Malaysia"),
    (re.compile(r"\bSingapore\b", re.I), "Singapore"),
    (re.compile(r"\bIsrael\b", re.I), "Israel"),
    (re.compile(r"\bNetherlands\b|\bHolland\b", re.I), "Netherlands"),
    (re.compile(r"\bSpain\b|\bEspana\b", re.I), "Spain"),
    (re.compile(r"\bSwitzerland\b", re.I), "Switzerland"),
    (re.compile(r"\bDenmark\b", re.I), "Denmark"),
    (re.compile(r"\bSweden\b", re.I), "Sweden"),
    (re.compile(r"\bNorway\b", re.I), "Norway"),
    (re.compile(r"\bBelgium\b", re.I), "Belgium"),
    (re.compile(r"\bPoland\b", re.I), "Poland"),
    (re.compile(r"\bTurkey\b|\bTürkiye\b", re.I), "Turkey"),
    (re.compile(r"\bMexico\b", re.I), "Mexico"),
    (re.compile(r"\bBrazil\b|\bBrasil\b", re.I), "Brazil"),
    (re.compile(r"\bSouth\s*Korea\b|\bRepublic\s*of\s*Korea\b", re.I), "South Korea"),
    (re.compile(r"\bTaiwan\b", re.I), "Taiwan"),
    (re.compile(r"\bIndia\b", re.I), "India"),  # explicit "India" in address
]


def _infer_country_from_address(address_text: str) -> str:
    """
    Infer the country of origin from a manufacturer/packer/importer address string.

    Returns country name (e.g. 'India') or empty string if cannot be determined.

    Priority:
      1. Explicit Indian state/city/UT name → India  (most reliable for India)
      2. Explicit other country name match
      3. 6-digit Indian PIN code → India  (fallback, only if no country name matched)
    """
    if not address_text or len(address_text.strip()) < 5:
        return ""

    # India check — state/city/UT names are highly reliable
    if _INDIA_GEO.search(address_text):
        return "India"

    # Check for explicit country names (including "India" word itself)
    for pat, country in _OTHER_COUNTRIES:
        if pat.search(address_text):
            return country

    # Indian PIN code as last resort (only if no other country identified above)
    # FSSAI is 14 digits — exclude any 14-digit runs first
    clean = re.sub(r"\d{14}", "", address_text)
    if _INDIA_PIN.search(clean):
        return "India"

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
    fssai = ""
    for pat in _FSSAI_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = _clean_fssai(m.group(1))
            if candidate:
                fssai = candidate
                break
    if fssai:
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

    # ── Infer Country of Origin from manufacturer/packer address ─────────────
    # When the label doesn't explicitly say "Country of Origin: India" but the
    # manufacturer address contains Indian states/cities/PIN codes, we infer India.
    # This is valid: PCR 2011 §6(1)(g) allows COO to be implied by Indian address.
    if not entities.get("country_of_origin"):
        # Collect all address text we have
        _addr_parts = [
            entities.get("manufacturer_raw", ""),
            entities.get("manufacturer_address", ""),
            entities.get("packer_raw", ""),
            entities.get("packer_address", ""),
            entities.get("importer_raw", ""),
            entities.get("importer_address", ""),
        ]
        _addr_text = " ".join(p for p in _addr_parts if p)
        if _addr_text:
            inferred = _infer_country_from_address(_addr_text)
            if inferred:
                entities["country_of_origin"] = inferred
                entities["country_inferred_from_address"] = True


    # ── Ingredients ───────────────────────────────────────────────────────────
    ingredients = _first_match(text, _INGREDIENTS_PATTERNS)
    if ingredients:
        cleaned_ing = _clean_entity_text(ingredients, max_len=2000)
        entities["ingredients"] = cleaned_ing
        # Completeness check — detect truncated lists
        entities["ingredient_complete"] = _check_ingredient_completeness(cleaned_ing)



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
