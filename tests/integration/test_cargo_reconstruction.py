from __future__ import annotations

import datetime as dt

import pytest

from app.backtest.cargo_reconstruction import (
    CargoReconstructionIntegrityError,
    reconstruct_cargo_at_t0,
)
from app.db.models.journal import JournalEvent

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _event(session, event_type: str, timestamp: dt.datetime, payload: dict, line_number: int):
    session.add(
        JournalEvent(
            file_name="Journal.1.log", line_number=line_number, event_type=event_type,
            timestamp=timestamp, payload=payload,
        )
    )
    session.commit()


def _checkpoint(session, timestamp: dt.datetime, inventory: list[dict], line_number: int):
    _event(session, "Cargo", timestamp, {"Vessel": "Ship", "Count": sum(r["Count"] for r in inventory), "Inventory": inventory}, line_number)


class TestNoCheckpoint:
    def test_returns_none_when_no_checkpoint_exists_before_t0(self, db_session):
        assert reconstruct_cargo_at_t0(db_session, T0) is None

    def test_returns_none_when_only_checkpoint_is_after_t0(self, db_session):
        _checkpoint(db_session, T0 + dt.timedelta(hours=1), [{"Name": "platinum", "Count": 5, "Stolen": 0}], 1)
        assert reconstruct_cargo_at_t0(db_session, T0) is None


class TestCheckpointOnly:
    def test_uses_checkpoint_inventory_directly_when_no_deltas_follow(self, db_session):
        _checkpoint(
            db_session, T0 - dt.timedelta(hours=1),
            [{"Name": "platinum", "Count": 5, "Stolen": 0}, {"Name": "painite", "Count": 2, "Stolen": 0}],
            1,
        )
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 5, "painite": 2}

    def test_uses_latest_checkpoint_at_or_before_t0_not_the_first(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=2), [{"Name": "platinum", "Count": 1, "Stolen": 0}], 1)
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 9, "Stolen": 0}], 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 9}


class TestDeltaReplay:
    def test_mining_refined_adds_one_unit(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [], 1)
        _event(db_session, "MiningRefined", T0 - dt.timedelta(minutes=30), {"Type": "$platinum_name;"}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 1}

    def test_market_buy_adds_count(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [], 1)
        _event(db_session, "MarketBuy", T0 - dt.timedelta(minutes=30), {"Type": "tritium", "Count": 12}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"tritium": 12}

    def test_market_sell_subtracts_count(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 10, "Stolen": 0}], 1)
        _event(db_session, "MarketSell", T0 - dt.timedelta(minutes=30), {"Type": "platinum", "Count": 4}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 6}

    def test_collect_cargo_adds_one_unit(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [], 1)
        _event(db_session, "CollectCargo", T0 - dt.timedelta(minutes=30), {"Type": "damagedescapepod", "Stolen": False}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"damagedescapepod": 1}

    def test_eject_cargo_subtracts_count(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 10, "Stolen": 0}], 1)
        _event(db_session, "EjectCargo", T0 - dt.timedelta(minutes=30), {"Type": "platinum", "Count": 3, "Abandoned": True}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 7}

    def test_multiple_deltas_apply_in_chronological_order(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [], 1)
        _event(db_session, "MiningRefined", T0 - dt.timedelta(minutes=40), {"Type": "$platinum_name;"}, 2)
        _event(db_session, "MiningRefined", T0 - dt.timedelta(minutes=30), {"Type": "$platinum_name;"}, 3)
        _event(db_session, "MarketSell", T0 - dt.timedelta(minutes=20), {"Type": "platinum", "Count": 1}, 4)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 1}

    def test_strips_internal_name_wrapper_consistently_across_event_types(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "$platinum_name;", "Count": 2, "Stolen": 0}], 1)
        _event(db_session, "MiningRefined", T0 - dt.timedelta(minutes=30), {"Type": "$platinum_name;"}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 3}


class TestFutureLeakage:
    def test_delta_events_after_t0_are_never_applied(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 5, "Stolen": 0}], 1)
        _event(db_session, "MarketSell", T0 + dt.timedelta(minutes=5), {"Type": "platinum", "Count": 5}, 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 5}

    def test_a_later_checkpoint_after_t0_is_never_used(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 5, "Stolen": 0}], 1)
        _checkpoint(db_session, T0 + dt.timedelta(hours=1), [{"Name": "platinum", "Count": 999, "Stolen": 0}], 2)
        result = reconstruct_cargo_at_t0(db_session, T0)
        assert result == {"platinum": 5}


class TestIntegrityFailure:
    def test_negative_quantity_raises_instead_of_clamping(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 2, "Stolen": 0}], 1)
        _event(db_session, "MarketSell", T0 - dt.timedelta(minutes=30), {"Type": "platinum", "Count": 5}, 2)
        with pytest.raises(CargoReconstructionIntegrityError):
            reconstruct_cargo_at_t0(db_session, T0)
