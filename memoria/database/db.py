from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from memoria.config import DB_PATH
from memoria.database.models import Base

_engine = None
SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
        # Enable WAL mode for better concurrent read performance
        @event.listens_for(_engine, "connect")
        def set_wal(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(_engine)
        _migrate(_engine)
    return _engine


def _migrate(engine):
    """Add columns introduced after initial schema creation (idempotent)."""
    new_columns = [
        ("metadata", "title",   "TEXT"),
        ("metadata", "subject", "TEXT"),
        ("files",    "renamed", "INTEGER NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in new_columns:
            existing = [
                row[1] for row in
                conn.execute(__import__("sqlalchemy").text(f"PRAGMA table_info({table})"))
            ]
            if col not in existing:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
                )
                conn.commit()


def get_session_factory() -> sessionmaker:
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal


def get_session() -> Session:
    """Return a session. Caller is responsible for commit/rollback/close."""
    return get_session_factory()()


# ── App settings helpers ───────────────────────────────────────────────────────

def get_app_setting(key: str, default: str = "") -> str:
    """Read a value from the app_settings table. Returns default if not set."""
    from memoria.database.models import AppSetting
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        return row.value if (row and row.value is not None) else default
    except Exception:
        return default
    finally:
        session.close()


def set_app_setting(key: str, value: str) -> None:
    """Write a value to the app_settings table (upsert)."""
    from memoria.database.models import AppSetting
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
