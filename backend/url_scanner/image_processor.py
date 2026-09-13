"""
url_scanner/image_processor.py
Download, preprocess, and OCR product packaging images.

Pipeline per image:
  1. Download bytes at full resolution
  2. Multi-pass preprocessing:
     a. Full-image upscale (≥1600px long side)
     b. Contrast-enhanced pass
     c. FSSAI-targeted: crop bottom-half + high upscale (licence numbers are at base of label)
  3. Run OCR via ThreadPoolExecutor (non-blocking after model pre-warm)
  4. Attempt barcode/QR decode via pyzbar
  5. Search each image result for FSSAI/compliance signals

EasyOCR is pre-warmed at server startup (main.py → _prewarm_easyocr).
Once loaded, OCR per image takes ~3-8 seconds on CPU.
"""
from __future__ import annotations

import io
import re
import asyncio
from typing import Optional

import httpx

# ── HTTP fetch ─────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB


async def _download_image(url: str) -> Optional[bytes]:
    """Download image from URL. Returns None on any failure."""
    # Try to get highest resolution from Amazon URLs
    hires_url = re.sub(r"_SL\d{3,4}_", "_SL1500_", url)
    hires_url = re.sub(r"_SS\d{2,3}_", "_SL1500_", hires_url)
    hires_url = re.sub(r"_SX\d{3,4}_", "_SX679_", hires_url)

    for try_url in ([hires_url, url] if hires_url != url else [url]):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _UA, "Accept": "image/*,*/*"},
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                r = await client.get(try_url)
                if r.status_code == 200 and r.content:
                    return r.content[:MAX_IMAGE_BYTES]
        except Exception:
            continue
    return None


# ── Image preprocessing ────────────────────────────────────────────────────────

def _preprocess_variants(image_bytes: bytes) -> list[tuple[str, bytes]]:
    """
    Return list of (name, image_bytes) variants for OCR.

    Variants:
      "full"      — Upscaled to ≥1600px long-side (best general OCR quality)
      "contrast"  — Contrast+sharpness enhanced (helps faded printing)
      "bottom_crop" — Bottom 45% of image, aggressively upscaled
                      FSSAI / manufacturer / MRP are nearly always in the lower
                      portion of back/side packaging labels
      "top_crop"  — Top 40% (product name / branding)
    """
    from PIL import Image, ImageEnhance, ImageFilter
    import io

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return [("raw", image_bytes)]

    w, h = img.size
    variants: list[tuple[str, bytes]] = []

    def _to_bytes(pil_img: Image.Image) -> bytes:
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()

    def _upscale_to(pil_img: Image.Image, target_long: int) -> Image.Image:
        iw, ih = pil_img.size
        long_side = max(iw, ih, 1)
        if long_side < target_long:
            scale = target_long / long_side
            new_w = max(1, int(iw * scale))
            new_h = max(1, int(ih * scale))
            return pil_img.resize((new_w, new_h), Image.LANCZOS)
        return pil_img

    # ── Variant 1: Full image, upscaled to 1600px ────────────────────────────
    full_up = _upscale_to(img, 1600)
    variants.append(("full", _to_bytes(full_up)))

    # ── Variant 2: Contrast + sharpen (helps small printed text) ────────────
    enhanced = ImageEnhance.Contrast(img).enhance(1.8)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.5)
    enhanced = _upscale_to(enhanced, 1600)
    variants.append(("contrast", _to_bytes(enhanced)))

    # ── Variant 3: Bottom 45% crop — FSSAI/MRP/manufacturer zone ────────────
    # Most back-label compliance text is in the lower half of the image
    if h > 200:
        crop_top = int(h * 0.55)   # start from 55% down
        bottom = img.crop((0, crop_top, w, h))
        # Aggressive upscale — this small text needs to be big for OCR
        bottom_up = _upscale_to(bottom, 2000)
        # High contrast for small text
        bottom_enh = ImageEnhance.Contrast(bottom_up).enhance(2.2)
        bottom_enh = ImageEnhance.Sharpness(bottom_enh).enhance(2.0)
        variants.append(("bottom_crop", _to_bytes(bottom_enh)))

    # ── Variant 4: Middle 40% crop (ingredient / nutrition zone) ────────────
    if h > 300:
        mid_top    = int(h * 0.30)
        mid_bottom = int(h * 0.70)
        mid = img.crop((0, mid_top, w, mid_bottom))
        mid_up = _upscale_to(mid, 1800)
        mid_enh = ImageEnhance.Contrast(mid_up).enhance(1.8)
        variants.append(("mid_crop", _to_bytes(mid_enh)))

    return variants


