from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import database
from app.db import sql_models as sm
from app.db.database import Base
from app.version import APP_VERSION


def test_init_db_records_schema_version(monkeypatch):
    eng = create_engine("sqlite://", echo=False)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(database, "SessionLocal", session_local)

    database.init_db()

    with session_local() as session:
        row = session.get(sm.SchemaVersion, database.SCHEMA_VERSION_KEY)
        assert row is not None
        assert row.version == database.SCHEMA_VERSION
        assert row.app_version == APP_VERSION

    status = database.get_schema_status()
    assert status["ok"] is True
    assert status["schema_version"] == database.SCHEMA_VERSION


def test_schema_status_reports_disabled_without_database(monkeypatch):
    monkeypatch.setattr(database, "engine", None)
    monkeypatch.setattr(database, "SessionLocal", None)

    status = database.get_schema_status()

    assert status["enabled"] is False
    assert status["schema_version"] == database.SCHEMA_VERSION
