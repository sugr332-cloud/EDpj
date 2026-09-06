# EDpj Specification — Trade Scope Amendment

**Version:** 0.2  
**Status:** Binding Specification Amendment  
**Date:** 2026-09-06  
**Supersedes:** `SPECIFICATION_V0.4.md` v0.7 sections that exclude generic A→B commodity trading  
**Revised by:** external multi-station market-data verification; previous Market No-Go decision is superseded by `DECISION_MARKET_REEVALUATION_V0.2.md`

## 1. Purpose

EDpj's purpose is to select the next action with the highest expected credit efficiency from the current Elite Dangerous game state.

**Station-to-station commodity Trade is a first-class EDpj money-making activity.** It must be evaluated alongside Mining and Exobiology.

The previous specification's statement below is therefore removed as a product non-goal:

```text
汎用A→B交易ルート検索を作らない
```

EDpj shall support commodity Trade candidate generation and evaluation.

## 2. Trade definition — binding

EDpj's Trade means **ordinary Commodities Market trading between NPC/station markets**:

```text
Station A
  ↓
NPC/station Commodities Market: Buy price
  ↓
Player purchases commodity and carries it as cargo
  ↓
Station B
  ↓
NPC/station Commodities Market: Sell price
  ↓
Player sells the commodity to the station
```

The two prices have the following exact semantic meaning:

- **Buy price:** the price the commander pays when buying the commodity from the station's Commodities Market. In market-data terminology this is the station's `Buy` price / available `Supply`.
- **Sell price:** the price the commander receives when selling the commodity to the station's Commodities Market. In market-data terminology this is the station's `Sell` price / available `Demand`.

This is **not** player-to-player trading and is **not** a Fleet Carrier owner order model. Fleet Carrier player orders are outside the MVP Trade definition.

## 3. Trade candidate

A Trade candidate represents:

```text
current state
  → source station A
  → buy commodity X
  → transport X
  → destination station B
  → sell commodity X
```

Minimum economic inputs:

- commodity
- source station
- destination station
- source `Buy` price
- source supply
- destination `Sell` price
- destination demand
- cargo capacity / planned cargo quantity
- market observation timestamp / freshness

Basic gross trading value:

```text
profit_per_unit = sell_price - buy_price
profit = profit_per_unit × cargo_quantity
```

The candidate must not be considered profitable when `profit_per_unit <= 0`.

Supply and demand are constraints/quality indicators, not interchangeable with price. A stale or insufficient market observation must reduce confidence or invalidate the candidate according to the market-freshness gate.

## 4. Trade and Mining are separate models

Trade must never be implemented as a variant of Mining Sell.

### Mining Sell

```text
ore was obtained by mining
→ player holds mined ore
→ station buys the mined ore
```

### Trade

```text
player purchases commodity from station A
→ transports purchased commodity
→ sells purchased commodity to station B
```

Therefore:

- Mining's `MarketSell` / `MiningRefined` player Journal history is **not** the Trade validation dataset.
- Trade validation may use historical station market observations, including EDDN observations, even when the player's own Journal contains zero `MarketSell` events.
- `MarketSell=0` in the player's Journal means only that no player sale history is available; it does **not** mean that historical Trade market data is unavailable.

## 5. Action horizon constraint — critical

EDpj must **not invent or fabricate transport time**.

The current EDpj data set does not provide sufficient historical data to reliably measure actual station-to-station Trade travel time. Therefore:

- jump count is not treated as travel time;
- route distance is not treated as travel time;
- supercruise distance is not treated as travel time;
- a global median travel time is not treated as a candidate-specific travel time;
- theoretical `Cr/h` must not be presented as measured `Cr/h` when the required transport-time component is unavailable.

When Trade action horizon is unavailable, the implementation must represent it explicitly as `unavailable` and must not silently substitute an arbitrary duration.

Trade profit and profit-per-unit may still be evaluated independently of `Cr/h` when sufficient market data exists.

## 6. Trade score

The unified EDpj score remains:

```text
score_per_hour = expected_action_value / action_horizon_hours
```

For Trade, `action_horizon_hours` is only valid when the required time components are actually measurable or validated by an explicitly approved model.

Until such a model is validated:

```text
expected_trade_profit =
    (destination Sell price - source Buy price)
    × executable cargo quantity
```

but:

```text
trade_score_per_hour = unavailable
```

if the transport-time component is unavailable.

This is intentional. EDpj must distinguish **high monetary margin** from **validated high credits/hour**.

## 7. Trade market data

Trade candidates may use:

