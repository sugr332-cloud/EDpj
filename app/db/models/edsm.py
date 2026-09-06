"""EDSM-sourced body physical parameters — Phase Bio Species Prediction
Backtest (docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md,
docs/BIO_BODY_PARAMETER_JOIN_INVESTIGATION_V0.1.md).

EDSM is used here only for system/body identity and physical metadata
(docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md §3.5 -- "EDSMをspecies
payoutのground truthとして使用してはならない", never for species
values/occurrence probabilities). Cached on (system_address, body_id)
since these are static physical facts (confirmed zero temporal-leakage
cases against real scanorganic/1 observations in the join
investigation) -- an on-demand cache, not a bulk import, matching this
project's existing Spansh policy (app/collectors/spansh.py).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BodyPhysicalParameters(Base):
    __tablename__ = "body_physical_parameters"
    __table_args__ = (UniqueConstraint("system_address", "body_id", name="uq_body_physical_parameters"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    body_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String, nullable=True)
    gravity: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    atmosphere_type: Mapped[str | None] = mapped_column(String, nullable=True)
    volcanism_type: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieved_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
