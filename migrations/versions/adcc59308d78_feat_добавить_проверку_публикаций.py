"""feat: добавить проверку публикаций

Revision ID: adcc59308d78
Revises: 9773180112a1
Create Date: 2026-08-18 14:06:17.375850

"""
from alembic import op
import sqlalchemy as sa


revision = "adcc59308d78"
down_revision = "9773180112a1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "publications",
        schema=None,
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=30),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "verified_by",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "verified_at",
                sa.DateTime(),
                nullable=True,
            )
        )

        batch_op.create_foreign_key(
            "fk_publications_verified_by_users",
            "users",
            ["verified_by"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        """
        UPDATE publications
        SET verification_status = 'PENDING'
        WHERE verification_status IS NULL
        """
    )

    with op.batch_alter_table(
        "publications",
        schema=None,
    ) as batch_op:
        batch_op.alter_column(
            "verification_status",
            existing_type=sa.String(length=30),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table(
        "publications",
        schema=None,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_publications_verified_by_users",
            type_="foreignkey",
        )
        batch_op.drop_column("verified_at")
        batch_op.drop_column("verified_by")
        batch_op.drop_column("verification_status")