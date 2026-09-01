"""
schemas.py — Pydantic request/response models for the VERIFIED v2 API.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr


# ── Auth schemas ──────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "REGULATOR"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Scan schemas ──────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    text: str
    source_type: str = "TEXT"          # TEXT | URL | IMAGE | CSV
    product_name: Optional[str] = None
    category: Optional[str] = None
    platform: Optional[str] = None


class FieldResultOut(BaseModel):
    field_id: str
    field_label: str
    legal_reference: str
    status: str                        # PASS | FAIL | REVIEW | N/A
    detected_value: Optional[str] = None
    normalized_value: Optional[str] = None
    confidence: float = 1.0
    evidence: Optional[str] = None
    reason: Optional[str] = None

    class Config:
        from_attributes = True


class ViolationOut(BaseModel):
    field_id: str
    field_label: str
    legal_reference: str
    severity: str
    reason: str
    evidence: Optional[str] = None

    class Config:
        from_attributes = True


class ScanOut(BaseModel):
    id: str
    product_name: str
    category: str
    platform: str
    source_type: str
    score: int
    status: str
    rule_version: str
    scanned_by: str
    created_at: datetime
    fields: List[FieldResultOut] = []
    violations: List[ViolationOut] = []

    class Config:
        from_attributes = True


# ── URL Fetch schema ──────────────────────────────────────────────────────────

class FetchUrlRequest(BaseModel):
    url: str


class FetchUrlOut(BaseModel):
    extracted_text: str
    product_name: str
    marketplace: str
    raw_html_length: int


# ── OCR schema ────────────────────────────────────────────────────────────────

class OcrOut(BaseModel):
    extracted_text: str
    confidence: float
    word_count: int


# ── Dashboard schemas ─────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    total_scans: int
    pass_count: int
    fail_count: int
    partial_count: int
    avg_score: float
    compliance_rate: float


class CategoryStat(BaseModel):
    category: str
    count: int
    avg_score: float


class PlatformStat(BaseModel):
    platform: str
    count: int
    fail_rate: float


class TrendPoint(BaseModel):
    date: str
    scans: int
    avg_score: float


class ViolationListItem(BaseModel):
    scan_id: str
    product_name: str
    field_label: str
    legal_reference: str
    severity: str
    reason: str
    created_at: datetime

    class Config:
        from_attributes = True
