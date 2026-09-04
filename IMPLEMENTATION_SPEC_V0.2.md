# EDpj Implementation Specification

**Version:** 0.2  
**Status:** Implementation Baseline  
**Date:** 2026-09-04  
**Target Specification:** `SPECIFICATION_V0.4.md`

## 1. Purpose

本書は `SPECIFICATION_V0.4.md` を実装へ落とし込むための実装仕様書である。

原則として、仕様書にない機能を先行実装しない。CLIで取得・状態復元・較正・スコアリングを成立させ、その後UIを実装する。

最大の設計原則は **State Driven / Unified Scoring** である。Mining Anchor やユーザー指定の帰投先は実装しない。

## 2. Repository Structure

```text
EDpj/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db/
│   │   ├── session.py
│   │   ├── models/
│   │   └── migrations/
│   ├── collectors/
│   │   ├── journal_watcher.py
│   │   ├── state_files.py
│   │   ├── eddn.py
│   │   └── spansh.py
│   ├── journal/
│   │   ├── parser.py
│   │   ├── events.py
│   │   └── extractor.py
│   ├── calibration/
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── metrics.py
│   ├── state/
│   │   ├── reducer.py
│   │   └── detector.py
│   ├── routing/
│   │   ├── range.py
│   │   ├── route.py
│   │   └── time.py
│   ├── mining/
│   │   ├── state.py
│   │   ├── yield.py
│   │   ├── price.py
│   │   └── scorer.py
│   ├── bio/
│   │   ├── conditions.py
│   │   ├── value.py
│   │   └── scorer.py
│   ├── scoring/
│   │   ├── models.py
│   │   └── next_action.py
│   ├── api/
│   │   ├── state.py
│   │   ├── mining.py
│   │   ├── bio.py
│   │   ├── score.py
│   │   └── calibration.py
│   └── cli/
│       ├── backfill.py
│       ├── calibration.py
│       ├── mining.py
│       └── score.py
├── frontend/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── migrations/
├── scripts/
├── data/
├── pyproject.toml
├── docker-compose.yml
└── README.md
```

## 3. Runtime Model

常駐時:

```text
edpj.service
├── Journal Watcher
├── State File Watcher
├── EDDN Subscriber
└── API Server
```

初期開発では各機能をCLIから個別実行できることを優先する。

必須CLI:

```bash
edpj journal backfill --dir <journal_dir>
edpj calibration fit
edpj calibration status
edpj state show
edpj mining candidates
edpj score next-action
```

Phase 1以降:

```bash
edpj collector journal
edpj collector state
edpj collector eddn
edpj collector spansh
```

## 4. Phase 0-A — Journal + State Files

### 4.1 Journal parser

Elite Dangerous Journal JSON Linesを1行ずつ処理する。各行は独立JSONとして扱う。

Raw payload は変更せず `journal_events.payload` に保存する。

一意性:

```text
(file_name, line_number)
```

再処理しても重複しないこと。

Journal timestamp は UTC ISO8601 (`Z`) として解釈し、JSTへ変換してから保存・比較しない。

### 4.2 State files

Phase 0-Aで以下を読み取る。

- `Status.json`
- `Cargo.json`
- `Market.json`

読み取り専用。ファイルがない、不完全、一時的に読めない場合でもプロセス全体を停止せず `NO_DATA` / `STALE` として扱う。

### 4.3 State reducer

Journal と state files を統合して singleton `player_state` と `cargo_state` を更新する。

`GET /api/state` はDBに保持された最新の状態を返す。

### 4.4 Backfill

```bash
edpj journal backfill --dir <journal_dir>
```

完了時に以下を表示する。

```text
files scanned
lines scanned
inserted
skipped duplicate
invalid lines
first event
last event
```

## 5. Phase 0-B — Timing Extraction

### 5.1 General

```text
start event → end event = timing sample
```

不完全なペアはモデル学習に使用しない。

