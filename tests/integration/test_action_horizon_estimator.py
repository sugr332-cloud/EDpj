from __future__ import annotations

import datetime as dt

import pytest

from app.db.models.timing import TimingSample
from app.routing.time import MEASURED_CONFIDENCE, MEASURED_SAMPLE_THRESHOLD, estimate_segment
from app.scoring.models import ActionCandidate, build_horizon

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _insert_samples(session, segment_type: str, durations: list[float]) -> None:
    for i, duration in enumerate(durations):
        start = BASE + dt.timedelta(seconds=i * 1000)
        end = start + dt.timedelta(seconds=duration)
        session.add(
            TimingSample(
                segment_type=segment_type,
                start_file_name="fixture.log",
                start_line_number=i * 2 + 1,
                end_file_name="fixture.log",
                end_line_number=i * 2 + 2,
                start_time=start,
                end_time=end,
                duration_seconds=duration,
                arrival_dist_from_star_ls=None,
                reached_known_target=False,
                extra={},
            )
        )
    session.commit()


class TestEstimateSegmentSupercruise:
    def test_supercruise_is_always_unavailable_even_with_ample_telemetry(self, db_session):
        _insert_samples(db_session, "supercruise", [float(x) for x in range(10, 60)])  # 50 samples

        # Phase 0-B storage must still work — the override is in
        # estimate_segment(), not in whether telemetry gets recorded.
        stored = db_session.query(TimingSample).filter_by(segment_type="supercruise").count()
        assert stored == 50

        result = estimate_segment("supercruise", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None
        assert result.basis  # explains why, not just that

    def test_supercruise_unavailable_even_with_zero_telemetry(self, db_session):
        result = estimate_segment("supercruise", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None


class TestEstimateSegmentOtherSegments:
    def test_zero_samples_is_unavailable(self, db_session):
        result = estimate_segment("dock", None, db_session)
        assert result.status == "unavailable"
        assert result.seconds is None
        assert result.confidence is None

    def test_dock_with_ample_samples_is_measured(self, db_session):
        _insert_samples(db_session, "dock", [10.0, 12.0, 11.0, 9.0, 13.0] * 5)  # 25 samples

        result = estimate_segment("dock", None, db_session)
        assert result.status == "measured"
        assert result.seconds == pytest.approx(11.0)
        assert result.confidence == MEASURED_CONFIDENCE
        assert "sample_count=25" in result.basis

    def test_mining_cycle_with_sparse_samples_is_estimated(self, db_session):
        _insert_samples(db_session, "mining_cycle", [100.0, 120.0, 110.0])  # 3 samples

        result = estimate_segment("mining_cycle", None, db_session)
        assert result.status == "estimated"
        assert result.seconds == pytest.approx(110.0)
        assert result.confidence is not None
        assert result.confidence < MEASURED_CONFIDENCE


class TestHorizonComplete:
    def test_action_requiring_supercruise_is_incomplete(self, db_session):
        _insert_samples(db_session, "dock", [10.0] * MEASURED_SAMPLE_THRESHOLD)

        components, complete, total = build_horizon(["dock", "supercruise"], db_session)

        assert components["dock"].status == "measured"
        assert components["supercruise"].status == "unavailable"
        assert complete is False
        assert total is None

    def test_action_not_requiring_supercruise_can_be_complete(self, db_session):
        _insert_samples(db_session, "descent", [30.0] * MEASURED_SAMPLE_THRESHOLD)
        _insert_samples(db_session, "bio_sample", [60.0] * MEASURED_SAMPLE_THRESHOLD)
        # Supercruise telemetry exists but this action doesn't require it —
        # horizon_complete must not be dragged down by an unrelated segment.
        _insert_samples(db_session, "supercruise", [200.0] * MEASURED_SAMPLE_THRESHOLD)

        components, complete, total = build_horizon(["descent", "bio_sample"], db_session)

        assert "supercruise" not in components
        assert complete is True
        assert total == pytest.approx(90.0)

    def test_action_candidate_reflects_incomplete_horizon(self, db_session):
        _insert_samples(db_session, "dock", [10.0] * MEASURED_SAMPLE_THRESHOLD)
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
        _insert_samples(db_session, "descent", [30.0] * MEASURED_SAMPLE_THRESHOLD)
        _insert_samples(db_session, "bio_sample", [60.0] * MEASURED_SAMPLE_THRESHOLD)
        components, complete, total = build_horizon(["descent", "bio_sample"], db_session)

        candidate = ActionCandidate(
            action="bio_current_body",
            target=None,
            expected_value=500_000.0,
            action_horizon_seconds=total,
            horizon_components=components,
            horizon_complete=complete,
            score_per_hour=500_000.0 / (total / 3600),
            confidence=MEASURED_CONFIDENCE,
            reason="fixture: bio_current_body needs no supercruise leg",
        )

        assert candidate.horizon_complete is True
        assert candidate.action_horizon_seconds == pytest.approx(90.0)
        assert candidate.score_per_hour == pytest.approx(500_000.0 / (90.0 / 3600))
