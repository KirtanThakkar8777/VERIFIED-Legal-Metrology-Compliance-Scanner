"""
url_scanner/intelligence/data_normalizer.py
Normalize quantities, prices, and units for comparison.
"""
from __future__ import annotations
import re


# ── Quantity normalization ─────────────────────────────────────────────────────

_QTY_PATTERN = re.compile(
    r"([\d,]+\.?\d*)\s*(kg|kgs|kilogram|kilograms|g|gm|gms|gram|grams|"
    r"ml|millilitre|milliliter|millilitres|milliliters|l|litre|liter|litres|liters|"
    r"oz|lb|lbs|pcs|pieces|nos|units|tablets?|tabs?|capsules?|sachets?|strips?|count)",
    re.IGNORECASE,
)

_UNIT_CANON = {
    # Weight → grams
    "kg": ("g", 1000), "kgs": ("g", 1000),
    "kilogram": ("g", 1000), "kilograms": ("g", 1000),
    "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1),
    "gram": ("g", 1), "grams": ("g", 1),
    "oz": ("g", 28.35), "lb": ("g", 453.59), "lbs": ("g", 453.59),
    # Volume → ml
    "l": ("ml", 1000), "litre": ("ml", 1000), "liter": ("ml", 1000),
    "litres": ("ml", 1000), "liters": ("ml", 1000),
    "ml": ("ml", 1), "millilitre": ("ml", 1), "milliliter": ("ml", 1),
    "millilitres": ("ml", 1), "milliliters": ("ml", 1),
    # Count
    "pcs": ("pcs", 1), "pieces": ("pcs", 1), "nos": ("pcs", 1), "units": ("pcs", 1),
    "tablets": ("tablets", 1), "tablet": ("tablets", 1),
    "tabs": ("tablets", 1), "tab": ("tablets", 1),
    "capsules": ("capsules", 1), "capsule": ("capsules", 1),
    "sachets": ("sachets", 1), "sachet": ("sachets", 1),
    "strips": ("strips", 1), "strip": ("strips", 1),
    "count": ("pcs", 1),
}


def normalize_quantity(raw: str) -> dict:
    """
    Parse and normalize a quantity string.

    Examples:
        "200 g" → { value: 200.0, unit: "g", canonical_value: 200.0, canonical_unit: "g", display: "200 g" }
        "1 kg" → { value: 1.0, unit: "kg", canonical_value: 1000.0, canonical_unit: "g", display: "1 kg (1000 g)" }
        "180 Tablets" → { value: 180.0, unit: "tablets", ... }
    """
    if not raw:
        return _empty_qty(raw)

    m = _QTY_PATTERN.search(raw)
    if not m:
        return _empty_qty(raw)

    num_str = m.group(1).replace(",", "")
    unit_raw = m.group(2).lower()

    try:
        value = float(num_str)
    except ValueError:
        return _empty_qty(raw)

    canon_unit, multiplier = _UNIT_CANON.get(unit_raw, (unit_raw, 1))
    canonical_value = value * multiplier

    display = f"{value:g} {unit_raw}"
    if multiplier != 1:
        display += f" ({canonical_value:g} {canon_unit})"

    return {
        "raw": raw,
        "value": value,
        "unit": unit_raw,
        "canonical_value": canonical_value,
        "canonical_unit": canon_unit,
        "display": display,
        "found": True,
    }


def _empty_qty(raw: str) -> dict:
    return {"raw": raw, "value": None, "unit": None, "canonical_value": None,
            "canonical_unit": None, "display": raw or "Not Found", "found": False}


def compare_quantities(a: str, b: str) -> dict:
    """Compare two quantity strings after normalization."""
    na = normalize_quantity(a)
    nb = normalize_quantity(b)

    if not na["found"] and not nb["found"]:
        return {"status": "NOT_FOUND", "a": na, "b": nb}
    if not na["found"]:
        return {"status": "WEBSITE_ONLY", "a": na, "b": nb}
    if not nb["found"]:
        return {"status": "PACKAGE_ONLY", "a": na, "b": nb}

    # Same canonical unit → compare values
    if na["canonical_unit"] == nb["canonical_unit"]:
        diff_pct = abs(na["canonical_value"] - nb["canonical_value"]) / max(na["canonical_value"], 1) * 100
        status = "MATCH" if diff_pct < 1 else "MISMATCH"
    else:
        status = "UNIT_MISMATCH"

    return {"status": status, "a": na, "b": nb}


# ── Price normalization ────────────────────────────────────────────────────────

_PRICE_PATTERN = re.compile(r"(?:₹|Rs\.?|INR|MRP\s*[:\-]?)\s*([\d,]+\.?\d{0,2})", re.IGNORECASE)


def normalize_price(raw: str) -> dict:
    """Normalize a price string to a canonical float."""
    if not raw:
        return {"raw": raw, "value": None, "display": "Not Found", "found": False}
    m = _PRICE_PATTERN.search(raw)
    if not m:
        # Try bare number
        m2 = re.search(r"([\d,]+\.?\d{0,2})", raw)
        if m2:
            try:
                val = float(m2.group(1).replace(",", ""))
                return {"raw": raw, "value": val, "display": f"₹{val:.2f}", "found": True}
            except ValueError:
                pass
        return {"raw": raw, "value": None, "display": raw, "found": False}
    try:
        val = float(m.group(1).replace(",", ""))
        return {"raw": raw, "value": val, "display": f"₹{val:.2f}", "found": True}
    except ValueError:
        return {"raw": raw, "value": None, "display": raw, "found": False}


def compare_prices(a: str, b: str) -> dict:
    """Compare two price strings after normalization."""
    na = normalize_price(a)
    nb = normalize_price(b)
    if not na["found"] and not nb["found"]:
        return {"status": "NOT_FOUND", "a": na, "b": nb}
    if not na["found"]:
        return {"status": "PACKAGE_ONLY", "a": na, "b": nb}
    if not nb["found"]:
        return {"status": "WEBSITE_ONLY", "a": na, "b": nb}
    diff = abs(na["value"] - nb["value"])
    status = "MATCH" if diff < 0.5 else "MISMATCH"
    return {"status": status, "a": na, "b": nb, "difference": diff}
