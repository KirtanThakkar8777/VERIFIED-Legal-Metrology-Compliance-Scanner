"""
main.py — VERIFIED v2 FastAPI application entry point.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from config import settings
from database import engine, Base

# Import all models so create_all picks them up
import models  # noqa: F401

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Legal Metrology (Packaged Commodities) Rules 2011 — Automated Compliance Scanner",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from auth.router import router as auth_router
from scan.router import router as scan_router
from dashboard.router import router as dashboard_router
from font_analysis.router import router as font_router

app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(dashboard_router)
app.include_router(font_router)


# ── URL fetch endpoint ────────────────────────────────────────────────────────
from scraper.service import fetch_and_extract
import schemas

@app.post("/api/fetch-url", response_model=schemas.FetchUrlOut, tags=["Scraper"])
async def fetch_url(payload: schemas.FetchUrlRequest):
    """Fetch a product URL and extract label text for scanning."""
    try:
        result = await fetch_and_extract(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {exc}")
    return result


# ── OCR endpoint ──────────────────────────────────────────────────────────────
from ocr.service import extract_text_from_image

@app.post("/api/ocr", response_model=schemas.OcrOut, tags=["OCR"])
async def ocr_image(file: UploadFile = File(...)):
    """Upload an image file; returns OCR-extracted text."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image files accepted.")
    image_bytes = await file.read()
    try:
        result = extract_text_from_image(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return result


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "service": "verified-backend-v2",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/", tags=["System"])
def root():
    return {"message": "VERIFIED v2 API — visit /docs for interactive documentation"}
