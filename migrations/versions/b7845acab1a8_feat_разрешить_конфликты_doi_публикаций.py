"""feat: разрешить конфликты DOI публикаций

Revision ID: b7845acab1a8
Revises: c4811c2fcceb
Create Date: 2026-08-20 11:41:35.079515

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7845acab1a8"
down_revision = "c4811c2fcceb"
branch_labels = None
depends_on = None


def upgrade():
    # The initial migration creates an unnamed constraint on SQLite; PostgreSQL
    # assigns this conventional name. Reflection names the SQLite equivalent.
    with op.batch_alter_table(
        "publications", naming_convention={"uq": "%(table_name)s_%(column_0_name)s_key"}
    ) as batch:
        batch.drop_constraint("publications_doi_key", type_="unique")


def downgrade():
    publications = sa.table("publications", sa.column("doi", sa.String(500)))
    duplicate = (
        op.get_bind()
        .execute(
            sa.select(publications.c.doi)
            .where(publications.c.doi.is_not(None))
            .group_by(publications.c.doi)
            .having(sa.func.count() > 1)
            .limit(1)
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore DOI uniqueness while duplicate DOI records exist. Keep the current revision or resolve conflicts first."
        )
    with op.batch_alter_table("publications") as batch:
        batch.create_unique_constraint("publications_doi_key", ["doi"])
