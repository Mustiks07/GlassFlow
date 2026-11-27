import os
from pathlib import Path

from fastapi import Request
from sqlalchemy import String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AppMetadata(Base):
    __tablename__ = "app_metadata"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


def create_database(data_dir: Path | None = None):
    directory = data_dir or Path(os.environ.get("GLASSFLOW_DATA_DIR", ".runtime"))
    directory.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{(directory / 'glassflow.db').resolve().as_posix()}")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    # Foundation only. GPT Pro replaces schema bootstrap with versioned Alembic migrations.
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        if session.get(AppMetadata, "foundation_version") is None:
            session.add(AppMetadata(key="foundation_version", value="0.1.0"))
    return engine, factory


def session_dependency(request: Request):
    """Request-scoped session. The platform owner supplies transaction boundaries."""
    with request.app.state.session_factory() as session:
        yield session


def session_is_ready(session: Session) -> bool:
    return session.get(AppMetadata, "foundation_version") is not None
