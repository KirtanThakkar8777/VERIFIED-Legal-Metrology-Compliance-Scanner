"""
scan/normalizer.py — Normalise raw detected values for MRP, quantity, and dates.
"""
import re
from typing import Optional


# ── MRP normaliser ────────────────────────────────────────────────────────────

def normalize_mrp(raw: Optional[str]) -> Optional[str]:
    """Return 'Rs. X.XX' or None if the value can't be parsed."""
    if not raw:
        return None
    # Strip non-numeric except dot and comma
    cleaned = re.sub(r"[^\d,.]", "", raw)
    cleaned = cleaned.replace(",", "")
    try:
        amount = float(cleaned)
        return f"Rs. {amount:.2f}"
    except ValueError:
        return raw.strip()


# ── Quantity normaliser ───────────────────────────────────────────────────────

_UNIT_ALIASES = {
    "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kilogram": "kg", "kgs": "kg",
    "millilitre": "ml", "milliliter": "ml",
    "litre": "L", "liter": "L",
    "pieces": "pcs", "pcs": "pcs", "nos": "nos", "units": "units",
}


def normalize_quantity(raw: Optional[str]) -> Optional[str]:
    """Return 'VALUE UNIT' with canonical unit abbreviation."""
    if not raw:
        return None
    m = re.match(
        r"([\d,]+(?:\.\d+)?)\s*([a-zA-Z]+)", raw.strip(), re.IGNORECASE
    )
    if not m:
        return raw.strip()
    value_str = m.group(1).replace(",", "")
    unit = _UNIT_ALIASES.get(m.group(2).lower(), m.group(2).lower())
    try:
        value = float(value_str)
        return f"{value:g} {unit}"
    except ValueError:
        return raw.strip()


# ── Date normaliser ───────────────────────────────────────────────────────────

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(raw: Optional[str]) -> Optional[str]:
    """Attempt to produce MM/YYYY from various date formats."""
    if not raw:
        return None
    s = raw.strip()

    # Named month: Jan 2024 / January 2024
    m = re.search(r"([A-Za-z]{3,9})\.?\s*(\d{4})", s)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return f"{mon}/{m.group(2)}"

    # MM/YYYY or MM-YYYY
    m = re.search(r"(\d{1,2})[/\-](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"

    # YYYY/MM or YYYY-MM
    m = re.search(r"(\d{4})[/\-](\d{2})", s)
    if m:
        return f"{m.group(2)}/{m.group(1)}"

    # DD/MM/YYYY
    m = re.search(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})", s)
    if m:
        return f"{m.group(2)}/{m.group(3)}"

    return s
