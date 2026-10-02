"""Encrypt account-owned Anthropic credentials and bind gather jobs to owners.

Revision ID: c52e8f1a4d90
Revises: b138df027ec5
"""

from alembic import op
import sqlalchemy as sa

revision = "c52e8f1a4d90"
down_revision = "b138df027ec5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_anthropic_credential",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.SmallInteger(), nullable=False),
        sa.Column("last_four", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("key_version > 0", name="key_version_positive"),
        sa.CheckConstraint("char_length(last_four) = 4", name="last_four_length"),
    )
    op.add_column("gather_run", sa.Column("credential_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_gather_run_credential_account_id",
        "gather_run",
        "account",
        ["credential_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_gather_run_credential_account_id",
        "gather_run",
        ["credential_account_id"],
    )


def downgrade():
    op.drop_index("ix_gather_run_credential_account_id", table_name="gather_run")
    op.drop_constraint(
        "fk_gather_run_credential_account_id",
        "gather_run",
        type_="foreignkey",
    )
    op.drop_column("gather_run", "credential_account_id")
    op.drop_table("account_anthropic_credential")
