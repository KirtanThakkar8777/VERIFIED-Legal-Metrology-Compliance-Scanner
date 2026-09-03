"""
url_scanner/router.py
E-Commerce URL Intelligence Scanner API endpoints.

POST /api/url-scan          — start scan (returns scan_id immediately)
GET  /api/url-scan/{id}/progress — poll progress
GET  /api/url-scan/{id}/result   — get final formatted text + model
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/url-scan", tags=["URL Scanner"])


# ── In-memory job store ────────────────────────────────────────────────────────
# { scan_id: { status, steps, result, error, created_at } }
_JOBS: dict[str, dict] = {}
_JOB_TTL_SECONDS = 3600  # Clean up after 1 hour


def _job(scan_id: str) -> dict:
    job = _JOBS.get(scan_id)
    if not job:
        raise HTTPException(404, f"Scan job '{scan_id}' not found.")
    return job


def _add_step(scan_id: str, label: str, done: bool = True, error: str = "") -> None:
    job = _JOBS.get(scan_id, {})
    step = {
        "label": label,
        "done": done,
        "error": error,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    job.setdefault("steps", []).append(step)


# ── Request / Response models ──────────────────────────────────────────────────

class UrlScanRequest(BaseModel):
    url: str


class ProgressResponse(BaseModel):
    scan_id: str
    status: str          # "pending" | "processing" | "done" | "error"
    platform: str
    steps: list[dict]
    error: str | None


class ResultResponse(BaseModel):
    scan_id: str
    status: str
    platform: str
    formatted_text: str
    product_name: str
    images_found: int
    packaging_images: int
    model: dict[str, Any]
    comparisons: list[dict]


# ── Background scan task ───────────────────────────────────────────────────────

async def _run_scan(scan_id: str, url: str) -> None:
    """Background task: fetch, extract, fuse, format."""
    job = _JOBS[scan_id]

    try:
        # ── Step 1: Validate URL ──────────────────────────────────────────────
        from url_scanner.platform_detector import validate_url, detect_platform
        validate_url(url)
        _add_step(scan_id, "✓ URL validated")

        # ── Step 2: Detect platform ───────────────────────────────────────────
        platform_info = detect_platform(url)
        job["platform"] = platform_info["display_name"]
        _add_step(scan_id, f"✓ {platform_info['display_name']} detected")

        if platform_info["is_js_heavy"]:
            _add_step(
                scan_id,
                f"⚠ {platform_info['display_name']} uses JavaScript rendering — "
                "data may be limited. Consider pasting text manually for full compliance.",
            )

        # ── Step 3: Fetch product page ────────────────────────────────────────
        _add_step(scan_id, "⟳ Fetching product page...", done=False)
        from url_scanner.page_fetcher import fetch_page
        page = await fetch_page(url, platform_info["adapter_key"])
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = f"✓ Product page fetched ({page['content_length']:,} bytes)"

        html = page["html"]
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        full_text = soup.get_text(" ", strip=True)

        # ── Step 4: Extract structured data (JSON-LD / OpenGraph) ─────────────
        _add_step(scan_id, "⟳ Extracting structured metadata...", done=False)
        from url_scanner.structured_extractor import extract_structured_data
        structured = extract_structured_data(html)
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = "✓ Structured metadata extracted"

        # ── Step 5: Platform-specific adapter extraction ──────────────────────
        _add_step(scan_id, "⟳ Extracting product information...", done=False)

        adapter_key = platform_info["adapter_key"]
        if adapter_key == "amazon":
            from url_scanner.adapters.amazon import extract as adapter_extract
        elif adapter_key == "flipkart":
            from url_scanner.adapters.flipkart import extract as adapter_extract
        elif adapter_key == "meesho":
            from url_scanner.adapters.meesho import extract as adapter_extract
        else:
            from url_scanner.adapters.generic import extract as adapter_extract

        adapter_data = adapter_extract(soup, full_text)
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = "✓ Product information extracted"

        # ── Step 6: Collect product images ────────────────────────────────────
        _add_step(scan_id, "⟳ Finding product images...", done=False)
        from url_scanner.image_collector import collect_images
        all_images = collect_images(html, page["final_url"])

        # Add JSON-LD images
        jl_imgs = structured.get("image_urls", []) + structured.get("og_images", [])
        jl_seen = {img["url"] for img in all_images}
        for img_url in jl_imgs:
            if img_url and img_url not in jl_seen:
                all_images.append({"url": img_url, "alt": "", "score": 5, "source": "jsonld"})
                jl_seen.add(img_url)

        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = f"✓ {len(all_images)} product images found"

        # ── Step 7: Classify images ───────────────────────────────────────────
        from url_scanner.image_classifier import select_packaging_images, classify_image
        for img in all_images:
            img["classification"] = classify_image(img["url"], img.get("alt", ""))
        packaging_images = select_packaging_images(all_images, max_for_ocr=5)
        packaging_count = sum(1 for img in all_images if img["classification"]["is_packaging"])
        _add_step(scan_id, f"✓ {packaging_count} packaging images identified")

        adapter_data["images"] = [
            {"url": img["url"], "classification": img.get("classification", {})}
            for img in all_images[:10]
        ]

        # ── Step 8: Fuse data ─────────────────────────────────────────────────
        _add_step(scan_id, "⟳ Analysing product data...", done=False)
        from url_scanner.intelligence.data_fusion import fuse
        model = fuse(adapter_data, ocr_text="", structured=structured)
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = "✓ Product data analysed"

        # Manufacturer detection
        mfr_name = model.get("manufacturer", {}).get("name", "") or \
                   model.get("manufacturer", {}).get("address_raw", "")
        if mfr_name:
            _add_step(scan_id, f"✓ Manufacturer identified: {mfr_name[:50]}")
        else:
            _add_step(scan_id, "⚠ Manufacturer not found in listing — check physical packaging")

        # Address parsing result
        parsed_addr = model.get("manufacturer", {}).get("parsed", {})
        if parsed_addr.get("state") or parsed_addr.get("pincode"):
            state = parsed_addr.get("state", "")
            pin = parsed_addr.get("pincode", "")
            _add_step(scan_id, f"✓ Address parsed: {state} {pin}".strip())

        # Country detection
        mfr_country = model.get("manufacturer", {}).get("country", "")
        if mfr_country and mfr_country != "Unknown":
            _add_step(scan_id, f"✓ Manufacturer country: {mfr_country}")
        elif model.get("origin", {}).get("detected_country"):
            detected = model["origin"]["detected_country"]
            _add_step(scan_id, f"✓ Country detected: {detected}")

        # ── Step 9: Mismatch detection ────────────────────────────────────────
        from url_scanner.intelligence.mismatch_detector import detect_mismatches
        comparisons = detect_mismatches(model)
        _add_step(scan_id, "✓ Website ↔ package comparison completed")

        # ── Step 10: Format output ────────────────────────────────────────────
        _add_step(scan_id, "⟳ Formatting extracted data...", done=False)
        from url_scanner.formatter import format_product
        formatted_text = format_product(model, platform_info, all_images, comparisons)
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = "✓ Data formatted"

        _add_step(scan_id, "✓ Extraction complete")

        # ── Store result ──────────────────────────────────────────────────────
        job["status"] = "done"
        job["result"] = {
            "scan_id": scan_id,
            "status": "done",
            "platform": platform_info["display_name"],
            "formatted_text": formatted_text,
            "product_name": model.get("product", {}).get("name", ""),
            "images_found": len(all_images),
            "packaging_images": packaging_count,
            "model": model,
            "comparisons": comparisons,
        }

    except ValueError as exc:
        _add_step(scan_id, f"✗ Error: {exc}", error=str(exc))
        job["status"] = "error"
        job["error"] = str(exc)

    except Exception as exc:
        _add_step(scan_id, f"✗ Unexpected error: {type(exc).__name__}: {exc}", error=str(exc))
        job["status"] = "error"
        job["error"] = (
            "Unable to access this product page automatically. "
            "Please use the Paste Text or Label Image tab to scan manually. "
            f"({type(exc).__name__}: {exc})"
        )


# ── API Endpoints ──────────────────────────────────────────────────────────────

@router.post("", response_model=dict)
async def start_url_scan(payload: UrlScanRequest, background_tasks: BackgroundTasks):
    """
    Start an intelligent URL scan.
    Returns scan_id immediately; use /progress to poll status.
    """
    url = payload.url.strip()
    if not url:
        raise HTTPException(422, "URL cannot be empty.")

    # Server-side SSRF guard — validate before creating job
    from url_scanner.platform_detector import validate_url
    try:
        validate_url(url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    scan_id = str(uuid.uuid4())[:8]
    _JOBS[scan_id] = {
        "scan_id": scan_id,
        "url": url,
        "status": "processing",
        "platform": "Detecting...",
        "steps": [],
        "result": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    background_tasks.add_task(_run_scan, scan_id, url)

    return {"scan_id": scan_id, "status": "processing", "platform": "Detecting..."}


@router.get("/{scan_id}/progress", response_model=ProgressResponse)
async def get_progress(scan_id: str):
    """Poll scan progress."""
    job = _job(scan_id)
    return ProgressResponse(
        scan_id=scan_id,
        status=job["status"],
        platform=job.get("platform", ""),
        steps=job.get("steps", []),
        error=job.get("error"),
    )


@router.get("/{scan_id}/result", response_model=ResultResponse)
async def get_result(scan_id: str):
    """Get the final scan result (only available when status == 'done')."""
    job = _job(scan_id)
    if job["status"] == "processing":
        raise HTTPException(202, "Scan still in progress. Poll /progress first.")
    if job["status"] == "error":
        raise HTTPException(422, job.get("error", "Scan failed."))
    result = job.get("result")
    if not result:
        raise HTTPException(500, "Scan completed but result is missing.")
    return ResultResponse(**result)
