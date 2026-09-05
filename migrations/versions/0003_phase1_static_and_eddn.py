"""Phase 1: static galaxy data, EDDN observations, market_latest, station_activity

Revision ID: 0003_phase1_static_and_eddn
Revises: 0002_phase_0b_timing
Create Date: 2026-09-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase1_static_and_eddn"
down_revision: Union[str, None] = "0002_phase_0b_timing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "systems",
        sa.Column("system_address", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("z", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_systems_name", "systems", ["name"])

    op.create_table(
        "bodies",
        sa.Column("body_id64", sa.BigInteger(), primary_key=True),
        sa.Column("system_address", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("body_type", sa.String(), nullable=True),
        sa.Column("sub_type", sa.String(), nullable=True),
        sa.Column("distance_to_arrival_ls", sa.Float(), nullable=True),
        sa.Column("gravity", sa.Float(), nullable=True),
        sa.Column("radius", sa.Float(), nullable=True),
        sa.Column("atmosphere", sa.String(), nullable=True),
        sa.Column("landable", sa.Boolean(), nullable=True),
        sa.Column("rings", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bodies_system_address", "bodies", ["system_address"])

    op.create_table(
        "stations",
        sa.Column("station_id", sa.BigInteger(), primary_key=True),
        sa.Column("system_address", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("station_type", sa.String(), nullable=True),
        sa.Column("distance_to_arrival_ls", sa.Float(), nullable=True),
        sa.Column("landing_pad", sa.JSON(), nullable=True),
        sa.Column("has_vista_genomics", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_fleet_carrier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stations_system_address", "stations", ["system_address"])

    op.create_table(
        "commodities",
        sa.Column("commodity_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("internal_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.UniqueConstraint("internal_name", name="uq_commodity_internal_name"),
    )

    op.create_table(
        "eddn_journal_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("system_address", sa.BigInteger(), nullable=False),
        sa.Column("body_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploader_id", sa.String(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "system_address", "event_type", "observed_at", "uploader_id", name="uq_eddn_journal_obs"
        ),
    )
    op.create_index("ix_eddn_journal_observations_system_address", "eddn_journal_observations", ["system_address"])
    op.create_index("ix_eddn_journal_observations_event_type", "eddn_journal_observations", ["event_type"])
    op.create_index("ix_eddn_journal_observations_observed_at", "eddn_journal_observations", ["observed_at"])

    op.create_table(
        "body_bio_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("system_address", sa.BigInteger(), nullable=False),
        sa.Column("body_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("system_address", "body_id", "signal_type", name="uq_body_bio_signal"),
    )
    op.create_index("ix_body_bio_signals_system_address", "body_bio_signals", ["system_address"])

    op.create_table(
        "market_latest",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("commodity_name", sa.String(), nullable=False),
        sa.Column("buy_price", sa.Integer(), nullable=False),
        sa.Column("sell_price", sa.Integer(), nullable=False),
        sa.Column("supply", sa.Integer(), nullable=False),
        sa.Column("demand", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.UniqueConstraint("station_id", "commodity_name", name="uq_market_latest_station_commodity"),
    )
    op.create_index("ix_market_latest_station_id", "market_latest", ["station_id"])
    op.create_index("ix_market_latest_commodity_name", "market_latest", ["commodity_name"])

    op.create_table(
        "station_activity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("station_id", name="uq_station_activity_station"),
    )
    op.create_index("ix_station_activity_station_id", "station_activity", ["station_id"])


def downgrade() -> None:
    op.drop_table("station_activity")
    op.drop_table("market_latest")
    op.drop_table("body_bio_signals")
    op.drop_table("eddn_journal_observations")
    op.drop_table("commodities")
    op.drop_table("stations")
    op.drop_table("bodies")
    op.drop_table("systems")
