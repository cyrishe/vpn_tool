from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def begin_write(session: Session) -> None:
    # SQLite ignores SELECT FOR UPDATE. Reserve the writer before reading lifecycle state.
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def get_session(request: Request) -> Generator[Session, None, None]:
    database: Database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

