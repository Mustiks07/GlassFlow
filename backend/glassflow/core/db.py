import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

SCHEMA_HEAD = "0003_material_use"


class Base(DeclarativeBase):
    pass


class AppMetadata(Base):
    __tablename__ = "app_metadata"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


def create_database(data_dir: Path | None = None):
    directory = data_dir or default_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    database_path = (directory / "glassflow.db").resolve()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    from glassflow.core import models  # noqa: F401

    with engine.connect() as connection:
        current = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).first()
        version = (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
            if current
            else None
        )
    if version != SCHEMA_HEAD and database_path.exists() and database_path.stat().st_size:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        backup_database(database_path, directory / f"pre-migration-{stamp}.db")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
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


def default_data_dir():
    configured = os.environ.get("GLASSFLOW_DATA_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "GlassFlow"
    return Path.home() / ".local" / "share" / "GlassFlow"


def backup_database(source: Path, destination: Path):
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as target:
        original.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
