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
    compliance_text: str = ""          # raw combined text for compliance engine
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
        elif adapter_key == "jiomart":
            from url_scanner.adapters.jiomart import extract as adapter_extract
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
                    fetch_rendered_page(url, timeout_s=60.0),
                    timeout=70.0,
                )
                browser_imgs = browser_result.get("images", [])
                rendered_html = browser_result.get("html", "")
                html_size = len(rendered_html)

                # Server-side log to diagnose bot-block vs actual 0 images
                import sys as _sys2
                _enc2 = getattr(_sys2.stdout, 'encoding', 'utf-8') or 'utf-8'
                _msg = (f"[BROWSER FETCH] html={html_size:,}B  "
                        f"images={len(browser_imgs)}  "
                        f"colorImages={'YES' if 'colorImages' in rendered_html else 'NO'}")
                print(_msg.encode(_enc2, errors='replace').decode(_enc2))

                if html_size < 10_000:
                    _add_step(scan_id, f"⚠ Browser got small page ({html_size:,} bytes) — Amazon bot-block")

                for img in browser_imgs:
                    if img.get("url") and img["url"] not in seen_img_urls:
                        all_images.append(img)
                        seen_img_urls.add(img["url"])

                # Do NOT re-run collect_images on rendered_html for Amazon —
                # browser_fetcher already called _extract_amazon_gallery_images on it.
                is_amazon_url = "amazon." in url.lower()
                if not is_amazon_url and rendered_html and html_size > 3000:
                    extra = collect_images(rendered_html, browser_result.get("final_url", url))
                    for img in extra:
                        if img.get("url") and img["url"] not in seen_img_urls:
                            all_images.append(img)
                            seen_img_urls.add(img["url"])

                browser_used = True

                # ── CRITICAL: Re-extract ALL metadata from browser HTML ────────
                # For Flipkart/Meesho/JioMart the static page has NO product data.
                # The browser got the real rendered page with all fields.
                # Re-run the full extraction pipeline on the browser HTML.
                if rendered_html and html_size > 5_000:
                    try:
                        from bs4 import BeautifulSoup as _BS
                        from url_scanner.structured_extractor import extract_structured_data as _esd

                        _add_step(scan_id, "⟳ Re-extracting product data from browser page...", done=False)

                        browser_soup     = _BS(rendered_html, "lxml")
                        browser_full_text = browser_soup.get_text(" ", strip=True)
                        browser_structured = _esd(rendered_html)
                        browser_adapter_data = adapter_extract(browser_soup, browser_full_text)

                        # Update full_text and soup with browser data (always richer)
                        if len(browser_full_text) > len(full_text):
                            full_text = browser_full_text
                            soup = browser_soup

                        # Merge structured — browser data wins for fields that were empty
                        for k, v in browser_structured.items():
                            if v and not structured.get(k):
                                structured[k] = v

                        # These fields are ONLY available from the browser-rendered page;
                        # always overwrite with browser values regardless of existing data.
                        _always_overwrite = {
                            "product_name", "brand", "mrp", "net_quantity",
                            "manufacturer_raw", "packer_raw", "importer_raw",
                            "country_of_origin", "fssai", "best_before",
                            "consumer_care_phone", "consumer_care_email",
                            "description", "price_block", "feature_bullets",
                            "mfg_date",
                        }

                        for k, v in browser_adapter_data.items():
                            if v and (k in _always_overwrite or not adapter_data.get(k)):
                                adapter_data[k] = v

                        # Also add browser adapter's product_image_urls to the image pool
                        browser_img_urls = browser_adapter_data.pop("product_image_urls", []) or []
                        for img_url in browser_img_urls:
                            if img_url and img_url not in seen_img_urls:
                                all_images.append({"url": img_url, "alt": "product", "score": 18, "source": "browser_adapter"})
                                seen_img_urls.add(img_url)

                        web_name_new = adapter_data.get("product_name") or structured.get("name") or ""
                        job["steps"][-1]["done"] = True
                        job["steps"][-1]["label"] = (
                            f"✓ Browser product data extracted: {web_name_new[:50]}"
                            if web_name_new else "✓ Browser product data extracted"
                        )
                    except Exception as _re_err:
                        import traceback as _tb
                        print(f"[BROWSER RE-EXTRACT ERROR] {_tb.format_exc()}")
                        # Non-fatal — continue with whatever data we have

            except asyncio.TimeoutError:
                _add_step(scan_id, "⚠ Browser fetch timed out — continuing with available data")
            except Exception as e:
                import traceback
                print(f"[BROWSER ERROR] {traceback.format_exc()}")
                _add_step(scan_id, f"⚠ Browser fetch failed: {str(e)[:120]}")

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

        # ── Store ALL images immediately so frontend can show manual picker ─────
        # Each image gets basic metadata; full scoring happens in Step 7.
        job["all_images"] = [
            {
                "url": img.get("url", ""),
                "alt": img.get("alt", ""),
                "score": img.get("score", 0),
                "source": img.get("source", "html"),
            }
            for img in all_images
            if img.get("url")
        ]

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

        # ── Step 8½: Extract entities from FULL webpage text (pre-OCR baseline) ──
        # Before running OCR on images, extract all LM fields from the product
        # page itself. Many e-commerce sites list manufacturer, FSSAI, country,
        # net qty, MRP in the product details table — no image needed for those.
        # OCR results will override/supplement these where images have richer data.
        _add_step(scan_id, "⟳ Extracting product details from webpage text...", done=False)

        from url_scanner.intelligence.entity_extractor import extract_entities

        # Build comprehensive web text: all adapter fields + full page text + structured
        web_text_parts: list[str] = []

        # 1. All string values from adapter_data (product details table, bullets, etc.)
        for _k, _v in adapter_data.items():
            if isinstance(_v, str) and _v.strip():
                web_text_parts.append(_v)
            elif isinstance(_v, list):
                web_text_parts.extend([str(x) for x in _v if str(x).strip()])

        # 2. Full visible page text (catches text that adapters may miss)
        if full_text:
            web_text_parts.append(full_text[:8000])   # first 8K chars (product detail area)

        # 3. Structured data (JSON-LD / OpenGraph)
        for _k, _v in structured.items():
            if isinstance(_v, str) and _v.strip():
                web_text_parts.append(_v)

        web_corpus = "\n".join(filter(None, web_text_parts))
        web_entities: dict = {}
        if web_corpus.strip():
            web_entities = extract_entities(web_corpus)

        # Show what was found on the webpage (separate from OCR)
        _web_found_fields = []
        if web_entities.get("manufacturer_raw") or web_entities.get("manufacturer_name"):
            _web_found_fields.append("MANUFACTURER")
        if web_entities.get("net_quantity"):
            _web_found_fields.append("NET_QTY")
        if web_entities.get("mrp"):
            _web_found_fields.append("MRP")
        if web_entities.get("fssai"):
            _web_found_fields.append("FSSAI")
        if web_entities.get("country_of_origin"):
            _web_found_fields.append("COUNTRY")
        if web_entities.get("expiry_date"):
            _web_found_fields.append("EXPIRY")
        if web_entities.get("mfg_date"):
            _web_found_fields.append("MFG_DATE")
        if web_entities.get("consumer_care_phone") or web_entities.get("consumer_care_email"):
            _web_found_fields.append("CONSUMER_CARE")
        if web_entities.get("ingredients"):
            _web_found_fields.append("INGREDIENTS")
        # Also count directly-extracted adapter keys
        if not _web_found_fields:
            if adapter_data.get("manufacturer_raw") or adapter_data.get("packer_raw"):
                _web_found_fields.append("MANUFACTURER")
            if adapter_data.get("net_quantity") or adapter_data.get("Item Weight"):
                _web_found_fields.append("NET_QTY")
            if adapter_data.get("mrp"):
                _web_found_fields.append("MRP")
            if adapter_data.get("fssai"):
                _web_found_fields.append("FSSAI")
            if adapter_data.get("country_of_origin"):
                _web_found_fields.append("COUNTRY")

        job["steps"][-1]["done"] = True
        if _web_found_fields:
            job["steps"][-1]["label"] = (
                f"✓ Webpage fields detected: {' | '.join(_web_found_fields)}"
            )
        else:
            job["steps"][-1]["label"] = (
                "⚠ Limited data on webpage — will rely on packaging image OCR"
            )

        # Seed ocr_entities with web baseline (OCR will override these)
        ocr_entities: dict = dict(web_entities)

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
                f"{imgs_downloaded}/{imgs_processed} images — using webpage data"
            )

        # Log barcode results
        if all_barcodes:
            barcode_summary = ", ".join(f"{b['type']}:{b['value']}" for b in all_barcodes[:3])
            _add_step(scan_id, f"✓ Barcode decoded: {barcode_summary[:80]}")

        # ── Step 9: Extract entities from OCR text → merge ON TOP of web baseline ─
        # OCR entities take priority over web entities for same field.
        # Fields only found on webpage (not in images) are preserved from web_entities.
        _ocr_entities_from_images: dict = {}
        if combined_ocr_text:
            _add_step(scan_id, "⟳ Extracting entities from packaging text...", done=False)
            _ocr_entities_from_images = extract_entities(combined_ocr_text)
            job["steps"][-1]["done"] = True

            found_from_ocr = [k for k, v in _ocr_entities_from_images.items() if v]
            if found_from_ocr:
                _add_step(scan_id, f"✓ OCR entities detected: {', '.join(found_from_ocr[:8])}")
            else:
                _add_step(scan_id, "⚠ Entity extraction: limited fields found in OCR text — using webpage data")

        # Merge: OCR image entities override web baseline for every field they find
        for k, v in _ocr_entities_from_images.items():
            if v:
                ocr_entities[k] = v

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
        _COUNTRY_PATTERN     = _re.compile(r"country\s*of\s*origin|made\s*in\s*india|product\s*of|india|Made In", _re.I)
        _INGREDIENTS_PATTERN = _re.compile(
            r"INGREDI[EA]N[T]?S?\s*[:\-.]?"
            r"|INGREDI[1l]ENTS\s*[:\-.]?"
            r"|COMPOSITION\s*[:\-.]?"
            r"|MADE\s+(?:FROM|WITH)\s*[:\-.]?"
            r"|PREPARED\s+FROM\s*[:\-.]?",
            _re.I,
        )

        _ALL_CRITICAL = ("manufacturer", "net_qty", "mrp", "fssai", "country", "ingredients")

        def _check_missing_fields(ocr_text: str, adp: dict) -> list[str]:
            """
            Return list of critical LM field names NOT yet found.
            Checks BOTH raw OCR/page text AND the structured adapter_data fields,
            so that fields extracted from the product details table are not falsely
            reported as missing just because the OCR images were blank.
            """
            # Build a combined search text: OCR + all adapter_data string values
            adp_text_parts = []
            for k, v in adp.items():
                if isinstance(v, str) and v:
                    adp_text_parts.append(v)
                elif isinstance(v, list):
                    adp_text_parts.extend([str(x) for x in v if x])
            combined = "\n".join(filter(None, [ocr_text] + adp_text_parts))

            missing = []

            # Manufacturer — also check structured adapter keys directly
            mfr_present = (
                _MFR_PATTERN.search(combined) or
                adp.get("manufacturer_raw") or adp.get("packer_raw") or adp.get("importer_raw")
            )
            if not mfr_present:
                missing.append("manufacturer")

            # Net Quantity — also check adapter direct keys
            qty_present = (
                _NETQTY_PATTERN.search(combined) or
                adp.get("net_quantity") or adp.get("Item Weight") or adp.get("Net Quantity") or
                adp.get("Unit Count") or adp.get("Net Content") or adp.get("Net Weight")
            )
            if not qty_present:
                missing.append("net_qty")

            # MRP — also check adapter mrp key
            mrp_present = (
                _MRP_PATTERN.search(combined) or
                adp.get("mrp") or adp.get("price_block")
            )
            if not mrp_present:
                missing.append("mrp")

            # FSSAI — also check adapter fssai key
            fssai_present = (
                _FSSAI_PATTERN.search(combined) or
                adp.get("fssai")
            )
            if not fssai_present:
                missing.append("fssai")

            # Country of Origin — check text, adapter key, OR infer from address
            country_present = (
                _COUNTRY_PATTERN.search(combined) or
                adp.get("country_of_origin")
            )
            if not country_present:
                # Infer from manufacturer/packer address — if address contains Indian
                # state/city/PIN code, country is India (very common case)
                from url_scanner.intelligence.entity_extractor import _infer_country_from_address
                _mfr_addr = " ".join(filter(None, [
                    adp.get("manufacturer_raw", ""),
                    adp.get("packer_raw", ""),
                    adp.get("importer_raw", ""),
                    adp.get("Manufacturer Address", ""),
                    adp.get("Manufacturer Name", ""),
                ]))
                if _mfr_addr and _infer_country_from_address(_mfr_addr):
                    country_present = True
                # Also check if OCR text itself implies India via address content
                if not country_present and combined:
                    _ocr_inferred = _infer_country_from_address(combined)
                    if _ocr_inferred:
                        country_present = True
            if not country_present:
                missing.append("country")


            # Ingredients — OCR text and adapter ingredients field
            ingr_present = (
                _INGREDIENTS_PATTERN.search(combined) or
                adp.get("ingredients")
            )
            if not ingr_present:
                missing.append("ingredients")

            return missing

        # ── Field coverage summary (shown after OCR on the 4 selected images) ──
        # Checks both OCR text AND webpage adapter data — so fields found on the
        # product page (manufacturer table, net weight, MRP, country) are not
        # falsely shown as missing just because OCR images were blank.
        missing_fields = _check_missing_fields(combined_ocr_text, adapter_data)
        found_fields   = [f for f in _ALL_CRITICAL if f not in missing_fields]

        _cov_found   = " | ".join(f.upper() for f in found_fields)   or "none"
        _cov_missing = " | ".join(f.upper() for f in missing_fields) or "none"
        _cov_pct     = int(100 * len(found_fields) / len(_ALL_CRITICAL))
        _add_step(
            scan_id,
            f"✓ Coverage after OCR + webpage data: {_cov_pct}% — "
            f"FOUND: {_cov_found}  |  MISSING: {_cov_missing}"
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

        # ── Build compliance_text — canonical text for the compliance engine ──
        # Rules.json patterns match phrases like "Manufactured by: X", "MRP: Rs. X"
        # "FSSAI: 12345678901234", "Country of Origin: India" etc.
        #
        # We build this from the ALREADY-EXTRACTED model values, written in
        # exactly the format the patterns expect. This avoids:
        #   • "===" being matched as consumer care contact
        #   • "INFORMATION" being matched as manufacturer name
        #   • Random OCR noise from navigation / UI text
        #
        # Raw OCR text is appended at the end as a last resort for patterns
        # the entity extractor may have missed.

        _cp = []

        # ── Manufacturer / Packer / Importer ─────────────────────────────────
        _mfr  = model.get("manufacturer", {})
        _pkr  = model.get("packer", {})
        _imp  = model.get("importer", {})
        _mfr_name = _mfr.get("name") or _mfr.get("address_raw") or adapter_data.get("manufacturer_raw") or ""
        _pkr_name = _pkr.get("name") or _pkr.get("address_raw") or adapter_data.get("packer_raw") or ""
        _imp_name = _imp.get("name") or _imp.get("address_raw") or ""
        if _mfr_name: _cp.append(f"Manufactured by: {_mfr_name}")
        if _pkr_name and _pkr_name != _mfr_name: _cp.append(f"Packed by: {_pkr_name}")
        if _imp_name: _cp.append(f"Imported by: {_imp_name}")
        # Fallback: feature bullets often contain "MKT. BY" text
        for bullet in adapter_data.get("feature_bullets", []):
            bl = bullet.strip()
            if any(k in bl.lower() for k in ("manufactur", "packed by", "mkt. by", "marketed", "importer")):
                _cp.append(bl)

        # ── Net Quantity ──────────────────────────────────────────────────────
        _qty = model.get("quantity", {})
        _qty_val = _qty.get("package_raw") or _qty.get("website_raw") or adapter_data.get("Net Quantity") or ""
        if _qty_val: _cp.append(f"Net Quantity: {_qty_val}")

        # ── MRP ───────────────────────────────────────────────────────────────
        _com = model.get("commerce", {})
        _mrp_raw = _com.get("mrp_raw") or adapter_data.get("mrp") or adapter_data.get("price_block") or ""
        _mrp_norm = _com.get("mrp_normalized") or {}
        if _mrp_norm.get("found") and _mrp_norm.get("amount"):
            _cp.append(f"MRP: Rs. {_mrp_norm['amount']}")
        elif _mrp_raw:
            _cp.append(f"MRP: Rs. {_mrp_raw}")

        # ── Dates ─────────────────────────────────────────────────────────────
        _dates = model.get("dates", {})
        if _dates.get("mfg_date"):      _cp.append(f"Mfg. Date: {_dates['mfg_date']}")
        if _dates.get("packing_date"):  _cp.append(f"Packed on: {_dates['packing_date']}")
        if _dates.get("expiry_date"):   _cp.append(f"Best Before: {_dates['expiry_date']}")
        # Also add shelf life from adapter
        if adapter_data.get("best_before"): _cp.append(f"Best Before: {adapter_data['best_before']}")

        # ── Consumer Care ─────────────────────────────────────────────────────
        _cc = model.get("consumer_care", {})
        if _cc.get("raw"):    _cp.append(f"Consumer Care: {_cc['raw']}")
        if _cc.get("phone"):  _cp.append(f"Consumer Care Helpline: {_cc['phone']}")
        if _cc.get("email"):  _cp.append(f"Consumer Care Email: {_cc['email']}")
        if adapter_data.get("consumer_care_phone"):
            _cp.append(f"Consumer Care: {adapter_data['consumer_care_phone']}")

        # ── Country of Origin ─────────────────────────────────────────────────
        _orig = model.get("origin", {})
        _country = (
            _orig.get("declared_country") or
            _orig.get("detected_country") or
            adapter_data.get("country_of_origin") or
            ocr_entities.get("country_of_origin") or ""
        )
        if not _country:
            # Infer from address — "HIMACHAL PRADESH" in manufacturer addr → India
            from url_scanner.intelligence.entity_extractor import _infer_country_from_address
            _addr_for_infer = " ".join(filter(None, [
                adapter_data.get("manufacturer_raw", ""),
                adapter_data.get("packer_raw", ""),
                adapter_data.get("Manufacturer Address", ""),
                adapter_data.get("Manufacturer Name", ""),
                model.get("manufacturer", {}).get("address_raw", ""),
            ]))
            if _addr_for_infer:
                _country = _infer_country_from_address(_addr_for_infer)
        if _country:
            _cp.append(f"Country of Origin: {_country}")


        # ── FSSAI ─────────────────────────────────────────────────────────────
        _reg = model.get("regulatory", {})
        _fssai_val = _reg.get("fssai") or adapter_data.get("fssai") or ""
        if _fssai_val: _cp.append(f"FSSAI Licence No. {_fssai_val}")

        # ── Ingredients ───────────────────────────────────────────────────────
        _ing = model.get("ingredients", "")
        if _ing: _cp.append(f"INGREDIENTS: {_ing}")

        # ── Barcode ───────────────────────────────────────────────────────────
        _bc = _reg.get("barcode", "")
        if _bc: _cp.append(f"Barcode: {_bc}")

        # ── Append raw OCR text as fallback for patterns we may have missed ──
        # Cleaned: remove === lines, "Not Detected" lines, and very short lines
        if combined_ocr_text:
            _ocr_lines = []
            for _ln in combined_ocr_text.splitlines():
                _stripped = _ln.strip()
                if (len(_stripped) > 8
                        and not set(_stripped) <= set("=-_*#")
                        and "Not Detected" not in _stripped
                        and "INFORMATION" != _stripped):
                    _ocr_lines.append(_stripped)
            if _ocr_lines:
                _cp.append("\n".join(_ocr_lines))

        compliance_text = "\n".join(_cp)

        # ── Infer category ────────────────────────────────────────────────────
        platform_info_with_url = {**platform_info, "url": url}
        inferred_category = _infer_category(model, platform_info_with_url)

        # ── Build lm_fields — 8 mandatory PCR 2011 §6 fields for UI display ──────
        _mfr_d  = model.get("manufacturer", {})
        _pkr_d  = model.get("packer", {})
        _imp_d  = model.get("importer", {})
        _qty_d  = model.get("quantity", {})
        _com_d  = model.get("commerce", {})
        _dt_d   = model.get("dates", {})
        _cc_d   = model.get("consumer_care", {})
        _ori_d  = model.get("origin", {})
        _reg_d  = model.get("regulatory", {})

        # Manufacturer / Importer — pick best non-empty value
        _mfr_val = (
            _mfr_d.get("name") or _mfr_d.get("address_raw") or
            _pkr_d.get("name") or _pkr_d.get("address_raw") or
            _imp_d.get("name") or _imp_d.get("address_raw") or
            adapter_data.get("manufacturer_raw") or
            adapter_data.get("packer_raw") or ""
        )
        # Importer separately (only if different from manufacturer)
        _imp_val = (_imp_d.get("name") or _imp_d.get("address_raw") or "")
        if _imp_val and _imp_val == _mfr_val:
            _imp_val = ""

        # Net Quantity
        _qty_val = _qty_d.get("package_raw") or _qty_d.get("website_raw") or ""

        # MRP
        _mrp_norm_d = _com_d.get("mrp_normalized") or {}
        _mrp_val = _mrp_norm_d.get("display") or _com_d.get("mrp_raw") or adapter_data.get("mrp") or ""

        # Dates — Mfg date and expiry as separate fields
        _mfg_val    = _dt_d.get("mfg_date") or ""
        _expiry_val = _dt_d.get("expiry_date") or adapter_data.get("best_before") or ""

        # Consumer Care
        _cc_val = _cc_d.get("raw") or _cc_d.get("phone") or _cc_d.get("email") or adapter_data.get("consumer_care_phone") or ""

        # Country of Origin — explicit value or inferred from manufacturer address
        _coo_val = (
            _ori_d.get("declared_country") or
            _ori_d.get("detected_country") or
            adapter_data.get("country_of_origin") or
            ocr_entities.get("country_of_origin") or ""
        )
        if not _coo_val:
            # Infer from manufacturer/packer/importer address
            from url_scanner.intelligence.entity_extractor import _infer_country_from_address
            _all_addr = " ".join(filter(None, [
                _mfr_d.get("address_raw", ""),
                _pkr_d.get("address_raw", ""),
                _imp_d.get("address_raw", ""),
                adapter_data.get("manufacturer_raw", ""),
                adapter_data.get("packer_raw", ""),
                adapter_data.get("Manufacturer Address", ""),
                adapter_data.get("Manufacturer Name", ""),
            ]))
            if _all_addr:
                _inferred = _infer_country_from_address(_all_addr)
                if _inferred:
                    _coo_val = _inferred
                    # Also add to compliance text so rules engine sees it
                    compliance_text = compliance_text + f"\nCountry of Origin: {_inferred}"

        # FSSAI
        _fssai_val = _reg_d.get("fssai") or adapter_data.get("fssai") or ""

        lm_fields = {
            "manufacturer": _mfr_val,
            "importer":     _imp_val,
            "net_quantity":  _qty_val,
            "mfg_date":     _mfg_val,
            "expiry_date":  _expiry_val,
            "mrp":          _mrp_val,
            "consumer_care": _cc_val,
            "country_of_origin": _coo_val,
            "fssai":        _fssai_val,
        }

        job["status"] = "done"
        job["result"] = {
            "scan_id": scan_id,
            "status": "done",
            "platform": platform_info["display_name"],
            "formatted_text": formatted_text,    # for display in text tab
            "compliance_text": compliance_text,   # for compliance engine — raw combined
            "product_name": model.get("product", {}).get("name", ""),
            "category": inferred_category,
            "images_found": len(all_images),
            "packaging_images": packaging_count,
            "model": model,
            "comparisons": comparisons,
            "lm_fields": lm_fields,              # 8 mandatory PCR 2011 §6 fields
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


# ── GET /api/url-scan/{id}/all-images ─────────────────────────────────────────

@router.get("/{scan_id}/all-images")
async def get_all_images(scan_id: str):
    """
    Return ALL images collected from the product page.
    Used by the manual image picker UI so users can override algorithm selection.
    Available as soon as Step 6 (image collection) completes.
    """
    job = _job(scan_id)
    all_images = job.get("all_images", [])
    ocr_selected = {img["url"] for img in job.get("ocr_selected_images", [])}

    # Enrich with scoring info if available (after Step 7 completes)
    return {
        "scan_id": scan_id,
        "total": len(all_images),
        "images": [
            {
                **img,
                "auto_selected": img["url"] in ocr_selected,
            }
            for img in all_images
        ],
    }


# ── POST /api/url-scan/{id}/manual-ocr ───────────────────────────────────────

class ManualOcrRequest(BaseModel):
    image_urls: list[str]   # Up to 6 user-chosen URLs


@router.post("/{scan_id}/manual-ocr")
async def manual_ocr(scan_id: str, payload: ManualOcrRequest):
    """
    Run OCR on a user-selected list of image URLs and return
    the compliance-formatted text.  Does NOT replace the original job result.
    """
    job = _job(scan_id)

    if not payload.image_urls:
        raise HTTPException(422, "No images selected.")
    if len(payload.image_urls) > 8:
        raise HTTPException(422, "Maximum 8 images allowed for manual OCR.")

    # Validate URLs are from the same job's image pool (SSRF guard)
    known_urls = {img["url"] for img in job.get("all_images", [])}
    # Also allow URLs from the auto-selected set (in case all_images isn't populated yet)
    known_urls |= {img["url"] for img in job.get("ocr_selected_images", [])}

    invalid = [u for u in payload.image_urls if u not in known_urls]
    if invalid:
        raise HTTPException(422, f"URL(s) not from this scan's image pool: {invalid[:2]}")

    # ── Run OCR pipeline on chosen images ─────────────────────────────────────
    from url_scanner.image_processor import process_images_parallel
    from url_scanner.intelligence.entity_extractor import extract_entities
    from url_scanner.formatter import format_product
    from url_scanner.intelligence.data_fusion import fuse
    from url_scanner.intelligence.mismatch_detector import detect_mismatches

    ocr_result = await process_images_parallel(payload.image_urls, max_images=8)
    combined_ocr_text = ocr_result["combined_ocr_text"]
    ocr_entities = extract_entities(combined_ocr_text) if combined_ocr_text else {}

    # Get existing job result for platform / adapter data
    existing_result = job.get("result", {})
    existing_model  = existing_result.get("model", {})
    platform_info   = {"display_name": job.get("platform", "Unknown"), "adapter_key": "generic"}

    # Re-fuse with new OCR text
    model = fuse(
        existing_model.get("_adapter_data", {}),
        ocr_text=combined_ocr_text,
        structured=existing_model.get("_structured", {}),
        ocr_entities=ocr_entities,
    )

    comparisons = detect_mismatches(model)
    formatted_text = format_product(model, platform_info, [], comparisons)

    return {
        "scan_id": scan_id,
        "images_processed": ocr_result["images_processed"],
        "ocr_char_count": len(combined_ocr_text),
        "avg_confidence": ocr_result["avg_confidence"],
        "formatted_text": formatted_text,
        "product_name": model.get("product", {}).get("name", existing_result.get("product_name", "")),
    }
