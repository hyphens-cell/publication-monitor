"""feat: добавить проверку файлов публикаций

Revision ID: c4811c2fcceb
Revises: adcc59308d78
Create Date: 2026-08-18 16:10:43.983982
"""

import sqlalchemy as sa
from alembic import op

revision = "c4811c2fcceb"
down_revision = "adcc59308d78"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode preserves the same PostgreSQL DDL and permits a fresh SQLite install.
    with op.batch_alter_table("attachments") as batch:
        batch.add_column(sa.Column("review_status", sa.String(30), nullable=False, server_default="PENDING"))
        batch.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("review_comment", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_attachments_reviewed_by_users", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("attachments") as batch:
        batch.alter_column("review_status", existing_type=sa.String(30), server_default=None)


def downgrade():
    with op.batch_alter_table("attachments") as batch:
        batch.drop_constraint("fk_attachments_reviewed_by_users", type_="foreignkey")
        for column in ("review_comment", "reviewed_at", "reviewed_by", "review_status"):
            batch.drop_column(column)
