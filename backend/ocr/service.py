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


def _try_easyocr(image_bytes: bytes) -> Optional[tuple[str, float]]:
    """Return (text, avg_confidence) using EasyOCR, or None on failure."""
    try:
        import easyocr
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        # gpu=False for CPU-only environments; model weights auto-download on first run
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        results = reader.readtext(img_array)

        if not results:
            return ("", 0.0)

        texts = [r[1] for r in results]
        confidences = [float(r[2]) for r in results]
        avg_conf = sum(confidences) / len(confidences)
        return " ".join(texts), avg_conf

    except ImportError:
        return None
    except Exception as exc:
        # EasyOCR is installed but something else went wrong; propagate
        raise RuntimeError(f"EasyOCR failed: {exc}") from exc


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


def extract_text_from_image(image_bytes: bytes) -> dict:
    """
    Extract text from image bytes.

    Tries EasyOCR first (no external binary required, downloads model weights
    on first run), then pytesseract as fallback.

    Returns:
        {"extracted_text": str, "confidence": float, "word_count": int}
    """
    result = _try_easyocr(image_bytes)

    if result is None:
        result = _try_pytesseract(image_bytes)

    if result is None:
        raise ValueError(
            "No OCR engine is installed. "
            "The server needs 'easyocr' (pip install easyocr) "
            "or 'pytesseract' + the Tesseract binary."
        )

    text, confidence = result

    # Normalise whitespace
    text = re.sub(r"\s+", " ", text).strip()
    word_count = len(text.split()) if text else 0

    return {
        "extracted_text": text,
        "confidence": round(confidence, 4),
        "word_count": word_count,
    }
