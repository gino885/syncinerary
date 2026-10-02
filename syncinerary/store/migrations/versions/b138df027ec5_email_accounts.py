"""Verified email accounts; revoke legacy handle-only sessions.

Revision ID: b138df027ec5
Revises: a027ce916db4
"""
from alembic import op
import sqlalchemy as sa

revision = 'b138df027ec5'
down_revision = 'a027ce916db4'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('email', 'password_hash', 'verify_digest', 'reset_digest'):
        op.add_column('account', sa.Column(name, sa.Text(), nullable=True))
    for name in ('verified_at', 'verify_expires_at', 'reset_expires_at'):
        op.add_column('account', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('account_email_key', 'account', ['email'])
    op.execute('UPDATE account_session SET expires_at = LEAST(expires_at, CURRENT_TIMESTAMP)')


def downgrade():
    op.drop_constraint('account_email_key', 'account', type_='unique')
    for name in ('reset_expires_at', 'verify_expires_at', 'verified_at', 'reset_digest', 'verify_digest', 'password_hash', 'email'):
        op.drop_column('account', name)
