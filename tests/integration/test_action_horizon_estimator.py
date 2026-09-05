from __future__ import annotations

import datetime as dt

import pytest

from app.db.models.calibration import CalibrationModel
from app.routing.time import ESTIMATED_CONFIDENCE, estimate_segment
from app.scoring.models import ActionCandidate, build_horizon

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _insert_calibration(
    session,
    segment_type: str,
    seconds: float,
    sample_count_fit: int = 20,
    sample_count_eval: int = 5,
    validation_status: str = "pass",
) -> None:
    session.add(
        CalibrationModel(
            segment_type=segment_type,
            seconds=seconds,
            sample_count_fit=sample_count_fit,
            sample_count_eval=sample_count_eval,
            median_absolute_error=0.0 if validation_status == "pass" else 0.9,
            median_signed_error=0.0 if validation_status == "pass" else 0.9,
            r_squared=1.0,
            validation_status=validation_status,
            fitted_at=NOW,
        )
    )
    session.commit()


class TestEstimateSegmentSupercruise:
    def test_supercruise_is_always_unavailable_even_with_a_calibration_row(self, db_session):
        # supercruise is never calibrated by app/calibration/engine.py, but
        # even if a row somehow existed, estimate_segment must ignore it —
        # the segment_type=="supercruise" check runs before any query.
        _insert_calibration(db_session, "supercruise", seconds=180.0)

        result = estimate_segment("supercruise", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None
        assert result.basis  # explains why, not just that

    def test_supercruise_unavailable_with_no_calibration_row(self, db_session):
        result = estimate_segment("supercruise", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None


class TestEstimateSegmentOtherSegments:
    def test_no_calibration_row_is_unavailable(self, db_session):
        result = estimate_segment("dock", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None

    def test_calibrated_and_validated_segment_is_estimated_not_measured(self, db_session):
        _insert_calibration(db_session, "dock", seconds=11.0, sample_count_fit=25, validation_status="pass")

        result = estimate_segment("dock", None, db_session)
        # Sample count alone never promotes a calibrated value to
        # "measured" — see app/routing/time.py's module docstring.
        assert result.status == "estimated"
        assert result.seconds == pytest.approx(11.0)
        assert result.confidence == ESTIMATED_CONFIDENCE
        assert "fit=25" in result.basis
        assert "validation=pass" in result.basis

    def test_calibrated_but_failed_validation_is_still_estimated(self, db_session):
        # Per review: sample count/validation failure is diagnostic
        # metadata, not a status/confidence downgrade in Phase 2-1.
        _insert_calibration(db_session, "mining_cycle", seconds=110.0, validation_status="fail")

        result = estimate_segment("mining_cycle", None, db_session)
        assert result.status == "estimated"
        assert result.confidence == ESTIMATED_CONFIDENCE
        assert "validation=fail" in result.basis

    def test_calibrated_with_zero_eval_samples_is_unavailable(self, db_session):
        _insert_calibration(db_session, "ascent", seconds=40.0, sample_count_fit=10, sample_count_eval=0, validation_status="insufficient")

        result = estimate_segment("ascent", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None
        assert "fit=10" in result.basis


class TestHorizonComplete:
    def test_action_requiring_supercruise_is_incomplete(self, db_session):
        _insert_calibration(db_session, "dock", seconds=10.0)

        components, complete, total = build_horizon(["dock", "supercruise"], db_session)

        assert components["dock"].status == "estimated"
        assert components["supercruise"].status == "unavailable"
        assert complete is False
        assert total is None

    def test_action_not_requiring_supercruise_can_be_complete(self, db_session):
        _insert_calibration(db_session, "descent", seconds=30.0)
        _insert_calibration(db_session, "bio_sample", seconds=60.0)
        # Supercruise telemetry exists but this action doesn't require it —
        # horizon_complete must not be dragged down by an unrelated segment.
        _insert_calibration(db_session, "supercruise", seconds=200.0)  # never actually consulted

        components, complete, total = build_horizon(["descent", "bio_sample"], db_session)

        assert "supercruise" not in components
        assert complete is True
        assert total == pytest.approx(90.0)

    def test_action_candidate_reflects_incomplete_horizon(self, db_session):
        _insert_calibration(db_session, "dock", seconds=10.0)
        components, complete, total = build_horizon(["dock", "supercruise"], db_session)

        candidate = ActionCandidate(
            action="mining_sell",
            target=None,
            expected_value=1_000_000.0,
            action_horizon_seconds=total,
            horizon_components=components,
            horizon_complete=complete,
            score_per_hour=None if not complete else 1_000_000.0 / (total / 3600),
            confidence=0.0,
            reason="fixture: mining_sell requires an unavailable supercruise leg",
        )

        assert candidate.horizon_complete is False
        assert candidate.action_horizon_seconds is None
        assert candidate.score_per_hour is None

    def test_action_candidate_reflects_complete_horizon(self, db_session):
        _insert_calibration(db_session, "descent", seconds=30.0)
        _insert_calibration(db_session, "bio_sample", seconds=60.0)
        components, complete, total = build_horizon(["descent", "bio_sample"], db_session)

        candidate = ActionCandidate(
            action="bio_current_body",
            target=None,
            expected_value=500_000.0,
            action_horizon_seconds=total,
            horizon_components=components,
            horizon_complete=complete,
            score_per_hour=500_000.0 / (total / 3600),
            confidence=ESTIMATED_CONFIDENCE,
            reason="fixture: bio_current_body needs no supercruise leg",
        )

        assert candidate.horizon_complete is True
        assert candidate.action_horizon_seconds == pytest.approx(90.0)
        assert candidate.score_per_hour == pytest.approx(500_000.0 / (90.0 / 3600))
