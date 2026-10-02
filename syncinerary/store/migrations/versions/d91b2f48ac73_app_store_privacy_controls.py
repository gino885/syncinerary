"""Record versioned Anthropic consent for every account.

Revision ID: d91b2f48ac73
Revises: c52e8f1a4d90
"""

from alembic import op
import sqlalchemy as sa

revision = "d91b2f48ac73"
down_revision = "c52e8f1a4d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "account",
        sa.Column("anthropic_consent_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "account",
        sa.Column(
            "anthropic_consent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "anthropic_consent_complete",
        "account",
        "(anthropic_consent_version IS NULL) = (anthropic_consent_at IS NULL)",
    )


def downgrade():
    op.drop_constraint("anthropic_consent_complete", "account", type_="check")
    op.drop_column("account", "anthropic_consent_at")
    op.drop_column("account", "anthropic_consent_version")
