"""Cutting migration snippet (owner: Claude 2). Pro registers it in the single Alembic history.

``render_ddl()`` produces the exact SQLite DDL of the cutting tables from the ORM models;
``0001_cutting.sql`` is its committed snapshot and a test keeps both in sync.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

SNAPSHOT = Path(__file__).with_name("0001_cutting.sql")


def render_ddl() -> str:
    from glassflow.core.db import Base
    from glassflow.modules.cutting import models  # noqa: F401  (register tables)

    dialect = sqlite.dialect()
    chunks = ["-- Generated from glassflow.modules.cutting.models; do not edit by hand.\n"]
    for table in Base.metadata.sorted_tables:
        if not table.name.startswith("cut_"):
            continue
        chunks.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            chunks.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
    return "\n".join(chunks)


def write_snapshot() -> None:
    SNAPSHOT.write_text(render_ddl(), encoding="utf-8", newline="\n")
