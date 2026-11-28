"""The platform-owned Alembic graph will run intelligence_0001.upgrade(op); it must match models."""

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from glassflow.modules.intelligence.migrations import intelligence_0001
from glassflow.modules.intelligence.models import INTELLIGENCE_TABLES


def test_migration_snippet_matches_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        intelligence_0001.upgrade(Operations(MigrationContext.configure(connection)))
    inspector = inspect(engine)
    for table in INTELLIGENCE_TABLES:
        migrated = {c["name"]: c["nullable"] for c in inspector.get_columns(table.name)}
        declared = {c.name: c.nullable for c in table.columns}
        assert migrated.keys() == declared.keys(), table.name
        for name, nullable in declared.items():
            if not table.columns[name].primary_key:
                assert migrated[name] == nullable, (table.name, name)
    with engine.begin() as connection:
        intelligence_0001.downgrade(Operations(MigrationContext.configure(connection)))
    assert not set(inspect(engine).get_table_names()) & {t.name for t in INTELLIGENCE_TABLES}
