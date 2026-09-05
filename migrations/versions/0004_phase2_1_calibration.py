"""Phase 2-1: calibration_models

Revision ID: 0004_phase2_1_calibration
Revises: 0003_phase1_static_and_eddn
Create Date: 2026-09-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase2_1_calibration"
down_revision: Union[str, None] = "0003_phase1_static_and_eddn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calibration_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("segment_type", sa.String(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("sample_count_fit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_count_eval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("median_absolute_error", sa.Float(), nullable=True),
        sa.Column("median_signed_error", sa.Float(), nullable=True),
        sa.Column("r_squared", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(), nullable=False, server_default="insufficient"),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("segment_type", name="uq_calibration_model_segment_type"),
    )
    op.create_index("ix_calibration_models_segment_type", "calibration_models", ["segment_type"])


def downgrade() -> None:
    op.drop_table("calibration_models")
