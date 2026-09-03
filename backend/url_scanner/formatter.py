"""
url_scanner/formatter.py
Format the normalized product model into structured textarea text.

RULE: Only write "Not Detected" when a field is truly empty.
      NEVER pre-fill "Not Detected" before extraction runs.
"""
from __future__ import annotations


_LINE = "=" * 52


def _section(title: str) -> str:
    return f"\n{_LINE}\n{title}\n{_LINE}\n"


def _field(label: str, value: str, indent: str = "") -> str:
    """Write a label:value pair. Skip entirely if value is empty."""
    v = (value or "").strip()
    if not v:
        return f"{indent}{label}:\nNot Detected\n"
    return f"{indent}{label}:\n{indent}{v}\n"


def _field_optional(label: str, value: str) -> str:
    """Write only if value is present — skip if empty."""
    v = (value or "").strip()
    if not v:
        return ""
    return f"{label}:\n{v}\n"


def _status_icon(status: str) -> str:
    return {
        "MATCH": "✓ MATCH",
        "MISMATCH": "⚠ MISMATCH — REVIEW REQUIRED",
        "REVIEW": "⚠ REVIEW",
        "WEBSITE_ONLY": "ℹ Website Only",
        "PACKAGE_ONLY": "ℹ Package Only (not on webpage)",
        "NOT_FOUND": "✗ Not Found",
        "UNIT_MISMATCH": "⚠ Unit Mismatch",
    }.get(status, status)


def _source_tag(source: str) -> str:
    if source == "ocr":
        return " [Source: Packaging Image]"
    if source == "webpage":
        return " [Source: Webpage]"
    return ""


