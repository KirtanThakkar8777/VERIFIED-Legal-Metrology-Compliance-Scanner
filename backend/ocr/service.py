"""
ocr/service.py — Server-side OCR using EasyOCR (with pytesseract fallback).

First-time EasyOCR use will download ~100 MB of model weights automatically.
Subsequent runs load from cache and are fast.
"""
from __future__ import annotations

import io
import re
import os
from typing import Optional


_READER = None


def _get_reader():
    global _READER
    if _READER is None:
        import easyocr
        _READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _READER


def _try_easyocr(image_bytes: bytes) -> Optional[tuple[str, float]]:
    """Return (text_with_newlines, avg_confidence) using EasyOCR, or None on failure.
    Preserves line layout by grouping words by Y-position into lines.
    """
    try:
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        reader = _get_reader()
        results = reader.readtext(img_array)

        if not results:
            return ("", 0.0)

        img_h = img.height
        if img_h > 0:
            # Group by Y-band (~20px buckets) → reconstruct text lines
            line_groups: dict[int, list] = {}
            for bbox, text, conf in results:
                cy = (bbox[0][1] + bbox[2][1]) / 2
                band = int(cy / 20)
                line_groups.setdefault(band, []).append((bbox[0][0], text, conf))

            lines = []
            confs = []
            for band in sorted(line_groups.keys()):
                items = sorted(line_groups[band], key=lambda x: x[0])  # sort by x
                line_text = " ".join(t for _, t, _ in items)
                line_conf = sum(c for _, _, c in items) / len(items)
                lines.append(line_text)
                confs.append(line_conf)

            full_text = "\n".join(lines)
            avg_conf = sum(confs) / len(confs) if confs else 0.0
        else:
            texts = [r[1] for r in results]
            confs_list = [float(r[2]) for r in results]
            full_text = "\n".join(texts)
            avg_conf = sum(confs_list) / len(confs_list)

        return full_text, avg_conf

    except ImportError:
        return None
    except Exception:
        # Don't raise — return None so fallback (pytesseract) can run
        return None


def _try_pytesseract(image_bytes: bytes) -> Optional[tuple[str, float]]:
    """Return (text, 0.75 fixed confidence) using pytesseract, or None on failure."""
    try:
        import pytesseract
        from PIL import Image

        # Common Windows install paths
        win_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for p in win_paths:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break

        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang="eng")
        return text, 0.75

    except ImportError:
        return None
    except pytesseract.TesseractNotFoundError:
        return None
    except Exception as exc:
        raise RuntimeError(f"Pytesseract failed: {exc}") from exc


def _preprocess_for_ocr(image_bytes: bytes) -> list[tuple[str, bytes]]:
    """Return (name, image_bytes) variants with different preprocessing for multi-pass OCR."""
    from PIL import Image, ImageEnhance
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return [("raw", image_bytes)]

    w, h = img.size
    variants = []

    def _to_bytes(pil_img):
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()

    def _upscale(pil_img, target):
        iw, ih = pil_img.size
        long_side = max(iw, ih, 1)
        if long_side < target:
            scale = target / long_side
            return pil_img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
        return pil_img

    # Full image, upscaled to 1600px long side
    variants.append(("full", _to_bytes(_upscale(img, 1600))))

    # Contrast + sharpness enhanced
    enh = ImageEnhance.Contrast(img).enhance(2.0)
    enh = ImageEnhance.Sharpness(enh).enhance(1.8)
    variants.append(("contrast", _to_bytes(_upscale(enh, 1600))))

    # Bottom 45% crop — FSSAI / MRP / manufacturer usually here
    if h > 200:
        bottom = img.crop((0, int(h * 0.55), w, h))
        bottom = _upscale(bottom, 2000)
        bottom = ImageEnhance.Contrast(bottom).enhance(2.5)
        bottom = ImageEnhance.Sharpness(bottom).enhance(2.2)
        variants.append(("bottom", _to_bytes(bottom)))

    # Middle 40% — ingredients / nutrition zone
    if h > 300:
        mid = img.crop((0, int(h * 0.28), w, int(h * 0.72)))
        mid = _upscale(mid, 1800)
        mid = ImageEnhance.Contrast(mid).enhance(1.8)
        variants.append(("mid", _to_bytes(mid)))

    return variants


