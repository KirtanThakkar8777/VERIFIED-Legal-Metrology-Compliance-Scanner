"""
models.py — SQLAlchemy ORM models.
All tables are created via Base.metadata.create_all() in main.py.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="REGULATOR")
    created_at = Column(DateTime, default=datetime.utcnow)


class Scan(Base):
    __tablename__ = "scans"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_name = Column(String(200), default="Unknown")
    category = Column(String(100), default="General Packaged Commodities")
    platform = Column(String(100), default="Unknown")
    source_type = Column(String(20), default="TEXT")   # TEXT | IMAGE | CSV | URL
    raw_text = Column(Text)
    score = Column(Integer, default=0)
    status = Column(String(10), default="FAIL")        # PASS | PARTIAL | FAIL
    rule_version = Column(String(30), default="PCR-2011-v2")
    scanned_by = Column(String(20), default="consumer")
    created_at = Column(DateTime, default=datetime.utcnow)

    fields = relationship("FieldResult", back_populates="scan", cascade="all, delete")
    violations = relationship("Violation", back_populates="scan", cascade="all, delete")


class FieldResult(Base):
    __tablename__ = "field_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(36), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(String(5), nullable=False)        # F01..F08
    field_label = Column(String(150), nullable=False)
    legal_reference = Column(String(50), nullable=False)
    status = Column(String(10), nullable=False)         # PASS | FAIL | REVIEW | N/A
    detected_value = Column(Text)
    normalized_value = Column(Text)
    confidence = Column(Float, default=1.0)
    evidence = Column(Text)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    scan = relationship("Scan", back_populates="fields")


class Violation(Base):
    __tablename__ = "violations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(36), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(String(5), nullable=False)
    field_label = Column(String(150), nullable=False)
    legal_reference = Column(String(50), nullable=False)
    severity = Column(String(10), default="high")
    reason = Column(Text, nullable=False)
    evidence = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    scan = relationship("Scan", back_populates="violations")
