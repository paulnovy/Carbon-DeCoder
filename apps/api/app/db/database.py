import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DOCKER_DATABASE_URL = "postgresql://wgs:wgs_pass@postgres:5432/wgs_cockpit"
DATABASE_URL = os.getenv("DATABASE_URL", "")
SCHEMA_VERSION_KEY = "wgs_cockpit"
SCHEMA_VERSION = "2026-05-26.1"
SCHEMA_VERSION_NOTES = "SQLAlchemy create_all baseline with additive runtime migrations."


class Base(DeclarativeBase):
    pass


def _resolved_database_url() -> str:
    if DATABASE_URL:
        return DATABASE_URL
    if os.getenv("RUNNING_IN_DOCKER") == "1":
        return DEFAULT_DOCKER_DATABASE_URL
    return ""


_RESOLVED_URL = _resolved_database_url()
_connect_args = {}
if _RESOLVED_URL.startswith("postgresql"):
    _connect_args["connect_timeout"] = int(os.getenv("DATABASE_CONNECT_TIMEOUT", "5"))
engine = create_engine(_RESOLVED_URL, pool_pre_ping=True, connect_args=_connect_args) if _RESOLVED_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None


def init_db() -> None:
    if engine is not None:
        from app.db import sql_models  # Registers ORM tables with Base metadata.

        _ = sql_models
        Base.metadata.create_all(bind=engine)
        _ensure_runtime_columns()
        _ensure_schema_version()


def _ensure_runtime_columns() -> None:
    """Small additive migrations for deployments that already have tables."""
    if engine is None:
        return
    inspector = inspect(engine)
    if "reference_genomes" not in inspector.get_table_names():
        return
    reference_columns = {col["name"] for col in inspector.get_columns("reference_genomes")}
    if "download_sha256" not in reference_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE reference_genomes ADD COLUMN download_sha256 TEXT"))

    if "variant_calls" in inspector.get_table_names():
        variant_columns = {col["name"] for col in inspector.get_columns("variant_calls")}
        with engine.begin() as conn:
            if "genotype" not in variant_columns:
                conn.execute(text("ALTER TABLE variant_calls ADD COLUMN genotype TEXT"))
            if "zygosity" not in variant_columns:
                conn.execute(text("ALTER TABLE variant_calls ADD COLUMN zygosity TEXT"))

    if "taxonomy_hits" in inspector.get_table_names():
        taxonomy_columns = {col["name"] for col in inspector.get_columns("taxonomy_hits")}
        with engine.begin() as conn:
            if "rank" not in taxonomy_columns:
                conn.execute(text("ALTER TABLE taxonomy_hits ADD COLUMN rank TEXT"))
            if "taxid" not in taxonomy_columns:
                conn.execute(text("ALTER TABLE taxonomy_hits ADD COLUMN taxid TEXT"))
            if "lineage" not in taxonomy_columns:
                conn.execute(text("ALTER TABLE taxonomy_hits ADD COLUMN lineage JSON"))
            if "top_clade" not in taxonomy_columns:
                conn.execute(text("ALTER TABLE taxonomy_hits ADD COLUMN top_clade TEXT"))


def _ensure_schema_version() -> None:
    if SessionLocal is None:
        return
    from app.db import sql_models as sm
    from app.version import APP_VERSION

    applied_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        current = session.get(sm.SchemaVersion, SCHEMA_VERSION_KEY)
        if current is None:
            current = sm.SchemaVersion(
                key=SCHEMA_VERSION_KEY,
                version=SCHEMA_VERSION,
                app_version=APP_VERSION,
                notes=SCHEMA_VERSION_NOTES,
                applied_at=applied_at,
            )
            session.add(current)
        elif current.version != SCHEMA_VERSION or current.app_version != APP_VERSION:
            current.version = SCHEMA_VERSION
            current.app_version = APP_VERSION
            current.notes = SCHEMA_VERSION_NOTES
            current.applied_at = applied_at
        session.commit()


def get_schema_status() -> dict:
    if engine is None or SessionLocal is None:
        return {
            "enabled": False,
            "schema_version": SCHEMA_VERSION,
            "schema_key": SCHEMA_VERSION_KEY,
        }
    from app.db import sql_models as sm

    with SessionLocal() as session:
        current = session.get(sm.SchemaVersion, SCHEMA_VERSION_KEY)
        return {
            "enabled": True,
            "schema_key": SCHEMA_VERSION_KEY,
            "schema_version": current.version if current else None,
            "app_version": current.app_version if current else None,
            "applied_at": current.applied_at if current else None,
            "notes": current.notes if current else None,
            "expected_schema_version": SCHEMA_VERSION,
            "ok": bool(current and current.version == SCHEMA_VERSION),
        }


def get_db():
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
