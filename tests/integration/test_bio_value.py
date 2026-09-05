from __future__ import annotations

import datetime as dt

from app.bio.value import (
    calibrate_expected_value_per_signal,
    total_analysed_sample_count,
    total_organic_sale_credits,
)
from app.db.models.journal import JournalEvent

NOW = dt.datetime.now(dt.timezone.utc)


def _event(session, event_type: str, timestamp: dt.datetime, payload: dict, line: int):
    session.add(
        JournalEvent(file_name="fixture.log", line_number=line, event_type=event_type, timestamp=timestamp, payload=payload)
    )


class TestTotalOrganicSaleCredits:
    def test_no_sales_is_zero(self, db_session):
        assert total_organic_sale_credits(db_session) == 0

    def test_sums_value_and_bonus_across_entries_and_events(self, db_session):
        _event(
            db_session, "SellOrganicData", NOW - dt.timedelta(minutes=10),
            {"BioData": [{"Species": "A", "Value": 1000, "Bonus": 0}, {"Species": "B", "Value": 2000, "Bonus": 500}]},
            1,
        )
        _event(
            db_session, "SellOrganicData", NOW - dt.timedelta(minutes=5),
            {"BioData": [{"Species": "C", "Value": 3000, "Bonus": 0}]},
            2,
        )
        db_session.commit()

        assert total_organic_sale_credits(db_session) == 1000 + 2000 + 500 + 3000

    def test_missing_bonus_field_defaults_to_zero(self, db_session):
        _event(db_session, "SellOrganicData", NOW, {"BioData": [{"Species": "A", "Value": 500}]}, 1)
        db_session.commit()

        assert total_organic_sale_credits(db_session) == 500


class TestTotalAnalysedSampleCount:
    def test_only_analyse_scan_type_counts(self, db_session):
        _event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=10), {"ScanType": "Log"}, 1)
        _event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=9), {"ScanType": "Sample"}, 2)
        _event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=8), {"ScanType": "Analyse"}, 3)
        db_session.commit()

        assert total_analysed_sample_count(db_session) == 1

    def test_counts_across_whole_history_not_just_since_last_sale(self, db_session):
        # Distinct from detect_unsold_bio_count(): this counts everything,
        # including samples that were already sold long ago.
        _event(db_session, "ScanOrganic", NOW - dt.timedelta(days=10), {"ScanType": "Analyse"}, 1)
        _event(db_session, "SellOrganicData", NOW - dt.timedelta(days=9), {"BioData": []}, 2)
        _event(db_session, "ScanOrganic", NOW - dt.timedelta(days=1), {"ScanType": "Analyse"}, 3)
        db_session.commit()

        assert total_analysed_sample_count(db_session) == 2


class TestCalibrateExpectedValuePerSignal:
    def test_none_when_no_analysed_samples(self, db_session):
        assert calibrate_expected_value_per_signal(db_session) is None

    def test_none_even_when_sales_exist_without_any_analysed_scans(self, db_session):
        # Never divides by zero regardless of numerator.
        _event(db_session, "SellOrganicData", NOW, {"BioData": [{"Species": "A", "Value": 1000, "Bonus": 0}]}, 1)
        db_session.commit()

        assert calibrate_expected_value_per_signal(db_session) is None

    def test_computes_ratio_correctly_when_sell_and_scan_counts_differ(self, db_session):
        # 2 sell events (with a combined 3 BioData entries) vs 5 analysed
        # scans -- no 1:1 correspondence assumed anywhere. The function
        # must still return a sensible ratio: total credits / 5.
        _event(
            db_session, "SellOrganicData", NOW - dt.timedelta(minutes=20),
            {"BioData": [{"Species": "A", "Value": 1000, "Bonus": 0}, {"Species": "B", "Value": 500, "Bonus": 0}]},
            1,
        )
        _event(
            db_session, "SellOrganicData", NOW - dt.timedelta(minutes=15),
            {"BioData": [{"Species": "C", "Value": 1500, "Bonus": 0}]},
            2,
        )
        for i, minutes in enumerate([10, 9, 8, 7, 6]):
            _event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=minutes), {"ScanType": "Analyse"}, 3 + i)
        db_session.commit()

        result = calibrate_expected_value_per_signal(db_session)

        assert result == (1000 + 500 + 1500) / 5