- `Market.json` snapshots at the player's current/docked station;
- EDDN station-market observations for other stations;
- existing `market_snapshots` storage with `source='journal'` or `source='eddn'`;
- external aggregated market/trade databases such as INARA, subject to the external-source audit in §8;
- `observed_at` and `received_at` for freshness evaluation.

EDDN is an observation-sharing network, not an authoritative live market feed. Freshness must therefore remain part of candidate confidence.

External trade databases are also not authoritative merely because they expose a route. Their provenance, freshness, historical retention, completeness, reproducibility, and reuse conditions must be evaluated before EDpj treats them as a validation source.

The specification must not assume that an externally displayed route remains executable when the player arrives.

## 8. External multi-station market data — binding correction

The previous Market investigation was performed against the market observations actually persisted in EDpj at that time. That dataset contained only two represented stations for the relevant Trade analysis:

```text
station 3221821952: 30 commodities
station 3789719552: 4 commodities
intersection: 0 commodities
```

That result is valid only for the EDpj dataset under test.

It is **not** evidence that Elite Dangerous lacks broad station Buy/Sell data or viable A→B Trade routes.

External verification has confirmed that public Elite Dangerous market services expose broad multi-station Trade data. Current INARA Trade Routes, for example, contain multiple different source stations routing to destination stations with explicit:

- source `Buy price`
- source `Supply`
- destination `Sell price`
- destination `Demand`
- route distance
- update/observation age
- profit per unit
- profit per trip
- profit per hour

INARA also exposes a `Max. price age` filter and warns that markets are dynamic and actual in-game prices should be checked.

Therefore the binding distinction is:

```text
EDpj persisted dataset
    ≠
external Elite Dangerous market data
```

and:

```text
EDpj had only two stations in the evaluated cache
    ≠
Elite Dangerous has only two usable market stations
```

### 8.1 Required external-source audit

Before external data is used for product claims, EDpj must evaluate:

1. **Coverage** — station count, system count, commodity count, station×commodity observations, and geographic coverage.
2. **Station diversity** — number of distinct stations and systems represented.
3. **Commodity overlap** — number of viable A/B station pairs sharing commodities.
4. **Historical depth** — whether timestamped historical observations are available rather than only current snapshots.
5. **Freshness** — distribution of observation age and whether stale routes can be filtered.
6. **Provenance** — how observations enter the external database.
7. **Reproducibility** — whether historical observations can be retrieved and replayed deterministically.
8. **Reuse conditions** — whether the source data may be retained, transformed, and used by EDpj under the applicable source terms/licensing conditions.
9. **Accuracy** — whether Buy/Sell/Supply/Demand observations are sufficiently reliable for EDpj's intended claims.

No external route result may be treated as EDpj-owned historical evidence until it has passed the applicable ingestion and validation rules.

## 9. Source separation rule

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

## 10. Validation requirement

Trade formula adoption is subject to the existing Formula Validation Gate.

The validation dataset must be based on historical market observations and must not depend on the player's own `MarketSell` history.

Minimum validation variables:

- source Buy price
- source supply
- destination Sell price
- destination demand
- market observation freshness
- executable cargo quantity
- observed future market state
- realized/validated profit where the historical data permits it

The existing 60% accuracy gate and chronological holdout requirements remain binding.

Insufficient historical evidence must produce:

```text
INSUFFICIENT
```

and must never be converted into PASS by assumption.

## 11. Product scope after this amendment

```text
EDpj
├─ Mining
│  ├─ Mining Start
│  ├─ Mining Continue
│  └─ Mining Sell
├─ Exobiology
│  ├─ Bio Current
│  ├─ Bio Next
│  └─ Bio Return
└─ Trade
   ├─ Buy at Station A
   ├─ Transport to Station B
   └─ Sell at Station B
```

All three domains are candidates for the unified next-action system.

However, **Trade is not allowed to claim a validated Cr/h advantage merely from price spread**. The system must keep `profit`, `profit_per_unit`, and `profit_per_hour` semantically separate.

## 12. External verification record

The following external verification was performed on 2026-09-06:

- INARA Trade Routes: `https://inara.cz/elite/market-traderoutes/`
- Current route records were observed with multiple source stations, Buy/Supply, destination Sell/Demand, route distance, update age, and calculated profit fields.
- INARA's own page warns that its trade-route results are samples and that market conditions are dynamic; actual in-game prices should be checked.

**Conclusion:** external multi-station Buy/Sell market data exists. The EDpj two-station dataset was a local evidence limitation and must not be generalized into a game-wide Market/Trade limitation. Trade therefore remains an active validation domain, subject to the external-data feasibility audit and Formula Validation Gate.
