"""
scan/router.py — Scan endpoints and report downloads.
"""
from __future__ import annotations

import io
import csv
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from scan.compliance_engine import run_compliance_check
from report.pdf_gen import generate_pdf

router = APIRouter(prefix="/api", tags=["Scan"])


# ── Helper: persist scan result ───────────────────────────────────────────────

def _save_scan(
    db: Session,
    raw_text: str,
    result: dict,
    product_name: str = "Unknown",
    category: str = "General Packaged Commodities",
    platform: str = "Unknown",
    source_type: str = "TEXT",
    scanned_by: str = "consumer",
) -> models.Scan:
    scan = models.Scan(
        product_name=product_name,
        category=category,
        platform=platform,
        source_type=source_type,
        raw_text=raw_text,
        score=result["score"],
        status=result["status"],
        rule_version=result["rule_version"],
        scanned_by=scanned_by,
    )
    db.add(scan)
    db.flush()  # get scan.id

    for f in result["fields"]:
        db.add(models.FieldResult(
            scan_id=scan.id,
            field_id=f["field_id"],
            field_label=f["field_label"],
            legal_reference=f["legal_reference"],
            status=f["status"],
            detected_value=f.get("detected_value"),
            normalized_value=f.get("normalized_value"),
            confidence=f.get("confidence", 1.0),
            evidence=f.get("evidence"),
            reason=f.get("reason"),
        ))

    for v in result["violations"]:
        db.add(models.Violation(
            scan_id=scan.id,
            field_id=v["field_id"],
            field_label=v["field_label"],
            legal_reference=v["legal_reference"],
            severity=v["severity"],
            reason=v["reason"],
            evidence=v.get("evidence"),
        ))

    db.commit()
    db.refresh(scan)
    return scan


# ── POST /api/scan ────────────────────────────────────────────────────────────

@router.post("/scan", response_model=schemas.ScanOut, status_code=201)
def create_scan(payload: schemas.ScanRequest, db: Session = Depends(get_db)):
    """Run compliance check on pasted/extracted text and persist the result."""
    if not payload.text or len(payload.text.strip()) < 10:
        raise HTTPException(status_code=422, detail="Text too short to analyse.")

    # ── Auto-extract product name from text if not provided ───────────────────
    import re as _re
    product_name = payload.product_name
    if not product_name:
        # Try: "Product: X", "Product Name: X", "Name: X", "Item: X", "Brand: X"
        _name_match = _re.search(
            r"(?:^|\n)\s*(?:product\s*(?:name)?|brand|item|commodity|generic\s*name)\s*[:\-]\s*(.+)",
            payload.text, _re.IGNORECASE
        )
        if _name_match:
            product_name = _name_match.group(1).strip()[:120]

    result = run_compliance_check(payload.text)
    scan = _save_scan(
        db,
        raw_text=payload.text,
        result=result,
        product_name=product_name or "Unknown",
        category=payload.category or "General Packaged Commodities",
        platform=payload.platform or "Unknown",
        source_type=payload.source_type,
    )
    return scan


# ── GET /api/scan/{id} ────────────────────────────────────────────────────────

@router.get("/scan/{scan_id}", response_model=schemas.ScanOut)
def get_scan(scan_id: str, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


# ── GET /api/scan/{id}/report.txt ─────────────────────────────────────────────

@router.get("/scan/{scan_id}/report.txt")
def download_txt(scan_id: str, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    lines = [
        "=" * 60,
        "  VERIFIED v2 — Legal Metrology Compliance Notice",
        "  Packaged Commodities Rules 2011 (PCR-2011)",
        "=" * 60,
        f"  Scan ID     : {scan.id}",
        f"  Product     : {scan.product_name}",
        f"  Category    : {scan.category}",
        f"  Platform    : {scan.platform}",
        f"  Source      : {scan.source_type}",
        f"  Rule Set    : {scan.rule_version}",
        f"  Scanned On  : {scan.created_at.strftime('%d %b %Y, %H:%M UTC')}",
        f"  Score       : {scan.score}/100",
        f"  Verdict     : {scan.status}",
        "-" * 60,
        "  FIELD RESULTS",
        "-" * 60,
    ]
    for f in scan.fields:
        lines.append(f"  [{f.status:6}] {f.field_id} — {f.field_label}")
        if f.detected_value:
            lines.append(f"           Value     : {f.detected_value}")
        if f.normalized_value:
            lines.append(f"           Normalised: {f.normalized_value}")
        if f.reason:
            lines.append(f"           Note      : {f.reason}")
        lines.append("")

    if scan.violations:
        lines += ["-" * 60, "  VIOLATIONS", "-" * 60]
        for v in scan.violations:
            lines.append(f"  • [{v.severity.upper()}] {v.field_label} ({v.legal_reference})")
            lines.append(f"    {v.reason}")
            lines.append("")

    lines += ["=" * 60, "  Generated by VERIFIED v2 — https://verified.gov.in", "=" * 60]
    content = "\n".join(lines)
    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id[:8]}.txt"'},
    )


# ── GET /api/scan/{id}/report.pdf ────────────────────────────────────────────

@router.get("/scan/{scan_id}/report.pdf")
def download_pdf(scan_id: str, db: Session = Depends(get_db)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    pdf_bytes = generate_pdf(scan)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id[:8]}.pdf"'},
    )


# ── POST /api/bulk (CSV batch scan) ──────────────────────────────────────────

@router.post("/bulk", status_code=200)
async def bulk_scan(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Accept a CSV with a 'text' column and run compliance on each row."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="Only CSV files accepted.")
    contents = await file.read()
    decoded = contents.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(decoded))
    
    if "text" not in (reader.fieldnames or []):
        raise HTTPException(status_code=422, detail="CSV must have a 'text' column.")

    results = []
    for i, row in enumerate(reader):
        if i >= 200:  # safety cap
            break
        text = row.get("text", "").strip()
        if not text:
            continue
        result = run_compliance_check(text)
        scan = _save_scan(
            db,
            raw_text=text,
            result=result,
            product_name=row.get("product_name", "Unknown"),
            category=row.get("category", "General Packaged Commodities"),
            platform=row.get("platform", "Unknown"),
            source_type="CSV",
        )
        results.append({
            "scan_id": scan.id,
            "product_name": scan.product_name,
            "score": scan.score,
            "status": scan.status,
        })
    return {"processed": len(results), "results": results}
