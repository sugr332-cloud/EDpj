# EDpj Phase Plan — External Market Source Feasibility / Multi-Station Trade Data Validation

**Version:** 0.1  
**Status:** Binding Phase Plan Amendment  
**Date:** 2026-09-06  
**Depends on:** `docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md` and `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`

## 1. Purpose

Validate whether external market sources can provide sufficiently broad, historical, reproducible, and temporally grounded data for EDpj's station-to-station Trade analysis.

This phase exists because the current EDpj market cache is not sufficient evidence of game-wide Trade coverage. A narrow EDpj dataset must not be interpreted as evidence that Elite Dangerous lacks multi-station market data.

External market sources may expose station-level Buy/Sell prices, Supply/Demand, route candidates, timestamps/update ages, and multi-station coverage. For example, INARA currently exposes multi-source station-to-station Trade routes and freshness controls. citeturn0search0turn0search1

The existence of external data does not by itself establish that the data is suitable for EDpj. Suitability must be measured under this phase.

## 2. Phase position

Trade validation flow becomes:

```text
2-6A Historical Replay / Dataset
        ↓
2-6B Volatility evaluation
        ↓
2-6C Freshness evaluation
        ↓
2-6F-T1 Trade Market Persistence Analysis
        ↓
2-6F-T4 External Market Source Feasibility / Multi-Station Trade Data Validation
        ↓
2-6D Recommendation / Ranking diagnostic
        ↓
2-6E Existing model evaluation / adoption decisions
        ↓
2-6F Formula Validation Gate
        ├─ Mining Value Formula
        ├─ Bio Value Formula
        └─ Trade Value Formula
```

`2-6F-T1` measures temporal persistence of the historical market observations already available to EDpj. `2-6F-T4` separately determines whether an external source can expand that evidence to sufficiently broad multi-station Trade coverage and whether that expanded dataset is reproducible and usable.

## 3. Scope

The target Trade domain is:

```text
NPC / station Commodities Market
source station Buy
        ↓
commodity
        ↓
destination station Sell
```

Player-to-player transactions, Fleet Carrier owner orders, and other non-target market mechanisms remain outside this phase unless explicitly added to the specification.

## 4. External source audit

For every candidate external source, record:

- source name;
- acquisition mechanism;
- market-data provenance;
- station coverage;
- system coverage;
- commodity coverage;
- Buy-price coverage;
- Sell-price coverage;
- Supply coverage;
- Demand coverage;
- observation timestamps;
- received/update timestamps where available;
- historical depth;
- update frequency;
- source freshness controls;
- geographic coverage;
- reproducibility of historical retrieval;
- data transformation performed by the source;
- licensing/reuse conditions;
- retention/storage conditions applicable to EDpj;
- known accuracy limitations.

## 5. Multi-station coverage measurement

The implementation must quantify, rather than merely assert, external coverage.

At minimum calculate:

```text
unique_stations
unique_systems
unique_commodities
station_commodity_series
buy_observation_count
sell_observation_count
source_station_count
destination_station_count
commodity_overlap_count
source_destination_pair_count
```

Coverage must be measured over a defined observation period.

The phase must explicitly distinguish:

```text
external-source coverage
vs.
EDpj currently persisted coverage
```

A two-station EDpj cache must never be used as a proxy for the total coverage of an external source or the game.

## 6. Historical depth and replayability

Determine whether the source permits chronological reconstruction.

Measure:

- earliest available observation timestamp;
- latest available observation timestamp;
- total history duration;
- observations per station × commodity series;
- observations per source/destination pair;
- observation interval distribution;
- ability to retrieve or reconstruct historical states;
- ability to reproduce the same analysis from preserved source data.

If only the latest state is available, classify the source as unsuitable for historical persistence analysis unless an independently preserved historical dataset exists.

## 7. Trade candidate construction

Where data permits, construct candidate opportunities using only observations available at the candidate T0:

