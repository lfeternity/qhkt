"""store source page numbers for document citations"""

import sqlalchemy as sa
from alembic import op

revision = "0003_citation_pages"
down_revision = "0002_graph_memory_objects"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_columns(table)} if inspector.has_table(table) else set()


def upgrade() -> None:
    for table in ("ai_citation", "ai_knowledge_chunk"):
        if "page_number" not in _columns(table):
            op.add_column(table, sa.Column("page_number", sa.Integer()))


def downgrade() -> None:
    for table in ("ai_knowledge_chunk", "ai_citation"):
        if "page_number" in _columns(table):
            op.drop_column(table, "page_number")
