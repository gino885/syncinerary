"""M7a group trips: accounts, invites, trip chat

Revision ID: f5a91c3d7e08
Revises: e42f7a1c9b30
Create Date: 2026-09-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f5a91c3d7e08"
down_revision: Union[str, Sequence[str], None] = "e42f7a1c9b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("handle"),
    )
    op.create_table(
        "account_session",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(
        "ix_account_session_account_id", "account_session", ["account_id"]
    )

    # Nullable: every existing traveler predates accounts, and the
    # single-player flow still creates travelers without one.
    op.add_column("traveler", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_traveler_account_id",
        "traveler",
        "account",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_traveler_account_id", "traveler", ["account_id"])
    # Postgres treats NULLs as distinct, so this constrains accounts without
    # blocking the many account-less travelers that already exist.
    op.create_unique_constraint(
        "uq_traveler_trip_account", "traveler", ["trip_id", "account_id"]
    )

    op.create_table(
        "trip_invite",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("created_by_traveler_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), server_default="20", nullable=False),
        sa.Column("uses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trip.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_trip_invite_trip_id", "trip_invite", ["trip_id"])

    trip_message_kind = postgresql.ENUM(
        "text", "link", "system", name="trip_message_kind"
    )
    trip_message_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "trip_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("traveler_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "text", "link", "system", name="trip_message_kind", create_type=False
            ),
            server_default="text",
            nullable=False,
        ),
        sa.Column("link_attachment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trip.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["traveler_id"], ["traveler.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["link_attachment_id"], ["source_attachment.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trip_message_trip_created", "trip_message", ["trip_id", "created_at"]
    )
    op.create_index("ix_trip_message_traveler_id", "trip_message", ["traveler_id"])
    op.create_index(
        "ix_trip_message_link_attachment_id", "trip_message", ["link_attachment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_trip_message_link_attachment_id", table_name="trip_message")
    op.drop_index("ix_trip_message_traveler_id", table_name="trip_message")
    op.drop_index("ix_trip_message_trip_created", table_name="trip_message")
    op.drop_table("trip_message")
    postgresql.ENUM(name="trip_message_kind").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_trip_invite_trip_id", table_name="trip_invite")
    op.drop_table("trip_invite")

    op.drop_constraint("uq_traveler_trip_account", "traveler", type_="unique")
    op.drop_index("ix_traveler_account_id", table_name="traveler")
    op.drop_constraint("fk_traveler_account_id", "traveler", type_="foreignkey")
    op.drop_column("traveler", "account_id")

    op.drop_index("ix_account_session_account_id", table_name="account_session")
    op.drop_table("account_session")
    op.drop_table("account")
