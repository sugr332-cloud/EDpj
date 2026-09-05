# EDpj Specification — Trade Market Persistence / External Observation Reliability Amendment

**Version:** 0.1  
**Status:** Binding Specification Amendment  
**Date:** 2026-09-06  
**Depends on:** `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`

## 1. Purpose

EDpj must not assume that an external Trade database price or route remains executable when the commander arrives at the destination.

External market data is treated as **timestamped market observation evidence**, not authoritative future market state.

The purpose of this amendment is to require an empirical measurement, using only the historical market observations currently available to EDpj, of how long observed Trade prices and profitable opportunities tend to persist.

## 2. Required empirical questions

Before external Trade observations are used to support stronger recommendation/ranking claims, EDpj shall measure:

1. probability that an observed `Buy`/`Sell` price remains unchanged after elapsed time `t`;
2. probability that the Trade profitable condition remains valid after elapsed time `t`;
3. elapsed-time distribution until the first material price decrease is observed;
4. magnitude of price decrease after fixed elapsed-time windows;
5. persistence of the complete source/destination Trade opportunity, where both sides can be observed;
6. differences by commodity, station, route, and market condition where sufficient observations exist.

Only observations actually present in the available historical dataset may be used. No assumed travel time, assumed market tick interval, or external-site accuracy claim may be substituted for missing evidence.

## 3. Fixed-window analysis

At minimum, evaluate:

```text
5 min
10 min
15 min
30 min
60 min
120 min
```

The analysis must record the eligible sample count for every window. Additional windows may be evaluated when observation density permits.

For each eligible T0 observation, identify the corresponding later observation of the same station × commodity, subject to the available observation gaps.

Required metrics:

```text
price_persistence(t)
= eligible T0 observations whose price remains within the
predefined unchanged/material-change criterion at T0 + t
  / eligible T0 observations with a valid comparison

profit_condition_persistence(t)
= eligible T0 Trade opportunities for which
sell_price - buy_price > 0 remains true at T0 + t
  / eligible T0 Trade opportunities with a valid comparison
```

The unchanged/material-change threshold must be fixed before result inspection. Where sample size permits, retain both absolute and relative price-change measures.

## 4. Time-to-first-material-decrease

For each eligible T0 price observation with subsequent observations, identify the first later observation that satisfies the predefined material-decrease criterion.

Report:

- median time-to-first-material-decrease;
- percentile distribution when sample size is sufficient;
- number/proportion with no observed decrease within the available observation window;
- observation-gap distribution;
- censoring status.

A price with no observed decrease is not treated as proof of indefinite stability. It is right-censored at the last usable observation.

## 5. Arrival-probability restriction

The following claim is prohibited unless historical arrival time and arrival market state are available:

```text
probability that the route is profitable when the player arrives
```

Until then, EDpj may only claim:

```text
probability that the observed market opportunity remains valid
after elapsed time t in the historical observation data
```

This distinction is binding.

## 6. External-site reliability model

EDpj shall distinguish:

```text
source reliability
    = whether the external source supplies usable observations

data freshness
    = age of the observation relative to T0

market persistence
    = probability that the observed market condition survives elapsed time

arrival validity
    = not measurable from current data unless actual arrival observations exist
```

A reputable external site does not automatically imply high market persistence.

## 7. Recommendation consequence

Until the persistence analysis is completed with sufficient historical evidence:

- external Trade prices may be used for candidate discovery;
- observed profit/profit-per-unit may be displayed as observation-based values;
- arrival profit must not be presented as guaranteed;
- validated Trade `Cr/h` remains unavailable when transport time is not measured/validated;
- persistence results must be incorporated into confidence/risk handling before making stronger claims about Trade reliability.

Insufficient data must produce:

```text
INSUFFICIENT
```

and must not be converted into PASS by assumption.

## 8. Relationship to Formula Validation

This analysis is a prerequisite evidence layer for Trade Formula Validation. It does not replace the existing 60% Formula Validation Gate or chronological holdout requirement.

The required sequence is:

```text
Historical market observations
        ↓
External Observation Persistence Analysis
        ↓
Trade formula baseline
        ↓
Formula validation
        ↓
Chronological holdout
        ↓
Production adoption decision
```

The persistence analysis itself must also preserve chronological ordering and must not leak future observations into the T0 feature set.

## 9. Ground-truth hierarchy

When available, evidence is ranked:

```text
1. actual in-game market observation at the relevant time
2. timestamped historical market observation
3. external aggregated route/database presentation
4. theoretical route/profit calculation
```

Lower levels must not be represented as stronger evidence than higher levels.

**Binding conclusion:** EDpj shall empirically determine price persistence, profit-condition persistence, and time-to-material-price-decrease from the historical observations available to it before treating external Trade data as reliable enough for stronger recommendation claims.
