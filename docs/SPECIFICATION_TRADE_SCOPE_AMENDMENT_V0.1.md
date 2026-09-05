# EDpj Specification — Trade Scope Amendment

**Version:** 0.1  
**Status:** Binding Specification Amendment  
**Date:** 2026-09-06  
**Supersedes:** `SPECIFICATION_V0.4.md` v0.7 sections that exclude generic A→B commodity trading  

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
Player sells commodity to the station
```

The two prices have the following exact semantic meaning:

- **Buy price:** the price the commander pays when buying the commodity from the station's Commodities Market. In market-data terminology this is the station's `Buy` price / available `Supply`.
- **Sell price:** the price the commander receives when selling the commodity to the station's Commodities Market. In market-data terminology this is the station's `Sell` price / available `Demand`.

This is **not** player-to-player trading and is **not** a Fleet Carrier owner order model. Fleet Carrier player orders are outside the MVP Trade definition.

External game references confirm this interpretation. Elite Dangerous commodity-market documentation describes commodities as being bought and sold at stations and describes trading as purchasing commodities at a low price and selling them at a higher price. Current INARA station-market data likewise exposes separate `Buy / Supply` and `Sell / Demand` values and its Trade Routes explicitly pair a station `Buy` price with a destination station `Sell` price. citeturn2search0turn2search1turn0search0

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
- `observed_at` and `received_at` for freshness evaluation.

EDDN is an observation-sharing network, not an authoritative live market feed. Freshness must therefore remain part of candidate confidence.

The specification must not assume that an externally displayed route remains executable when the player arrives.

## 8. Validation requirement

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

## 9. Product scope after this amendment

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

## 10. External verification record

The following external game references were checked before adopting this definition:

1. Elite Dangerous Wiki — Commodities: station Commodities Markets allow commanders to buy and sell commodities; trading is described as buying low and selling higher. citeturn2search0
2. Elite Dangerous Wiki — Market Economy: stations have their own supply/demand and commanders trade by buying low and selling high. citeturn2search1
3. Elite Dangerous Wiki — Trader: Trader is defined around purchasing commodities in one location and selling them at another lucrative market for profit. citeturn2search3
4. INARA current station-market data: station markets expose separate `Sell / Demand` and `Buy / Supply` values, matching the semantic definition above. citeturn0search0turn0search3
5. INARA current Trade Routes: route records explicitly show source `Buy price`/`Supply` and destination `Sell price`/`Demand`, with profit per unit calculated from that spread. citeturn0search1turn0search5

**Conclusion:** The EDpj Trade definition is confirmed as ordinary NPC/station Commodities Market buy-low → transport → sell-high trading. The Buy/Sell semantics above are the binding meanings to use in EDpj.
