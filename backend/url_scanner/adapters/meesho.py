"""
url_scanner/adapters/meesho.py — Meesho product data extractor.
Meesho is React-rendered; plain httpx gets limited data.
We do best-effort extraction from available static HTML.
"""
from __future__ import annotations
import json
import re
from bs4 import BeautifulSoup


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    result: dict = {"source": "Meesho", "note": "Meesho uses JavaScript rendering — data may be incomplete"}

    # Try to find product info in embedded JSON (Next.js __NEXT_DATA__ or similar)
    for script in soup.find_all("script", id="__NEXT_DATA__"):
        try:
            data = json.loads(script.string or "")
            props = data.get("props", {}).get("pageProps", {})
            product = props.get("product") or props.get("productDetails") or {}
            if product:
                result["product_name"] = product.get("name", "")
                result["brand"] = product.get("brand", "")
                result["mrp"] = str(product.get("mrp", ""))
                result["description"] = str(product.get("description", ""))[:400]
        except Exception:
            pass

    # Fallback: h1
    if not result.get("product_name"):
        h1 = soup.find("h1")
        if h1:
            result["product_name"] = h1.get_text(" ", strip=True)

    # Price
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s₹Rs.]*\s*([\d,]+\.?\d{0,2})", full_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")

    # Country of origin
    coo = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30})(?:\n|$|\|)",
                    full_text, re.IGNORECASE)
    if coo:
        result["country_of_origin"] = coo.group(1).strip()

    return result


