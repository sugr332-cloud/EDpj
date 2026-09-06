# EDpj Market / Trade Re-evaluation Decision

**Version:** 0.2  
**Status:** Binding Decision  
**Date:** 2026-09-06  
**Supersedes:** `docs/DECISION_MARKET_NOT_IMPLEMENTED_V0.1.md`

## 1. Decision

EDpj **reopens Market / station-to-station Trade for external-data feasibility and formula validation**.

The previous Market No-Go decision was based on a narrow EDpj persisted dataset containing observations from only two stations. That dataset was insufficient for cross-station Trade validation, but it is not sufficient evidence to conclude that Elite Dangerous Trade itself is unusable.

Trade therefore returns to the research/validation roadmap.

This decision does **not** authorize immediate production implementation. A new validation gate is required.

## 2. External market-data fact confirmed

Current external verification confirms that Elite Dangerous market services expose multi-station Buy/Sell data and use it to construct Trade Routes.

INARA currently exposes Trade Route records containing, among other fields:

- source station
- destination station
- commodity
- source Buy price
- source Supply
- destination Sell price
- destination Demand
- route distance
- observation/update age
- profit per unit
- profit per trip
- profit per hour

The current Trade Routes page also exposes a `Max. price age` filter and explicitly warns that markets are dynamic and that actual in-game prices should be checked.

This establishes that:

```text
broad external multi-station Buy/Sell data exists
```

It does **not** yet establish that the data is sufficiently complete, historical, reproducible, fresh, or legally/reuse-appropriate for EDpj.

## 3. Critical correction to the previous Market analysis

The previous analysis found:

```text
EDpj station 3221821952: 30 commodities
EDpj station 3789719552: 4 commodities
commodity intersection: 0
```

That finding remains correct for the EDpj dataset that was evaluated.

It must be interpreted only as:

> The EDpj dataset under test had insufficient station diversity and zero commodity overlap for constructing historical A→B Trade candidates.

It must **not** be interpreted as:

> Elite Dangerous has no station Buy/Sell data, no viable Trade routes, or no usable external market data.

The distinction is binding for all future analysis.

## 4. Required external-data feasibility audit

Before Trade implementation resumes, EDpj must evaluate at least one broad external market source and determine:

### 4.1 Coverage

Measure:

- number of stations
- number of systems
- number of commodities
- station×commodity observation count
- source Buy observations
- destination Sell observations
- commodity overlap across station pairs
- geographic coverage

### 4.2 Time coverage

Determine whether the source provides:

- observation timestamps
- update/received timestamps where available
- historical observations rather than only current snapshots
- sufficient history for chronological replay
- reproducible historical retrieval

### 4.3 Freshness

Measure the age distribution of observations and determine whether route candidates can be filtered by freshness.

Freshness must remain an explicit input to candidate confidence.

### 4.4 Trade candidate construction

Construct candidates as:

```text
Station A
  Buy commodity X
       ↓
  transport
       ↓
Station B
  Sell commodity X
```

Candidate-level economic inputs:

```text
source_buy_price
source_supply
destination_sell_price
destination_demand
cargo_quantity
observed_at / freshness
```

At minimum:

```text
profit_per_unit = destination_sell_price - source_buy_price
profit = profit_per_unit × executable_cargo_quantity
```

## 5. Historical validation requirement

The external dataset must be tested with leakage-safe chronological replay.

For each historical T0:

1. use only observations available at or before T0;
2. construct Trade candidates;
3. record the predicted route, commodity, Buy/Sell prices and expected profit;
4. observe later market data after T0;
5. measure whether the candidate remained economically valid.

The evaluation must distinguish:

- price persistence
- supply persistence
- demand persistence
- profit persistence
- route persistence

A route that was profitable only because a future observation was accidentally used at T0 is invalid evidence.

## 6. Transport-time limitation remains binding

External Trade-route sites may display `profit per hour`, but EDpj must not automatically treat that number as validated evidence.

EDpj must independently establish the inputs required for its own `profit_per_hour` calculation.

Until transport time is validated:

```text
profit
profit_per_unit
```

may be evaluated independently, while:

```text
profit_per_hour = unavailable
```

unless an explicitly validated action-horizon model exists.

Jump count, route distance, supercruise distance, and arbitrary fixed travel-time assumptions must not be silently substituted for measured transport time.

## 7. Source separation rule

The following datasets are distinct and must be labeled separately in code, documentation, tests, and analysis:

### Player data

The player's own Journal and EDpj-local observations represent personal observations/actions.

They must not be used as a statistical population representing all commanders or all stations.

### EDDN / population observations

EDDN observations represent shared external observations from participating clients.

They are population/external evidence and must not be described as the user's personal history.

### External trade databases

INARA and similar services are aggregated external datasets.

Their data provenance, update mechanism, historical retention, completeness, accuracy, licensing/reuse conditions, and reproducibility must be audited before EDpj depends on them.

### EDpj persisted data

EDpj's own database contains only the observations that EDpj actually ingested and retained.

The size or diversity of an external site must never be presented as if that data already exists inside EDpj.

## 8. Go / No-Go gate

Trade may proceed to productization only if the external-data validation demonstrates sufficient evidence for the intended product claims.

At minimum the gate must establish:

- broad multi-station coverage;
- sufficient commodity overlap;
- usable timestamp/history coverage;
- acceptable freshness behavior;
- leakage-safe replay;
- statistically meaningful route/profit persistence;
- a defensible candidate ranking method;
- explicit `INSUFFICIENT` behavior when evidence is inadequate.

Failure of any required evidence must result in `INSUFFICIENT` or `NO-GO` for that claim.

The absence of evidence in EDpj's old two-station cache is **not** itself a No-Go for the entire Trade domain.

## 9. Current status

```text
Old EDpj two-station dataset
        ↓
Trade validation: INSUFFICIENT
        ↓
Historical Market No-Go decision
        ↓
External multi-station market data confirmed
        ↓
Old No-Go superseded
        ↓
External-data feasibility audit
        ↓
Chronological Trade validation
        ↓
New Go / No-Go decision
```

## 10. External verification record

The current external verification used INARA's public Trade Routes pages.

Observed current records include multiple different source stations routing to the same destination with explicit source Buy/Supply and destination Sell/Demand values, together with route distance, update age, profit per unit, profit per trip, and profit per hour.

Reference:

- INARA Trade Routes: https://inara.cz/elite/market-traderoutes/

The external source itself states that its trade-route results are samples of profitable trades and warns that markets are dynamic and actual in-game prices should be checked.

**Binding conclusion:** external multi-station Trade data exists; EDpj must now evaluate whether that data can support a reproducible, leakage-safe, independently validated Trade recommendation system.
