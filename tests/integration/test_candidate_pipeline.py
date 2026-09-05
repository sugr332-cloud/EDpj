from __future__ import annotations

import datetime as dt

import pytest

from app.db.models.calibration import CalibrationModel
from app.db.models.eddn import BodyBioSignal
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketLatest
from app.db.models.player import SINGLETON_ID, CargoState, PlayerState
from app.db.models.static import Station, System
from app.scoring.pipeline import generate_and_classify

NOW = dt.datetime.now(dt.timezone.utc)


def _player_state(**overrides) -> PlayerState:
    defaults = dict(
        id=SINGLETON_ID, current_system="Deciat", current_system_address=1, current_body_id=None,
        current_body_name=None, docked=False, landed=False, on_foot=False, source_status={}, updated_at=NOW,
    )
    defaults.update(overrides)
    return PlayerState(**defaults)


def _calibrate(session, segment_type: str, seconds: float) -> None:
    session.add(
        CalibrationModel(
            segment_type=segment_type, seconds=seconds, sample_count_fit=20, sample_count_eval=5,
            median_absolute_error=0.0, median_signed_error=0.0, r_squared=1.0,
            validation_status="pass", fitted_at=NOW,
        )
    )


def _mining_active_fixture(session) -> None:
    session.add(JournalEvent(file_name="f.log", line_number=1, event_type="ApproachBody",
                              timestamp=NOW - dt.timedelta(minutes=10), payload={"BodyID": 5, "SystemAddress": 1}))
    session.add(JournalEvent(file_name="f.log", line_number=2, event_type="MiningRefined",
                              timestamp=NOW - dt.timedelta(minutes=5), payload={"Type": "$platinum_name;"}))


class TestCompleteCandidates:
    """docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §0/§6: reaching
    `result.complete` now requires BOTH horizon_complete AND value_calculable
    (is_scoreable) -- mining_continue is the only action for which every
    input (commodity/quantity/cargo capacity/market) can currently be
    supplied, and only once all of them actually are."""

    def test_mining_continue_reaches_score_when_all_value_inputs_are_known(self, db_session):
        _mining_active_fixture(db_session)
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=100, system_address=1, name="Farseer Inc", station_type="Outpost",
                                distance_to_arrival_ls=100.0, landing_pad={}, has_vista_genomics=False,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.add(JournalEvent(file_name="f.log", line_number=3, event_type="Loadout",
                                     timestamp=NOW - dt.timedelta(minutes=20), payload={"CargoCapacity": 32}))
        # Small enough that r stays in the no-penalty zone (r=11/178 <= 0.25), so
        # this doesn't change the expected_value assertion below -- just gives
        # cargo_state_data_source (Phase 2-5D) something real to report.
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        _calibrate(db_session, "mining_cycle", 120.0)
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        mining_continue = [c for c in result.complete if c.action == "mining_continue"]
        assert len(mining_continue) == 1
        candidate = mining_continue[0]
        assert candidate.horizon_complete is True
        assert candidate.action_horizon_seconds == 120.0
        assert candidate.expected_value == 44586.0  # 1t at r~0 -> no demand penalty
        assert candidate.score_per_hour == 44586.0 / (120.0 / 3600)
        # generation_confidence(1.0, body_context found) x mining_cycle(estimated=0.85)
        # x market freshness(~1.0, observed_at is effectively "now")
        assert candidate.confidence == pytest.approx(0.85, abs=1e-6)

        # Phase 2-5D: reasons/data_sources are populated on the winning candidate.
        reason_factors = {r.factor for r in candidate.reasons}
        assert reason_factors == {"mining_cycle", "expected_value", "confidence", "data_freshness", "score_per_hour"}
        assert all(r.effect == "positive" for r in candidate.reasons if r.factor in ("expected_value", "score_per_hour"))
        assert all(r.effect == "negative" for r in candidate.reasons if r.factor not in ("expected_value", "score_per_hour"))

        source_names = {s.name for s in candidate.data_sources}
        assert source_names == {"market_latest", "cargo_state", "loadout", "calibration_model"}


