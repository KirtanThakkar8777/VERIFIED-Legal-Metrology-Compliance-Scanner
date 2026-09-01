"""
font_analysis/service.py — Rule 9 / Schedule II font-size & PDP compliance engine.

Legal Metrology (Packaged Commodities) Rules 2011:
  Rule 9   — Principal Display Panel (PDP) must occupy ≥ 40% of the total display area.
  Schedule II — Minimum font heights:
    • Package ≤ 200 cm²  → 1 mm
    • Package 200–500 cm² → 2 mm
    • Package 500–2500 cm² → 4 mm
    • Package > 2500 cm²  → 6 mm

We estimate font height in mm using bounding box pixel heights from EasyOCR
and a pixel-to-mm conversion derived from a reference dimension supplied by
the user (or estimated from the image dimensions).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ── Schedule II thresholds ────────────────────────────────────────────────────

SCHEDULE_II = [
    (200,   1.0),   # area ≤ 200 cm²  → min 1 mm
    (500,   2.0),   # area ≤ 500 cm²  → min 2 mm
    (2500,  4.0),   # area ≤ 2500 cm² → min 4 mm
    (float("inf"), 6.0),  # area > 2500 cm² → min 6 mm
]


def min_font_height_mm(package_area_cm2: float) -> float:
    """Return the minimum required font height in mm per Schedule II."""
    for limit, min_mm in SCHEDULE_II:
        if package_area_cm2 <= limit:
            return min_mm
    return 6.0


# ── PDP calculator ────────────────────────────────────────────────────────────

def pdp_compliance(
    total_surface_cm2: float,
    pdp_area_cm2: float,
) -> dict:
    """
    Evaluate whether the PDP area meets Rule 9's 40% minimum.

    Returns dict with: pdp_percentage, required_percentage, status, verdict
    """
    if total_surface_cm2 <= 0:
        return {"error": "Total surface area must be > 0"}

    pct = round((pdp_area_cm2 / total_surface_cm2) * 100, 1)
    required = 40.0
    status = "PASS" if pct >= required else "FAIL"

    return {
        "pdp_area_cm2": round(pdp_area_cm2, 2),
        "total_surface_cm2": round(total_surface_cm2, 2),
        "pdp_percentage": pct,
        "required_percentage": required,
        "status": status,
        "verdict": (
            f"PDP occupies {pct}% of total surface — {'meets' if status == 'PASS' else 'does NOT meet'} "
            f"the ≥40% requirement of Rule 9."
        ),
    }


# ── Font analyser ─────────────────────────────────────────────────────────────

@dataclass
class WordMeasurement:
    text: str
    height_px: float
    height_mm: float
    confidence: float
    bbox: List


@dataclass
class FontAnalysisResult:
    package_area_cm2: float
    min_required_mm: float
    measurements: List[WordMeasurement]
    smallest_mm: float
    avg_mm: float
    non_compliant_words: List[WordMeasurement]
    overall_status: str        # PASS | FAIL | REVIEW
    verdict: str
    px_per_mm: float
    pdp: Optional[dict] = None


def analyse_font(
    image_bytes: bytes,
    package_area_cm2: float = 200.0,
    reference_width_mm: Optional[float] = None,
    total_surface_cm2: Optional[float] = None,
    pdp_area_cm2: Optional[float] = None,
) -> FontAnalysisResult:
    """
    Measure font heights in the image and check Rule 9 / Schedule II compliance.

    Args:
        image_bytes        : Raw image file bytes (PNG/JPG/WEBP).
        package_area_cm2   : Estimated principal display area in cm². Default 200.
        reference_width_mm : Actual physical width of the label in mm (improves mm accuracy).
        total_surface_cm2  : For PDP check — total surface area of the package.
        pdp_area_cm2       : For PDP check — area of the principal display panel.
    """
    try:
        import easyocr
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(f"easyocr / Pillow not installed: {e}")

    # ── Load image ──────────────────────────────────────────────────────────
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_array = np.array(pil_img)
    img_width_px = pil_img.width

    # ── Pixel-to-mm conversion ──────────────────────────────────────────────
    # If caller provides the real physical width, use it; otherwise estimate
    # from image resolution (assuming 96 DPI as web/camera default → 1px ≈ 0.265 mm)
    if reference_width_mm and reference_width_mm > 0:
        px_per_mm = img_width_px / reference_width_mm
    else:
        px_per_mm = 96 / 25.4   # ≈ 3.78 px/mm at 96 DPI

    # ── EasyOCR detection ───────────────────────────────────────────────────
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    detections = reader.readtext(img_array)  # [[bbox, text, conf], ...]

    min_req_mm = min_font_height_mm(package_area_cm2)
    measurements: List[WordMeasurement] = []

    for bbox, text, conf in detections:
        if not text.strip():
            continue
        # bbox = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        ys = [pt[1] for pt in bbox]
        height_px = max(ys) - min(ys)
        height_mm = height_px / px_per_mm

        measurements.append(WordMeasurement(
            text=text.strip(),
            height_px=round(height_px, 1),
            height_mm=round(height_mm, 2),
            confidence=round(conf, 3),
            bbox=bbox,
        ))

    if not measurements:
        return FontAnalysisResult(
            package_area_cm2=package_area_cm2,
            min_required_mm=min_req_mm,
            measurements=[],
            smallest_mm=0.0,
            avg_mm=0.0,
            non_compliant_words=[],
            overall_status="REVIEW",
            verdict="No text detected in the image. Cannot assess font compliance.",
            px_per_mm=round(px_per_mm, 3),
        )

    heights = [m.height_mm for m in measurements]
    smallest_mm = round(min(heights), 2)
    avg_mm = round(sum(heights) / len(heights), 2)

    non_compliant = [m for m in measurements if m.height_mm < min_req_mm]

    if not non_compliant:
        status = "PASS"
        verdict = (
            f"All {len(measurements)} detected text elements meet the minimum "
            f"{min_req_mm} mm height required by Schedule II for a "
            f"{package_area_cm2} cm² package. Smallest detected: {smallest_mm} mm."
        )
    else:
        status = "FAIL"
        verdict = (
            f"{len(non_compliant)} of {len(measurements)} text elements are below "
            f"the {min_req_mm} mm minimum (Schedule II). "
            f"Smallest detected: {smallest_mm} mm. Non-compliant text: "
            + ", ".join(f'"{m.text}"({m.height_mm}mm)' for m in non_compliant[:5])
        )

    pdp_result = None
    if total_surface_cm2 and pdp_area_cm2:
        pdp_result = pdp_compliance(total_surface_cm2, pdp_area_cm2)

    return FontAnalysisResult(
        package_area_cm2=package_area_cm2,
        min_required_mm=min_req_mm,
        measurements=measurements,
        smallest_mm=smallest_mm,
        avg_mm=avg_mm,
        non_compliant_words=non_compliant,
        overall_status=status,
        verdict=verdict,
        px_per_mm=round(px_per_mm, 3),
        pdp=pdp_result,
    )
