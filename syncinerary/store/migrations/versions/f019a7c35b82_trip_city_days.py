"""Persist reviewed city days instead of inferring time from search supply.

Revision ID: f019a7c35b82
Revises: e8b10a6c2d91
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f019a7c35b82"
down_revision = "e8b10a6c2d91"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trip", sa.Column("city_days", postgresql.ARRAY(sa.Integer()),
                                  nullable=False, server_default=sa.text("'{}'::integer[]")))
    op.add_column("trip", sa.Column("priority_city_index", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_trip_city_days", "trip",
        "cardinality(city_days) = 0 OR (cardinality(city_days) = cardinality(cities) "
        "AND 0 < ALL(city_days) AND array_position(city_days, NULL) IS NULL)")
    op.create_check_constraint("ck_trip_priority_city", "trip",
        "priority_city_index IS NULL OR "
        "(priority_city_index >= 0 AND priority_city_index < cardinality(cities))")


def downgrade():
    op.drop_constraint("ck_trip_priority_city", "trip", type_="check")
    op.drop_constraint("ck_trip_city_days", "trip", type_="check")
    op.drop_column("trip", "priority_city_index")
    op.drop_column("trip", "city_days")
