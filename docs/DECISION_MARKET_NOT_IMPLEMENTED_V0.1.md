# EDpj Market Implementation Decision

**Version:** 0.1  
**Status:** Binding Decision  
**Date:** 2026-09-06

## 1. Decision

EDpj will **not implement Market as a standalone product/recommendation feature**.

The Market-related investigation is retained as research/evidence work, but its current real-data evidence does not provide sufficient practical utility to justify product implementation.

The project therefore moves the active development focus to **Exobiology (Bio)**.

## 2. Evidence supporting the decision

The Trade market-data investigation was completed through the current persistence and large-price-movement analysis.

The latest real-data backfill successfully populated:

- `buy_price`: 0 NULL rows
- `supply`: populated
- `received_at`: 0 NULL rows
- observations: 1,784 → 2,496

However, the actual Trade profit-condition analysis remained `INSUFFICIENT` because the two stations currently represented in the real dataset have **zero common commodities**:

- station `3221821952`: 30 commodities
- station `3789719552`: 4 commodities
- intersection: 0 commodities

Therefore no real `source Buy → destination Sell` Trade route can currently be constructed from the observed station set.

The limitation is structural station coverage, not merely missing Buy-price data or insufficient observation volume.

## 3. Practicality conclusion

The Market investigation produced useful diagnostic evidence about observed price behavior, including persistence and large price movements, but the current evidence cannot support a sufficiently reliable and broadly applicable production recommendation system.

In particular:

- Trade profit-condition persistence cannot currently be measured from the available cross-station commodity overlap.
- Current market evidence is heavily concentrated in a very small number of stations.
- The observed evidence therefore does not justify implementing Market as a production decision domain at this stage.
- Additional station observations may improve the evidence later, but EDpj will not block the main development roadmap waiting for that condition.

## 4. Scope boundary

This decision means **do not productize the Market analysis**. It does not delete the existing historical-analysis code, test suite, or stored research conclusions.

Existing Market/Trade research artifacts remain available for future re-evaluation if substantially better real-data coverage becomes available.

This decision also does not alter the binding definition of ordinary station-to-station Trade itself. It records that the currently investigated Market evidence is **not sufficiently useful to justify implementing Market as an active product feature**.

## 5. Development transition

The active development target after this decision is:

```text
Market investigation
    ↓
Practicality judged insufficient for product implementation
    ↓
Record evidence and stop productization
    ↓
Move to Bio / Exobiology
```

Bio work must continue to follow the existing Bio specifications and Formula Validation requirements, including explicit `INSUFFICIENT` classification where real evidence is inadequate.

## 6. Source records

This decision is based on the completed Trade market-data work, including:

- `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`
- `docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md`
- `docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md`
- `docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md`
- `docs/PHASE_2_6F_T2_LARGE_PRICE_MOVEMENT_CHARACTERIZATION_DESIGN_BASELINE_V0.1.md`
- `docs/PHASE_2_6F_T3_TRADE_WINDOW_PERSISTENCE_DESIGN_BASELINE_V0.1.md`
- `docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`

The latest backfill outcome was recorded in commit `e64176b`.
