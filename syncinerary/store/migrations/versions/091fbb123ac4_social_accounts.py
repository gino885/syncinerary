"""Keep provider identities distinct from unverified email/password accounts."""
from alembic import op
import sqlalchemy as sa

revision = "091fbb123ac4"
down_revision = "d91b2f48ac73"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("account", sa.Column("auth_provider", sa.Text(), nullable=False, server_default="email"))
    op.add_column("account", sa.Column("provider_subject", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_account_provider_subject", "account", ["auth_provider", "provider_subject"])
    op.create_check_constraint("ck_account_provider", "account",
        "(auth_provider = 'email' AND provider_subject IS NULL) OR "
        "(auth_provider IN ('google', 'apple') AND provider_subject IS NOT NULL "
        "AND length(provider_subject) > 0 AND email IS NULL AND password_hash IS NULL)")


def downgrade():
    op.drop_constraint("ck_account_provider", "account", type_="check")
    op.drop_constraint("uq_account_provider_subject", "account", type_="unique")
    op.drop_column("account", "provider_subject")
    op.drop_column("account", "auth_provider")
