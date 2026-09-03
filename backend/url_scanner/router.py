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
    """
    Full two-source product intelligence pipeline:
      Source 1: E-commerce webpage (HTML + JSON-LD + structured data)
      Source 2: Product/packaging images (download → preprocess → OCR → entities)
    """
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
                "webpage data may be limited. Packaging images will still be analysed.",
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
        jld_found = bool(structured.get("name") or structured.get("price") or structured.get("image_urls"))
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = f"✓ Structured metadata {'found' if jld_found else 'extracted (basic)'}"

        # ── Step 5: Platform adapter extraction ──────────────────────────────
        _add_step(scan_id, "⟳ Extracting webpage product data...", done=False)
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
        web_name = adapter_data.get("product_name") or structured.get("name") or ""
        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = (
            f"✓ Webpage data extracted: {web_name[:50]}" if web_name else "✓ Webpage data extracted"
        )

        # ── Step 6: Collect all product images ────────────────────────────────
        _add_step(scan_id, "⟳ Collecting product images...", done=False)
        from url_scanner.image_collector import collect_images
        all_images = collect_images(html, page["final_url"])

        # Supplement with JSON-LD images
        jl_imgs = structured.get("image_urls", []) + structured.get("og_images", [])
        jl_seen = {img["url"] for img in all_images}
        for img_url in jl_imgs:
            if img_url and img_url not in jl_seen:
                all_images.append({"url": img_url, "alt": "", "score": 5, "source": "jsonld"})
                jl_seen.add(img_url)

        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = f"✓ {len(all_images)} product images found"

        # ── Step 7: Classify images → select packaging candidates ─────────────
        from url_scanner.image_classifier import select_packaging_images, classify_image
        for img in all_images:
            img["classification"] = classify_image(img["url"], img.get("alt", ""))

        # Select top packaging images for OCR (all non-lifestyle images, max 3)
        packaging_candidates = select_packaging_images(all_images, max_for_ocr=3)
        packaging_count = sum(1 for img in all_images if img["classification"]["is_packaging"])

        # If classifier found 0 packaging, fall back to top-scored images (website may not have alt text)
        if not packaging_candidates:
            packaging_candidates = [
                {**img, "classification": {"category": "unknown", "confidence": 0.5, "is_packaging": True}}
                for img in sorted(all_images, key=lambda x: x["score"], reverse=True)[:3]
            ]

        _add_step(scan_id, f"✓ {len(packaging_candidates)} packaging images selected for OCR")

        adapter_data["images"] = [
            {"url": img["url"], "classification": img.get("classification", {})}
            for img in all_images[:10]
        ]

        # ── Step 8: DOWNLOAD AND OCR PACKAGING IMAGES ─────────────────────────
        # This is the critical step that was missing before.
        _add_step(scan_id, f"⟳ Downloading and analysing {len(packaging_candidates)} images...", done=False)

        from url_scanner.image_processor import process_images_parallel
        packaging_urls = [img["url"] for img in packaging_candidates]

        ocr_pipeline_result = await process_images_parallel(packaging_urls, max_images=6)

        combined_ocr_text = ocr_pipeline_result["combined_ocr_text"]
        ocr_char_count = len(combined_ocr_text)
        imgs_downloaded = ocr_pipeline_result["images_downloaded"]
        imgs_processed = ocr_pipeline_result["images_processed"]
        avg_conf = ocr_pipeline_result["avg_confidence"]
        all_barcodes = ocr_pipeline_result["all_barcodes"]

        job["steps"][-1]["done"] = True
        if ocr_char_count > 50:
            job["steps"][-1]["label"] = (
                f"✓ OCR complete: {imgs_downloaded}/{imgs_processed} images, "
                f"{ocr_char_count} chars, {avg_conf*100:.0f}% confidence"
            )
        else:
            job["steps"][-1]["label"] = (
                f"⚠ OCR extracted limited text ({ocr_char_count} chars) from "
                f"{imgs_downloaded}/{imgs_processed} images — packaging data may be incomplete"
            )

        # Log barcode results
        if all_barcodes:
            barcode_summary = ", ".join(f"{b['type']}:{b['value']}" for b in all_barcodes[:3])
            _add_step(scan_id, f"✓ Barcode decoded: {barcode_summary[:80]}")

        # ── Step 9: Extract Legal Metrology entities from OCR text ─────────────
        from url_scanner.intelligence.entity_extractor import extract_entities
        ocr_entities = {}
        if combined_ocr_text:
            _add_step(scan_id, "⟳ Extracting entities from packaging text...", done=False)
            ocr_entities = extract_entities(combined_ocr_text)
            job["steps"][-1]["done"] = True

            found_fields = [k for k, v in ocr_entities.items() if v]
            if found_fields:
                _add_step(scan_id, f"✓ Entities detected: {', '.join(found_fields[:8])}")
            else:
                _add_step(scan_id, "⚠ Entity extraction: limited fields found in OCR text")

        # Merge barcodes from pyzbar into ocr_entities
        if all_barcodes and not ocr_entities.get("barcode"):
            for bc in all_barcodes:
                if bc["type"] in ("EAN13", "EAN8", "CODE128", "UPCA", "GTIN"):
                    ocr_entities["barcode"] = bc["value"]
                    ocr_entities["barcode_type"] = bc["type"]
                    break
            for bc in all_barcodes:
                if bc["type"] == "QRCODE":
                    ocr_entities["qr_code"] = bc["value"][:200]
                    break

        # ── Step 10: Fuse ALL sources → normalized product model ──────────────
        _add_step(scan_id, "⟳ Merging webpage + packaging data...", done=False)
        from url_scanner.intelligence.data_fusion import fuse
        model = fuse(
            adapter_data,
            ocr_text=combined_ocr_text,
            structured=structured,
            ocr_entities=ocr_entities,
        )

        # Add OCR image stats to model
        model["ocr_stats"] = {
            "images_processed": imgs_processed,
            "images_downloaded": imgs_downloaded,
            "ocr_char_count": ocr_char_count,
            "avg_confidence": avg_conf,
            "image_results": ocr_pipeline_result["image_results"],
        }

        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = "✓ Data merged"

        # ── Step 11: Report key findings ──────────────────────────────────────
        mfr = model.get("manufacturer", {})
        mfr_name = mfr.get("name", "") or mfr.get("address_raw", "")
        if mfr_name:
            src = "package" if mfr.get("source") == "ocr" else "webpage"
            _add_step(scan_id, f"✓ Manufacturer identified ({src}): {mfr_name[:60]}")
        else:
            _add_step(scan_id, "⚠ Manufacturer not found in webpage or packaging images")

        parsed = mfr.get("parsed", {})
        if parsed.get("state") or parsed.get("pincode"):
            _add_step(scan_id, f"✓ Address parsed: {parsed.get('state', '')} {parsed.get('pincode', '')}".strip())

        mfr_country = mfr.get("country", "")
        if mfr_country and mfr_country != "Unknown":
            conf = mfr.get("country_confidence", 0)
            _add_step(scan_id, f"✓ Country: {mfr_country} ({conf}% confidence)")

        # FSSAI
        reg = model.get("regulatory", {})
        fssai = reg.get("fssai", "")
        if fssai:
            _add_step(scan_id, f"✓ FSSAI detected: {fssai}")

        # Quantity
        qty = model.get("quantity", {})
        qty_val = qty.get("website_raw") or qty.get("package_raw") or ""
        if qty_val:
            _add_step(scan_id, f"✓ Net quantity: {qty_val}")

        # Ingredients
        if model.get("ingredients"):
            _add_step(scan_id, f"✓ Ingredients detected ({len(model['ingredients'])} chars)")

        # ── Step 12: Mismatch detection ───────────────────────────────────────
        from url_scanner.intelligence.mismatch_detector import detect_mismatches
        comparisons = detect_mismatches(model)
        _add_step(scan_id, "✓ Website ↔ package comparison completed")

        # ── Step 13: Format output ────────────────────────────────────────────
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
        import traceback
        tb = traceback.format_exc()
        _add_step(scan_id, f"✗ Unexpected error: {type(exc).__name__}: {exc}", error=str(exc))
        job["status"] = "error"
        job["error"] = (
            "Unable to complete scan. "
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
