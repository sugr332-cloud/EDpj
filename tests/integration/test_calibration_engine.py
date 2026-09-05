from __future__ import annotations

import datetime as dt

from app.calibration.engine import CALIBRATED_SEGMENT_TYPES, fit_all, fit_segment
from app.db.models.calibration import CalibrationModel
from app.db.models.timing import TimingSample

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _insert_session(session, segment_type: str, file_name: str, start_offset: int, durations: list[float]) -> None:
    t = start_offset
    for i, duration in enumerate(durations):
        session.add(
            TimingSample(
                segment_type=segment_type,
                start_file_name=file_name,
                start_line_number=i * 2 + 1,
                end_file_name=file_name,
                end_line_number=i * 2 + 2,
                start_time=BASE + dt.timedelta(seconds=t),
                end_time=BASE + dt.timedelta(seconds=t + duration),
                duration_seconds=duration,
                arrival_dist_from_star_ls=None,
                reached_known_target=False,
                extra={},
            )
        )
        t += 1000
    session.commit()


class TestFitSegment:
    def test_no_samples_is_insufficient(self, db_session):
        result = fit_segment("dock", db_session)
        assert result.sample_count_fit == 0
        assert result.sample_count_eval == 0
        assert result.validation_status == "insufficient"
        assert result.seconds is None

    def test_single_session_has_no_eval_data_is_insufficient(self, db_session):
        _insert_session(db_session, "dock", "a.log", 0, [10.0] * 10)
        result = fit_segment("dock", db_session)
        assert result.sample_count_fit == 10
        assert result.sample_count_eval == 0
        assert result.validation_status == "insufficient"
        assert result.seconds == 10.0  # still computed, just unvalidated

    def test_consistent_durations_across_sessions_validation_passes(self, db_session):
        _insert_session(db_session, "dock", "a.log", 0, [10.0] * 14)
        _insert_session(db_session, "dock", "b.log", 100_000, [10.0] * 6)

        result = fit_segment("dock", db_session)

        assert result.sample_count_fit == 14
        assert result.sample_count_eval == 6
        assert result.seconds == 10.0
        assert result.median_absolute_error == 0.0
        assert result.median_signed_error == 0.0
        assert result.validation_status == "pass"

    def test_inconsistent_durations_across_sessions_validation_fails(self, db_session):
        _insert_session(db_session, "dock", "a.log", 0, [10.0] * 14)  # fit median = 10
        _insert_session(db_session, "dock", "b.log", 100_000, [20.0] * 6)  # eval actual = 20

        result = fit_segment("dock", db_session)

        assert result.sample_count_fit == 14
        assert result.sample_count_eval == 6
        assert result.seconds == 10.0
        assert result.median_absolute_error == 0.5  # |10-20|/20
        assert result.validation_status == "fail"

    def test_refit_replaces_previous_result_not_appends(self, db_session):
        _insert_session(db_session, "dock", "a.log", 0, [10.0] * 14)
        _insert_session(db_session, "dock", "b.log", 100_000, [10.0] * 6)
        fit_segment("dock", db_session)

        # more data arrives; refit
        _insert_session(db_session, "dock", "c.log", 200_000, [10.0] * 5)
        result = fit_segment("dock", db_session)

        assert db_session.query(CalibrationModel).filter_by(segment_type="dock").count() == 1
        stored = db_session.query(CalibrationModel).filter_by(segment_type="dock").one()
        assert stored.sample_count_fit == result.sample_count_fit
        assert stored.sample_count_eval == result.sample_count_eval

    def test_result_is_persisted_to_calibration_models(self, db_session):
        _insert_session(db_session, "dock", "a.log", 0, [10.0] * 14)
        _insert_session(db_session, "dock", "b.log", 100_000, [10.0] * 6)
        fit_segment("dock", db_session)

        stored = db_session.query(CalibrationModel).filter_by(segment_type="dock").one()
        assert stored.validation_status == "pass"
        assert stored.seconds == 10.0


class TestFitAll:
    def test_supercruise_is_never_calibrated(self):
        assert "supercruise" not in CALIBRATED_SEGMENT_TYPES

    def test_covers_all_expected_segment_types(self):
        assert set(CALIBRATED_SEGMENT_TYPES) == {
            "jump",
            "dock",
            "undock",
            "descent",
            "ascent",
            "mining_cycle",
            "bio_sample",
        }

    def test_fit_all_produces_a_result_per_segment_type_even_with_no_data(self, db_session):
        results = fit_all(db_session)
        assert set(results.keys()) == set(CALIBRATED_SEGMENT_TYPES)
        for r in results.values():
            assert r.validation_status == "insufficient"

        stored_count = db_session.query(CalibrationModel).count()
        assert stored_count == len(CALIBRATED_SEGMENT_TYPES)
