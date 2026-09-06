# EDpj Phase Plan — Trade Market Persistence Analysis

**Version:** 0.2  
**Status:** Binding Phase Plan Amendment  
**Date:** 2026-09-06  
**Depends on:** `docs/PHASE_FORMULA_VALIDATION_AMENDMENT_V0.1.md` and `docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md`

## 1. Purpose

Before EDpj adopts external Trade market observations as evidence strong enough for recommendation/ranking, measure empirically how long the observed prices and profitable opportunities persist.

The phase uses **only the historical market information already available to EDpj**. It must not invent travel time or assume a market update interval.

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

`2-6F-T1` is a Trade-specific evidence gate. Trade Formula Validation must not claim stronger temporal reliability without this analysis or an explicit `INSUFFICIENT` result.

`2-6F-T4` is the separate external-source feasibility gate. It determines whether external market sources can provide sufficiently broad, historical, reproducible, and temporally grounded multi-station Trade data. The size of the current EDpj cache must not be treated as evidence about game-wide Trade coverage.

## 3. 2-6F-T1 — Historical market observation persistence

### Objective

Determine, from repeated historical observations of the same station × commodity, how frequently an observed price and a profitable Trade condition remain valid after elapsed time.

### Required fixed windows

```text
5 min
10 min
15 min
30 min
60 min
120 min
```

The implementation may add windows when the available observation density supports them. Every reported window must include its eligible sample count.

### Required observations

For each eligible T0 observation:

```text
station
commodity
Buy price
Sell price
Supply
Demand
observed_at
received_at
```

For Trade opportunity analysis, retain source and destination observations separately and combine them only when their temporal relationship is supported by the data.

## 4. Price persistence measurement

For every fixed window `t`, calculate:

```text
price_persistence(t)
= observations whose later price remains within the
predefined unchanged/material-change criterion
  / observations with a valid later comparison
```

Measure both:

- absolute price change;
- relative percentage price change;

when the data volume permits.

The material-decrease threshold must be defined before inspecting the results.

## 5. Profit-condition persistence

For eligible Trade observations, calculate:

```text
profit_condition(t) = destination_sell_price - source_buy_price > 0
```

and:

```text
profit_condition_persistence(t)
= T0 profitable opportunities still satisfying the profit condition at t
  / T0 profitable opportunities with a valid comparison at t
```

Where a complete source/destination comparison cannot be reconstructed, do not fabricate a route-level result. Report the evidence limitation explicitly.

## 6. Time-to-first-price-decrease

For each eligible T0 price observation, scan later observations chronologically and identify the first observation satisfying the predefined material-decrease criterion.

Report:

- median time-to-first-material-decrease;
- percentile distribution where sample size permits;
- proportion with no observed decrease during the available history;
- observation-gap distribution;
- right-censored observations.

A lack of a later decrease is not a successful proof of indefinite stability.

## 7. Opportunity-level analysis

Where source and destination observations permit a valid chronological comparison, measure the persistence of the complete opportunity:

```text
source Buy price
       +
destination Sell price
       +
supply/demand constraints
       ↓
profitable Trade condition
       ↓
remains profitable after elapsed time t?
```

At minimum report:

- number of eligible T0 opportunities;
- number with valid future comparison;
- persistence rate at each time window;
- number of opportunities invalidated by price change;
- number invalidated by supply/demand condition where measurable.

## 8. Data quality and censoring

The phase must report:

- total market observations;
- unique station × commodity series;
- observation period;
- median/percentile observation interval;
- missing future comparison rate;
- duplicate observations where detectable;
- timestamp anomalies;
- right-censored observations.

Sparse observations must not be treated as evidence that a price remained unchanged between observations.

## 9. Chronological and leakage requirements

For every T0 case:

```text
features = observations available at or before T0
future outcome = observations strictly after T0
```

Future observations must never be used to construct T0 freshness, price, supply, demand, or candidate features.

Random train/test splitting is prohibited for this analysis when it would mix future and past market states.

## 10. Arrival-time restriction

This phase does **not** estimate actual arrival probability unless historical departure/arrival times and arrival market observations are available.

The output means:

```text
historical probability that the observed market opportunity remains valid
after elapsed time t
```

It must not be labeled:

```text
probability of profit when the player arrives
```

unless the required arrival evidence exists.

Jump count, route distance, supercruise distance, and global median travel time must not be substituted for actual candidate-specific travel time.

## 11. Exit criteria

### PASS

The phase may be marked `PASS` when:

- required historical market data is available;
- fixed-window persistence metrics are calculable;
- material-decrease criterion was frozen before result inspection;
- chronological/leakage checks pass;
- sample counts and censoring are reported;
- results are reproducible from the available dataset.

**PASS does not mean that every Trade route will remain profitable.** It means the persistence behavior has been empirically characterized with sufficient evidence.

### INSUFFICIENT

Return `INSUFFICIENT` when the available historical observations cannot support the requested measurement, including insufficient repeated observations or insufficient source/destination overlap.

Do not lower the evidence requirement solely to obtain PASS.

### FAIL

Return `FAIL` for methodological failures such as future leakage, post-hoc threshold selection, invalid chronological construction, or non-reproducible measurement.

## 12. Required deliverables

The implementation must produce a machine-readable result containing at least:

```text
window_minutes
eligible_count
comparison_count
price_persistence
profit_condition_persistence
material_decrease_count
material_decrease_rate
median_time_to_first_decrease
censored_count
median_observation_gap
status
```

Where data permits, include breakdowns by:

```text
commodity
station
source/destination pair
```

## 13. Relationship to Trade Formula Validation

The result of this phase becomes an input to the existing Formula Validation Gate.

```text
Trade Market Persistence
        ↓
External Market Source Feasibility
        ↓
understand external-data temporal reliability and coverage
        ↓
Trade formula baseline
        ↓
60% formula validation
        ↓
chronological holdout
        ↓
production adoption
```

The persistence analysis does not itself validate the Trade profit formula. It establishes the empirical reliability characteristics of the market observations on which that formula would depend.

`2-6F-T4` must separately establish whether an external source has enough multi-station historical coverage, chronological replayability, freshness, provenance, reuse conditions, and accuracy for EDpj to use it as a production evidence source. It must not treat external-site `profit_per_hour` as validated unless EDpj independently validates the transport-time model.

**Binding conclusion:** EDpj must first measure how often external market prices and profitable Trade opportunities survive 5/10/15/30/60/120-minute elapsed-time windows, and how long it takes before material price decreases are observed, using only available historical observations. In parallel, external-source feasibility must be empirically validated before broad multi-station Trade data is adopted. No unsupported arrival-time probability may be claimed.
