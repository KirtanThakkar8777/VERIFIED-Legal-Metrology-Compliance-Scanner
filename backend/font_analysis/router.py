"""
font_analysis/router.py — Font size and PDP compliance endpoints (Phase 8).
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/font", tags=["Font Analysis"])


# ── Response schemas ──────────────────────────────────────────────────────────

class WordMeasurementOut(BaseModel):
    text: str
    height_px: float
    height_mm: float
    confidence: float


class FontAnalysisOut(BaseModel):
    package_area_cm2: float
    min_required_mm: float
    word_count: int
    smallest_mm: float
    avg_mm: float
    non_compliant_count: int
    overall_status: str
    verdict: str
    px_per_mm: float
    measurements: List[WordMeasurementOut]
    non_compliant_words: List[WordMeasurementOut]
    pdp: Optional[dict] = None


class PdpRequest(BaseModel):
    total_surface_cm2: float
    pdp_area_cm2: float


# ── POST /api/font/analyse ────────────────────────────────────────────────────

@router.post("/analyse", response_model=FontAnalysisOut)
async def analyse_font(
    file: UploadFile = File(...),
    package_area_cm2: float = Form(200.0),
    reference_width_mm: Optional[float] = Form(None),
    total_surface_cm2: Optional[float] = Form(None),
    pdp_area_cm2: Optional[float] = Form(None),
):
    """
    Upload a label image and measure font heights against Rule 9 / Schedule II.

    Form fields:
    - **package_area_cm2** — Principal display area in cm² (default 200)
    - **reference_width_mm** — Physical label width in mm for accurate px→mm scale
    - **total_surface_cm2** — (optional) Full package surface for PDP check
    - **pdp_area_cm2** — (optional) PDP area for PDP % check
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image files accepted.")

    image_bytes = await file.read()

    try:
        from font_analysis.service import analyse_font as _analyse
        result = _analyse(
            image_bytes=image_bytes,
            package_area_cm2=package_area_cm2,
            reference_width_mm=reference_width_mm,
            total_surface_cm2=total_surface_cm2,
            pdp_area_cm2=pdp_area_cm2,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    def _to_out(m):
        return WordMeasurementOut(
            text=m.text,
            height_px=m.height_px,
            height_mm=m.height_mm,
            confidence=m.confidence,
        )

    return FontAnalysisOut(
        package_area_cm2=result.package_area_cm2,
        min_required_mm=result.min_required_mm,
        word_count=len(result.measurements),
        smallest_mm=result.smallest_mm,
        avg_mm=result.avg_mm,
        non_compliant_count=len(result.non_compliant_words),
        overall_status=result.overall_status,
        verdict=result.verdict,
        px_per_mm=result.px_per_mm,
        measurements=[_to_out(m) for m in result.measurements],
        non_compliant_words=[_to_out(m) for m in result.non_compliant_words],
        pdp=result.pdp,
    )


# ── POST /api/font/pdp ────────────────────────────────────────────────────────

@router.post("/pdp")
def check_pdp(payload: PdpRequest):
    """Quick PDP Rule 9 check without image upload."""
    from font_analysis.service import pdp_compliance
    return pdp_compliance(payload.total_surface_cm2, payload.pdp_area_cm2)


# ── GET /api/font/schedule ────────────────────────────────────────────────────

@router.get("/schedule")
def get_schedule():
    """Return the Schedule II minimum font height table."""
    return {
        "rule": "Schedule II — Legal Metrology (Packaged Commodities) Rules 2011",
        "table": [
            {"max_area_cm2": 200,    "min_font_mm": 1.0, "label": "≤ 200 cm²"},
            {"max_area_cm2": 500,    "min_font_mm": 2.0, "label": "201–500 cm²"},
            {"max_area_cm2": 2500,   "min_font_mm": 4.0, "label": "501–2500 cm²"},
            {"max_area_cm2": None,   "min_font_mm": 6.0, "label": "> 2500 cm²"},
        ],
    }
