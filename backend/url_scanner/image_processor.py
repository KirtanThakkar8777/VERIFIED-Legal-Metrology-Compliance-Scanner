"""
url_scanner/image_processor.py
Download, preprocess, and OCR product packaging images.

Pipeline per image:
  1. Download bytes (async httpx)
  2. Decode + upscale with PIL
  3. Run OCR via ThreadPoolExecutor (non-blocking after model pre-warm)
  4. Attempt barcode/QR decode via pyzbar

EasyOCR is pre-warmed at server startup (main.py → _prewarm_easyocr).
Once loaded, OCR per image takes ~3-8 seconds on CPU.
"""
from __future__ import annotations

import io
import asyncio
from typing import Optional

import httpx

# ── HTTP fetch ─────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 8 MB


async def _download_image(url: str) -> Optional[bytes]:
    """Download image from URL. Returns None on any failure."""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "image/*,*/*"},
            timeout=12.0,
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                return r.content[:MAX_IMAGE_BYTES]
    except Exception:
        pass
    return None


# ── Image preprocessing ────────────────────────────────────────────────────────

def _preprocess_variants(image_bytes: bytes) -> list[bytes]:
    """
    Return list of image variants to try for OCR.
    2 passes: upscaled original + contrast enhanced.
    """
    from PIL import Image, ImageEnhance
    import io

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return [image_bytes]

    w, h = img.size
    variants: list[bytes] = []

    def _to_bytes(pil_img: Image.Image) -> bytes:
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()

    # Pass 1: Upscale to at least 1200px on longest side for better OCR
    long_side = max(w, h, 1)
    if long_side < 1200:
        scale = max(1, int(1200 / long_side))
        upscaled = img.resize((w * scale, h * scale), Image.LANCZOS)
        variants.append(_to_bytes(upscaled))
    else:
        variants.append(image_bytes)

    # Pass 2: Contrast enhanced (helps for small printed text on packaging)
    contrast = ImageEnhance.Contrast(img).enhance(2.0)
    variants.append(_to_bytes(contrast))

    return variants


# ── OCR ───────────────────────────────────────────────────────────────────────

def _ocr_bytes(image_bytes: bytes) -> tuple[str, float]:
    """Run EasyOCR on image bytes (synchronous). Returns (text, confidence)."""
    from ocr.service import extract_text_from_image
    try:
        result = extract_text_from_image(image_bytes)
        return result["extracted_text"], result["confidence"]
    except Exception:
        return "", 0.0


def _best_ocr_sync(variants: list[bytes]) -> tuple[str, float]:
    """
    Run OCR on each variant synchronously.
    Returns best result by score = len(text) * confidence.
    """
    best_text = ""
    best_conf = 0.0
    best_score = 0.0

    for img_bytes in variants:
        text, conf = _ocr_bytes(img_bytes)
        if not text:
            continue
        score = len(text) * conf
        if score > best_score:
            best_text = text
            best_conf = conf
            best_score = score

    return best_text, best_conf


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
                "type": code.type,       # "EAN13", "QRCODE", etc.
                "value": code.data.decode("utf-8", errors="replace"),
            })
    except ImportError:
        pass
    except Exception:
        pass
    return results


# ── Main public API ────────────────────────────────────────────────────────────

async def process_image(image_url: str, img_index: int) -> dict:
    """
    Download + preprocess + OCR + barcode-decode one product image.

    OCR runs in a thread (run_in_executor). EasyOCR must be pre-warmed
    at startup (main.py → _prewarm_easyocr) for non-blocking operation.

    Returns:
    {
      url: str,
      index: int,
      downloaded: bool,
      ocr_text: str,
      ocr_confidence: float,
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
        "barcodes": [],
        "error": "",
    }

    # Download
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

    # Build preprocessing variants (fast PIL ops)
    try:
        loop = asyncio.get_event_loop()
        variants = await loop.run_in_executor(None, _preprocess_variants, raw_bytes)
    except Exception:
        variants = [raw_bytes]

    # Run OCR in thread (non-blocking once EasyOCR model is loaded)
    try:
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(None, _best_ocr_sync, variants)
        result["ocr_text"] = text
        result["ocr_confidence"] = conf
    except Exception as e:
        result["error"] = f"OCR failed: {e}"

    return result


async def process_images_parallel(image_urls: list[str], max_images: int = 3) -> dict:
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

    return {
        "combined_ocr_text": combined_text,
        "avg_confidence": round(avg_conf, 3),
        "images_processed": len(results),
        "images_downloaded": len(downloaded),
        "all_barcodes": all_barcodes,
        "image_results": [
            {
                "url": r["url"],
                "downloaded": r["downloaded"],
                "ocr_text_len": len(r["ocr_text"]),
                "ocr_confidence": r["ocr_confidence"],
                "barcodes": r["barcodes"],
                "error": r["error"],
            }
            for r in results
        ],
    }