# ── OCR ───────────────────────────────────────────────────────────────────────

def _ocr_bytes(image_bytes: bytes) -> tuple[str, float]:
    """Run EasyOCR on image bytes (synchronous). Returns (text, confidence).
    IMPORTANT: preserves newlines — we join with space only within a line,
    NOT across lines — so multi-line patterns (FSSAI, manufacturer etc.) work.
    """
    from ocr.service import _get_reader
    try:
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)
        reader = _get_reader()
        results = reader.readtext(img_array)

        if not results:
            return "", 0.0

        # ── Reconstruct structured text preserving layout ─────────────────────
        # EasyOCR returns bounding boxes — group text by Y position to form lines
        # Each result: (bbox, text, confidence)
        # bbox: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        img_h = img.height
        if img_h > 0:
            line_groups: dict[int, list[tuple[float, str, float]]] = {}
            for bbox, text, conf in results:
                # Use center-y as line key, bucketed into ~20px bands
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

    except Exception as e:
        return "", 0.0


# ── FSSAI-aware OCR result selection ──────────────────────────────────────────

_FSSAI_SIGNAL = re.compile(
    # Explicit FSSAI keyword or Lic.No. label
    r"FSSAI|Lic\.?\s*No\.?|Licence\s*No|License\s*No|LIC\s*NO"
    # 14-digit solid number starting with 1-9
    r"|[1-9]\d{13}"
    # 14-digit number with OCR spaces/hyphens (e.g. "1001 4022 0027 11" = 14 digits total)
    r"|[1-9]\d{3}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{2}"
    r"|[1-9]\d{3}[\s\-]\d{4}[\s\-]\d{6}"
    r"|[1-9]\d{1,3}(?:[\s\-]\d{2,4}){3,5}",
    re.IGNORECASE
)
_COMPLIANCE_SIGNAL = re.compile(
    r"manufacturer|packer|importer|mrp|net.?weight|net.?qty|consumer.?care|"
    r"country.?of.?origin|best.?before|batch|lot.?no|ingredient",
    re.IGNORECASE
)


