"""feat: добавить проверку файлов публикаций

Revision ID: c4811c2fcceb
Revises: adcc59308d78
Create Date: 2026-08-18 16:10:43.983982
"""

from alembic import op
import sqlalchemy as sa


revision = "c4811c2fcceb"
down_revision = "adcc59308d78"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "attachments",
        sa.Column(
            "review_status",
            sa.String(length=30),
            nullable=False,
            server_default="PENDING",
        ),
    )

    op.add_column(
        "attachments",
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "attachments",
        sa.Column(
            "reviewed_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "attachments",
        sa.Column(
            "review_comment",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_attachments_reviewed_by_users",
        "attachments",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column(
        "attachments",
        "review_status",
        server_default=None,
    )


def downgrade():
    op.drop_constraint(
        "fk_attachments_reviewed_by_users",
        "attachments",
        type_="foreignkey",
    )

    op.drop_column(
        "attachments",
        "review_comment",
    )

    op.drop_column(
        "attachments",
        "reviewed_at",
    )

    op.drop_column(
        "attachments",
        "reviewed_by",
    )

    op.drop_column(
        "attachments",
        "review_status",
    )