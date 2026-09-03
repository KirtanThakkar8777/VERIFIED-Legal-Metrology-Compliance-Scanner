"""
url_scanner/image_classifier.py
Classify product images into categories using URL/alt-text heuristics.
No ML model required — fast rule-based classification.
"""
from __future__ import annotations
import re


CATEGORIES = {
    "front_package": [
        "front", "main", "primary", "_SL1500_", "_SL1000_", "front-view",
        "pack-front", "thumbnail", "_AC_SL", "product-image",
    ],
    "back_package": [
        "back", "rear", "reverse", "back-view", "pack-back",
        "ingredients", "nutrition", "nutrition-label",
    ],
    "side_label": [
        "side", "label", "detail", "spec", "specification",
        "manufacturer", "mfg", "barcode", "qr",
    ],
    "nutrition": [
        "nutrition", "nutritional", "ingredient", "allergen",
        "supplement-facts", "facts-panel",
    ],
    "lifestyle": [
        "lifestyle", "model", "person", "happy", "banner",
        "hero", "mood", "scene", "background",
    ],
}


def classify_image(url: str, alt: str = "") -> dict:
    """
    Classify a product image URL into a category.

    Returns:
        { category: str, confidence: float, is_packaging: bool }
    """
    combined = (url + " " + alt).lower()

    scores: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in combined:
                scores[cat] += 1

    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    if best_score == 0:
        # Heuristic: Amazon _SL\d+_ is usually front pack; _SS\d+_ is thumbnail
        if re.search(r"_SL\d{3,4}_|_AC_SL\d+|_SX\d+", url):
            best_cat = "front_package"
            best_score = 1
        else:
            best_cat = "unknown"

    confidence = min(0.5 + best_score * 0.1, 0.95)
    is_packaging = best_cat in ("front_package", "back_package", "side_label", "nutrition")

    return {
        "category": best_cat,
        "confidence": round(confidence, 2),
        "is_packaging": is_packaging,
    }


def select_packaging_images(images: list[dict], max_for_ocr: int = 5) -> list[dict]:
    """
    Given image list from image_collector, classify each and select
    the best candidates for OCR.

    Returns list of images with classification added, ordered by relevance.
    """
    classified = []
    for img in images:
        clf = classify_image(img["url"], img.get("alt", ""))
        classified.append({**img, "classification": clf})

    # Sort: packaging images first, then by score
    classified.sort(
        key=lambda x: (
            -int(x["classification"]["is_packaging"]),
            -x["score"],
        )
    )

    return classified[:max_for_ocr]
