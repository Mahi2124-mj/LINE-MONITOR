from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    f"sqlite:///{settings.db_path.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """For background threads: commit on success, rollback on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()


# columns added after the first release: create_all() does not alter existing tables
_NEW_COLUMNS = {"stations": {"parallel_group": "VARCHAR(40) NOT NULL DEFAULT ''"},
                "lines": {"slot_plan": "JSON NOT NULL DEFAULT '[]'", "off_days": "JSON NOT NULL DEFAULT '[]'"},
                "cycles": {"elements": "JSON"}}


def _add_missing_columns() -> None:
    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            have = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in cols.items():
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