def format_product(
    model: dict,
    platform_info: dict,
    all_images: list[dict],
    comparisons: list[dict],
) -> str:
    parts: list[str] = []

    product = model.get("product", {})
    commerce = model.get("commerce", {})
    manufacturer = model.get("manufacturer", {})
    packer = model.get("packer", {})
    importer = model.get("importer", {})
    origin = model.get("origin", {})
    qty = model.get("quantity", {})
    dates = model.get("dates", {})
    cc = model.get("consumer_care", {})
    reg = model.get("regulatory", {})
    ocr_stats = model.get("ocr_stats", {})

    # ── PRODUCT INFORMATION ────────────────────────────────────────────────────
    parts.append(_section("PRODUCT INFORMATION"))
    parts.append(_field("Product Name", product.get("name", "")))
    parts.append(_field("Brand",        product.get("brand", "")))
    parts.append(_field_optional("Category",  product.get("category", "")))
    parts.append(_field_optional("Variant",   product.get("variant", "")))
    parts.append(_field_optional("SKU",       product.get("sku", "")))
    parts.append(_field_optional("Vegetarian / Non-Vegetarian", product.get("veg_status", "")))
    desc = (product.get("description") or "").strip()[:200]
    if desc:
        parts.append(f"Description:\n{desc}\n")

    # ── E-COMMERCE INFORMATION ─────────────────────────────────────────────────
    parts.append(_section("E-COMMERCE INFORMATION"))
    parts.append(_field("Platform", platform_info.get("display_name", "")))
    parts.append(_field_optional("Seller", commerce.get("seller", "")))

    mrp_norm = commerce.get("mrp_normalized") or {}
    if mrp_norm.get("found"):
        parts.append(f"MRP:\n{mrp_norm['display']}\n")
    elif commerce.get("mrp_raw"):
        parts.append(f"MRP:\n{commerce['mrp_raw']}\n")
    else:
        parts.append("MRP:\nNot Detected\n")

    parts.append(_field_optional("Selling Price", commerce.get("selling_price_raw", "")))

    # Website quantity
    w_qty = qty.get("website_raw", "")
    parts.append(_field_optional("Listed Quantity", w_qty))

    # ── MANUFACTURER INFORMATION ───────────────────────────────────────────────
    parts.append(_section("MANUFACTURER INFORMATION"))
    mfr_name = manufacturer.get("name", "") or manufacturer.get("address_raw", "")
    mfr_src = _source_tag(manufacturer.get("source", ""))

    if mfr_name:
        parts.append(f"Manufacturer{mfr_src}:\n{mfr_name}\n")
    else:
        parts.append("Manufacturer:\nNot Detected\n")

    # Address — prefer structured, fallback to raw
    mfr_addr = manufacturer.get("address_structured", "") or manufacturer.get("address_raw", "")
    if mfr_addr:
        # Clean up if same as manufacturer name
        if mfr_addr.strip() != mfr_name.strip():
            parts.append(f"Manufacturer Address:\n{mfr_addr}\n")

    mfr_country = manufacturer.get("country", "")
    mfr_conf = manufacturer.get("country_confidence", 0)
    if mfr_country and mfr_country != "Unknown":
        parts.append(f"Manufacturer Country:\n{mfr_country}\n")
        if mfr_conf:
            parts.append(f"Country Confidence:\n{mfr_conf}% (from address analysis)\n")
    else:
        parts.append("Manufacturer Country:\nNot Detected\n")

    # ── PACKER INFORMATION ─────────────────────────────────────────────────────
    packer_name = packer.get("name", "") or packer.get("address_raw", "")
    packer_src = _source_tag(packer.get("source", ""))
    if packer_name and packer_name.strip() != mfr_name.strip():
        parts.append(_section("PACKER INFORMATION"))
        parts.append(f"Packer{packer_src}:\n{packer_name}\n")
        p_addr = packer.get("address_structured", "") or packer.get("address_raw", "")
        if p_addr and p_addr.strip() != packer_name.strip():
            parts.append(f"Packer Address:\n{p_addr}\n")

    # ── IMPORTER INFORMATION ───────────────────────────────────────────────────
    imp_name = importer.get("name", "") or importer.get("address_raw", "")
    if imp_name:
        parts.append(_section("IMPORTER INFORMATION"))
        imp_src = _source_tag(importer.get("source", ""))
        parts.append(f"Importer{imp_src}:\n{imp_name}\n")
        i_addr = importer.get("address_structured", "") or importer.get("address_raw", "")
        if i_addr and i_addr.strip() != imp_name.strip():
            parts.append(f"Importer Address:\n{i_addr}\n")
        if importer.get("country"):
            parts.append(f"Importer Country:\n{importer['country']}\n")

    # ── COUNTRY OF ORIGIN ──────────────────────────────────────────────────────
    parts.append(_section("COUNTRY OF ORIGIN"))
    declared = origin.get("declared_country", "")
    detected = origin.get("detected_country", "")
    conf = origin.get("confidence", 0)

    if declared:
        parts.append(f"Declared Country of Origin:\n{declared}\n")
    else:
        parts.append("Declared Country of Origin:\nNot Detected\n")

    if detected and detected != "Unknown":
        src_note = "(from address analysis)" if not declared else "(confirmed)"
        parts.append(f"Detected Country:\n{detected} {src_note}\n")
        if conf:
            parts.append(f"Detection Confidence:\n{conf}%\n")

    pc = model.get("product_classification", {})
    if pc.get("classification"):
        parts.append(f"Product Classification:\n{pc['classification']}\n")

    # ── PACKAGE INFORMATION ────────────────────────────────────────────────────
    parts.append(_section("PACKAGE INFORMATION"))
    p_qty = qty.get("package_raw", "")
    if p_qty:
        parts.append(f"Net Weight / Quantity [Package]:\n{p_qty}\n")
    elif w_qty:
        parts.append(f"Net Weight / Quantity [Website]:\n{w_qty}\n")
    else:
        parts.append("Net Weight / Quantity:\nNot Detected\n")

    norm = qty.get("normalized") or {}
    if norm.get("found"):
        parts.append(f"Normalized Quantity:\n{norm['display']}\n")

    # ── REGULATORY INFORMATION ─────────────────────────────────────────────────
    parts.append(_section("REGULATORY INFORMATION"))
    parts.append(_field("FSSAI Licence Number", reg.get("fssai", "")))

    barcode = reg.get("barcode", "")
    barcode_type = reg.get("barcode_type", "")
    if barcode:
        btype = f" ({barcode_type})" if barcode_type else ""
        parts.append(f"Barcode{btype}:\n{barcode}\n")
    else:
        parts.append("Barcode:\nNot Detected\n")

    qr = reg.get("qr_code", "")
    if qr:
        parts.append(f"QR Code:\n{qr[:200]}\n")

    batch = reg.get("batch_no", "")
    parts.append(_field_optional("Batch / Lot Number", batch))

    decls = reg.get("declarations", [])
    if decls:
        parts.append(f"Legal Declarations:\n" + "\n".join(decls) + "\n")

    # ── INGREDIENTS ────────────────────────────────────────────────────────────
    ingredients = model.get("ingredients", "")
    if ingredients:
        parts.append(_section("INGREDIENTS"))
        parts.append(f"{ingredients}\n")

    # ── ALLERGEN INFORMATION ───────────────────────────────────────────────────
    allergen = model.get("allergen_info", "")
    if allergen:
        parts.append(_section("ALLERGEN INFORMATION"))
        parts.append(f"{allergen}\n")

    # ── STORAGE INSTRUCTIONS ───────────────────────────────────────────────────
    storage = model.get("storage_instructions", "")
    if storage:
        parts.append(_section("STORAGE INSTRUCTIONS"))
        parts.append(f"{storage}\n")

    # ── DATES ─────────────────────────────────────────────────────────────────
    parts.append(_section("DATES"))
    parts.append(_field("Manufacturing Date",   dates.get("mfg_date", "")))
    parts.append(_field("Packing Date",         dates.get("packing_date", "")))
    parts.append(_field("Expiry / Best Before", dates.get("expiry_date", "")))

    # ── CONSUMER CARE ──────────────────────────────────────────────────────────
    parts.append(_section("CONSUMER CARE"))
    cc_raw = cc.get("raw", "")
    cc_phone = cc.get("phone", "")
    cc_email = cc.get("email", "")

    if cc_raw:
        parts.append(f"Consumer Care:\n{cc_raw}\n")
    if cc_phone:
        parts.append(f"Phone:\n{cc_phone}\n")
    if cc_email:
        parts.append(f"Email:\n{cc_email}\n")
    if not cc_raw and not cc_phone and not cc_email:
        parts.append("Consumer Care:\nNot Detected\n")

    # ── WEBSITE ↔ PACKAGE COMPARISON ──────────────────────────────────────────
    if comparisons:
        parts.append(_section("WEBSITE ↔ PACKAGE COMPARISON"))
        for c in comparisons:
            field = c.get("field", "")
            w_val = c.get("website_value", "Not Found")
            p_val = c.get("package_value", "Not Found")
            status = _status_icon(c.get("status", ""))
            notes = c.get("notes", "")
            parts.append(f"{field}:\n  Website:  {w_val}\n  Package:  {p_val}\n  Status:   {status}")
            if notes:
                parts.append(f"  Note:     {notes}")
            parts.append("")

    # ── IMAGE ANALYSIS ─────────────────────────────────────────────────────────
    if ocr_stats:
        parts.append(_section("IMAGE ANALYSIS"))
        parts.append(
            f"Images Found: {len(all_images)}\n"
            f"Images Downloaded: {ocr_stats.get('images_downloaded', 0)}/{ocr_stats.get('images_processed', 0)}\n"
            f"OCR Characters Extracted: {ocr_stats.get('ocr_char_count', 0)}\n"
            f"Average OCR Confidence: {ocr_stats.get('avg_confidence', 0)*100:.0f}%\n"
        )
        # Per-image results
        img_results = ocr_stats.get("image_results", [])
        for ir in img_results:
            url_short = ir.get("url", "")[-60:]
            ok = "✓" if ir["downloaded"] else "✗"
            chars = ir.get("ocr_text_len", 0)
            conf = ir.get("ocr_confidence", 0)
            bc = ir.get("barcodes", [])
            bc_str = f" | Barcode: {bc[0]['value']}" if bc else ""
            parts.append(f"  {ok} ...{url_short} | {chars} chars | {conf*100:.0f}% conf{bc_str}\n")

    # ── OCR RAW TEXT ──────────────────────────────────────────────────────────
    ocr_text = model.get("ocr_text", "")
    if ocr_text and len(ocr_text) > 20:
        parts.append(_section("OCR EXTRACTED TEXT (Packaging Images)"))
        parts.append(ocr_text[:2000])
        if len(ocr_text) > 2000:
            parts.append("\n... [truncated]")
        parts.append("")

    # ── DATA SOURCE ────────────────────────────────────────────────────────────
    parts.append(_section("DATA SOURCE"))
    parts.append(
        f"Webpage Data:\n{platform_info.get('display_name', 'E-Commerce')} product listing\n"
    )
    if ocr_stats and ocr_stats.get("ocr_char_count", 0) > 20:
        imgs_dl = ocr_stats.get("images_downloaded", 0)
        parts.append(f"Packaging Data:\n{imgs_dl} product image(s) downloaded and OCR analysed\n")
    else:
        parts.append(
            "Packaging Data:\nNot available — "
            "use the Label Image tab to upload packaging photos for full OCR analysis\n"
        )

    parts.append(
        "Note:\nAI/OCR extraction is an assistance mechanism. "
        "Manual verification required before making any legal compliance determination.\n"
    )

    # ── Source marker for compliance engine ────────────────────────────────────
    parts.append(
        f"Source: {platform_info.get('display_name', 'E-Commerce')} "
        "e-commerce listing (online marketplace)"
    )

    return "\n".join(p for p in parts if p is not None)
