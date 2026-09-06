from __future__ import annotations

import datetime as dt

from app.db.models.market import MarketHistoricalFetchLog, MarketHistoricalObservation
from app.market.predictability import analyze_market, ensure_days_fetched, ensure_days_fetched_batch, get_predictability
from tests.integration.test_eddn_archive import FakeStreamingHttpClient, _archive_url, _compress_day, _envelope

NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _payloads_for_window(
    station_id: int, commodity_name: str, window_days: int, now: dt.datetime, prices: list[int]
) -> dict[str, bytes]:
    """One envelope per day in the window, cycling through `prices` so
    there's real price movement to compute volatility from."""
    window_start = now - dt.timedelta(days=window_days)
    dates = [(window_start + dt.timedelta(days=i)).date() for i in range((now.date() - window_start.date()).days + 1)]
    payloads = {}
    for i, date in enumerate(dates):
        price = prices[i % len(prices)]
        envelope = _envelope(
            station_id, f"{date:%Y-%m-%d}T12:00:00Z", [{"name": commodity_name, "sellPrice": price, "demand": 100}]
        )
        payloads[_archive_url(date)] = _compress_day([envelope])
    return payloads


class TestEnsureDaysFetchedBatch:
    """docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md
    §14: a real Model Validation run found 5 same-station targets over a
    7-day window triggering 35 redundant downloads of the same 7 archive
    files (once per target, per date). This batches the fetch so each
    date is downloaded at most once regardless of target count, while
    keeping MarketHistoricalFetchLog's per-target granularity so a
    genuinely new target is never silently skipped."""

    def test_one_archive_request_per_date_regardless_of_target_count(self, db_session):
        dates = [NOW.date() - dt.timedelta(days=i) for i in range(3)]
        payloads = {
            _archive_url(date): _compress_day(
                [_envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 1, "demand": 1}])]
            )
            for date in dates
        }
        client = FakeStreamingHttpClient(payloads)
        targets = [(100, "platinum"), (100, "gold"), (200, "silver")]

        ensure_days_fetched_batch(db_session, targets, dates, client)

        assert len(client.requested_urls) == 3  # not 3 dates * 3 targets = 9

    def test_extracts_rows_for_each_target_in_one_pass(self, db_session):
        date = NOW.date()
        envelopes = [
            _envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}]),
            _envelope(200, f"{date:%Y-%m-%d}T11:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 2}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        ensure_days_fetched_batch(db_session, [(100, "platinum"), (200, "gold")], [date], client)

        assert (
            db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").count()
            == 1
        )
        assert (
            db_session.query(MarketHistoricalObservation).filter_by(station_id=200, commodity_name="gold").count() == 1
        )

    def test_persists_buy_price_supply_and_gateway_timestamp_when_present(self, db_session):
        # Phase 2-6F-T1: these fields were previously extracted by
        # parse_commodity_message() and then discarded here -- now kept.
        date = NOW.date()
        envelope = _envelope(
            100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5, "buyPrice": 39000, "stock": 12}]
        )
        envelope["header"]["gatewayTimestamp"] = f"{date:%Y-%m-%d}T10:00:05Z"
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day([envelope])})

        ensure_days_fetched_batch(db_session, [(100, "platinum")], [date], client)

        row = db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").one()
        assert row.buy_price == 39000
        assert row.supply == 12
        # SQLite doesn't round-trip tzinfo (project-wide known quirk) --
        # compare naive, as every other datetime assertion in this codebase does.
        assert row.received_at == dt.datetime(2026, 8, 20, 10, 0, 5)

    def test_received_at_is_none_when_envelope_has_no_gateway_timestamp(self, db_session):
        date = NOW.date()
        envelope = _envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 1, "demand": 1}])
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day([envelope])})

        ensure_days_fetched_batch(db_session, [(100, "platinum")], [date], client)

        row = db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").one()
        assert row.received_at is None
        assert row.buy_price == 0
        assert row.supply == 0

    def test_second_call_does_not_refetch_already_covered_dates(self, db_session):
        date = NOW.date()
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day([])})
        targets = [(100, "platinum")]

        ensure_days_fetched_batch(db_session, targets, [date], client)
        first_count = len(client.requested_urls)
        ensure_days_fetched_batch(db_session, targets, [date], client)

        assert len(client.requested_urls) == first_count

    def test_a_target_added_in_a_later_call_is_still_correctly_scanned(self, db_session):
        # Correctness guarantee that motivates keeping FetchLog's
        # per-(station, commodity, date) granularity instead of
        # collapsing it to date-only.
        date = NOW.date()
        envelopes = [
            _envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 1, "demand": 1}]),
            _envelope(200, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "gold", "sellPrice": 1, "demand": 1}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        ensure_days_fetched_batch(db_session, [(100, "platinum")], [date], client)
        assert (
            db_session.query(MarketHistoricalObservation).filter_by(station_id=200, commodity_name="gold").count() == 0
        )

        ensure_days_fetched_batch(db_session, [(200, "gold")], [date], client)
        assert (
            db_session.query(MarketHistoricalObservation).filter_by(station_id=200, commodity_name="gold").count() == 1
        )


