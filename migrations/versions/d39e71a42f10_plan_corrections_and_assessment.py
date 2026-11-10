"""Preserve approved plans during corrections and record monitor assessments.

Revision ID: d39e71a42f10
Revises: b7845acab1a8
"""

import sqlalchemy as sa
from alembic import op

revision = "d39e71a42f10"
down_revision = "b7845acab1a8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plans") as batch:
        batch.add_column(sa.Column("approved_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("correction_requested_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("manual_assessment", sa.String(30), nullable=True))
        batch.add_column(sa.Column("assessment_comment", sa.Text(), nullable=True))
        batch.add_column(sa.Column("assessed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("assessed_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_plans_assessed_by_users", "users", ["assessed_by"], ["id"], ondelete="SET NULL"
        )

    # Copy saved approval data; do not import application models into migrations.
    connection = op.get_bind()
    plans = sa.table("plans", sa.column("id", sa.Integer), sa.column("approved_snapshot", sa.JSON))
    versions = sa.table(
        "plan_versions",
        sa.column("plan_id", sa.Integer),
        sa.column("version_number", sa.Integer),
        sa.column("status", sa.String),
        sa.column("data", sa.JSON),
    )
    publications = sa.table(
        "publications", sa.column("id", sa.Integer), sa.column("plan_item_id", sa.Integer)
    )
    publication_ids = dict(
        connection.execute(sa.select(publications.c.plan_item_id, publications.c.id)).all()
    )
    latest = (
        sa.select(versions.c.plan_id, sa.func.max(versions.c.version_number).label("number"))
        .where(versions.c.status == "APPROVED")
        .group_by(versions.c.plan_id)
        .subquery()
    )
    rows = connection.execute(
        sa.select(versions.c.plan_id, versions.c.data).join(
            latest, (versions.c.plan_id == latest.c.plan_id) & (versions.c.version_number == latest.c.number)
        )
    )
    for plan_id, snapshot in rows:
        for item in snapshot.get("items", []):
            item["publication_id"] = publication_ids.get(item["id"])
        connection.execute(plans.update().where(plans.c.id == plan_id).values(approved_snapshot=snapshot))


def downgrade():
    with op.batch_alter_table("plans") as batch:
        batch.drop_constraint("fk_plans_assessed_by_users", type_="foreignkey")
        for column in (
            "assessed_at",
            "assessed_by",
            "assessment_comment",
            "manual_assessment",
            "correction_requested_at",
            "approved_snapshot",
        ):
            batch.drop_column(column)