### 5.2 Segment types

最低限:

- `jump`
- `supercruise`
- `dock`
- `undock`
- `descent`
- `ascent`
- `bio_sample`
- `mining_cycle`
- `route_plot`

### 5.3 Supercruise

`SupercruiseEntry` → `SupercruiseExit` を基本区間とする。

距離は同一Journalから以下の順で復元する。

1. `Docked` 対象に関連付け可能な到着星情報
2. `Scan` の天体情報
3. `ApproachBody` と直前の `Scan`
4. 不明なら NULL

距離モデル採用条件:

```text
SupercruiseExit
  → 120秒以内
  → Docked または ApproachBody
```

条件を満たさないSCは時間統計には使えるが距離モデルfitには混ぜない。

Phase 0でSpansh body/station importは必須にしない。

### 5.4 Route plot

`NavRoute` は設定イベントに過ぎないため、過去経路を完全復元できることを前提にしない。

- Phase 0 Go/No-Go対象外
- `NavRouteClear` を成功サンプルにしない
- 完全な前方NavRouteだけ `route_plot` として保存
- 不足時の `detour_factor=1.15`
- 実測蓄積後に再較正

## 6. Phase 0-C — Calibration

### 6.1 Fit/eval

時系列昇順で70/30を基本とする。

```text
older 70%  → FIT
newer 30%  → EVAL
```

ランダム分割は禁止。同一sessionがfit/evalへ跨らないよう境界をsession単位で調整する。

evalデータはfit、bucket選択、パラメータ選択に使用しない。

### 6.2 Metrics

```text
absolute_error = abs(predicted - actual) / actual
signed_error   = (predicted - actual) / actual
```

保存:

- median_absolute_error
- median_signed_error
- sample_count_fit
- sample_count_eval
- R² (diagnostic)
- residual_stddev

Go/No-Go はeval側の誤差のみで判定する。

### 6.3 SC buckets

初期:

```text
0–100 ls
100–1,000 ls
1,000–10,000 ls
10,000–50,000 ls
50,000+ ls
```

20 samples未満の区分は隣接区分と統合する。統合結果はmodel metadataへ保存する。

### 6.4 Mining cycle calibration

`MiningRefined` の連続イベントから採掘サイクル時間を推定する。

外れ値に強い median / trimmed statistics を初期モデルとする。最低20サンプルを目安とし、不足時は confidence を下げる。

## 7. Database

### 7.1 Static tables

```sql
systems
bodies
stations
commodities
```

`systems` は `system_address`、座標、name、source を保持。

`bodies` は body type、sub type、arrival LS、gravity、radius、atmosphere、landable 等を保持。

`stations` は station type、arrival LS、landing pad、Fleet Carrier、Vista Genomics 等を保持。

### 7.2 Market

`market_snapshots`:

```text
station_id
commodity_id
buy_price
sell_price
supply
demand
observed_at
received_at
source
```

`market_latest` は `(station_id, commodity_id)` の最新 `observed_at` を保持する normal table とする。MVPではmaterialized view refreshに依存せず upsert する。

`station_activity` は1h/6h/24h observationsとlast_observed_atを保持する。

Snapshots retention は約3日。

### 7.3 Player state

`player_state` singleton:

```text
current_system
current_body_id
current_station_id
current_ship_id
credits
fuel_main
cargo_tons
docked
landed
on_foot
updated_at
```

`cargo_state`:

```text
commodity_id
quantity
updated_at
```

### 7.4 Mining Anchor禁止

以下のDDL/API/UIを実装してはならない。

```text
mining_anchor
GET /api/mining/anchor
PUT /api/mining/anchor
return_to_anchor
anchor UI
```

## 8. State Detection

### 8.1 Mining

```python
has_mining_cargo = any(c.is_ore and c.qty > 0 for c in cargo)
```

`mining_active` は cargo の存在だけでは確定しない。

