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
    from auth.utils import hash_password, verify_password
    db = SessionLocal()
    try:
        admin = db.query(models.User).filter(models.User.email == "admin@verified.in").first()
        if not admin:
            # Also check old email from previous seed
            old = db.query(models.User).filter(models.User.email == "admin@verified.dev").first()
            if old:
                # Migrate email to correct one
                old.email = "admin@verified.in"
                old.password_hash = hash_password("Admin@123")
                db.commit()
                print("✅ Admin email migrated → admin@verified.in  password: Admin@123")
            else:
                admin = models.User(
                    name="Admin",
                    email="admin@verified.in",
                    password_hash=hash_password("Admin@123"),
                    role="REGULATOR",
                )
                db.add(admin)
                db.commit()
                print("✅ Default admin created → email: admin@verified.in  password: Admin@123")
        else:
            # Ensure password is correct (fix if old seed used wrong password)
            if not verify_password("Admin@123", admin.password_hash):
                admin.password_hash = hash_password("Admin@123")
                db.commit()
                print("✅ Admin password updated → Admin@123")
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
import asyncio

@app.post("/api/ocr", response_model=schemas.OcrOut, tags=["OCR"])
async def ocr_image(file: UploadFile = File(...)):
    """Upload a label/packaging image; returns structured compliance-ready text."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image files accepted (PNG, JPG, WEBP).")
    image_bytes = await file.read()
    if len(image_bytes) < 1000:
        raise HTTPException(status_code=422, detail="Image too small — please upload a clear label photo.")
    try:
        # Run synchronous OCR in a thread (heavy CPU — would block event loop otherwise)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, extract_text_from_image, image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"OCR engine error: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {exc}")
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
