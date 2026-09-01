"""
scan/compliance_engine.py — Core rule-checking engine.

Reads rules.json, applies regex patterns to the raw product text,
computes field-level PASS/FAIL/REVIEW/N/A verdicts, then aggregates
a total compliance score (0-100).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from scan.normalizer import normalize_mrp, normalize_quantity, normalize_date

# Load rules once at module level
_RULES_PATH = Path(__file__).parent / "rules.json"
with open(_RULES_PATH, encoding="utf-8") as _f:
    _RULES = json.load(_f)

RULE_VERSION: str = _RULES["rule_version"]
FIELDS: List[Dict[str, Any]] = _RULES["fields"]


# ── Normaliser dispatch ───────────────────────────────────────────────────────

def _normalise(field_id: str, raw: Optional[str]) -> Optional[str]:
    if field_id == "F05":
        return normalize_mrp(raw)
    if field_id == "F02":
        return normalize_quantity(raw)
    if field_id in ("F03", "F04"):
        return normalize_date(raw)
    return raw.strip() if raw else None


# ── Single field check ────────────────────────────────────────────────────────

def _check_field(field: Dict[str, Any], text: str) -> Dict[str, Any]:
    fid = field["id"]
    patterns = field.get("patterns", [])
    detected: Optional[str] = None
    evidence: Optional[str] = None

    # Try every pattern; stop on first match
    for pat in patterns:
        try:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        except re.error:
            continue
        if m:
            # Prefer capture group 1 if it exists
            detected = (m.group(1) if m.lastindex else m.group(0)).strip()
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            evidence = "..." + text[start:end].replace("\n", " ").strip() + "..."
            break

    # F01 also needs an address — check address_patterns if name found
    if fid == "F01" and detected:
        address_found = False
        for apat in field.get("address_patterns", []):
            try:
                am = re.search(apat, text, re.IGNORECASE | re.MULTILINE)
            except re.error:
                continue
            if am:
                address_found = True
                break
        if not address_found:
            return {
                "field_id": fid,
                "field_label": field["label"],
                "legal_reference": field["legal_ref"],
                "status": "REVIEW",
                "detected_value": detected,
                "normalized_value": _normalise(fid, detected),
                "confidence": 0.6,
                "evidence": evidence,
                "reason": "Manufacturer name found but complete address not clearly identified.",
            }

    if detected:
        return {
            "field_id": fid,
            "field_label": field["label"],
            "legal_reference": field["legal_ref"],
            "status": "PASS",
            "detected_value": detected,
            "normalized_value": _normalise(fid, detected),
            "confidence": 0.9,
            "evidence": evidence,
            "reason": None,
        }

    # Not detected — check if this is an e-commerce source scan
    # Fields F03, F04, F07, F08 often don't appear on marketplace listing pages
    # but ARE required on physical packaging — mark as REVIEW not FAIL
    PHYSICAL_LABEL_ONLY = {"F03", "F04", "F07", "F08"}
    is_ecommerce = bool(re.search(
        r"(?:amazon|flipkart|meesho|myntra|e-commerce|marketplace)\s*(?:\.in|listing|online)",
        text, re.IGNORECASE
    ))
    if fid in PHYSICAL_LABEL_ONLY and is_ecommerce:
        return {
            "field_id": fid,
            "field_label": field["label"],
            "legal_reference": field["legal_ref"],
            "status": "REVIEW",
            "detected_value": None,
            "normalized_value": None,
            "confidence": 0.5,
            "evidence": None,
            "reason": (
                f"{field['label']} not found in the online listing — "
                "this field is mandatory on the physical packaging. "
                f"Verify compliance on the physical product label. ({field['legal_ref']})"
            ),
        }
    return {
        "field_id": fid,
        "field_label": field["label"],
        "legal_reference": field["legal_ref"],
        "status": "FAIL",
        "detected_value": None,
        "normalized_value": None,
        "confidence": 1.0,
        "evidence": None,
        "reason": f"{field['label']} not found in the provided text. Required by {field['legal_ref']}.",
    }


# ── Score calculation ─────────────────────────────────────────────────────────

def _calculate_score(results: List[Dict]) -> int:
    """Weighted score: PASS=full, REVIEW=partial, FAIL=0."""
    weights = {"PASS": 1.0, "REVIEW": 0.5, "FAIL": 0.0, "N/A": 0.0}
    total_weight = 0.0
    earned = 0.0
    for r in results:
        w = 1.0
        total_weight += w
        earned += w * weights.get(r["status"], 0)
    if total_weight == 0:
        return 0
    return round((earned / total_weight) * 100)


def _status_from_score(score: int, results: List[Dict]) -> str:
    high_fails = sum(
        1 for r in results
        if r["status"] == "FAIL"
        and next(
            (f["severity"] for f in FIELDS if f["id"] == r["field_id"]), "low"
        ) == "high"
    )
    if score >= 85 and high_fails == 0:
        return "PASS"
    if score >= 50:
        return "PARTIAL"
    return "FAIL"


# ── Public API ────────────────────────────────────────────────────────────────

def run_compliance_check(text: str) -> Dict[str, Any]:
    """
    Run all 8 field checks against *text*.

    Returns a dict with:
        rule_version, score, status, fields, violations
    """
    results = [_check_field(f, text) for f in FIELDS]
    score = _calculate_score(results)
    status = _status_from_score(score, results)

    violations = [
        {
            "field_id": r["field_id"],
            "field_label": r["field_label"],
            "legal_reference": r["legal_reference"],
            "severity": next(
                (f["severity"] for f in FIELDS if f["id"] == r["field_id"]), "medium"
            ),
            "reason": r["reason"] or "",
            "evidence": r.get("evidence"),
        }
        for r in results
        if r["status"] in ("FAIL", "REVIEW")
    ]

    return {
        "rule_version": RULE_VERSION,
        "score": score,
        "status": status,
        "fields": results,
        "violations": violations,
    }