def extract_text_from_image(image_bytes: bytes) -> dict:
    """
    Extract text from an uploaded label image using multi-pass OCR.

    Pipeline:
      1. Preprocess image (upscale, contrast boost, crop variants)
      2. EasyOCR with Y-band line grouping (preserves layout)
      3. Combine passes for maximum coverage
      4. Run entity extractor on combined text
      5. Format into compliance-ready "Field: Value" structure
      6. Country of Origin inferred from address if not explicitly stated

    Returns:
      extracted_text  — compliance-ready structured text (used by scan engine)
      raw_ocr_text    — raw OCR output (for display/debugging)
      confidence      — average OCR confidence
      word_count      — word count
      fields_detected — list of field names found
    """
    # ── Step 1: Multi-pass OCR ────────────────────────────────────────────────
    variants = _preprocess_for_ocr(image_bytes)

    best_full_text = ""
    best_conf = 0.0
    crop_texts: list[str] = []

    # Pass A: Full image variants — keep the longest result
    for name, vbytes in variants:
        if name not in ("full", "contrast"):
            continue
        ocr_result = _try_easyocr(vbytes)
        if ocr_result and ocr_result[0] and len(ocr_result[0]) > len(best_full_text):
            best_full_text = ocr_result[0]
            best_conf = ocr_result[1]

    # Pass B: Crop zones — always run for FSSAI/manufacturer bottom zone
    for name, vbytes in variants:
        if name not in ("bottom", "mid"):
            continue
        ocr_result = _try_easyocr(vbytes)
        if ocr_result and ocr_result[0] and len(ocr_result[0]) > 20:
            crop_texts.append(ocr_result[0])

    # Combine: full + crop zones
    all_texts = [t for t in [best_full_text] + crop_texts if t]

    # Pytesseract fallback if EasyOCR got nothing
    if not all_texts:
        fallback = _try_pytesseract(image_bytes)
        if fallback and fallback[0]:
            all_texts = [fallback[0]]
            best_conf = fallback[1]

    if not all_texts:
        raise ValueError(
            "Could not extract text from this image. "
            "Please ensure the image is clear, well-lit, and shows the product label."
        )

    combined_raw = "\n\n".join(t for t in all_texts if t)

    # ── Step 2: Entity extraction ─────────────────────────────────────────────
    try:
        from url_scanner.intelligence.entity_extractor import extract_entities, _infer_country_from_address
        entities = extract_entities(combined_raw)
    except Exception:
        entities = {}

    # ── Step 3: Format as compliance-ready structured text ────────────────────
    lines: list[str] = []

    def _add(label: str, value: str):
        if value and value.strip():
            lines.append(f"{label}: {value.strip()}")

    # Manufacturer / Packer / Importer
    mfr_name = entities.get("manufacturer_name") or entities.get("manufacturer_raw") or ""
    mfr_addr = entities.get("manufacturer_address") or ""
    packer   = entities.get("packer_name") or entities.get("packer_raw") or ""
    importer = entities.get("importer_name") or entities.get("importer_raw") or ""

    if mfr_name and mfr_addr:
        _add("Manufactured by", f"{mfr_name}, {mfr_addr}")
    elif mfr_name:
        _add("Manufactured by", mfr_name)
    elif mfr_addr:
        _add("Manufactured by", mfr_addr)

    if packer and packer not in (mfr_name, mfr_addr):
        _add("Packed by", packer)
    if importer:
        _add("Imported by", importer)

    # Net Quantity
    qty = entities.get("net_quantity") or entities.get("net_weight") or ""
    _add("Net Quantity", qty)

    # MRP
    mrp = entities.get("mrp") or ""
    if mrp:
        mrp_num = re.sub(r"[^\d.]", "", str(mrp))
        if mrp_num:
            _add("MRP", f"Rs. {mrp_num}")

    # Dates
    mfg_date  = entities.get("mfg_date") or ""
    best_bef  = entities.get("expiry_date") or entities.get("best_before") or ""
    _add("Mfg. Date", mfg_date)
    _add("Best Before", best_bef)

    # Consumer Care
    cc_phone = entities.get("consumer_care_phone") or ""
    cc_email = entities.get("consumer_care_email") or ""
    _add("Consumer Care", cc_phone)
    _add("Consumer Care Email", cc_email)

    # Country of Origin — explicit or inferred from manufacturer address
    coo = entities.get("country_of_origin") or ""
    if not coo:
        try:
            from url_scanner.intelligence.entity_extractor import _infer_country_from_address
            addr_text = " ".join(filter(None, [mfr_name, mfr_addr, packer]))
            if addr_text:
                coo = _infer_country_from_address(addr_text)
            if not coo:
                coo = _infer_country_from_address(combined_raw)
        except Exception:
            pass
    _add("Country of Origin", coo)

    # FSSAI
    fssai = entities.get("fssai") or ""
    if fssai:
        lines.append(f"FSSAI Licence No. {fssai}")

    # Ingredients
    ingredients = entities.get("ingredients") or ""
    _add("Ingredients", ingredients[:600] if ingredients else "")

    # Batch / Lot
    batch = entities.get("batch_no") or ""
    _add("Batch No.", batch)

    # ── Step 4: Append cleaned raw OCR as fallback ────────────────────────────
    clean_raw_lines = []
    for ln in combined_raw.splitlines():
        stripped = ln.strip()
        if (len(stripped) >= 4
                and not set(stripped) <= set("=-_*#|[]")
                and "Not Detected" not in stripped):
            clean_raw_lines.append(stripped)

    if clean_raw_lines:
        lines.append("")
        lines.append("--- Extracted Text ---")
        lines.extend(clean_raw_lines)

    compliance_text = "\n".join(lines)

    # Fields detected list for the UI
    fields_detected = [k for k, v in entities.items() if v and k != "country_inferred_from_address"]
    if coo and "country_of_origin" not in fields_detected:
        fields_detected.append("country_of_origin (inferred)")

    return {
        "extracted_text":  compliance_text,
        "raw_ocr_text":    combined_raw,
        "confidence":      round(best_conf, 4),
        "word_count":      len(compliance_text.split()),
        "fields_detected": fields_detected,
    }
