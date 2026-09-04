from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.cli.backfill import run_backfill
from app.db.models.timing import RoutePlotSample, TimingSample

FIXTURES = Path(__file__).parent.parent / "fixtures" / "journal_timing"


@pytest.fixture()
def journal_dir(tmp_path) -> Path:
    for f in FIXTURES.glob("*"):
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


def _counts_by_segment(session) -> dict[str, int]:
    rows = session.query(TimingSample).all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.segment_type] = counts.get(row.segment_type, 0) + 1
    return counts


def test_backfill_extracts_all_segment_types(journal_dir, db_session):
    summary = run_backfill(journal_dir, db_session)

    counts = _counts_by_segment(db_session)
    assert counts == {
        "jump": 1,
        "supercruise": 2,
        "dock": 1,
        "undock": 1,
        "descent": 1,
        "ascent": 1,
        "mining_cycle": 1,
        "bio_sample": 1,
    }

    assert summary.timing_sample_totals == counts
    assert summary.supercruise_reached_target_total == 2  # both SC legs reached Docked/ApproachBody
    assert summary.route_plot_samples_total == 1


def test_supercruise_sample_details(journal_dir, db_session):
    run_backfill(journal_dir, db_session)

    sc_samples = (
        db_session.query(TimingSample)
        .filter(TimingSample.segment_type == "supercruise")
        .order_by(TimingSample.start_time)
        .all()
    )
    assert len(sc_samples) == 2

    first, second = sc_samples
    assert first.duration_seconds == 300
    assert first.reached_known_target is True
    assert first.arrival_dist_from_star_ls == 450.0  # from Docked's DistFromStarLS

    assert second.duration_seconds == 75
    assert second.reached_known_target is True
    assert second.arrival_dist_from_star_ls is None  # ApproachBody carries no DistFromStarLS -> NO_DATA


def test_route_plot_sample_persisted(journal_dir, db_session):
    run_backfill(journal_dir, db_session)

    routes = db_session.query(RoutePlotSample).all()
    assert len(routes) == 1
    assert routes[0].systems == ["Wolf 359", "Sol"]
    assert len(routes[0].leg_arrivals) == 2


def test_backfill_timing_extraction_is_idempotent(journal_dir, db_session):
    run_backfill(journal_dir, db_session)
    run_backfill(journal_dir, db_session)

    assert db_session.query(TimingSample).count() == 9
    assert db_session.query(RoutePlotSample).count() == 1
