"""
dashboard/router.py — Regulator dashboard analytics endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, desc, case
from sqlalchemy.orm import Session

import models
import schemas
from auth.utils import get_current_user
from database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummary)
def get_summary(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    total = db.query(func.count(models.Scan.id)).scalar() or 0
    pass_c = db.query(func.count(models.Scan.id)).filter(models.Scan.status == "PASS").scalar() or 0
    fail_c = db.query(func.count(models.Scan.id)).filter(models.Scan.status == "FAIL").scalar() or 0
    part_c = db.query(func.count(models.Scan.id)).filter(models.Scan.status == "PARTIAL").scalar() or 0
    avg_score = db.query(func.avg(models.Scan.score)).scalar() or 0.0
    compliance_rate = round((pass_c / total * 100) if total else 0, 1)
    return {
        "total_scans": total,
        "pass_count": pass_c,
        "fail_count": fail_c,
        "partial_count": part_c,
        "avg_score": round(float(avg_score), 1),
        "compliance_rate": compliance_rate,
    }


@router.get("/categories", response_model=List[schemas.CategoryStat])
def get_categories(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    rows = (
        db.query(
            models.Scan.category,
            func.count(models.Scan.id).label("count"),
            func.avg(models.Scan.score).label("avg_score"),
        )
        .group_by(models.Scan.category)
        .order_by(desc("count"))
        .all()
    )
    return [
        {"category": r.category, "count": r.count, "avg_score": round(float(r.avg_score or 0), 1)}
        for r in rows
    ]


@router.get("/platforms", response_model=List[schemas.PlatformStat])
def get_platforms(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    rows = (
        db.query(
            models.Scan.platform,
            func.count(models.Scan.id).label("count"),
            func.sum(
                case((models.Scan.status == "FAIL", 1), else_=0)
            ).label("fails"),
        )
        .group_by(models.Scan.platform)
        .order_by(desc("count"))
        .all()
    )
    result = []
    for r in rows:
        fail_rate = round((int(r.fails or 0) / r.count * 100) if r.count else 0, 1)
        result.append({"platform": r.platform, "count": r.count, "fail_rate": fail_rate})
    return result


@router.get("/trends", response_model=List[schemas.TrendPoint])
def get_trends(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Daily scan counts + avg score for the last N days."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.strftime("%Y-%m-%d", models.Scan.created_at).label("date"),
            func.count(models.Scan.id).label("scans"),
            func.avg(models.Scan.score).label("avg_score"),
        )
        .filter(models.Scan.created_at >= since)
        .group_by("date")
        .order_by("date")
        .all()
    )
    return [
        {"date": r.date, "scans": r.scans, "avg_score": round(float(r.avg_score or 0), 1)}
        for r in rows
    ]


@router.get("/violations")
def get_violations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Paginated violations list with optional filters."""
    q = (
        db.query(models.Violation, models.Scan)
        .join(models.Scan, models.Violation.scan_id == models.Scan.id)
    )
    if severity:
        q = q.filter(models.Violation.severity == severity.lower())
    if platform:
        q = q.filter(models.Scan.platform.ilike(f"%{platform}%"))
    total = q.count()
    rows = q.order_by(desc(models.Violation.created_at)).offset(skip).limit(limit).all()

    items = [
        {
            "scan_id": scan.id,
            "product_name": scan.product_name,
            "platform": scan.platform,
            "field_label": v.field_label,
            "legal_reference": v.legal_reference,
            "severity": v.severity,
            "reason": v.reason,
            "created_at": v.created_at.isoformat(),
        }
        for v, scan in rows
    ]
    return {"total": total, "skip": skip, "limit": limit, "items": items}
