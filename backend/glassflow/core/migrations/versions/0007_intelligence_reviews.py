"""Review and correction drafts on the shared database and migration graph."""

from alembic import op

from glassflow.modules.intelligence.migrations import intelligence_reviews_0007 as domain

revision = "0007_intelligence_reviews"
down_revision = "0006_operational_documents"


def upgrade():
    domain.upgrade(op)


def downgrade():
    raise RuntimeError("Restore a verified backup instead of deleting review history")
