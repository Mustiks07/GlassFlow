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
            connection.execute(text("BEGIN IMMEDIATE"))
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session(factory) -> Iterator[Session]:
    # Passing an existing Session is an explicit borrowed scope: its caller
    # retains commit/rollback/close ownership, including BEGIN IMMEDIATE.
    borrowed = isinstance(factory, Session)
    session: Session = factory if borrowed else factory()
    try:
        connection = session.connection()
        if connection.dialect.name == 'sqlite':
            driver = connection.connection.driver_connection
            # Session autobegin does not imply a DBAPI transaction in sqlite's
            # legacy mode. SELECTs need an actual BEGIN for one WAL snapshot.
            if not driver.in_transaction:
                connection.exec_driver_sql('BEGIN')
        yield session
    finally:
        if not borrowed:
            session.rollback()
            session.close()
