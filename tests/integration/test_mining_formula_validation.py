from __future__ import annotations

import datetime as dt

from app.backtest.formula_validation import GateVerdict
from app.backtest.mining_formula_validation import (
    collect_mining_sell_evaluation_cases,
    evaluate_mining_sell_formula,
)
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketHistoricalObservation
from app.db.models.player import CargoState
from app.mining.price import effective_price

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)
STATION_ID = 100


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


def _market_obs(session, station_id: int, commodity_name: str, sell_price: int, demand: int, observed_at: dt.datetime):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=sell_price,
            demand=demand, observed_at=observed_at,
        )
    )
    session.commit()


class TestNoRealSellEvents:
    def test_zero_sell_events_yields_insufficient(self, db_session):
        result, collection = evaluate_mining_sell_formula(db_session, minimum_cases=1)
        assert result.verdict == GateVerdict.INSUFFICIENT
        assert result.formula_accuracy is None
        assert collection.total_sell_events == 0
        assert collection.cases == []


class TestCaseCollection:
    def test_sell_with_checkpoint_and_market_data_produces_a_case(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 10, "Stolen": 0}], 1)
        _market_obs(db_session, STATION_ID, "platinum", sell_price=44586, demand=178, observed_at=T0 - dt.timedelta(minutes=30))
        _event(
            db_session, "MarketSell", T0,
            {"MarketID": STATION_ID, "Type": "platinum", "Count": 10, "SellPrice": 44586, "TotalSale": 445860},
            2,
        )

        collection = collect_mining_sell_evaluation_cases(db_session)

        assert collection.total_sell_events == 1
        assert len(collection.cases) == 1
        expected_predicted = 10 * effective_price(44586, 10, 178)
        assert collection.cases[0].predicted_value == expected_predicted
        assert collection.cases[0].actual_value == 445860.0

    def test_actual_value_falls_back_to_count_times_sell_price_when_total_sale_missing(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 5, "Stolen": 0}], 1)
        _market_obs(db_session, STATION_ID, "platinum", sell_price=1000, demand=50, observed_at=T0 - dt.timedelta(minutes=10))
        _event(db_session, "MarketSell", T0, {"MarketID": STATION_ID, "Type": "platinum", "Count": 5, "SellPrice": 1000}, 2)

        collection = collect_mining_sell_evaluation_cases(db_session)

        assert collection.cases[0].actual_value == 5000.0

    def test_no_cargo_checkpoint_before_sell_is_excluded_and_counted(self, db_session):
        _event(db_session, "MarketSell", T0, {"MarketID": STATION_ID, "Type": "platinum", "Count": 5, "TotalSale": 5000}, 1)

        collection = collect_mining_sell_evaluation_cases(db_session)

        assert collection.cases == []
        assert collection.excluded.no_cargo_checkpoint == 1

    def test_no_market_data_for_held_commodity_is_excluded_and_counted(self, db_session):
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 5, "Stolen": 0}], 1)
        _event(db_session, "MarketSell", T0, {"MarketID": STATION_ID, "Type": "platinum", "Count": 5, "TotalSale": 5000}, 2)

        collection = collect_mining_sell_evaluation_cases(db_session)

        assert collection.cases == []
        assert collection.excluded.no_market_data == 1

    def test_predicted_value_never_reads_live_cargo_state(self, db_session):
        # Live CargoState says 999 platinum -- reconstruction from journal
        # says 10. If predicted_value used the live table, it would be
        # wildly different from the journal-reconstructed expectation.
        db_session.add(CargoState(commodity_name="platinum", quantity=999, updated_at=T0))
        db_session.commit()
        _checkpoint(db_session, T0 - dt.timedelta(hours=1), [{"Name": "platinum", "Count": 10, "Stolen": 0}], 1)
        _market_obs(db_session, STATION_ID, "platinum", sell_price=1000, demand=50, observed_at=T0 - dt.timedelta(minutes=10))
        _event(db_session, "MarketSell", T0, {"MarketID": STATION_ID, "Type": "platinum", "Count": 10, "TotalSale": 10000}, 2)

        collection = collect_mining_sell_evaluation_cases(db_session)

        expected_from_journal = 10 * effective_price(1000, 10, 50)
        assert collection.cases[0].predicted_value == expected_from_journal
