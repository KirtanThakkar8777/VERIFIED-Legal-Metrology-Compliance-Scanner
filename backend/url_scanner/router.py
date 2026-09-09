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
    ocr_selected_images: list[dict]   # [{"url": str, "rank": int}] — set as soon as images are selected


class ResultResponse(BaseModel):
    scan_id: str
    status: str
    platform: str
    formatted_text: str
    product_name: str
    category: str
    images_found: int
    packaging_images: int
    model: dict[str, Any]
    comparisons: list[dict]


# ── Category inference ─────────────────────────────────────────────────────────

def _infer_category(model: dict, platform_info: dict) -> str:
    """
    Infer a human-readable product category from the model data.
    Checks product name, ingredients, brand, and URL category hints.
    Returns a concise label like 'Food & Beverage', 'Cosmetics', etc.
    """
    import re

    _CATEGORY_RULES = [
        # (keywords to search, category label)
        (r"\b(shampoo|conditioner|serum|moisturiser|moisturizer|sunscreen|face\s*wash|toner|"
         r"lip\s*balm|lipstick|mascara|foundation|concealer|kajal|eyeliner|nail\s*polish|"
         r"lotion|cream|gel|scrub|cleanser|deodorant|perfume|cologne|soap|body\s*wash|"
         r"hair\s*oil|hair\s*mask|hand\s*wash)\b",
         "Beauty & Personal Care"),
        (r"\b(ragi|powder|porridge|oats|flour|atta|maida|rice|dal|lentil|pulse|"
         r"biscuit|cookie|snack|chips|namkeen|chocolate|candy|jam|pickle|sauce|"
         r"ghee|oil|butter|milk|curd|yogurt|cheese|paneer|honey|sugar|salt|"
         r"spice|masala|tea|coffee|juice|drink|beverage|water|protein|supplement|"
         r"multivitamin|vitamin|mineral|probiotic|cereal|granola|muesli|"
         r"noodle|pasta|bread|cake|cookie|cracker|wafer|bar)\b",
         "Food & Beverage"),
        (r"\b(tablet|capsule|syrup|drops|ointment|cream|gel|spray|inhaler|"
         r"antibiotic|painkiller|ibuprofen|paracetamol|ayurvedic|homeopathic|"
         r"pharmaceutical|medicine|drug|rx|prescription)\b",
         "Pharmaceuticals & Healthcare"),
        (r"\b(detergent|dishwash|floor\s*cleaner|toilet\s*cleaner|glass\s*cleaner|"
         r"bleach|insecticide|pesticide|disinfectant|sanitizer|mosquito|cockroach|"
         r"fabric\s*softener|stain\s*remover|air\s*freshener)\b",
         "Household & Cleaning"),
        (r"\b(baby|infant|toddler|child|kids|diapers|nappy|formula|baby\s*food)\b",
         "Baby & Child Care"),
        (r"\b(pet\s*food|dog\s*food|cat\s*food|pet\s*care|aquarium)\b",
         "Pet Care"),
        (r"\b(electronic|phone|laptop|tablet|charger|cable|earphone|speaker|"
         r"camera|watch|gadget|appliance)\b",
         "Electronics"),
    ]

    # Combine all searchable text
    combined = " ".join(filter(None, [
        model.get("product", {}).get("name", ""),
        model.get("product", {}).get("brand", ""),
        model.get("ingredients", "")[:200],
        model.get("product", {}).get("description", "")[:200],
    ])).lower()

    # URL-based hint (groceries → Food, beauty → Beauty, etc.)
    url_hints = {
        "groceries": "Food & Beverage",
        "food": "Food & Beverage",
        "beauty": "Beauty & Personal Care",
        "health": "Pharmaceuticals & Healthcare",
        "baby": "Baby & Child Care",
        "household": "Household & Cleaning",
        "pet": "Pet Care",
    }
    url_str = platform_info.get("url", "").lower()
    for hint, cat in url_hints.items():
        if hint in url_str:
            return cat

    for pattern, label in _CATEGORY_RULES:
        if re.search(pattern, combined, re.IGNORECASE):
            return label

    return ""


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
        elif adapter_key == "myntra":
            from url_scanner.adapters.myntra import extract as adapter_extract
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

        seen_img_urls = {img["url"] for img in all_images}

        # Supplement with JSON-LD images
        jl_imgs = structured.get("image_urls", []) + structured.get("og_images", [])
        for img_url in jl_imgs:
            if img_url and img_url not in seen_img_urls:
                all_images.append({"url": img_url, "alt": "", "score": 5, "source": "jsonld"})
                seen_img_urls.add(img_url)

        # Supplement with adapter-provided image URLs (e.g. Myntra Redux state images)
        adapter_imgs = adapter_data.pop("product_image_urls", []) or []
        for img_url in adapter_imgs:
            if img_url and img_url not in seen_img_urls:
                all_images.append({"url": img_url, "alt": "product", "score": 12, "source": "adapter"})
                seen_img_urls.add(img_url)

        static_count = len(all_images)

        # ── Browser fallback — only when static HTML yields 0 images ──────────
        # JS-rendered SPAs (Flipkart, Meesho, JioMart, etc.) don't put product
        # images in the initial HTML response. We launch headless Chromium to
        # get the fully rendered DOM and extract images from it.
        browser_used = False
        if static_count == 0:
            job["steps"][-1]["label"] = (
                "⟳ JS-rendered page detected — launching headless browser to find product images..."
            )
            try:
                from url_scanner.browser_fetcher import fetch_rendered_page
                browser_result = await asyncio.wait_for(
                    fetch_rendered_page(url, timeout_s=35.0),
                    timeout=45.0,
                )
                browser_imgs = browser_result.get("images", [])
                for img in browser_imgs:
                    if img["url"] not in seen_img_urls:
                        all_images.append(img)
                        seen_img_urls.add(img["url"])

                # Re-parse rendered HTML for more images
                rendered_html = browser_result.get("html", "")
                if rendered_html and len(rendered_html) > 3000:
                    extra = collect_images(rendered_html, browser_result.get("final_url", url))
                    for img in extra:
                        if img["url"] not in seen_img_urls:
                            all_images.append(img)
                            seen_img_urls.add(img["url"])

                browser_used = True
            except asyncio.TimeoutError:
                _add_step(scan_id, "⚠ Browser fetch timed out — continuing with available data")
            except Exception as e:
                _add_step(scan_id, f"⚠ Browser fetch failed: {str(e)[:80]}")

        job["steps"][-1]["done"] = True
        if len(all_images) == 0:
            job["steps"][-1]["label"] = (
                "⚠ 0 product images found — this may be a bot-protected or login-required page"
            )
        elif browser_used:
            job["steps"][-1]["label"] = (
                f"✓ {len(all_images)} product images found (browser-rendered)"
            )
        else:
            job["steps"][-1]["label"] = f"✓ {len(all_images)} product images found"

        # ── Step 7: Select packaging images for OCR ───────────────────────────
        # Three-stage compliance image scoring:
        #   Stage 1   — URL/metadata signals (fast, always runs)
        #   Stage 2   — PIL visual analysis on top-12 candidates
        #   Stage 2.5 — Thumbnail OCR pre-scan (detects FSSAI/compliance text)
        #   Stage 3   — Coverage-optimized selection (greedy set-cover)
        _add_step(scan_id, f"⟳ Analysing {len(all_images)} images for compliance content...", done=False)


        from url_scanner.image_classifier import score_and_select_images

        # For adapter-provided images, pre-boost score (they are real product images)
        for img in all_images:
            if img.get("source") == "adapter":
                img["score"] = img.get("score", 0) + 20

        packaging_candidates = await score_and_select_images(
            all_images,
            max_for_ocr=4,
            enable_visual=True,
            enable_thumb_ocr=True,
        )
        packaging_count = len(packaging_candidates)

        job["steps"][-1]["done"] = True
        job["steps"][-1]["label"] = f"✓ {packaging_count} packaging images selected for OCR"

        # ── Debug: log all candidate scores to server console ─────────────────
        import sys as _sys
        _enc = getattr(_sys.stdout, 'encoding', 'utf-8') or 'utf-8'
        def _safe_print(s: str) -> None:
            print(s.encode(_enc, errors='replace').decode(_enc))

        # Build debug summary for step label
        from url_scanner.image_classifier import IMAGE_TYPES
        _type_counts: dict[str, int] = {}
        for _img in packaging_candidates:
            _cat = _img.get("classification", {}).get("category", "unknown")
            _type_counts[_cat] = _type_counts.get(_cat, 0) + 1

        _type_summary = ", ".join(
            f"{v} {k.replace('_', ' ')}" for k, v in _type_counts.items()
        )
        job["steps"][-1]["label"] = (
            f"✓ {packaging_count} packaging images selected for OCR"
            + (f" ({_type_summary})" if _type_summary else "")
        )

        # ── Classification breakdown step (UI visibility) ─────────────────────
        all_cat_counts: dict[str, int] = {}
        rejected_count = 0
        for _img in all_images:
            _cat = _img.get("classification", {}).get("category", "unknown")
            all_cat_counts[_cat] = all_cat_counts.get(_cat, 0) + 1
            if _img.get("skip_reason"):
                rejected_count += 1

        _clf_parts = []
        for _cat in ("back_package", "side_label", "front_package", "nutrition"):
            if all_cat_counts.get(_cat, 0):
                _clf_parts.append(f"{all_cat_counts[_cat]} {_cat.replace('_', '/')}")
        _lifestyle_n = all_cat_counts.get("lifestyle", 0) + all_cat_counts.get("non_packaging", 0)
        if _lifestyle_n:
            _clf_parts.append(f"{_lifestyle_n} lifestyle/promo (rejected)")
        if all_cat_counts.get("unknown", 0):
            _clf_parts.append(f"{all_cat_counts['unknown']} unclassified")

        if _clf_parts:
            _add_step(scan_id, f"✓ Image types: {'; '.join(_clf_parts)}")

        _safe_print(
            f"\n[IMAGE SELECTION] {len(all_images)} candidates -> {packaging_count} selected"
        )
        for i, img in enumerate(
            sorted(all_images, key=lambda x: -x.get("compliance_score", 0))[:14]
        ):
            sigs = img.get("ocr_signals", {})
            clf = img.get("classification", {})
            cat = clf.get("category", "unknown")
            # Look up LM relevance from IMAGE_TYPES (map legacy category names)
            _cat_upper = cat.upper()
            _lm = IMAGE_TYPES.get(_cat_upper, {}).get("lm_relevance", "?")
            selected_mark = "-> SELECTED" if img in packaging_candidates else ""
            rejected_mark = f"skip: {img.get('skip_reason', '')[:40]}" if img.get("skip_reason") else ""
            sig_str = " ".join(
                k.replace("has_", "").upper()
                for k, v in sigs.items()
                if v and k != "is_marketing_only"
            )
            _safe_print(
                f"  #{i+1:02d} score={img.get('compliance_score', 0):+4d} "
                f"cat={cat:<20} lm={_lm} "
                f"signals=[{sig_str}] "
                f"{selected_mark}{rejected_mark}"
            )
            _safe_print(f"        url=...{img.get('url', '')[-60:]}")
        print()



        # ── Store selected images immediately so frontend can preview them ──────
        # Single source of truth: packaging_candidates -> preview AND OCR
        job["ocr_selected_images"] = [
            {
                "url": img["url"],
                "rank": i + 1,
                "score": img.get("compliance_score", 0),
                "reason": img.get("score_reason", ""),
                "ocr_signals": img.get("ocr_signals", {}),   # compliance pills for UI
            }
            for i, img in enumerate(packaging_candidates)
        ]

        adapter_data["images"] = [
            {"url": img["url"], "classification": img.get("classification", {})}
            for img in all_images[:12]
        ]

        # ── Step 8: DOWNLOAD AND OCR PACKAGING IMAGES ─────────────────────────
        # EasyOCR is pre-warmed at startup. Multi-pass: full + contrast + crop.
        _add_step(scan_id, f"⟳ Downloading and analysing {len(packaging_candidates)} images...", done=False)

        from url_scanner.image_processor import process_images_parallel, process_image
        packaging_urls = [img["url"] for img in packaging_candidates]

        ocr_pipeline_result = await process_images_parallel(packaging_urls, max_images=4)

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

        # ── Step 9b: Adaptive field-tracking OCR loop (field-type routed) ─────
        # After initial OCR, check which key LM fields are still missing.
        # Uses rank_for_missing_fields() to pick the image MOST LIKELY to
        # contain those specific fields — not just the next-highest-score image.
        #
        # Stopping conditions:
        #   A) All critical fields found
        #   B) All relevant candidates exhausted
        #   C) OCR budget (6 images total) reached

        from url_scanner.image_classifier import rank_for_missing_fields

        import re as _re
        _MFR_PATTERN         = _re.compile(r"manufactur|mfg\.?\s*by|packed\s*by|marketed\s*by|packer|importer", _re.I)
        _NETQTY_PATTERN      = _re.compile(r"net\s*(?:weight|wt|quantity|qty|content|vol)|nett?\s*wt|\d+\s*(?:kg|g\b|ml|litre|liter)\b", _re.I)
        _MRP_PATTERN         = _re.compile(r"m\.?r\.?p\.?|maximum\s*retail\s*price|rs\.?\s*\d|₹\s*\d", _re.I)
        _FSSAI_PATTERN       = _re.compile(r"fssai|f\.?s\.?s\.?a\.?i|lic(?:ence|ense)?\s*no|[1-9]\d{13}", _re.I)
        _COUNTRY_PATTERN     = _re.compile(r"country\s*of\s*origin|made\s*in\s*india|product\s*of", _re.I)
        # Ingredient detection — same fuzzy variants as thumbnail OCR signal
        _INGREDIENTS_PATTERN = _re.compile(
            r"INGREDI[EA]N[T]?S?\s*[:\-.]?"
            r"|INGREDI[1l]ENTS\s*[:\-.]?"
            r"|COMPOSITION\s*[:\-.]?"
            r"|MADE\s+(?:FROM|WITH)\s*[:\-.]?"
            r"|PREPARED\s+FROM\s*[:\-.]?",
            _re.I,
        )

        _ALL_CRITICAL = ("manufacturer", "net_qty", "mrp", "fssai", "country", "ingredients")

        def _check_missing_fields(text: str) -> list[str]:
            """Return list of critical LM field names NOT yet found in combined OCR text."""
            missing = []
            if not _MFR_PATTERN.search(text):         missing.append("manufacturer")
            if not _NETQTY_PATTERN.search(text):      missing.append("net_qty")
            if not _MRP_PATTERN.search(text):         missing.append("mrp")
            if not _FSSAI_PATTERN.search(text):       missing.append("fssai")
            if not _COUNTRY_PATTERN.search(text):     missing.append("country")
            if not _INGREDIENTS_PATTERN.search(text): missing.append("ingredients")
            return missing

        selected_urls_set = set(packaging_urls)
        missing_fields = _check_missing_fields(combined_ocr_text)
        found_fields   = [f for f in _ALL_CRITICAL if f not in missing_fields]

        # ── Field coverage matrix step (always shown after initial OCR) ────────
        _cov_found   = " | ".join(f.upper() for f in found_fields)   or "none"
        _cov_missing = " | ".join(f.upper() for f in missing_fields) or "none"
        _cov_pct     = int(100 * len(found_fields) / len(_ALL_CRITICAL))
        _add_step(
            scan_id,
            f"✓ Coverage after initial OCR: {_cov_pct}% — "
            f"FOUND: {_cov_found}  |  MISSING: {_cov_missing}"
        )


        # ── Adaptive extension (field-type-routed while loop) ─────────────────
        if missing_fields:
            ocr_budget_used = len(packaging_urls)
            MAX_OCR_BUDGET  = 7  # initial 4 + up to 3 adaptive images

            remaining_pool = [
                img for img in all_images
                if img.get("url") not in selected_urls_set
                and img.get("compliance_score", 0) > -50
            ]

            if remaining_pool and ocr_budget_used < MAX_OCR_BUDGET:
                _add_step(
                    scan_id,
                    f"⟳ Searching for {', '.join(missing_fields)} in "
                    f"{len(remaining_pool)} remaining candidate image(s)...",
                    done=False,
                )

                last_fb_result: dict = {}

                while missing_fields and remaining_pool and ocr_budget_used < MAX_OCR_BUDGET:
                    # Re-rank per round so we always pick the image most likely to cover
                    # THE SPECIFIC fields still missing (not just generic compliance score)
                    routed = rank_for_missing_fields(
                        remaining_pool,
                        missing_fields,
                        already_processed_urls=selected_urls_set,
                    )
                    if not routed:
                        break

                    fb_img = routed[0]
                    remaining_pool = [
                        img for img in remaining_pool
                        if img.get("url") != fb_img.get("url")
                    ]

                    fb_result = await process_image(fb_img["url"], img_index=99)
                    last_fb_result = fb_result
                    selected_urls_set.add(fb_img["url"])

                    if not fb_result.get("ocr_text"):
                        continue  # image downloaded but no text — try next

                    ocr_budget_used += 1
                    combined_ocr_text += "\n\n" + fb_result["ocr_text"]

                    fb_entities = extract_entities(fb_result["ocr_text"])
                    for k, v in fb_entities.items():
                        if v and not ocr_entities.get(k):
                            ocr_entities[k] = v

                    prev_missing   = list(missing_fields)
                    missing_fields = _check_missing_fields(combined_ocr_text)
                    newly_found    = [f for f in prev_missing if f not in missing_fields]

                    job["ocr_selected_images"].append({
                        "url": fb_img["url"],
                        "rank": len(job["ocr_selected_images"]) + 1,
                        "score": fb_img.get("compliance_score", 0),
                        "reason": (
                            f"Field-targeted — sought: {', '.join(prev_missing[:3])}; "
                            f"found: {', '.join(newly_found) or 'none'}"
                        ),
                        "ocr_signals": fb_img.get("ocr_signals", {}),
                    })

                # Collect barcodes
                for bc in last_fb_result.get("barcodes", []):
                    if bc not in all_barcodes:
                        all_barcodes.append(bc)

                found_now = [f for f in _ALL_CRITICAL if f not in missing_fields]
                _pct2 = int(100 * len(found_now) / len(_ALL_CRITICAL))
                job["steps"][-1]["done"] = True
                job["steps"][-1]["label"] = (
                    f"✓ All critical fields found after {ocr_budget_used} images ({_pct2}%)"
                    if not missing_fields else
                    f"⚠ After {ocr_budget_used} images: still missing {', '.join(missing_fields)} "
                    f"({_pct2}% coverage)"
                )





        # Also run entity extraction on combined adapter text (catches fields in JS-extracted data)
        # This helps for Myntra/Meesho where manufacturer info is in Redux state text
        web_text_for_entities = " ".join(filter(None, [
            adapter_data.get("manufacturer_raw", ""),
            adapter_data.get("packer_raw", ""),
            adapter_data.get("importer_raw", ""),
            full_text[:2000],  # Visible page text
        ]))
        if web_text_for_entities.strip():
            web_entities = extract_entities(web_text_for_entities)
            # Merge web entities as fallback (OCR entities take priority)
            for k, v in web_entities.items():
                if v and not ocr_entities.get(k):
                    ocr_entities[k] = v

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
        # Infer category from model data + URL hints
        platform_info_with_url = {**platform_info, "url": url}
        inferred_category = _infer_category(model, platform_info_with_url)

        job["status"] = "done"
        job["result"] = {
            "scan_id": scan_id,
            "status": "done",
            "platform": platform_info["display_name"],
            "formatted_text": formatted_text,
            "product_name": model.get("product", {}).get("name", ""),
            "category": inferred_category,
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
        "ocr_selected_images": [],
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
        ocr_selected_images=job.get("ocr_selected_images", []),
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
