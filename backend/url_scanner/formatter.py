"""
url_scanner/formatter.py
Format the normalized product model into structured textarea text.
"""
from __future__ import annotations


def _section(title: str) -> str:
    line = "=" * 52
    return f"\n{line}\n{title}\n{line}\n"


def _field(label: str, value: str, indent: int = 0) -> str:
    v = (value or "Not Detected").strip()
    prefix = " " * indent
    return f"{prefix}{label}:\n{prefix}{v}\n"


def _status_line(status: str) -> str:
    icons = {
        "MATCH": "✓ MATCH",
        "MISMATCH": "⚠ MISMATCH — REVIEW REQUIRED",
        "REVIEW": "⚠ REVIEW",
        "WEBSITE_ONLY": "ℹ Website Only (verify on package)",
        "PACKAGE_ONLY": "ℹ Package Only",
        "NOT_FOUND": "✗ Not Found",
        "UNIT_MISMATCH": "⚠ Unit Mismatch — verify manually",
    }
    return icons.get(status, status)


def format_product(model: dict, platform_info: dict, images: list[dict], comparisons: list[dict]) -> str:
    """
    Format the complete normalized product model into textarea-ready text.
    """
    lines = []

    # ─────────────────────────────────────────────────────────────────────────
    # HEADER
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("PRODUCT INFORMATION"))

    product = model.get("product", {})
    lines.append(_field("Product Name",  product.get("name", "")))
    lines.append(_field("Brand",         product.get("brand", "")))
    lines.append(_field("Category",      product.get("category", "")))
    lines.append(_field("Variant",       product.get("variant", "")))
    lines.append(_field("SKU / Model",   product.get("sku", "")))
    if product.get("description"):
        desc = product["description"][:200].replace("\n", " ")
        lines.append(_field("Description", desc))

    # ─────────────────────────────────────────────────────────────────────────
    # E-COMMERCE INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("E-COMMERCE INFORMATION"))

    commerce = model.get("commerce", {})
    lines.append(_field("Platform",       platform_info.get("display_name", "")))
    lines.append(_field("Seller",         commerce.get("seller", "")))

    mrp_raw = commerce.get("mrp_raw", "")
    if mrp_raw:
        from url_scanner.intelligence.data_normalizer import normalize_price
        mrp_norm = normalize_price(mrp_raw)
        lines.append(_field("MRP",  mrp_norm["display"]))
    else:
        lines.append(_field("MRP",  ""))

    lines.append(_field("Selling Price",  commerce.get("selling_price_raw", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # MANUFACTURER INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("MANUFACTURER INFORMATION"))
    mfr = model.get("manufacturer", {})
    parsed = mfr.get("parsed", {})

    lines.append(_field("Manufacturer",       mfr.get("name") or mfr.get("address_raw", "")))
    if parsed.get("address_line1"):
        addr = "\n".join(filter(None, [
            parsed.get("address_line1", ""),
            parsed.get("address_line2", ""),
            parsed.get("city", ""),
            f"{parsed.get('state', '')} - {parsed.get('pincode', '')}".strip(" -"),
            parsed.get("country", ""),
        ]))
        lines.append(_field("Address",  addr))
    elif mfr.get("address_raw"):
        lines.append(_field("Address",  mfr["address_raw"]))
    else:
        lines.append(_field("Address",  ""))

    mc = mfr.get("country", "")
    mconf = mfr.get("country_confidence", 0)
    lines.append(_field("Manufacturer Country", mc))
    if mc and mconf:
        lines.append(_field("Confidence",        f"{mconf}%"))

    # ─────────────────────────────────────────────────────────────────────────
    # PACKER INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("PACKER INFORMATION"))
    packer = model.get("packer", {})
    lines.append(_field("Packer",         packer.get("name") or packer.get("address_raw", "")))
    lines.append(_field("Packer Address", packer.get("parsed", {}).get("full_address", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # IMPORTER INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("IMPORTER INFORMATION"))
    importer = model.get("importer", {})
    lines.append(_field("Importer",         importer.get("name") or importer.get("address_raw", "")))
    lines.append(_field("Importer Country", importer.get("country", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # COUNTRY OF ORIGIN
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("COUNTRY OF ORIGIN"))
    origin = model.get("origin", {})
    lines.append(_field("Declared Country of Origin", origin.get("declared_country", "")))
    lines.append(_field("Detected Country",           origin.get("detected_country", "")))
    conf = origin.get("confidence", 0)
    if conf:
        lines.append(_field("Confidence",  f"{conf}%"))

    pc = model.get("product_classification", {})
    lines.append(_field("Product Classification", pc.get("classification", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # QUANTITY INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("QUANTITY INFORMATION"))
    qty = model.get("quantity", {})
    lines.append(_field("Website Quantity",  qty.get("website_raw", "")))
    lines.append(_field("Package Quantity",  qty.get("package_raw", "")))
    norm = qty.get("normalized") or {}
    lines.append(_field("Normalized",        norm.get("display", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # DATES
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("DATES"))
    dates = model.get("dates", {})
    lines.append(_field("Manufacturing Date",    dates.get("mfg_date", "")))
    lines.append(_field("Packing Date",          dates.get("packing_date", "")))
    lines.append(_field("Expiry / Best Before",  dates.get("expiry_date") or dates.get("best_before", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # CONSUMER CARE
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("CONSUMER CARE"))
    cc = model.get("consumer_care", {})
    lines.append(_field("Consumer Care", cc.get("raw", "")))
    lines.append(_field("Phone",         cc.get("phone", "")))
    lines.append(_field("Email",         cc.get("email", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # REGULATORY INFORMATION
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("REGULATORY / FOOD INFORMATION"))
    reg = model.get("regulatory", {})
    lines.append(_field("FSSAI Licence Number", reg.get("fssai", "")))
    lines.append(_field("Barcode / EAN",         reg.get("barcode", "")))
    lines.append(_field("Batch / Lot Number",    reg.get("batch_no", "")))
    decls = reg.get("declarations", [])
    if decls:
        lines.append(_field("Legal Declarations", "\n".join(decls)))

    # OCR text (if available) — truncated
    ocr = model.get("ocr_text", "")
    if ocr and len(ocr) > 20:
        lines.append(_section("OCR EXTRACTED TEXT (Packaging Images)"))
        lines.append(ocr[:1500])
        if len(ocr) > 1500:
            lines.append("... [truncated — full text available in scan history]")

    # ─────────────────────────────────────────────────────────────────────────
    # IMAGE ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("IMAGE ANALYSIS"))
    total_imgs = len(images)
    packaging_imgs = sum(1 for img in images if img.get("classification", {}).get("is_packaging", False))
    lines.append(f"Product Images Found:\n{total_imgs}\n")
    lines.append(f"Packaging Images Identified:\n{packaging_imgs}\n")
    if total_imgs:
        lines.append("Image URLs (top 5):")
        for img in images[:5]:
            clf = img.get("classification", {})
            cat = clf.get("category", "unknown").replace("_", " ").title()
            lines.append(f"  [{cat}] {img.get('url', '')[:80]}")

    # ─────────────────────────────────────────────────────────────────────────
    # WEBSITE ↔ PACKAGE COMPARISON
    # ─────────────────────────────────────────────────────────────────────────
    if comparisons:
        lines.append(_section("VERIFICATION STATUS (Website ↔ Package)"))
        for c in comparisons:
            field = c.get("field", "")
            w_val = c.get("website_value", "Not Found")
            p_val = c.get("package_value", "Not Found")
            status = _status_line(c.get("status", ""))
            notes = c.get("notes", "")
            lines.append(f"{field}:\n  Website:  {w_val}\n  Package:  {p_val}\n  Status:   {status}")
            if notes:
                lines.append(f"  Note:     {notes}")
            lines.append("")

    # ─────────────────────────────────────────────────────────────────────────
    # DATA SOURCE
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(_section("DATA SOURCE"))
    lines.append(f"Website Data:\n{platform_info.get('display_name', 'Unknown')} Product Page\n")
    lines.append(f"Packaging Data:\n{'Product Images + OCR' if ocr else 'Not available — use Label Image tab to add packaging OCR'}\n")
    lines.append("Note: AI/OCR extraction is an assistance mechanism. Manual verification "
                 "required before making any legal compliance determination.\n")

    # ─────────────────────────────────────────────────────────────────────────
    # Source marker for compliance engine
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(f"Source: {platform_info.get('display_name', 'E-Commerce')} e-commerce listing (online marketplace)")

    return "\n".join(lines)
