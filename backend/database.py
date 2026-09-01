"""
database.py — SQLAlchemy engine, session factory, and Base class.
All models import Base from here.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # needed for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