補助情報:

- recent `MiningRefined`
- recent Location at ring body
- current body is known ring

### 8.2 Bio

保持:

```text
has_bio_signals
current_body_scanned_by_user
unsold_bio_value
nearest_vista_station
```

本人未スキャンを候補条件とし、「銀河全体で未探索」とは解釈しない。

### 8.3 Candidate generation

Mining:

```text
ore cargo > 0 → mining_sell
mining_active → mining_continue
no ore → mining_start
```

Bio:

```text
current body has bio signal → bio_current_body
nearby unscanned bio candidate → bio_next_system
unsold bio data → bio_return
```

## 9. Routing / Time Service

### 9.1 FSD range

`Loadout.MaxJumpRange` をladen rangeとして直接使用しない。

FSD module の optimal mass / total mass / fuel limit / engineering等から質量依存成分を計算し、Guardian FSD Booster等の加算を分離する。

単体テストで空荷と積載時のレンジが区別されることを確認する。

### 9.2 Route time

route plannerは汎用交易ルーターではなく、score候補の時間評価に必要な最小機能だけを提供する。

```text
current location → target system/body/station
```

jump time、SC time、dock time等のcalibration modelを組み合わせる。

`route_plot` 実測が不足する間は `detour_factor=1.15` を使用する。

## 10. Mining Scoring

### 10.1 Effective price

```text
r = cargo / demand
```

```text
r <= 0.25        penalty = 1.00
0.25 < r < 0.80  linear 1.00 → 0.45
r >= 0.80        penalty = 0.45
```

```text
effective_price = listed_price × penalty
```

需要0以下は候補除外。

### 10.2 Mining Sell

```text
value = Σ(quantity × effective_price)
horizon = route(current location, sell station)
          + docking / market transaction
score_per_hour = value / horizon_hours
```

保有済み鉱石の取得コストは0とする。

### 10.3 Mining Continue

```text
expected_value
 = expected_mined_quantity × expected_effective_sell_price
horizon = calibrated mining cycle
```

採掘期待量・売却価格は本人の過去実績を優先し、サンプル不足時は低confidenceにする。

### 10.4 Mining Start

```text
horizon = route(current location, mining ring)
          + mining cycle
```

候補ringはbody static dataと本人の過去採掘実績から生成する。

## 11. Bio Scoring

### 11.1 Base value

speciesごとの期待値:

```text
expected_value_base = Σ p(s) × base_value(s)
```

FD upside:

```text
expected_value_best = Σ p(s) × base_value(s) × fd_multiplier
```

base valueをランキング正本とし、bestは参考値とする。

### 11.2 Current body

```text
horizon = descent / landing / walk / sample
value = expected bio value
```

gravity、walk distance、surface condition等をcalibrationへ渡す。

### 11.3 Next system

```text
horizon = route(current location, candidate body)
          + bio investigation time
```

本人未スキャン候補のみ。

### 11.4 Return

```text
horizon = route(current location, nearest Vista Genomics)
          + docking / transaction
value = unsold bio value
```

Anchor概念は使用しない。

## 12. Unified Next Action

### 12.1 Input DTO

```python
class NextActionRequest:
    state: PlayerStateDTO
    mining_enabled: bool = True
    bio_enabled: bool = True
    distance_limit_ly: float = 200
```

### 12.2 Candidate DTO

```python
class ActionCandidate:
    action: str
    target: dict
    expected_value: float
    action_horizon_seconds: float
    score_per_hour: float
    confidence: float
    reason: str
```

### 12.3 Selection

```python
candidates = []
if mining_enabled:
    candidates += mining_scorer.generate(state)
if bio_enabled:
    candidates += bio_scorer.generate(state)

valid = [c for c in candidates if c.action_horizon_seconds > 0]
hero = max(valid, key=lambda c: c.score_per_hour, default=None)
```

`hero` が最終的な `next_action` となる。