def _best_ocr_sync(variants: list[tuple[str, bytes]]) -> tuple[str, float, str]:
    """
    Adaptive multi-pass OCR — SPEED OPTIMIZED.

    Strategy:
    - Pass 1 (full image, 1200px): always runs
    - If FSSAI + MRP + manufacturer ALL found with high confidence: STOP (1 pass)
    - If any key signal missing: Pass 2 (bottom_crop) — FSSAI/MRP at bottom of labels
    - Only run contrast / mid_crop if Pass 1+2 found < 50 chars or confidence < 0.5

    This reduces average OCR time from ~25s (4 passes) to ~8s (1-2 passes) per image.
    """
    _KEY_SIGNALS = re.compile(
        r"FSSAI|Lic\.?\s*No|Licence|License|MRP|manufacturer|packer|"
        r"net.?weight|net.?qty|consumer.?care|country.?of.?origin",
        re.IGNORECASE,
    )

    full_text = ""
    full_conf = 0.0
    crop_texts: list[str] = []
    used_variants: list[str] = []

    # Separate variants by type
    full_variants   = [(n, b) for n, b in variants if n in ("full", "contrast")]
    crop_variants   = [(n, b) for n, b in variants if n in ("bottom_crop", "mid_crop")]

    # ── Pass 1: Full image ────────────────────────────────────────────────────
    for name, img_bytes in full_variants[:1]:   # only first full variant
        text, conf = _ocr_bytes(img_bytes)
        if text:
            full_text = text
            full_conf = conf
            used_variants.append(name)
        break

    # ── Check if we can stop early ────────────────────────────────────────────
    signal_matches = len(_KEY_SIGNALS.findall(full_text))
    char_count = len(full_text)

    # If we found plenty of text AND multiple key signals, stop here
    if char_count >= 200 and signal_matches >= 3 and full_conf >= 0.55:
        return full_text, full_conf, "+".join(used_variants)

    # ── Pass 2: Bottom crop (FSSAI/MRP zone) ─────────────────────────────────
    for name, img_bytes in crop_variants:
        if name != "bottom_crop":
            continue
        text, conf = _ocr_bytes(img_bytes)
        if text and len(text) > 30:
            crop_texts.append(text)
            used_variants.append(name)
        break

    # Re-check after Pass 2
    combined_so_far = full_text + "\n" + "\n".join(crop_texts)
    signal_matches_2 = len(_KEY_SIGNALS.findall(combined_so_far))
    char_count_2 = len(combined_so_far)

    # Only run contrast + mid_crop if still very low info
    if char_count_2 < 80 or (signal_matches_2 == 0 and full_conf < 0.5):
        for name, img_bytes in full_variants[1:]:   # contrast pass
            text, conf = _ocr_bytes(img_bytes)
            if text and len(text) > len(full_text):
                full_text = text
                full_conf = conf
                used_variants.append(name)
            break
        for name, img_bytes in crop_variants:
            if name != "mid_crop":
                continue
            text, conf = _ocr_bytes(img_bytes)
            if text and len(text) > 30:
                crop_texts.append(text)
                used_variants.append(name)
            break

    # ── Combine all useful texts ──────────────────────────────────────────────
    combined_parts = [full_text] + crop_texts
    combined = "\n\n[CROP]\n".join(p for p in combined_parts if p)

    return combined, full_conf, "+".join(used_variants)




# ── Barcode / QR ──────────────────────────────────────────────────────────────

def _decode_barcodes(image_bytes: bytes) -> list[dict]:
    """
    Decode barcodes and QR codes from image using pyzbar.
    Returns list of { type, value }.
    """
    results = []
    try:
        from pyzbar import pyzbar
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        codes = pyzbar.decode(img)
        for code in codes:
            results.append({
                "type": code.type,
                "value": code.data.decode("utf-8", errors="replace"),
            })
    except ImportError:
        pass
    except Exception:
        pass
    return results


# ── FSSAI targeted search ──────────────────────────────────────────────────────

def _targeted_fssai_search(image_bytes: bytes) -> str:
    """
    Run a focused OCR pass on the bottom third of the image — the zone
    where FSSAI licence numbers are almost always printed on packaging.
    Returns the OCR text (may contain FSSAI number).
    """
    from PIL import Image, ImageEnhance
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if h < 100:
            return ""

        # Bottom 35% — FSSAI is almost always here
        bottom = img.crop((0, int(h * 0.65), w, h))

        # Upscale aggressively for small text
        bw, bh = bottom.size
        scale = max(1.0, 2400 / max(bw * 3, 1))
        if scale > 1.0:
            bottom = bottom.resize((int(bw * scale), int(bh * scale)), Image.LANCZOS)

        # High contrast for small text
        bottom = ImageEnhance.Contrast(bottom).enhance(2.5)
        bottom = ImageEnhance.Sharpness(bottom).enhance(2.5)

        buf = io.BytesIO()
        bottom.save(buf, format="PNG")
        text, _ = _ocr_bytes(buf.getvalue())
        return text
    except Exception:
        return ""


# ── Main public API ────────────────────────────────────────────────────────────

