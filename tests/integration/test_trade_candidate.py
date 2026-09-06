from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from app.market.trade_candidate import TradeCandidate, attach_route

T0 = dt.datetime(2026, 9, 5, tzinfo=dt.timezone.utc)


def _candidate(**overrides) -> TradeCandidate:
    base = dict(
        commodity="gold",
        origin_station="Turing's Folly", origin_system="Col 285 Sector RX-Q a48-3",
        origin_buy_price=45531, origin_supply=100000, origin_observed_at=T0,
        destination_station="Cheranovsky City", destination_system="Ngurii",
        destination_sell_price=54779, destination_demand=1183, destination_observed_at=T0,
        unit_profit=9248,
    )
    base.update(overrides)
    return TradeCandidate(**base)


@dataclass
class FakeResponse:
    status_code: int
    _json: dict

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


@dataclass
class FakeRouteClient:
    poll_result: dict
    calls: list = field(default_factory=list)

    def post(self, url, *, params=None, timeout=None):
        self.calls.append(params)
        return FakeResponse(202, {"job": "abc123"})

    def get(self, url, *, timeout=None):
        return FakeResponse(200, {"state": "completed", "status": "ok", "result": self.poll_result})


def _no_sleep(seconds: float) -> None:
    pass


class TestAttachRoute:
    def test_fills_in_distance_and_jump_derived_fields(self):
        client = FakeRouteClient(poll_result={"total_jumps": 3, "distance": 120.5})

        result = attach_route(_candidate(), ship_range_ly=25.0, client=client, sleep_fn=_no_sleep)

        assert result.distance_ly == 120.5
        assert result.jump_count == 3
        assert result.profit_per_ly == 9248 / 120.5
        assert result.profit_per_jump == 9248 / 3

    def test_route_failure_leaves_fields_none(self):
        client = FakeRouteClient(poll_result={})  # missing total_jumps -> plot_route returns None

        result = attach_route(_candidate(), ship_range_ly=25.0, client=client, sleep_fn=_no_sleep)

        assert result.distance_ly is None
        assert result.jump_count is None
        assert result.profit_per_ly is None
        assert result.profit_per_jump is None

    def test_zero_jump_same_system_does_not_crash_and_leaves_profit_per_jump_none(self):
        client = FakeRouteClient(poll_result={"total_jumps": 0, "distance": 0.0})

        result = attach_route(_candidate(), ship_range_ly=25.0, client=client, sleep_fn=_no_sleep)

        assert result.jump_count == 0
        assert result.profit_per_jump is None  # division by zero avoided, never fabricated

    def test_preserves_original_candidate_fields(self):
        client = FakeRouteClient(poll_result={"total_jumps": 1, "distance": 4.4})
        original = _candidate()

        result = attach_route(original, ship_range_ly=25.0, client=client, sleep_fn=_no_sleep)

        assert result.commodity == original.commodity
        assert result.origin_station == original.origin_station
        assert result.destination_station == original.destination_station
        assert result.unit_profit == original.unit_profit
