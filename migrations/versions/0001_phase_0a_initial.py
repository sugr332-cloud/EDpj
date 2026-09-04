"""Phase 0-A initial schema: journal_events, market_snapshots, player_state, cargo_state

Revision ID: 0001_phase_0a_initial
Revises:
Create Date: 2026-09-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase_0a_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "journal_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_name", "line_number", name="uq_journal_file_line"),
    )
    op.create_index("ix_journal_events_file_name", "journal_events", ["file_name"])
    op.create_index("ix_journal_events_event_type", "journal_events", ["event_type"])
    op.create_index("ix_journal_events_timestamp", "journal_events", ["timestamp"])

    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("commodity_name", sa.String(), nullable=False),
        sa.Column("commodity_id", sa.BigInteger(), nullable=True),
        sa.Column("buy_price", sa.Integer(), nullable=False),
        sa.Column("sell_price", sa.Integer(), nullable=False),
        sa.Column("supply", sa.Integer(), nullable=False),
        sa.Column("demand", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "station_id", "commodity_name", "observed_at", "source", name="uq_market_snapshot_observation"
        ),
    )
    op.create_index("ix_market_snapshots_station_id", "market_snapshots", ["station_id"])
    op.create_index("ix_market_snapshots_commodity_name", "market_snapshots", ["commodity_name"])
    op.create_index("ix_market_snapshots_observed_at", "market_snapshots", ["observed_at"])
    op.create_index("ix_market_snapshots_source", "market_snapshots", ["source"])

    op.create_table(
        "player_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_system", sa.String(), nullable=True),
        sa.Column("current_system_address", sa.BigInteger(), nullable=True),
        sa.Column("current_body_id", sa.BigInteger(), nullable=True),
        sa.Column("current_body_name", sa.String(), nullable=True),
        sa.Column("current_station_id", sa.BigInteger(), nullable=True),
        sa.Column("current_station_name", sa.String(), nullable=True),
        sa.Column("current_ship_id", sa.BigInteger(), nullable=True),
        sa.Column("credits", sa.BigInteger(), nullable=True),
        sa.Column("fuel_main", sa.Float(), nullable=True),
        sa.Column("cargo_tons", sa.Integer(), nullable=True),
        sa.Column("docked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("landed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("on_foot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_status", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "cargo_state",
        sa.Column("commodity_name", sa.String(), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cargo_state")
    op.drop_table("player_state")
    op.drop_table("market_snapshots")
    op.drop_table("journal_events")
