"""
url_scanner/intelligence/country_detector.py
Detect country from address text, phone numbers, PIN codes, and explicit names.
"""
from __future__ import annotations
import re


# Indian PIN code ranges (valid 6-digit codes start with 1-8)
_INDIA_PIN = re.compile(r"\b([1-8]\d{5})\b")

# Indian state names (subset for quick detection)
_INDIA_STATES = re.compile(
    r"\b(Maharashtra|Gujarat|Karnataka|Tamil Nadu|Rajasthan|Delhi|"
    r"Uttar Pradesh|Madhya Pradesh|West Bengal|Punjab|Haryana|Kerala|"
    r"Bihar|Odisha|Assam|Telangana|Andhra Pradesh|Himachal Pradesh|"
    r"Uttarakhand|Jharkhand|Chhattisgarh|Goa|Sikkim|Tripura|Manipur|"
    r"Meghalaya|Mizoram|Nagaland|Arunachal Pradesh|Puducherry|Chandigarh)\b",
    re.IGNORECASE,
)

# India phone
_INDIA_PHONE = re.compile(r"(\+91|0\d{10}|1800[\s\-]?\d{6,})")

# Country name keywords
_COUNTRY_KEYWORDS = {
    "india": ("India", 95),
    "china": ("China", 95),
    "usa": ("USA", 95),
    "united states": ("USA", 95),
    "united kingdom": ("United Kingdom", 95),
    "uk": ("United Kingdom", 80),
    "germany": ("Germany", 95),
    "france": ("France", 95),
    "japan": ("Japan", 95),
    "south korea": ("South Korea", 95),
    "korea": ("South Korea", 85),
    "bangladesh": ("Bangladesh", 95),
    "sri lanka": ("Sri Lanka", 95),
    "pakistan": ("Pakistan", 95),
    "vietnam": ("Vietnam", 95),
    "thailand": ("Thailand", 95),
    "indonesia": ("Indonesia", 95),
    "malaysia": ("Malaysia", 95),
    "singapore": ("Singapore", 95),
    "nepal": ("Nepal", 95),
    "italy": ("Italy", 95),
    "spain": ("Spain", 95),
    "australia": ("Australia", 95),
    "new zealand": ("New Zealand", 95),
    "canada": ("Canada", 95),
    "brazil": ("Brazil", 95),
    "israel": ("Israel", 95),
    "turkey": ("Turkey", 95),
}


def detect_country(text: str) -> dict:
    """
    Detect the country associated with an address text.

    Returns:
        { country: str, confidence: int, signals: list[str] }
    """
    if not text:
        return {"country": "Unknown", "confidence": 0, "signals": []}

    tl = text.lower()
    signals = []
    country = ""
    confidence = 0

    # 1. Explicit country keyword match
    for kw, (name, conf) in _COUNTRY_KEYWORDS.items():
        if kw in tl:
            country = name
            confidence = max(confidence, conf)
            signals.append(f"Explicit country name: '{name}'")
            break

    # 2. Indian state detection (implies India)
    state_m = _INDIA_STATES.search(text)
    if state_m:
        if not country:
            country = "India"
            confidence = max(confidence, 88)
        signals.append(f"Indian state detected: '{state_m.group(1)}'")

    # 3. Indian PIN code
    pin_m = _INDIA_PIN.search(text)
    if pin_m:
        if not country:
            country = "India"
            confidence = max(confidence, 82)
        elif country == "India":
            confidence = min(confidence + 5, 98)
        signals.append(f"Indian PIN code: {pin_m.group(1)}")

    # 4. Indian phone number
    phone_m = _INDIA_PHONE.search(text)
    if phone_m:
        if not country:
            country = "India"
            confidence = max(confidence, 75)
        signals.append(f"Indian phone number detected")

    if not country:
        country = "Unknown"
        confidence = 0

    return {
        "country": country,
        "confidence": confidence,
        "signals": signals,
    }


def classify_product_origin(
    manufacturer_country: str,
    importer_country: str,
    declared_country: str,
) -> dict:
    """
    Classify product as Domestic / Imported / Unknown.
    """
    mc = manufacturer_country.lower()
    ic = importer_country.lower()
    dc = declared_country.lower()

    if mc == "india" and not ic:
        return {"classification": "Domestic Product", "notes": "Manufactured in India"}
    if ic == "india" and mc and mc != "india":
        return {"classification": "Imported Product", "notes": f"Manufactured in {manufacturer_country}, Imported to India"}
    if dc and dc != "india":
        return {"classification": "Imported Product", "notes": f"Declared Country of Origin: {declared_country}"}
    if mc == "india" or dc == "india":
        return {"classification": "Domestic Product", "notes": "Manufactured/Originated in India"}
    return {"classification": "Unknown", "notes": "Insufficient data to classify"}
