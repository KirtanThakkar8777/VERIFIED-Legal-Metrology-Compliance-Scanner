"""
url_scanner/intelligence/address_parser.py
Parse raw address text into structured fields.
Optimized for Indian addresses (PIN codes, state names, etc.)
"""
from __future__ import annotations
import re
from typing import Optional


# Indian state names (full + common abbreviations)
INDIAN_STATES = {
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry", "Chandigarh",
    "Andaman and Nicobar Islands", "Dadra and Nagar Haveli", "Daman and Diu",
    "Lakshadweep",
    # Abbreviations
    "AP", "UP", "MP", "HP", "J&K",
}

STATE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in sorted(INDIAN_STATES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# 6-digit Indian PIN code
PIN_PATTERN = re.compile(r"\b([1-9]\d{5})\b")

# Company name indicators
COMPANY_SUFFIX = re.compile(
    r"\b(Private\s+Limited|Pvt\.?\s*Ltd\.?|Limited|Ltd\.?|LLP|"
    r"Industries|Enterprises|Corporation|Co\.|Foods|Agro|Dairy|"
    r"Pharmaceuticals|Healthcare|Wellness|Solutions|Products|Traders)\b",
    re.IGNORECASE,
)

# Manufacturer/packer role keywords
ROLE_PATTERN = re.compile(
    r"(?:Manufactured|Marketed|Packed|Processed|Imported|Distributed)\s*"
    r"(?:and\s+\w+\s*)?(?:by|for)\s*[:\-]?",
    re.IGNORECASE,
)


def parse_address(raw_text: str) -> dict:
    """
    Parse a raw address string into structured components.

    Input example:
        "Bolas Agro Private Limited, Ground Floor, Block K56, Kakina-574110, Udupi, Karnataka, India."

    Returns:
        {
          company, address_line1, address_line2,
          city, state, pincode, country,
          full_address, confidence
        }
    """
    if not raw_text:
        return _empty()

    text = raw_text.strip().rstrip(".")

    # Strip role prefix
    text = ROLE_PATTERN.sub("", text).strip()

    # Split by comma/newline to get components
    parts = [p.strip() for p in re.split(r"[,\n]+", text) if p.strip()]

    result = _empty()
    result["full_address"] = raw_text.strip()

    # ── Company name ──────────────────────────────────────────────────────────
    company_idx = -1
    for i, part in enumerate(parts):
        if COMPANY_SUFFIX.search(part) and len(part) > 5:
            result["company"] = part
            company_idx = i
            break

    if not result["company"] and parts:
        # First part is often the company name if it has title case
        if re.match(r"^[A-Z]", parts[0]) and len(parts[0]) > 4:
            result["company"] = parts[0]
            company_idx = 0

    # ── PIN code ──────────────────────────────────────────────────────────────
    pin_m = PIN_PATTERN.search(text)
    if pin_m:
        result["pincode"] = pin_m.group(1)

    # ── State ─────────────────────────────────────────────────────────────────
    state_m = STATE_PATTERN.search(text)
    if state_m:
        result["state"] = state_m.group(1).strip()

    # ── Country ───────────────────────────────────────────────────────────────
    country_m = re.search(r"\b(India|China|USA|United States|UK|Germany|France|Japan|Korea)\b",
                          text, re.IGNORECASE)
    if country_m:
        result["country"] = country_m.group(1).strip()
    elif result["state"] or result["pincode"]:
        result["country"] = "India"  # Inferred from Indian state/PIN

    # ── City ─────────────────────────────────────────────────────────────────
    # City is usually the part just before state or just after address lines
    remaining_parts = [p for i, p in enumerate(parts) if i != company_idx]
    for part in remaining_parts:
        if result["state"] and result["state"].lower() in part.lower():
            continue
        if result["country"] and result["country"].lower() in part.lower():
            continue
        if result["pincode"] and result["pincode"] in part:
            # Remove PIN from part to get city
            city_candidate = PIN_PATTERN.sub("", part).strip(" -")
            if city_candidate and len(city_candidate) > 2:
                result["city"] = city_candidate
            break

    # ── Address lines ─────────────────────────────────────────────────────────
    addr_parts = [
        p for i, p in enumerate(parts)
        if i != company_idx
        and not (result["state"] and result["state"].lower() == p.lower())
        and not (result["country"] and result["country"].lower() == p.lower())
    ]
    if addr_parts:
        result["address_line1"] = addr_parts[0] if len(addr_parts) > 0 else ""
        result["address_line2"] = ", ".join(addr_parts[1:3]) if len(addr_parts) > 1 else ""

    # ── Confidence ────────────────────────────────────────────────────────────
    score = 0
    if result["company"]: score += 25
    if result["pincode"]: score += 30
    if result["state"]: score += 25
    if result["country"]: score += 10
    if result["city"]: score += 10
    result["confidence"] = min(score, 100)

    return result


def _empty() -> dict:
    return {
        "company": "",
        "address_line1": "",
        "address_line2": "",
        "city": "",
        "state": "",
        "pincode": "",
        "country": "",
        "full_address": "",
        "confidence": 0,
    }
