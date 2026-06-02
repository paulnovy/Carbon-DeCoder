"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "samples",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("sample_id", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=False),
        sa.Column("r1_path", sa.String(), nullable=True),
        sa.Column("r2_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_samples_project_id", "samples", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_samples_project_id", table_name="samples")
    op.drop_table("samples")
    op.drop_table("projects")
