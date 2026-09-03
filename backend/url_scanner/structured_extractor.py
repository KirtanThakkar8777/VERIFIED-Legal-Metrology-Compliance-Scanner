"""
url_scanner/structured_extractor.py
Extract JSON-LD, OpenGraph, schema.org microdata, and meta tags from HTML.
"""
from __future__ import annotations
import json
import re
from typing import Any

from bs4 import BeautifulSoup


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _flatten_jsonld(obj: Any, depth: int = 0) -> dict:
    """Recursively find a Product JSON-LD node."""
    if depth > 5:
        return {}
    if isinstance(obj, list):
        for item in obj:
            r = _flatten_jsonld(item, depth + 1)
            if r:
                return r
        return {}
    if isinstance(obj, dict):
        t = obj.get("@type", "")
        if isinstance(t, str) and "product" in t.lower():
            return obj
        if isinstance(t, list) and any("product" in x.lower() for x in t if isinstance(x, str)):
            return obj
        # Recurse into @graph
        graph = obj.get("@graph")
        if graph:
            return _flatten_jsonld(graph, depth + 1)
    return {}


def extract_structured_data(html: str) -> dict:
    """
    Extract all structured product data from HTML.

    Returns a best-effort dict with keys:
        name, brand, description, image_urls, sku, gtin,
        price, currency, availability,
        manufacturer, country_of_origin,
        og_title, og_image, og_description
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {}

    # ── JSON-LD ──────────────────────────────────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        data = _safe_json(script.string or "")
        if not data:
            continue
        product = _flatten_jsonld(data)
        if not product:
            continue

        result["name"] = result.get("name") or product.get("name", "")
        result["description"] = result.get("description") or product.get("description", "")
        result["sku"] = result.get("sku") or product.get("sku", "")
        result["gtin"] = result.get("gtin") or (
            product.get("gtin13") or product.get("gtin") or
            product.get("gtin8") or product.get("mpn", "")
        )

        # Brand
        brand = product.get("brand")
        if isinstance(brand, dict):
            result["brand"] = brand.get("name", "")
        elif isinstance(brand, str):
            result["brand"] = brand

        # Offers / price
        offers = product.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            result["price"] = str(offers.get("price", ""))
            result["currency"] = offers.get("priceCurrency", "INR")
            result["availability"] = str(offers.get("availability", ""))
            result["seller"] = (
                offers.get("seller", {}).get("name", "")
                if isinstance(offers.get("seller"), dict)
                else str(offers.get("seller", ""))
            )

        # Images
        imgs = product.get("image", [])
        if isinstance(imgs, str):
            imgs = [imgs]
        elif isinstance(imgs, dict):
            imgs = [imgs.get("url", "")]
        result.setdefault("image_urls", []).extend([i for i in imgs if i])

    # ── OpenGraph ─────────────────────────────────────────────────────────────
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        content = meta.get("content", "")
        if not content:
            continue
        if prop == "og:title":
            result["og_title"] = content
        elif prop == "og:image":
            result.setdefault("og_images", []).append(content)
        elif prop == "og:description":
            result["og_description"] = content
        elif prop == "product:price:amount":
            result["price"] = result.get("price") or content
        elif prop == "product:brand":
            result["brand"] = result.get("brand") or content

    # ── Canonical URL ─────────────────────────────────────────────────────────
    link = soup.find("link", rel="canonical")
    if link:
        result["canonical_url"] = link.get("href", "")

    return result
