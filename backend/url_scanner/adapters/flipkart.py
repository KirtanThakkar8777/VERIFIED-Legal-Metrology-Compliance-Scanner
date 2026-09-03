"""
url_scanner/adapters/flipkart.py — Flipkart product data extractor.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup


_COMPLIANCE_KEYS = [
    "manufactur", "packer", "importer", "country", "origin",
    "fssai", "net weight", "net quantity", "mrp", "maximum retail",
    "best before", "expiry", "consumer care", "contact", "address",
    "item weight", "ingredients", "allergen", "nutritional", "storage",
]


def _is_compliance(key: str) -> bool:
    kl = key.lower()
    return any(c in kl for c in _COMPLIANCE_KEYS)


def _table_rows(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            k = cells[0].get_text(" ", strip=True).strip(":")
            v = cells[1].get_text(" ", strip=True)
            if k and v:
                data[k] = v
    return data


def extract(soup: BeautifulSoup, full_text: str) -> dict:
    result: dict = {"source": "Flipkart"}

    # Product name
    h1 = soup.find("h1")
    if h1:
        result["product_name"] = h1.get_text(" ", strip=True)

    # Compliance table rows
    rows = _table_rows(soup)
    for k, v in rows.items():
        if _is_compliance(k):
            result[k] = v[:300]

    # Flipkart product description sections (dynamic class names change frequently)
    # Try multiple known class patterns
    for cls_pattern in [r"X3BRps", r"_2o-xpa", r"_1mXcCf", r"rgWa7D", r"dGKuTl",
                         r"_14cfVK", r"yN\+eNr", r"_1An\+bv", r"pqs9Lf", r"Izz52n"]:
        for el in soup.find_all("div", class_=re.compile(cls_pattern)):
            text = el.get_text("\n", strip=True)
            if any(kw in text.lower() for kw in _COMPLIANCE_KEYS):
                result.setdefault("detail_sections", []).append(text[:400])

    # MRP
    mrp_m = re.search(r"M\.?R\.?P\.?\s*[:\s₹Rs.]*\s*([\d,]+\.?\d{0,2})", full_text, re.IGNORECASE)
    if mrp_m:
        result["mrp"] = mrp_m.group(1).replace(",", "")

    # Price (selling)
    price_m = re.search(r"₹\s*([\d,]+)", full_text)
    if price_m:
        result["selling_price"] = price_m.group(1).replace(",", "")

    # Country of origin
    coo = re.search(r"Country\s*of\s*Origin\s*[:\-]?\s*([A-Za-z\s]{3,30}?)(?:\n|$|\|)",
                    full_text, re.IGNORECASE)
    if coo:
        result["country_of_origin"] = coo.group(1).strip()

    # FSSAI
    fssai = re.search(r"\b([1-9]\d{13})\b", full_text)
    if fssai:
        result["fssai"] = fssai.group(1)

    # Manufacturer
    mfr = re.search(
        r"(?:Manufactured|Marketed|Packed)\s*(?:and\s+\w+\s*)?[Bb]y\s*[:\-]?\s*([^\n,\.]{5,80})",
        full_text
    )
    if mfr:
        result["manufacturer_raw"] = mfr.group(1).strip()

    return result
