"""
main.py — VERIFIED v2 FastAPI application entry point.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from config import settings
from database import engine, Base, SessionLocal

# Import all models so create_all picks them up
import models  # noqa: F401

# Create all tables on startup
Base.metadata.create_all(bind=engine)


# ── Seed default admin user (runs once on startup if no users exist) ──────────
def _seed_admin():
    from auth.utils import hash_password
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                name="Admin",
                email="admin@verified.dev",
                password_hash=hash_password("admin123"),
                role="REGULATOR",
            )
            db.add(admin)
            db.commit()
            print("✅ Default admin created → email: admin@verified.dev  password: admin123")
    finally:
        db.close()

_seed_admin()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Legal Metrology (Packaged Commodities) Rules 2011 — Automated Compliance Scanner",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from auth.router import router as auth_router
from scan.router import router as scan_router
from dashboard.router import router as dashboard_router
from font_analysis.router import router as font_router
from url_scanner.router import router as url_scan_router

app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(dashboard_router)
app.include_router(font_router)
app.include_router(url_scan_router)


# ── Pre-warm EasyOCR on startup (in background thread) ───────────────────────
@app.on_event("startup")
async def _prewarm_easyocr():
    """Load EasyOCR model in a thread at startup so first scan isn't slow."""
    import threading

    def _warm():
        try:
            from ocr.service import _get_reader
            _get_reader()
            print("[INFO] EasyOCR model pre-warmed and ready")
        except Exception as e:
            print(f"[WARN] EasyOCR pre-warm failed (will load on first use): {e}")

    threading.Thread(target=_warm, daemon=True).start()



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
