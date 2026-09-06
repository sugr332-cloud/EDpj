# EDpj Market Implementation Decision

**Version:** 0.1  
**Status:** Superseded  
**Date:** 2026-09-06  
**Superseded by:** `docs/DECISION_MARKET_REEVALUATION_V0.2.md`

## 1. Historical decision

EDpj previously decided not to implement Market as a standalone product/recommendation feature.

That decision was based on the **then-current EDpj persisted market dataset**, not on an exhaustive investigation of all external Elite Dangerous market-data sources.

## 2. Evidence that supported the historical decision

The Trade market-data investigation was performed against the market observations actually available in EDpj at the time.

The latest real-data backfill populated:

- `buy_price`: 0 NULL rows
- `supply`: populated
- `received_at`: 0 NULL rows
- observations: 1,784 → 2,496

However, the real Trade profit-condition analysis remained `INSUFFICIENT` because the two stations represented in that EDpj dataset had **zero common commodities**:

- station `3221821952`: 30 commodities
- station `3789719552`: 4 commodities
- intersection: 0 commodities

Therefore no real `source Buy → destination Sell` Trade route could be constructed **from that EDpj station set**.

That result was valid as a statement about the dataset under test.

## 3. Why the historical conclusion is now superseded

The historical decision must **not** be interpreted as evidence that Elite Dangerous station-to-station Trade is inherently unusable, or that broad Buy/Sell market data does not exist.

External verification has since confirmed that public Elite Dangerous market services provide multi-station market observations and construct Trade Routes from source-station `Buy / Supply` and destination-station `Sell / Demand` data.

For example, current INARA Trade Routes contain multiple different source stations routing to the same destination station, with explicit Buy price, Supply, Sell price, Demand, route distance, freshness/update time, profit per unit, profit per trip, and profit per hour fields. INARA also provides a `Max. price age` filter and explicitly warns that market conditions are dynamic and should be checked in-game.

Therefore:

```text
EDpj current dataset at the time of Phase 2-6F
    ≠
all available Elite Dangerous market data
```

The previous two-station limitation is a **dataset coverage limitation**, not a game-wide Trade limitation.

## 4. Correct interpretation of the previous analysis

The following statement remains valid:

> The EDpj dataset then available was insufficient to validate cross-station Trade profitability because its observed station set had zero commodity overlap.

The following statements are **invalid and must not be used**:

- Elite Dangerous Trade is not useful.
- Elite Dangerous lacks station Buy/Sell data.
- Trade cannot be evaluated because Buy and Sell prices are unavailable in external data.
- Two EDpj stations with zero overlap demonstrate that broad Trade-route analysis is impossible.
- The absence of player `MarketSell` Journal events demonstrates that Trade market data is unavailable.

## 5. New decision

The Market/Trade domain is **reopened for external-data feasibility and validation research**.

This does **not** mean that Trade is already validated for production use.

The next evaluation must determine whether external market sources provide sufficient historical, multi-station, timestamped Buy/Sell observations for EDpj to independently validate:

- source Buy price
- source supply
- destination Sell price
- destination demand
- freshness
- station diversity
- commodity overlap
- historical route profitability
- persistence of route profitability
- leakage-safe chronological replay

Only after this external-data evaluation may EDpj make a new Go/No-Go decision for Trade productization.

## 6. Binding data-source distinction

All future Market/Trade analysis must explicitly identify which dataset is being used:

| Dataset | Meaning |
|---|---|
| Player Journal / EDpj personal data | Evidence of the player's own observed actions and local market observations |
| EDPN/EDDN observations | Population-shared station market observations; external observational dataset |
| INARA or other external trade database | Aggregated external market/trade data; must be evaluated for provenance, freshness, history, and reuse suitability |
| EDpj persisted market DB | The subset of market observations actually ingested and retained by EDpj |

These datasets must never be silently combined or treated as interchangeable.

In particular:

```text
EDpj has 2 stations
```

must never be generalized to:

```text
Elite Dangerous has only 2 stations worth of market data.
```

## 7. Productization gate

Trade remains subject to the existing Formula Validation Gate and chronological holdout requirements.

Insufficient evidence must remain:

```text
INSUFFICIENT
```

and must not be converted into PASS by assumption.

The existing Trade specification remains binding regarding the distinction between:

```text
profit / profit_per_unit / profit_per_hour
```

and regarding the prohibition against inventing transport time.

## 8. Historical artifacts

The following research artifacts remain valid as historical analysis of the EDpj dataset available at the time:

- `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`
- `docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md`
- `docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md`
- `docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md`
- `docs/PHASE_2_6F_T2_LARGE_PRICE_MOVEMENT_CHARACTERIZATION_DESIGN_BASELINE_V0.1.md`
- `docs/PHASE_2_6F_T3_TRADE_WINDOW_PERSISTENCE_DESIGN_BASELINE_V0.1.md`
- `docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`

The latest backfill outcome was recorded in commit `e64176b`.

**Historical conclusion:** insufficient evidence in the EDpj two-station dataset.

**Current conclusion:** Trade must be re-evaluated using broad external multi-station market data before any productization decision is made.
