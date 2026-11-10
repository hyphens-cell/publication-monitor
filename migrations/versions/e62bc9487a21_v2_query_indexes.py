"""Add indexes for bounded lists and relationship loading without changing data.

Revision ID: e62bc9487a21
Revises: d39e71a42f10
"""

from alembic import op

revision = "e62bc9487a21"
down_revision = "d39e71a42f10"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_employees_department_active_name", "employees", ["department_id", "is_active", "full_name"]),
    ("ix_plan_items_plan", "plan_items", ["plan_id"]),
    ("ix_plans_year_status", "plans", ["year", "status"]),
    ("ix_publications_department_created", "publications", ["department_id", "created_at", "id"]),
    ("ix_publications_verification_created", "publications", ["verification_status", "created_at", "id"]),
    ("ix_publication_history_publication_changed", "publication_history", ["publication_id", "changed_at"]),
    ("ix_attachments_publication", "attachments", ["publication_id"]),
    ("ix_notifications_email_pending", "notifications", ["email_sent", "id"]),
)


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
