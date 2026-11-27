"""Interim transaction helpers for the cutting router until Pro's platform UoW is merged.

``write_transaction`` takes the SQLite write lock first (like ``BEGIN IMMEDIATE``) so the version check and the write of one confirmation
are serialised by SQLite; the compare-and-set UPDATEs and the partial unique index remain the real
correctness guards. ``read_session`` is a short read with no write lock. Pro may replace both with the
shared UoW without changing the service code (the service never commits).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


@contextmanager
def write_transaction(factory) -> Iterator[Session]:
    session: Session = factory()
    try:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            # A write statement (even matching no row) makes the DBAPI open the transaction and take the
            # SQLite write lock now, before any version is read. Equivalent to BEGIN IMMEDIATE.
            connection.execute(text("UPDATE cut_datasets SET mode = mode WHERE dataset_id = '__lock__'"))
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session(factory) -> Iterator[Session]:
    session: Session = factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()
