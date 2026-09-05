from __future__ import annotations

import datetime as dt

from app.db.models.journal import JournalEvent
from app.db.models.market import MarketLatest
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
        value, reason = calculate_value(draft, db_session)
        assert value is None
        assert reason == MINING_START_VALUE_UNAVAILABLE_REASON

    def test_bio_current_body_and_bio_next_system_value_is_always_unavailable(self, db_session):
        for action, segments in [
            ("bio_current_body", ["descent", "bio_sample", "ascent"]),
            ("bio_next_system", ["jump", "supercruise", "descent", "bio_sample", "ascent"]),
        ]:
            draft = DraftCandidate(action=action, target=_bio_target(), required_segments=segments)
            value, reason = calculate_value(draft, db_session)
            assert value is None
            assert reason == BIO_VALUE_UNAVAILABLE_REASON

    def test_bio_return_value_is_always_unavailable(self, db_session):
        draft = DraftCandidate(
            action="bio_return", target=_mining_target(), required_segments=["jump", "supercruise", "dock"]
        )
        value, reason = calculate_value(draft, db_session)
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
        value, reason = calculate_value(draft, db_session)
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
        value, reason = calculate_value(draft, db_session)
        assert reason is None
        assert value == 90000.0