class TestEnsureDaysFetchedSingleTargetWrapper:
    def test_matches_batch_behavior_for_one_target(self, db_session):
        date = NOW.date()
        envelopes = [_envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}])]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        ensure_days_fetched(db_session, 100, "platinum", [date], client)

        assert (
            db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").count()
            == 1
        )
        assert (
            db_session.query(MarketHistoricalFetchLog)
            .filter_by(station_id=100, commodity_name="platinum", date=date)
            .count()
            == 1
        )


class TestAnalyzeMarket:
    def test_first_call_fetches_persists_and_classifies(self, db_session):
        payloads = _payloads_for_window(100, "platinum", window_days=2, now=NOW, prices=[40000, 44586, 42000])
        client = FakeStreamingHttpClient(payloads)

        result = analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=2, now=NOW)

        assert result.station_id == 100
        assert result.commodity_name == "platinum"
        assert result.sample_count == 3  # 3 days in a 2-day window (inclusive range)
        assert result.volatility_class in ("STABLE", "MODERATE", "VOLATILE", "INSUFFICIENT")
        assert len(client.requested_urls) == 3

        stored = db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").all()
        assert len(stored) == 3

    def test_second_call_does_not_refetch_already_cached_days(self, db_session):
        payloads = _payloads_for_window(100, "platinum", window_days=2, now=NOW, prices=[40000])
        client = FakeStreamingHttpClient(payloads)

        analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=2, now=NOW)
        first_call_request_count = len(client.requested_urls)

        analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=2, now=NOW)

        assert len(client.requested_urls) == first_call_request_count  # no new requests on the second run

    def test_day_with_zero_matching_rows_is_logged_and_not_refetched(self, db_session):
        # Archive has data for this day, but none of it matches our target station/commodity.
        date = NOW.date()
        unrelated = _envelope(999, f"{date:%Y-%m-%d}T12:00:00Z", [{"name": "gold", "sellPrice": 1, "demand": 1}])
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day([unrelated])})

        analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=0, now=NOW)
        assert db_session.query(MarketHistoricalFetchLog).filter_by(station_id=100, commodity_name="platinum").count() == 1
        assert db_session.query(MarketHistoricalObservation).filter_by(station_id=100, commodity_name="platinum").count() == 0

        first_call_request_count = len(client.requested_urls)
        analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=0, now=NOW)
        assert len(client.requested_urls) == first_call_request_count  # the zero-match day wasn't re-requested

    def test_insufficient_when_too_few_samples(self, db_session):
        # Only 1 day of data -- 0 usable pairs, well below MIN_SAMPLES_FOR_CLASSIFICATION.
        client = FakeStreamingHttpClient(_payloads_for_window(100, "platinum", window_days=0, now=NOW, prices=[40000]))

        result = analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=0, now=NOW)
        assert result.volatility_class == "INSUFFICIENT"


class TestComputeVolatilityStatsRefactor:
    def test_analyze_market_result_matches_direct_compute_volatility_stats(self, db_session):
        # Phase 2-6A extracted analyze_market()'s calculation into
        # _compute_volatility_stats() (docs/PHASE_2_6A... §2.1) so
        # app/backtest/replay.py's compare_windows() can reuse the exact
        # same classification logic without persisting. This proves the
        # extraction didn't change analyze_market()'s persisted result.
        from app.market.predictability import _compute_volatility_stats

        payloads = _payloads_for_window(100, "platinum", window_days=2, now=NOW, prices=[40000, 44586, 42000])
        client = FakeStreamingHttpClient(payloads)

        persisted = analyze_market(
            db_session, station_id=100, commodity_name="platinum", client=client, window_days=2, now=NOW
        )

        direct = _compute_volatility_stats(
            db_session,
            station_id=100,
            commodity_name="platinum",
            window_start=NOW - dt.timedelta(days=2),
            now=NOW,
        )

        assert persisted.sample_count == direct.sample_count
        assert persisted.median_abs_price_change == direct.median_abs_price_change
        assert persisted.p95_abs_price_change == direct.p95_abs_price_change
        assert persisted.median_abs_demand_change == direct.median_abs_demand_change
        assert persisted.p95_abs_demand_change == direct.p95_abs_demand_change
        assert persisted.median_observation_gap_seconds == direct.median_observation_gap_seconds
        assert persisted.p95_observation_gap_seconds == direct.p95_observation_gap_seconds
        assert persisted.volatility_class == direct.volatility_class


class TestGetPredictability:
    def test_returns_none_when_never_analyzed(self, db_session):
        assert get_predictability(db_session, station_id=100, commodity_name="platinum") is None

    def test_returns_the_most_recent_analysis(self, db_session):
        client = FakeStreamingHttpClient(_payloads_for_window(100, "platinum", window_days=0, now=NOW, prices=[40000]))
        analyze_market(db_session, station_id=100, commodity_name="platinum", client=client, window_days=0, now=NOW)

        result = get_predictability(db_session, station_id=100, commodity_name="platinum")
        assert result is not None
        assert result.station_id == 100
