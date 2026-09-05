from __future__ import annotations

import datetime as dt

import pytest

from app.db.models.eddn import BodyBioSignal
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketLatest
from app.db.models.player import CargoState
from app.scoring.models import BioTarget, DraftCandidate, MiningTarget
from app.scoring.value import (
    MINING_START_VALUE_UNAVAILABLE_REASON,
    calculate_value,
)

NOW = dt.datetime.now(dt.timezone.utc)


def _mining_target(**overrides) -> MiningTarget:
    defaults = dict(
        station_name="", system_name="Deciat", parent_body_name=None, station_type="ring",
        arrival_dist_from_star_ls=None,
    )
    defaults.update(overrides)
    return MiningTarget(**defaults)


def _bio_target(**overrides) -> BioTarget:
    defaults = dict(body_name="", system_name="Deciat", body_suffix="", arrival_dist_from_star_ls=None)
    defaults.update(overrides)
    return BioTarget(**defaults)


class TestMiningStartValueDeferred:
    """docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.4/§5:
    mining_start has no value model at all -- not a per-candidate data
    gap, so the reason is always the same fixed string."""

    def test_mining_start_value_is_always_unavailable(self, db_session):
        draft = DraftCandidate(
            action="mining_start", target=_mining_target(), required_segments=["jump", "supercruise", "mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == MINING_START_VALUE_UNAVAILABLE_REASON
        assert result.market_observed_ats == []  # no Market observation was ever consulted


class TestBioValue:
    """docs/PHASE_3_BIO_VALUE_MODEL_V1_DESIGN_BASELINE_V0.1.md §4: unlike
    mining_start, Bio's value_unavailable_reason is per-candidate
    (no biological signal count, or no calibration data yet) -- not a
    single fixed "not implemented" string."""

    def _add_biological_signal(self, session, system_address: int, body_id: int, count: int):
        session.add(
            BodyBioSignal(
                system_address=system_address, body_id=body_id, signal_type="$SAA_SignalType_Biological;",
                count=count, source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW,
            )
        )

    def _sell(self, session, line: int, value: int, bonus: int = 0, timestamp: dt.datetime = NOW):
        session.add(
            JournalEvent(
                file_name="f.log", line_number=line, event_type="SellOrganicData", timestamp=timestamp,
                payload={"BioData": [{"Species": "A", "Value": value, "Bonus": bonus}]},
            )
        )

    def _analysed_scan(self, session, line: int, timestamp: dt.datetime = NOW):
        session.add(
            JournalEvent(
                file_name="f.log", line_number=line, event_type="ScanOrganic", timestamp=timestamp,
                payload={"ScanType": "Analyse"},
            )
        )

    def test_bio_current_body_no_biological_signal_count_when_target_has_none(self, db_session):
        draft = DraftCandidate(
            action="bio_current_body",
            target=_bio_target(system_address=1, body_id=5),
            required_segments=["descent", "bio_sample", "ascent"],
        )
        result = calculate_value(draft, db_session)
        assert result.expected_value is None
        assert result.value_unavailable_reason == "no_biological_signal_count"

    def test_bio_current_body_insufficient_sell_history_when_no_calibration_data(self, db_session):
        self._add_biological_signal(db_session, 1, 5, count=3)
        db_session.commit()

        draft = DraftCandidate(
            action="bio_current_body",
            target=_bio_target(system_address=1, body_id=5),
            required_segments=["descent", "bio_sample", "ascent"],
        )
        result = calculate_value(draft, db_session)
        assert result.expected_value is None
        assert result.value_unavailable_reason == "insufficient_sell_history"

    def test_bio_current_body_computes_signal_count_times_calibrated_value(self, db_session):
        self._add_biological_signal(db_session, 1, 5, count=3)
        self._sell(db_session, 1, value=1000)
        self._analysed_scan(db_session, 2)
        db_session.commit()

        draft = DraftCandidate(
            action="bio_current_body",
            target=_bio_target(system_address=1, body_id=5),
            required_segments=["descent", "bio_sample", "ascent"],
        )
        result = calculate_value(draft, db_session)
        assert result.value_unavailable_reason is None
        assert result.expected_value == 3 * 1000.0

    def test_bio_next_system_uses_same_value_logic_as_current_body(self, db_session):
        self._add_biological_signal(db_session, 2, 7, count=2)
        self._sell(db_session, 1, value=600)
        self._analysed_scan(db_session, 2)
        db_session.commit()

        draft = DraftCandidate(
            action="bio_next_system",
            target=_bio_target(system_address=2, body_id=7),
            required_segments=["jump", "supercruise", "descent", "bio_sample", "ascent"],
        )
        result = calculate_value(draft, db_session)
        assert result.value_unavailable_reason is None
        assert result.expected_value == 2 * 600.0

    def test_bio_value_ignores_geological_signals(self, db_session):
        db_session.add(
            BodyBioSignal(
                system_address=1, body_id=5, signal_type="$SAA_SignalType_Geological;", count=5,
                source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW,
            )
        )
        db_session.commit()

        draft = DraftCandidate(
            action="bio_current_body",
            target=_bio_target(system_address=1, body_id=5),
            required_segments=["descent", "bio_sample", "ascent"],
        )
        result = calculate_value(draft, db_session)
        assert result.expected_value is None
        assert result.value_unavailable_reason == "no_biological_signal_count"

    def test_bio_return_no_unsold_bio_data(self, db_session):
        draft = DraftCandidate(
            action="bio_return", target=_mining_target(), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        assert result.expected_value is None
        assert result.value_unavailable_reason == "no_unsold_bio_data"

    def test_bio_return_insufficient_sell_history(self, db_session):
        self._analysed_scan(db_session, 1)  # one completed, unsold sample -- but no sale history to calibrate from
        db_session.commit()

        draft = DraftCandidate(
            action="bio_return", target=_mining_target(), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        assert result.expected_value is None
        assert result.value_unavailable_reason == "insufficient_sell_history"

    def test_bio_return_computes_unsold_count_times_calibrated_value(self, db_session):
        self._analysed_scan(db_session, 1, timestamp=NOW - dt.timedelta(minutes=20))  # before the sale below
        self._sell(db_session, 2, value=900, timestamp=NOW - dt.timedelta(minutes=15))
        self._analysed_scan(db_session, 3, timestamp=NOW - dt.timedelta(minutes=10))  # unsold (after the sale)
        self._analysed_scan(db_session, 4, timestamp=NOW - dt.timedelta(minutes=5))  # unsold (after the sale)
        db_session.commit()

        # calibration: total_organic_sale_credits=900, total_analysed_sample_count=3 (all three scans)
        # detect_unsold_bio_count: only the 2 scans strictly after the sale
        draft = DraftCandidate(
            action="bio_return", target=_mining_target(), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        assert result.value_unavailable_reason is None
        assert result.expected_value == 2 * (900 / 3)


class TestMiningContinueValueEdgeCases:
    def test_no_market_target_when_commodity_has_no_known_market(self, db_session):
        db_session.add(
            JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={"CargoCapacity": 32})
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_continue", target=_mining_target(commodity_name="platinum"), required_segments=["mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == "no_market_target"

    def test_picks_market_with_highest_effective_price_not_highest_listed_price(self, db_session):
        db_session.add(
            JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={"CargoCapacity": 32})
        )
        # Higher listed price, but a near-empty demand pool penalizes it hard.
        db_session.add(
            MarketLatest(station_id=1, commodity_name="platinum", buy_price=0, sell_price=100000, supply=0,
                         demand=1, observed_at=NOW, source="eddn")
        )
        # Lower listed price, but ample demand means no penalty at all.
        db_session.add(
            MarketLatest(station_id=2, commodity_name="platinum", buy_price=0, sell_price=90000, supply=0,
                         demand=1000, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_continue", target=_mining_target(commodity_name="platinum"), required_segments=["mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert reason is None
        assert value == 90000.0
        # SQLite doesn't round-trip tzinfo on DateTime(timezone=True) columns
        # (same project-wide quirk as elsewhere) -- compare naive values.
        assert [ts.replace(tzinfo=None) for ts in result.market_observed_ats] == [NOW.replace(tzinfo=None)]


class TestMiningSellMultiCommodity:
    """Edge-case review, Phase 2-3 follow-up: a mining_sell candidate is
    per-station (app/mining/candidates.py generates one per station), so
    a commodity this station's market has no row for is a genuine unknown
    -- not the same as a row that confirms demand=0."""

    def test_sums_effective_price_across_multiple_known_commodities(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(CargoState(commodity_name="painite", quantity=5, updated_at=NOW))
        db_session.add(
            MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=178, observed_at=NOW, source="eddn")
        )
        db_session.add(
            MarketLatest(station_id=100, commodity_name="painite", buy_price=0, sell_price=44586, supply=0,
                         demand=178, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_sell", target=_mining_target(station_id=100), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert reason is None
        assert value == 10 * 44586.0 + 5 * 44586.0
        assert len(result.market_observed_ats) == 2  # both commodities' market rows contributed

    def test_confirmed_zero_demand_commodity_is_excluded_but_others_still_count(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(CargoState(commodity_name="painite", quantity=5, updated_at=NOW))
        db_session.add(
            MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=178, observed_at=NOW, source="eddn")
        )
        # Station's market has been observed for painite too -- it just isn't buying any right now.
        db_session.add(
            MarketLatest(station_id=100, commodity_name="painite", buy_price=0, sell_price=500000, supply=0,
                         demand=0, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_sell", target=_mining_target(station_id=100), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert reason is None
        assert value == 10 * 44586.0  # painite confirmed unsellable here right now, contributes 0 -- not unknown

    def test_unobserved_commodity_makes_the_whole_candidate_value_unavailable(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(CargoState(commodity_name="gold", quantity=5, updated_at=NOW))
        db_session.add(
            MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=178, observed_at=NOW, source="eddn")
        )
        # No MarketLatest row for gold at this station at all -- unknown, not "doesn't buy it".
        db_session.commit()

        draft = DraftCandidate(
            action="mining_sell", target=_mining_target(station_id=100), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == "market_data_incomplete"

    def test_negative_demand_is_treated_as_unknown_not_confirmed_zero(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(
            MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=-1, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_sell", target=_mining_target(station_id=100), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == "market_data_incomplete"


class TestMiningContinueCargoHeadroom:
    """§4.3 (v0.4): evaluation_cargo = min(current cargo + 1t, cargo
    capacity) -- confirms the cap actually binds when the ship is near
    full, rather than always just using current+1."""

    def test_evaluation_cargo_is_capped_at_capacity_when_nearly_full(self, db_session):
        db_session.add(
            JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={"CargoCapacity": 5})
        )
        db_session.add(CargoState(commodity_name="platinum", quantity=5, updated_at=NOW))  # already at capacity
        db_session.add(
            MarketLatest(station_id=1, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=20, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_continue", target=_mining_target(commodity_name="platinum"), required_segments=["mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert reason is None
        # evaluation_cargo = min(5+1, 5) = 5 -> r = 5/20 = 0.25 (boundary, no penalty)
        assert value == pytest.approx(44586.0)

    def test_evaluation_cargo_uses_current_plus_one_when_capacity_has_room(self, db_session):
        db_session.add(
            JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={"CargoCapacity": 100})
        )
        db_session.add(CargoState(commodity_name="platinum", quantity=5, updated_at=NOW))  # plenty of room left
        db_session.add(
            MarketLatest(station_id=1, commodity_name="platinum", buy_price=0, sell_price=44586, supply=0,
                         demand=20, observed_at=NOW, source="eddn")
        )
        db_session.commit()

        draft = DraftCandidate(
            action="mining_continue", target=_mining_target(commodity_name="platinum"), required_segments=["mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert reason is None
        # evaluation_cargo = min(5+1, 100) = 6 -> r = 6/20 = 0.3 -> some penalty
        assert value == pytest.approx(44586.0 * 0.95)
