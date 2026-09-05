from __future__ import annotations

import datetime as dt

import pytest

from app.db.models.journal import JournalEvent
from app.db.models.market import MarketLatest
from app.db.models.player import CargoState
from app.scoring.models import BioTarget, DraftCandidate, MiningTarget
from app.scoring.value import (
    BIO_VALUE_UNAVAILABLE_REASON,
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


class TestMiningStartAndBioValueDeferred:
    """docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.4/§5: these
    four actions have no Phase 2-3 value model at all -- not a per-candidate
    data gap, so the reason is always the same fixed string."""

    def test_mining_start_value_is_always_unavailable(self, db_session):
        draft = DraftCandidate(
            action="mining_start", target=_mining_target(), required_segments=["jump", "supercruise", "mining_cycle"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == MINING_START_VALUE_UNAVAILABLE_REASON
        assert result.market_observed_ats == []  # no Market observation was ever consulted

    def test_bio_current_body_and_bio_next_system_value_is_always_unavailable(self, db_session):
        for action, segments in [
            ("bio_current_body", ["descent", "bio_sample", "ascent"]),
            ("bio_next_system", ["jump", "supercruise", "descent", "bio_sample", "ascent"]),
        ]:
            draft = DraftCandidate(action=action, target=_bio_target(), required_segments=segments)
            result = calculate_value(draft, db_session)
            value, reason = result.expected_value, result.value_unavailable_reason
            assert value is None
            assert reason == BIO_VALUE_UNAVAILABLE_REASON

    def test_bio_return_value_is_always_unavailable(self, db_session):
        draft = DraftCandidate(
            action="bio_return", target=_mining_target(), required_segments=["jump", "supercruise", "dock"]
        )
        result = calculate_value(draft, db_session)
        value, reason = result.expected_value, result.value_unavailable_reason
        assert value is None
        assert reason == BIO_VALUE_UNAVAILABLE_REASON


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
