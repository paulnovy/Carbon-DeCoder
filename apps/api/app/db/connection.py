"""Postgres database connection and session management."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://wgs:wgs_pass@postgres:5432/wgs_cockpit",
)

engine = None
SessionLocal = None
Base = declarative_base()


def init_db():
    """Initialize database connection and create tables."""
    global engine, SessionLocal
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
