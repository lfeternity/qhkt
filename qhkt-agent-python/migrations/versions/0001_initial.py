"""create agent tables

Revision ID: 0001_initial
"""

from alembic import op

from app.persistence.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The first migration is generated from the same metadata used by the service.
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
