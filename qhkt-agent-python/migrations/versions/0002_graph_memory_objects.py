"""add durable graph memory and source object metadata"""

import sqlalchemy as sa
from alembic import op

revision = "0002_graph_memory_objects"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_columns(table)} if inspector.has_table(table) else set()


def upgrade() -> None:
    bind = op.get_bind()
    document_columns = _columns("ai_knowledge_document")
    for name, column in {
        "object_file_id": sa.Column("object_file_id", sa.String(80)),
        "object_key": sa.Column("object_key", sa.String(500)),
        "mime_type": sa.Column("mime_type", sa.String(120)),
        "file_size": sa.Column("file_size", sa.Integer()),
        "checksum": sa.Column("checksum", sa.String(64)),
    }.items():
        if name not in document_columns:
            op.add_column("ai_knowledge_document", column)
    if not sa.inspect(bind).has_table("ai_memory_fact"):
        op.create_table(
            "ai_memory_fact",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("fact_key", sa.String(64), nullable=False),
            sa.Column("fact_value", sa.String(1000), nullable=False),
            sa.Column("source_message_id", sa.String(36)),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("expire_time", sa.DateTime()),
            sa.Column("deleted_time", sa.DateTime()),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
        )
        op.create_index("idx_memory_fact_user_key", "ai_memory_fact", ["user_id", "fact_key"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_memory_fact"):
        op.drop_index("idx_memory_fact_user_key", table_name="ai_memory_fact")
        op.drop_table("ai_memory_fact")
    columns = _columns("ai_knowledge_document")
    for name in ("checksum", "file_size", "mime_type", "object_key", "object_file_id"):
        if name in columns:
            op.drop_column("ai_knowledge_document", name)