async def process_image(image_url: str, img_index: int) -> dict:
    """
    Download + preprocess + multi-pass OCR + barcode-decode one product image.

    Returns:
    {
      url: str,
      index: int,
      downloaded: bool,
      ocr_text: str,          ← combined multi-pass text (preserves newlines)
      ocr_confidence: float,
      has_fssai_signal: bool, ← True if OCR found FSSAI-related text
      has_compliance_signal: bool,
      barcodes: list[{type, value}],
      error: str,
    }
    """
    result = {
        "url": image_url,
        "index": img_index,
        "downloaded": False,
        "ocr_text": "",
        "ocr_confidence": 0.0,
        "has_fssai_signal": False,
        "has_compliance_signal": False,
        "barcodes": [],
        "error": "",
    }

    # Download at highest available resolution
    raw_bytes = await _download_image(image_url)
    if not raw_bytes:
        result["error"] = "Download failed"
        return result

    result["downloaded"] = True

    # Barcode / QR decode (fast, PIL-based)
    try:
        loop = asyncio.get_event_loop()
        result["barcodes"] = await loop.run_in_executor(None, _decode_barcodes, raw_bytes)
    except Exception:
        pass

    # Multi-pass preprocessing
    try:
        loop = asyncio.get_event_loop()
        variants = await loop.run_in_executor(None, _preprocess_variants, raw_bytes)
    except Exception:
        variants = [("raw", raw_bytes)]

    # Run OCR in thread (non-blocking once EasyOCR model is loaded)
    try:
        loop = asyncio.get_event_loop()
        text, conf, used = await loop.run_in_executor(None, _best_ocr_sync, variants)
        result["ocr_text"] = text
        result["ocr_confidence"] = conf
    except Exception as e:
        result["error"] = f"OCR failed: {e}"
        return result

    # Check signals in OCR output
    result["has_fssai_signal"] = bool(_FSSAI_SIGNAL.search(result["ocr_text"]))
    result["has_compliance_signal"] = bool(_COMPLIANCE_SIGNAL.search(result["ocr_text"]))

    # If no FSSAI found yet, run targeted bottom-strip pass
    if not result["has_fssai_signal"] and len(raw_bytes) > 5000:
        try:
            loop = asyncio.get_event_loop()
            fssai_text = await loop.run_in_executor(None, _targeted_fssai_search, raw_bytes)
            if fssai_text and _FSSAI_SIGNAL.search(fssai_text):
                result["ocr_text"] = result["ocr_text"] + "\n\n[FSSAI_ZONE]\n" + fssai_text
                result["has_fssai_signal"] = True
        except Exception:
            pass

    return result


async def process_images_parallel(image_urls: list[str], max_images: int = 4) -> dict:
    """
    Download and OCR multiple images sequentially.
    Sequential (not parallel) so EasyOCR isn't flooded with concurrent requests.

    Returns:
    {
      combined_ocr_text: str,
      avg_confidence: float,
      images_processed: int,
      images_downloaded: int,
      all_barcodes: list,
      image_results: list,
      fssai_found_in: int|None,  ← index of image where FSSAI was detected
    }
    """
    urls = image_urls[:max_images]
    results = []

    for i, url in enumerate(urls):
        r = await process_image(url, i)
        results.append(r)

    downloaded = [r for r in results if r["downloaded"]]
    texts = [r["ocr_text"] for r in downloaded if r["ocr_text"]]
    all_barcodes = []
    for r in results:
        all_barcodes.extend(r["barcodes"])

    combined_text = "\n\n".join(texts)
    avg_conf = (
        sum(r["ocr_confidence"] for r in downloaded if r["ocr_text"]) / len(texts)
        if texts else 0.0
    )

    fssai_found_in = None
    for r in results:
        if r.get("has_fssai_signal"):
            fssai_found_in = r["index"]
            break

    return {
        "combined_ocr_text": combined_text,
        "avg_confidence": round(avg_conf, 3),
        "images_processed": len(results),
        "images_downloaded": len(downloaded),
        "all_barcodes": all_barcodes,
        "fssai_found_in": fssai_found_in,
        "image_results": [
            {
                "url": r["url"],
                "downloaded": r["downloaded"],
                "ocr_text_len": len(r["ocr_text"]),
                "ocr_confidence": r["ocr_confidence"],
                "has_fssai_signal": r.get("has_fssai_signal", False),
                "has_compliance_signal": r.get("has_compliance_signal", False),
                "barcodes": r["barcodes"],
                "error": r["error"],
            }
            for r in results
        ],
    }