### 12.4 API

```text
POST /api/score/next-action
```

Response:

```json
{
  "next_action": "mining_sell",
  "target": {
    "station_id": 99999,
    "commodity": "platinum",
    "score_per_hour": 304000000,
    "action_horizon_seconds": 1860,
    "reason": "現在地から販売まで31分、需要に対して十分な余裕"
  },
  "alternatives": [
    {"action": "bio_next_system", "score_per_hour": 103000000},
    {"action": "mining_continue", "score_per_hour": 82000000}
  ]
}
```

候補なし:

```json
{
  "next_action": "none",
  "target": null,
  "alternatives": [],
  "reason": "有効な候補行動がありません"
}
```

## 13. EDDN

ZeroMQ subscriberを実装する。

市場観測では:

- `observed_at` = EDDN payloadの観測時刻
- `received_at` = local receive time

を分離する。

stale 判定は `observed_at`、activity は観測件数で別計算する。

## 14. Feedback

### Mining Sell

Journal `MarketSell` と直前 market observation を対応付ける。

一致しない場合:

```text
matched = false
```

とし、無理な推定値で学習しない。

10件以上の実売却を目標に effective price model を検証する。

### Bio

`ScanOrganic` / `SellOrganicData` を本人の行動履歴として保存する。売却済みspeciesはFD upside候補から除外する。

## 15. Phase Plan / Exit Criteria

### Phase 0-A

- Journal parser
- Raw event persistence
- Status/Cargo/Market parser
- State reducer
- backfill CLI

### Phase 0-B

- jump / SC / dock / undock extraction
- mining cycle extraction
- SC distance recovery
- incomplete pair rejection

### Phase 0-C

- robust calibration
- chronological 70/30 holdout
- session boundary protection
- SC bucket merge
- metrics output

Go/No-Go目標:

- 30h以上のJournal
- jump/SC/dock 等20 samples以上を目安
- eval median absolute error ≤20%
- median signed error ±10%
- R²は診断のみ

### Phase 1

- EDDN
- static data
- market_latest upsert
- state integration

### Phase 2 Mining

- candidate generation
- effective price
- mining sell score
- mining continue/start score
- actual feedback
- 10 real sales
- effective price prediction median error ≤10%目標
- Anchor依存ゼロ

### Phase 3 Bio

- current body / next system / return
- 10 real landing/sample observations
- time prediction median error ≤25%目標
- sold species exclusion

### Phase 4 UI

- hero action
- alternatives
- current state
- freshness
- confidence
- reason / estimated time
- manual Mining-only / Bio-only toggle
- Anchor UIなし

## 16. Test Requirements

### Unit

- Journal UTC parsing
- duplicate `(file,line)` handling
- Status/Cargo/Market parsing
- laden FSD range
- effective price boundaries
- sparse SC bucket merge
- session-safe 70/30 split
- mining state detection
- bio state detection
- score selection
- no-candidate behavior

### Integration

- Journal backfill → state
- EDDN → market_latest
- state → candidate generation
- candidate → unified score
- MarketSell → feedback

### Regression

- Anchor table is absent
- Anchor API is absent
- `return_to_anchor` is absent
- no scoring path calculates a configured round trip
- Mining Sell with ore cargo does not require `mining_active`
- bio sold data cannot create FD upside

## 17. Implementation Rules

1. CLI-firstで成立させる。
2. 仕様にない機能を先行実装しない。
3. 実測値と推定値をDB/APIで区別する。
4. EDDNのfreshnessとactivityを混同しない。
5. route plotをFSD rangeと混同しない。
6. evalデータをfitへ漏らさない。
7. 不確実なFirst Discoveryを確定値として扱わない。
8. Mining Anchor / 帰投先指定を実装しない。
9. 最終的なhero actionの選択はfrontendではなくbackend scoring serviceで行う。
10. すべての提案はユーザーの手動操作を前提とする。
