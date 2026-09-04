"""Phase 0-B: timing_samples, route_plot_samples

Revision ID: 0002_phase_0b_timing
Revises: 0001_phase_0a_initial
Create Date: 2026-09-05

`arrival_dist_from_star_ls` is a station/body's static distance from its
system's main star (from Docked's DistFromStarLS) — not supercruise travel
distance. See app/journal/timing.py's module docstring.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase_0b_timing"
down_revision: Union[str, None] = "0001_phase_0a_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timing_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("segment_type", sa.String(), nullable=False),
        sa.Column("start_file_name", sa.String(), nullable=False),
        sa.Column("start_line_number", sa.Integer(), nullable=False),
        sa.Column("end_file_name", sa.String(), nullable=False),
        sa.Column("end_line_number", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("arrival_dist_from_star_ls", sa.Float(), nullable=True),
        sa.Column("reached_known_target", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "segment_type",
            "start_file_name",
            "start_line_number",
            "end_file_name",
            "end_line_number",
            name="uq_timing_sample_pair",
        ),
    )
    op.create_index("ix_timing_samples_segment_type", "timing_samples", ["segment_type"])
    op.create_index("ix_timing_samples_start_file_name", "timing_samples", ["start_file_name"])
    op.create_index("ix_timing_samples_start_time", "timing_samples", ["start_time"])

    op.create_table(
        "route_plot_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("navroute_file_name", sa.String(), nullable=False),
        sa.Column("navroute_line_number", sa.Integer(), nullable=False),
        sa.Column("systems", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leg_arrivals", sa.JSON(), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("navroute_file_name", "navroute_line_number", name="uq_route_plot_sample"),
    )
    op.create_index("ix_route_plot_samples_navroute_file_name", "route_plot_samples", ["navroute_file_name"])
    op.create_index("ix_route_plot_samples_completed_at", "route_plot_samples", ["completed_at"])


def downgrade() -> None:
    op.drop_table("route_plot_samples")
    op.drop_table("timing_samples")