```text
source Buy price
source Supply
        ↓
commodity overlap
        ↓
destination Sell price
destination Demand
        ↓
profit_per_unit = destination Sell - source Buy
```

Candidate construction must preserve source and destination timestamps.

A candidate is not considered historically valid merely because the source currently reports both endpoints; the chronological availability of both observations must be established for the T0 analysis.

## 8. Freshness and persistence integration

For external sources that provide timestamps or update ages, measure the age distribution of candidate observations.

Reuse the fixed temporal windows from `2-6F-T1` where sufficient historical density exists:

```text
5 min
10 min
15 min
30 min
60 min
120 min
```

For each window, evaluate whether the external-data Trade opportunity remains valid under the later observed state.

The analysis must remain leakage-safe:

```text
T0 features = data available at or before T0
future outcome = data strictly after T0
```

Future source observations must not be used to construct T0 prices, freshness, Supply, Demand, or route candidates.

## 9. Accuracy / consistency check

Where EDpj can obtain an independent in-game observation, compare the external source against the observed game state.

Measure where possible:

- Buy-price difference;
- Sell-price difference;
- Supply difference;
- Demand difference;
- timestamp difference;
- station/commodity identity consistency.

External data must not be treated as ground truth merely because it is published by a popular third-party service.

## 10. Reuse and provenance gate

Before productization, determine whether EDpj may legally and technically:

- retrieve the source data;
- store historical observations;
- transform/aggregate the data;
- redistribute derived results if applicable;
- reproduce analyses later;
- retain the required history for backtesting.

If reuse conditions cannot be established, the source may be used for exploratory research but must not automatically become a production dependency.

## 11. Profit-per-hour restriction

External sites may publish route distance, travel estimates, profit per trip, or profit per hour. These values are not automatically valid EDpj metrics.

This phase may validate:

```text
Buy price
Sell price
Supply
Demand
profit_per_unit
historical persistence
```

It must not adopt an external `profit_per_hour` value as validated evidence unless EDpj independently validates the underlying transport-time model.

Candidate-specific travel time remains a separate validation problem.

## 12. Exit criteria

### PASS

Return `PASS` only when:

- the source provides sufficient multi-station and commodity coverage for the intended Trade analysis;
- historical depth supports chronological analysis;
- Buy/Sell observations can be paired without temporal leakage;
- freshness and persistence can be measured reproducibly;
- provenance and reuse conditions are established sufficiently for the intended use;
- reproducibility checks pass;
- accuracy/consistency checks do not reveal an unacceptable systematic failure for the intended use.

### INSUFFICIENT

Return `INSUFFICIENT` when the source has useful current data but lacks sufficient historical depth, station/commodity overlap, reproducibility, timestamp quality, or other evidence required for EDpj's intended analysis.

Do not convert a coverage or history limitation into a game-wide Trade No-Go conclusion.

### FAIL

Return `FAIL` for methodological failures such as future leakage, irreproducible reconstruction, invalid station/commodity identity mapping, or use of unsupported external metrics as validated ground truth.

## 13. Required deliverables

Produce a machine-readable source audit containing at least:

```text
source
observation_start
observation_end
unique_stations
unique_systems
unique_commodities
station_commodity_series
buy_observation_count
sell_observation_count
commodity_overlap_count
source_destination_pair_count
median_observation_gap
freshness_distribution
historical_replay_available
provenance_status
reuse_status
accuracy_check_status
status
```

Where applicable, also produce chronological Trade persistence results compatible with the `2-6F-T1` result schema.

## 14. Binding conclusion

EDpj must not infer the availability or unavailability of game-wide Trade data from the size of its current local cache.

The external-data question is an empirical feasibility question: identify candidate sources, quantify their multi-station historical coverage, verify chronological replayability and freshness, test Trade candidate construction and persistence, audit provenance/reuse conditions, and only then decide whether external market data can support EDpj Trade recommendations.
