"""Integrate domain schemas into the single platform migration graph."""

from alembic import op

revision = "0004_domains"
down_revision = "0003_material_use"


def upgrade():
    from glassflow.core.db import Base
    from glassflow.modules.cutting import models as cutting  # noqa: F401
    from glassflow.modules.intelligence.migrations.intelligence_0001 import upgrade as intelligence

    connection = op.get_bind()
    # C2's versioned ORM definitions generate its checked DDL snapshot.
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("cut_"):
            table.create(connection, checkfirst=True)
    intelligence(op)


def downgrade():
    from glassflow.core.db import Base
    from glassflow.modules.intelligence.migrations.intelligence_0001 import downgrade as intelligence

    intelligence(op)
    for table in reversed(Base.metadata.sorted_tables):
        if table.name.startswith("cut_"):
            table.drop(op.get_bind(), checkfirst=True)
