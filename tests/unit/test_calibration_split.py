from __future__ import annotations

import datetime as dt

from app.calibration.engine import chronological_session_split
from app.db.models.timing import TimingSample

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _sample(file_name: str, line: int, offset_seconds: int) -> TimingSample:
    return TimingSample(
        segment_type="dock",
        start_file_name=file_name,
        start_line_number=line,
        end_file_name=file_name,
        end_line_number=line + 1,
        start_time=BASE + dt.timedelta(seconds=offset_seconds),
        end_time=BASE + dt.timedelta(seconds=offset_seconds + 10),
        duration_seconds=10.0,
        arrival_dist_from_star_ls=None,
        reached_known_target=False,
        extra={},
    )


def test_empty_input():
    fit, eval_ = chronological_session_split([])
    assert fit == []
    assert eval_ == []


def test_never_splits_a_single_session():
    # One session with many samples: even though ~70% would land mid-session,
    # the whole session must go to one side (there's nowhere else to put it
    # here since there's only one session, so it all goes to fit).
    samples = [_sample("a.log", i, i * 10) for i in range(10)]
    fit, eval_ = chronological_session_split(samples)
    assert len(fit) == 10
    assert eval_ == []


def test_splits_along_session_boundaries_not_mid_session():
    session_a = [_sample("a.log", i, i * 10) for i in range(7)]  # 7 samples, earliest
    session_b = [_sample("b.log", i, 1000 + i * 10) for i in range(3)]  # 3 samples, latest
    samples = session_a + session_b

    fit, eval_ = chronological_session_split(samples)

    fit_files = {s.start_file_name for s in fit}
    eval_files = {s.start_file_name for s in eval_}
    assert fit_files.isdisjoint(eval_files)  # no session appears on both sides
    assert len(fit) == 7
    assert len(eval_) == 3

    fit_names = {s.start_file_name for s in fit}
    assert fit_names == {"a.log"}
    assert {s.start_file_name for s in eval_} == {"b.log"}


def test_sessions_are_ordered_chronologically_not_by_file_name_string():
    # "z.log" happens chronologically FIRST; file name sorts do not
    # determine session order, start_time does.
    early_session = [_sample("z.log", i, i * 10) for i in range(7)]
    late_session = [_sample("a.log", i, 100_000 + i * 10) for i in range(3)]
    samples = early_session + late_session

    fit, eval_ = chronological_session_split(samples)

    assert {s.start_file_name for s in fit} == {"z.log"}
    assert {s.start_file_name for s in eval_} == {"a.log"}
