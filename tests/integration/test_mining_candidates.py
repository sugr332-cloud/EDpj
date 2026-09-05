from __future__ import annotations

import datetime as dt

from app.db.models.journal import JournalEvent
from app.db.models.market import MarketLatest
from app.db.models.player import CargoState
from app.db.models.static import Station, System
from app.mining.candidates import (
    generate_mining_continue_candidates,
    generate_mining_sell_candidates,
    generate_mining_start_candidates,
)
from app.mining.state import detect_mining_context

NOW = dt.datetime.now(dt.timezone.utc)


def _add_event(session, event_type: str, timestamp: dt.datetime, payload: dict, line: int) -> None:
    session.add(JournalEvent(file_name="fixture.log", line_number=line, event_type=event_type, timestamp=timestamp, payload=payload))


def _add_system(session, system_address: int, name: str) -> None:
    session.add(System(system_address=system_address, name=name, x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))


def _add_station(session, station_id: int, system_address: int, name: str, station_type: str = "Outpost") -> None:
    session.add(
        Station(
            station_id=station_id, system_address=system_address, name=name, station_type=station_type,
            distance_to_arrival_ls=100.0, landing_pad={"small": 1, "medium": 1, "large": 1},
            has_vista_genomics=False, is_fleet_carrier=False, source="spansh", updated_at=NOW,
        )
    )


class TestGenerateMiningSellCandidates:
    def test_no_ore_cargo_produces_no_candidates(self, db_session):
        context = detect_mining_context(db_session)
        assert generate_mining_sell_candidates(db_session, context) == []

    def test_ore_cargo_with_demand_produces_candidate(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        _add_system(db_session, 1, "Deciat")
        _add_station(db_session, 100, 1, "Farseer Inc")
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.commit()

        context = detect_mining_context(db_session)
        candidates = generate_mining_sell_candidates(db_session, context)

        assert len(candidates) == 1
        assert candidates[0].action == "mining_sell"
        assert candidates[0].target.station_name == "Farseer Inc"
        assert candidates[0].target.system_name == "Deciat"
        assert candidates[0].required_segments == ["jump", "supercruise", "dock"]

    def test_zero_demand_station_is_excluded(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        _add_system(db_session, 1, "Deciat")
        _add_station(db_session, 100, 1, "Farseer Inc")
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=0, observed_at=NOW, source="eddn"))
        db_session.commit()

        context = detect_mining_context(db_session)
        assert generate_mining_sell_candidates(db_session, context) == []

    def test_generated_even_without_mining_active(self, db_session):
        # Regression: mining_sell must not require mining_active (§16/§7.1).
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        _add_system(db_session, 1, "Deciat")
        _add_station(db_session, 100, 1, "Farseer Inc")
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.commit()

        context = detect_mining_context(db_session)
        assert context.mining_active is False
        assert len(generate_mining_sell_candidates(db_session, context)) == 1

    def test_multiple_commodities_at_same_station_are_not_duplicated(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(CargoState(commodity_name="painite", quantity=5, updated_at=NOW))
        _add_system(db_session, 1, "Deciat")
        _add_station(db_session, 100, 1, "Farseer Inc")
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.add(MarketLatest(station_id=100, commodity_name="painite", buy_price=0, sell_price=30000,
                                     supply=0, demand=50, observed_at=NOW, source="eddn"))
        db_session.commit()

        context = detect_mining_context(db_session)
        candidates = generate_mining_sell_candidates(db_session, context)
        assert len(candidates) == 1  # one candidate per station, not per commodity

    def test_unresolved_station_is_skipped(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        # No Station row for station_id=999 -- not yet resolved via Spansh.
        db_session.add(MarketLatest(station_id=999, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.commit()

        context = detect_mining_context(db_session)
        assert generate_mining_sell_candidates(db_session, context) == []


class TestGenerateMiningContinueCandidates:
    def test_not_active_produces_no_candidates(self, db_session):
        context = detect_mining_context(db_session)
        assert generate_mining_continue_candidates(db_session, context) == []

    def test_active_produces_one_candidate_with_only_mining_cycle_segment(self, db_session):
        _add_event(db_session, "ApproachBody", NOW - dt.timedelta(minutes=10), {"BodyID": 5, "SystemAddress": 1}, 1)
        _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=5), {"Type": "$platinum_name;"}, 2)
        _add_system(db_session, 1, "Deciat")
        db_session.commit()

        context = detect_mining_context(db_session)
        candidates = generate_mining_continue_candidates(db_session, context)

        assert len(candidates) == 1
        assert candidates[0].action == "mining_continue"
        assert candidates[0].required_segments == ["mining_cycle"]  # no travel required
        assert candidates[0].target.system_name == "Deciat"


class TestGenerateMiningStartCandidates:
    def test_has_cargo_produces_no_candidates(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.commit()
        context = detect_mining_context(db_session)
        assert generate_mining_start_candidates(db_session, context) == []

    def test_no_history_produces_no_candidates(self, db_session):
        context = detect_mining_context(db_session)
        assert generate_mining_start_candidates(db_session, context) == []

    def test_history_produces_candidate_with_full_confidence(self, db_session):
        _add_event(db_session, "ApproachBody", NOW - dt.timedelta(days=1), {"BodyID": 7, "SystemAddress": 1}, 1)
        _add_event(db_session, "MiningRefined", NOW - dt.timedelta(days=1) + dt.timedelta(minutes=1), {"Type": "$platinum_name;"}, 2)
        _add_system(db_session, 1, "Deciat")
        db_session.commit()

        context = detect_mining_context(db_session)  # not currently active (too old for lookback), no cargo
        assert context.has_mining_cargo is False

        candidates = generate_mining_start_candidates(db_session, context)
        assert len(candidates) == 1
        assert candidates[0].action == "mining_start"
        assert candidates[0].required_segments == ["jump", "supercruise", "mining_cycle"]
        assert candidates[0].generation_confidence == 1.0
        assert candidates[0].target.system_name == "Deciat"
