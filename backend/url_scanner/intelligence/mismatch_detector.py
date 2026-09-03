"""
url_scanner/intelligence/mismatch_detector.py
Compare website data vs. package (OCR) data and flag mismatches.
"""
from __future__ import annotations
from .data_normalizer import compare_quantities, compare_prices, normalize_price


def detect_mismatches(model: dict) -> list[dict]:
    """
    Compare website vs package fields and return list of comparison results.

    Each result:
    {
      field: str,
      website_value: str,
      package_value: str,
      status: "MATCH" | "MISMATCH" | "REVIEW" | "WEBSITE_ONLY" | "PACKAGE_ONLY" | "NOT_FOUND",
      notes: str,
    }
    """
    results = []

    # ── Quantity comparison ───────────────────────────────────────────────────
    w_qty = model.get("quantity", {}).get("website_raw", "")
    p_qty = model.get("quantity", {}).get("package_raw", "")

    if w_qty or p_qty:
        cmp = compare_quantities(w_qty, p_qty)
        results.append({
            "field": "Net Quantity",
            "website_value": w_qty or "Not Found",
            "package_value": p_qty or "Not Found",
            "status": cmp["status"],
            "notes": _qty_note(cmp),
        })

    # ── MRP comparison ────────────────────────────────────────────────────────
    w_mrp = model.get("commerce", {}).get("mrp_raw", "")
    # For package MRP, look in ocr_text
    ocr = model.get("ocr_text", "")
    import re
    mrp_ocr_m = re.search(r"(?:MRP|M\.R\.P\.)\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,]+\.?\d{0,2})", ocr, re.IGNORECASE)
    p_mrp = mrp_ocr_m.group(1) if mrp_ocr_m else ""

    if w_mrp or p_mrp:
        cmp = compare_prices(w_mrp, p_mrp)
        results.append({
            "field": "MRP",
            "website_value": normalize_price(w_mrp)["display"] if w_mrp else "Not Found",
            "package_value": normalize_price(p_mrp)["display"] if p_mrp else "Not Found",
            "status": cmp["status"],
            "notes": _price_note(cmp),
        })

    # ── Country of Origin ─────────────────────────────────────────────────────
    declared = model.get("origin", {}).get("declared_country", "")
    detected = model.get("origin", {}).get("detected_country", "")

    if declared or detected:
        if not declared:
            status, notes = "PACKAGE_ONLY", "Country of Origin only found via address detection"
        elif not detected:
            status, notes = "WEBSITE_ONLY", "Country declared on page, not confirmed from OCR"
        elif declared.lower() == detected.lower():
            status, notes = "MATCH", "Declared and detected country agree"
        else:
            status, notes = "REVIEW", f"Declared: {declared}, Detected: {detected}"
        results.append({
            "field": "Country of Origin",
            "website_value": declared or "Not Found",
            "package_value": detected or "Not Found",
            "status": status,
            "notes": notes,
        })

    # ── Brand ────────────────────────────────────────────────────────────────
    w_brand = model.get("product", {}).get("brand", "")
    if w_brand:
        results.append({
            "field": "Brand",
            "website_value": w_brand,
            "package_value": "Not verified from package",
            "status": "WEBSITE_ONLY",
            "notes": "Brand confirmed from product listing",
        })

    # ── Manufacturer ─────────────────────────────────────────────────────────
    mfr = model.get("manufacturer", {})
    mfr_name = mfr.get("name", "") or mfr.get("address_raw", "")
    if mfr_name:
        source = mfr.get("source", "webpage")
        results.append({
            "field": "Manufacturer",
            "website_value": mfr_name if source == "webpage" else "Not Found on website",
            "package_value": mfr_name if source == "ocr" else "Not verified from package",
            "status": "WEBSITE_ONLY" if source == "webpage" else "PACKAGE_ONLY",
            "notes": f"Source: {source}",
        })

    return results


def _qty_note(cmp: dict) -> str:
    status = cmp["status"]
    a = cmp.get("a", {})
    b = cmp.get("b", {})
    if status == "MATCH":
        return f"Both normalized to {a.get('canonical_value', '')} {a.get('canonical_unit', '')}"
    if status == "MISMATCH":
        return f"Website: {a.get('display', '')} vs Package: {b.get('display', '')}"
    if status == "WEBSITE_ONLY":
        return f"Only website value found: {a.get('display', '')}"
    if status == "PACKAGE_ONLY":
        return f"Only package value found: {b.get('display', '')}"
    return ""


def _price_note(cmp: dict) -> str:
    status = cmp["status"]
    if status == "MATCH":
        return "MRP matches between website and package"
    if status == "MISMATCH":
        diff = cmp.get("difference", 0)
        return f"Price difference: ₹{diff:.2f} — REVIEW REQUIRED"
    if status == "WEBSITE_ONLY":
        return "MRP found only on website listing"
    if status == "PACKAGE_ONLY":
        return "MRP found only on package/OCR"
    return ""
