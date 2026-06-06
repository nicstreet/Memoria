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
    return _engine


def get_session_factory() -> sessionmaker:
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal


def get_session() -> Session:
    """Return a session. Caller is responsible for commit/rollback/close."""
    return get_session_factory()()