class TestHorizonCompleteButValueUnavailable:
    """The other half of the same discovery: horizon_complete=True is no
    longer sufficient on its own -- these stay IncompleteCandidate with
    blocking_segments == [] (horizon is fine) but a populated
    value_unavailable_reason."""

    def test_mining_continue_stays_incomplete_when_cargo_capacity_unknown(self, db_session):
        _mining_active_fixture(db_session)
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        _calibrate(db_session, "mining_cycle", 120.0)
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        assert result.complete == []
        mining_continue = [c for c in result.incomplete if c.action == "mining_continue"]
        assert len(mining_continue) == 1
        assert mining_continue[0].blocking_segments == []
        assert mining_continue[0].expected_value is None
        assert mining_continue[0].value_unavailable_reason == "cargo_capacity_unknown"

    def test_bio_current_body_stays_incomplete_because_species_value_model_is_unimplemented(self, db_session):
        db_session.add(
            BodyBioSignal(system_address=1, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        _calibrate(db_session, "descent", 60.0)
        _calibrate(db_session, "bio_sample", 90.0)
        _calibrate(db_session, "ascent", 30.0)
        db_session.commit()

        result = generate_and_classify(db_session, _player_state(current_body_id=5))

        assert result.complete == []
        bio_current = [c for c in result.incomplete if c.action == "bio_current_body"]
        assert len(bio_current) == 1
        assert bio_current[0].blocking_segments == []
        assert bio_current[0].value_unavailable_reason == "species value model not implemented"


class TestValuePreservedDespiteIncompleteHorizon:
    """docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §1: a candidate
    whose Value IS calculable must keep `expected_value` even while
    `blocking_segments` is non-empty, so a future SC estimate doesn't
    require recomputing Value from scratch."""

    def test_mining_sell_keeps_expected_value_while_horizon_incomplete(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=100, system_address=1, name="Farseer Inc", station_type="Outpost",
                                distance_to_arrival_ls=100.0, landing_pad={}, has_vista_genomics=False,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        _calibrate(db_session, "jump", 30.0)
        _calibrate(db_session, "dock", 15.0)
        # supercruise is never calibrated -- horizon can never be complete
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        mining_sell = [c for c in result.incomplete if c.action == "mining_sell"]
        assert len(mining_sell) == 1
        assert mining_sell[0].blocking_segments == ["supercruise"]
        assert mining_sell[0].expected_value == 10 * 44586.0  # r = 10/178 -> no demand penalty
        assert mining_sell[0].value_unavailable_reason is None


class TestIncompleteCandidates:
    def test_mining_sell_is_always_incomplete_because_of_supercruise(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=100, system_address=1, name="Farseer Inc", station_type="Outpost",
                                distance_to_arrival_ls=100.0, landing_pad={}, has_vista_genomics=False,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        # Even calibrating jump/dock fully -- supercruise is never
        # calibrated at all, so this candidate can never become complete.
        _calibrate(db_session, "jump", 30.0)
        _calibrate(db_session, "dock", 15.0)
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        assert result.complete == []
        assert len(result.incomplete) == 1
        assert result.incomplete[0].action == "mining_sell"
        assert result.incomplete[0].blocking_segments == ["supercruise"]

    def test_bio_next_system_is_always_incomplete(self, db_session):
        db_session.add(System(system_address=1, name="Origin", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(System(system_address=2, name="Nearby", x=10.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(
            BodyBioSignal(system_address=2, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        assert any(c.action == "bio_next_system" for c in result.incomplete)
        assert all(c.action != "bio_next_system" for c in result.complete)


class TestPipelineToggles:
    def test_mining_disabled_produces_no_mining_candidates(self, db_session):
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.commit()

        result = generate_and_classify(db_session, _player_state(), mining_enabled=False)

        all_actions = [c.action for c in result.complete] + [c.action for c in result.incomplete]
        assert not any(a.startswith("mining_") for a in all_actions)

    def test_bio_disabled_produces_no_bio_candidates(self, db_session):
        db_session.add(
            BodyBioSignal(system_address=1, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()

        result = generate_and_classify(db_session, _player_state(current_body_id=5), bio_enabled=False)

        all_actions = [c.action for c in result.complete] + [c.action for c in result.incomplete]
        assert not any(a.startswith("bio_") for a in all_actions)


class TestDesignDocRegression:
    """docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §9/§12:
    only mining_continue and bio_current_body can ever be horizon_complete
    today -- the other four action types structurally require supercruise,
    which is always unavailable. This must not silently change (e.g. if a
    future edit accidentally adds supercruise to one of the "no travel"
    action's required_segments).

    docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §0/§2 (v0.4) adds a
    second, independent axis on top of that: horizon_complete is no longer
    sufficient for `result.complete` on its own. This fixture has no
    `Loadout` event, so mining_continue's cargo capacity is unknown, and no
    species value model exists for bio_current_body -- both stay
    horizon-complete-but-value-blocked `IncompleteCandidate`s, and
    `result.complete` is empty."""

    def test_all_six_action_types_present_and_correctly_bucketed(self, db_session):
        # Mining: cargo + market + history, so sell/continue/start all apply
        _mining_active_fixture(db_session)
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=100, system_address=1, name="Farseer Inc", station_type="Outpost",
                                distance_to_arrival_ls=100.0, landing_pad={}, has_vista_genomics=True,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        # Bio: current body signal + a nearby system + unsold data
        db_session.add(
            BodyBioSignal(system_address=1, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.add(System(system_address=2, name="Nearby", x=10.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(
            BodyBioSignal(system_address=2, body_id=9, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.add(JournalEvent(file_name="f.log", line_number=10, event_type="ScanOrganic",
                                     timestamp=NOW - dt.timedelta(minutes=5), payload={"ScanType": "Analyse"}))
        # Calibrate every non-supercruise segment generously
        for segment_type, seconds in [
            ("jump", 30.0), ("dock", 15.0), ("mining_cycle", 120.0),
            ("descent", 60.0), ("bio_sample", 90.0), ("ascent", 30.0),
        ]:
            _calibrate(db_session, segment_type, seconds)
        db_session.commit()

        result = generate_and_classify(db_session, _player_state(current_body_id=5))

        complete_actions = {c.action for c in result.complete}
        incomplete_actions = {c.action for c in result.incomplete}

        # mining_start is intentionally absent here: it requires
        # has_mining_cargo == False (§4.3), which is mutually exclusive
        # with this fixture's ore cargo (needed for mining_sell/continue)
        # -- the two states can't co-occur, so this isn't a bug. Its own
        # generation is covered separately in tests/integration/test_mining_candidates.py.
        incomplete_by_action = {c.action: c for c in result.incomplete}
        assert complete_actions == set()
        assert set(incomplete_by_action) == {
            "mining_sell", "mining_continue", "bio_current_body", "bio_next_system", "bio_return",
        }

        # Horizon-blocked (supercruise required, always unavailable today)
        for action in ("mining_sell", "bio_next_system", "bio_return"):
            assert incomplete_by_action[action].blocking_segments == ["supercruise"]

        # Horizon-complete but Value-blocked (docs/PHASE_2_3... v0.4)
        assert incomplete_by_action["mining_continue"].blocking_segments == []
        assert incomplete_by_action["mining_continue"].value_unavailable_reason == "cargo_capacity_unknown"
        assert incomplete_by_action["bio_current_body"].blocking_segments == []
        assert (
            incomplete_by_action["bio_current_body"].value_unavailable_reason
            == "species value model not implemented"
        )


class TestNonPositiveHorizon:
    """Edge-case review, Phase 2-3 follow-up: blocking_segments == [] only
    means no segment is `unavailable` -- a calibrated segment landing on
    a 0.0-second median must not turn into an infinite/undefined score."""

    def test_zero_second_calibrated_horizon_stays_incomplete_even_with_a_known_value(self, db_session):
        _mining_active_fixture(db_session)
        db_session.add(System(system_address=1, name="Deciat", x=0.0, y=0.0, z=0.0, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=100, system_address=1, name="Farseer Inc", station_type="Outpost",
                                distance_to_arrival_ls=100.0, landing_pad={}, has_vista_genomics=False,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(MarketLatest(station_id=100, commodity_name="platinum", buy_price=0, sell_price=44586,
                                     supply=0, demand=178, observed_at=NOW, source="eddn"))
        db_session.add(JournalEvent(file_name="f.log", line_number=3, event_type="Loadout",
                                     timestamp=NOW - dt.timedelta(minutes=20), payload={"CargoCapacity": 32}))
        _calibrate(db_session, "mining_cycle", 0.0)  # degenerate: two samples with an identical timestamp
        db_session.commit()

        result = generate_and_classify(db_session, _player_state())

        assert result.complete == []
        mining_continue = [c for c in result.incomplete if c.action == "mining_continue"]
        assert len(mining_continue) == 1
        candidate = mining_continue[0]
        assert candidate.blocking_segments == []  # no segment reports "unavailable"
        assert candidate.expected_value == 44586.0  # Value was calculable
        assert candidate.value_unavailable_reason is None
        assert "positive duration" in candidate.reason
