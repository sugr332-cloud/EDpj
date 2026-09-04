# EDpj Implementation Specification

**Version:** 0.3  
**Status:** Implementation Baseline  
**Date:** 2026-09-04  
**Target Specification:** `SPECIFICATION_V0.5.md`

## 1. Purpose

本書は `SPECIFICATION_V0.4.md` を実装へ落とし込むための実装仕様書である。

原則として、仕様書にない機能を先行実装しない。CLIで取得・状態復元・較正・スコアリングを成立させ、その後UIを実装する。

最大の設計原則は **State Driven / Unified Scoring** である。Mining Anchor やユーザー指定の帰投先は実装しない。ただし、売却後に採掘状態へ戻るための通常の復路は状態から自動導出し、同一の行動サイクルとして評価する。

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
│   │   ├── yield_model.py
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

`yield.py` は Python の予約語と衝突するため使用しない。採掘期待量モデルは `yield_model.py` とする。

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

`Market.json` は **Docked イベントをトリガーとしてキャプチャする**。Market.json は次回のドックで上書きされ得るため、Docked 時点の内容を raw payload として保存し、`market_snapshots` に `source='journal'` として取り込む。EDDN由来の観測とは source を分離するが、同一テーブルで保持できるものとする。

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

**評価区分が0件の場合はPASSにしてはならず `INSUFFICIENT` とする。** bucket統合はfit側の件数だけで決めず、統合後にfit/eval双方の件数を検証する。evalが0件となる区分は `INSUFFICIENT` として扱い、全体PASSへすり替えない。

### 6.3 SC buckets

初期:

```text
0–100 ls
100–1,000 ls
1,000–10,000 ls
10,000–50,000 ls
50,000+ ls
```

20 samples未満の区分は隣接区分との統合候補とする。統合判断後、fit/eval双方にサンプルが存在することを確認する。evalが0件ならその区分の判定は `INSUFFICIENT`。統合結果と件数はmodel metadataへ保存する。

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

`systems` は `system_address`、座標、name、sourceを保持。

`bodies` は body type、sub type、arrival LS、gravity、radius、atmosphere、landable 等を保持する。リング情報を静的データとして利用する場合は `rings JSONB` を保持し、少なくとも ring type / inner radius / outer radius / composition 等を表現できる構造とする。

`stations` は station type、arrival LS、landing pad、Fleet Carrier、Vista Genomics 等を保持する。

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

`source` は少なくとも `eddn` / `journal` を区別する。

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
return_to_anchor DTO
anchor UI
configured round-trip score
```

ただし、**復路そのものは禁止しない**。`mining_sell` の評価では、売却後に次の採掘を再開する状態へ戻るための通常ルートを、直近の採掘状態から自動導出する。

## 8. State Detection

### 8.1 Mining

```python
has_mining_cargo = any(c.is_ore and c.qty > 0 for c in cargo)
```

`mining_active` はcargoの存在だけでは確定しない。

補助情報:

- recent `MiningRefined`
- recent Location at ring body
- current body is known ring

`last_ring_body_id` は直近の信頼できる `MiningRefined` / ring上Locationから導出する。`bodies.rings` が利用できない環境では「known ring」判定を静的ring情報だけに依存せず、直近 `MiningRefined` と位置履歴による判定へフォールバックする。

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

### 8.4 Return target derivation

`mining_sell` の終端を売却ステーション到着だけにしない。売却後の通常復路を状態から導出する。

```text
return_target =
  latest credible MiningRefined location's system/body
  → if unavailable, latest credible mining ring Location
  → if unavailable, no return target
```

これはDB設定項目ではなく、Journal/stateから毎回導出される一時的な計算結果である。

return targetを導出できる場合:

```text
mining_sell horizon
  = current → sell station
  + docking / market transaction
  + sell station → return_target
  + mining re-entry / positioning overhead
```

return targetを導出できない場合、`mining_sell` は除外せず `confidence` を低下させ、reasonに「採掘復帰先を導出できない」旨を明示する。実装では保守的な追加時間fallbackを適用してもよいが、ユーザー設定のAnchorを作ってはならない。

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
          + route(sell station, derived return target)
          + mining re-entry overhead
score_per_hour = value / horizon_hours
```

売却後の復路は、直近採掘状態から自動導出する。ユーザー指定のAnchorではない。

保有済み鉱石の取得コストは0とする。

### 10.3 Mining Continue

`Mining Continue` は満載した状態での販売価値を基準として評価する。現在cargo量をそのまま `r` に使って将来の追加採掘価値を過小評価してはならない。

```text
evaluation_cargo = expected cargo after one calibrated mining cycle
                    capped at cargo_capacity
```

`expected_effective_sell_price` の `r` は、少なくとも「満載時の評価cargo / demand」で算出する。複数commodityを扱う場合は、本人の過去実績から得た満載時のcommodity compositionを使う。

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

候補ringはbody static dataと本人の過去採掘実績から生成する。ライブyieldをSpansh static dataだけから推定したことにはしない。

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

候補生成にはPhase 1で購読・保存した `journal/1` と `fssbodysignals/1` の観測を利用する。市場EDDNだけでは本人未スキャンのbio候補を生成できないため、Phase 1のデータ収集要件に含める。

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
    target: dict | None
    expected_value: float
    action_horizon_seconds: float
    score_per_hour: float
    confidence: float
    reason: str
```

### 12.3 Confidence-aware selection

`confidence` を表示専用の属性にしてはならない。候補選択にも使用する。

初期実装では、最低confidence thresholdを設ける。

```python
MIN_ACTION_CONFIDENCE = 0.50
valid = [
    c for c in candidates
    if c.action_horizon_seconds > 0
    and c.confidence >= MIN_ACTION_CONFIDENCE
]
```

threshold未満しか存在しない場合は、低confidence候補を勝手にheroへ昇格させず、`next_action="none"` として reason に「候補はあるがconfidence不足」と返す。将来、下側信頼限界によるrankingへ変更する場合は仕様変更として明示する。

confidenceの目安:

```text
1.00  十分な本人実測 + 新鮮な市場/静的データ
0.75  十分なモデルだが一部fallback
0.50  最低限の観測、実績不足
<0.50 初期仮定 / sparse / target導出不能
```

候補ごとのconfidence計算は各scorerが担当し、Unified scorerはthresholdと順位だけを扱う。

### 12.4 Selection

```python
candidates = []
if mining_enabled:
    candidates += mining_scorer.generate(state)
if bio_enabled:
    candidates += bio_scorer.generate(state)

valid = [
    c for c in candidates
    if c.action_horizon_seconds > 0
    and c.confidence >= MIN_ACTION_CONFIDENCE
]

valid.sort(key=lambda c: c.score_per_hour, reverse=True)
hero = valid[0] if valid else None
alternatives = valid[1:]
```

同じ状態から実行可能な候補を比較する。特に `mining_sell` は売却後に採掘へ戻る通常復路をhorizonへ含めることで、`mining_continue` と異なる終端状態を理由に構造的に常勝しないようにする。

## 13. API

### 13.1 State

```text
GET /api/state
GET /api/state/ship
GET /api/state/cargo
```

### 13.2 Unified score

```text
POST /api/score/next-action
```

Request:

```json
{
  "state": {},
  "mining_enabled": true,
  "bio_enabled": true,
  "distance_limit_ly": 200
}
```

Responseは `target` と `alternatives` で同じ `ActionCandidate` 形状を使用する。

```json
{
  "next_action": "mining_sell",
  "target": {
    "action": "mining_sell",
    "station_id": 99999,
    "commodity": "platinum",
    "expected_value": 420000000,
    "action_horizon_seconds": 4200,
    "score_per_hour": 360000000,
    "confidence": 0.91,
    "reason": "現在地から販売、採掘復帰先までを含めて評価"
  },
  "alternatives": [
    {
      "action": "bio_next_system",
      "target": {"body_id": 123456},
      "expected_value": 120000000,
      "action_horizon_seconds": 4200,
      "score_per_hour": 102857142,
      "confidence": 0.82,
      "reason": "本人未スキャンのbio候補"
    }
  ]
}
```

候補が存在しない場合:

```json
{
  "next_action": "none",
  "target": null,
  "alternatives": [],
  "reason": "有効な候補行動がありません"
}
```

### 13.3 Other APIs

```text
GET /api/mining/candidates
GET /api/mining/multi
GET /api/bio/system/{system_address}
GET /api/bio/body/{body_id}
GET /api/bio/unsold
GET /api/calibration
POST /api/calibration/refit
GET /api/calibration/samples
WS /ws/state
```

廃止:

```text
GET /api/mining/anchor
PUT /api/mining/anchor
GET /api/mining/candidates/{id}
```

## 14. EDDN / External Data

Phase 1では以下を購読・保存する。

### 14.1 Market

市場観測を `market_snapshots` に保存し、`observed_at` と `received_at` を分離する。

### 14.2 Bio discovery support

Phase 3の本人未スキャン候補生成に必要なため、以下を購読・保存する。

```text
journal/1
fssbodysignals/1
```

観測はsourceとobserved_atを保持し、既存のbody/bio signalモデルへupsertする。

市場観測だけでbio候補が存在すると仮定しない。

## 15. Feedback / Teacher Data

### 15.1 Mining sell observation

売却時に以下を保存する。

```text
station_id
commodity_id
quantity
listed_price
actual_price
supply
 demand
observed_at
source
```

`penalty_ratio = actual_price / listed_price` を学習対象とする。

### 15.2 Listed price source

`listed_price` は売却直前の `Market.json` snapshotを優先する。Docked時点でMarket.jsonをraw保存しているため、次のドックによる上書きで教師データが失われない。

EDDNの市場観測だけを売却直前価格の正本として扱わない。

### 15.3 Effective price calibration

初期経験則をfallbackとし、本人の実測売却データが蓄積されたら区分ごとのpenalty modelを較正する。評価データをモデル選択へ混ぜない。

## 16. Phase Plan / Exit Criteria

### Phase 0-A

- Journal parser
- raw journal persistence
- Status/Cargo/Market reader
- Docked時Market snapshot
- state reducer
- backfill CLI
- duplicate handling

Exit:

- Journal fixtures pass
- Status/Cargo/Market fixtures pass
- Docked Market capture pass
- state reconstruction pass

### Phase 0-B

- jump timing
- SC timing with `FSDJump` and `SupercruiseEntry` starts
- event-sequence-based SC distance sample filtering
- dock/undock
- mining cycle
- bio timing
- route_plot collection

Exit:

- FSDJump-origin SC sample is extracted
- no fixed 120-second SC distance filter
- intervening FSDJump/SupercruiseEntry invalidates the preceding SC distance sample
- timing samples are session-safe

### Phase 0-C

- robust calibration
- 30h history target
- approximately 20 timing samples per required calibration where applicable
- chronological 70/30 fit/eval
- bucket merge
- insufficient-data status

Exit:

```text
median absolute error <= 20%
median signed error between -10% and +10%
R² diagnostic only
```

Any required eval segment with zero samples returns `INSUFFICIENT`, never implicit PASS.

### Phase 1

- EDDN market
- `journal/1`
- `fssbodysignals/1`
- static DB
- market_latest
- state API

Exit:

- fresh market observation available
- bio signal observation available
- state endpoint returns coherent state

### Phase 2 — Mining

- mining candidates
- effective price
- start/continue/sell
- derived mining return target
- confidence-aware selection
- feedback capture

Exit:

- 10 real sales captured
- effective price median error <= 10% where sample sufficiency permits
- sell horizon includes derived return leg
- continue price evaluation uses full-capacity / expected post-cycle cargo ratio
- no Anchor implementation

### Phase 3 — Bio

- current body
- next system
- return
- 10 landings / sample observations target
- time prediction median error <= 25%
- sold species FD exclusion

Exit:

-本人未スキャン候補が実データから生成できる
- FD確定と未売却を混同しない

### Phase 4 — UI

- hero action
- alternatives
- current state
- freshness
- confidence
- reason / horizon
- manual Mining/Bio mode toggle

No Anchor UI.

## 17. Tests

### Unit

- Journal UTC parsing
- duplicate `(file,line)` handling
- Status/Cargo/Market parsing
- Docked Market capture
- laden FSD range
- effective price boundary values
- full-capacity ratio for mining continue
- sparse SC bucket merge
- zero-eval => INSUFFICIENT
- session-safe split
- FSDJump-origin SC extraction
- event-sequence SC termination
- mining/bio state detection
- derived mining return target
- confidence threshold
- no candidate

### Integration

```text
Journal → state
Docked → Market snapshot → feedback
EDDN → market_latest
journal/1 + fssbodysignals/1 → bio signal
state → mining candidate
state → bio candidate
candidate → unified score
MarketSell → feedback
```

### Regression: forbidden features

以下が存在しないことを自動テストする。

```text
mining_anchor table
GET /api/mining/anchor
PUT /api/mining/anchor
return_to_anchor DTO
anchor UI
configured round-trip score
app/mining/yield.py
```

また、以下を回帰テストする。

- Mining Sellは`mining_active`を必須としない
- 売却候補はore cargoだけで生成可能
- Mining Sellは片道だけのhorizonを使用しない
- Mining Continueは現在cargo量だけでprice penaltyを計算しない
- confidence不足候補をheroにしない
- sold bio speciesにFD upsideを付与しない

## 18. Implementation Order

```text
1. Journal parser / raw persistence
2. Status/Cargo/Market reader
3. Docked Market snapshot
4. State reducer
5. Timing extraction (FSDJump-origin SC first)
6. Calibration + INSUFFICIENT handling
7. Static import + EDDN + journal/1 + fssbodysignals/1
8. Mining candidate/scorer
9. Bio candidate/scorer
10. Unified confidence-aware scorer
11. API
12. CLI verification
13. UI
```

各段階でCLIとテストを通してから次段階へ進む。

## 19. 用語の統一

UI表示・CLI出力では、Elite Dangerous のプレイヤーが実際に使う呼称をそのまま使う。日本語への言い換えはしない。

| UI/CLI表示 | コード識別子 |
|---|---|
| スーパークルーズ | `supercruise` |
| ホンク | `honk` |
| FSS | `fss` |
| DSS | `dss` |

補足表記のルール:

- ドキュメント本文で初出時のみ正式名称を併記してよい（例: FSS（全周波数システムスキャナ））。UI上では不要
- 所要時間の内訳バーなど幅の狭い箇所では `SC` への短縮を許可する。同一画面内で `スーパークルーズ` と `SC` を混在させないこと

## 20. 探索状態の管理

Journalから探索の進捗を復元し、候補の所要時間に反映する。

参照イベント:

| イベント | 意味 |
|---|---|
| `FSSDiscoveryScan` | 星系スキャン完了。`BodyCount` も取得 |
| `FSSAllBodiesFound` | その星系の天体スキャン完了 |
| `SAAScanComplete` | その天体のプローブ完了 |

```sql
CREATE TABLE system_discovery (
    system_address    BIGINT PRIMARY KEY,
    honked            BOOLEAN NOT NULL DEFAULT FALSE,
    body_count        INTEGER,
    all_bodies_found  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE body_discovery (
    body_id      BIGINT PRIMARY KEY,
    fss_scanned  BOOLEAN NOT NULL DEFAULT FALSE,
    dss_scanned  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Bio候補の horizon に未完了分を加算する:

```text
bio_horizon =
    route(現在地 → 目標星系)
  + honk_time              星系スキャン未完了なら
  + fss_time(body_count)   天体スキャン未完了なら
  + supercruise_time
  + dss_time               プローブ未完了なら
  + descent + sample + ascent
```

`fss_time` は天体数に比例するため、`FSSDiscoveryScan.BodyCount` を説明変数として `timing_samples` に追加し較正する。`honk` / `fss` / `dss` を `segment_type` に追加すること。

プローブ未完了の天体は着陸地点が確定しないため、UIに明示する。

## 21. ターゲットDTOの構造化

`ActionCandidate.target` を `dict` から構造化型に変更する。CLI出力とUIの両方がこの構造から生成される。

```python
class DiscoveryState:
    honked: bool
    fss_scanned: bool
    dss_scanned: bool

class BioTarget:
    body_name: str            # 表示用 例 "HIP 20277 A 5 a"
    system_name: str          # コピー用 例 "HIP 20277"
    body_suffix: str          # 現地探索用 例 "A 5 a"
    distance_ls: float
    gravity: float
    colony_spacing_m: int
    discovery: DiscoveryState
    time_breakdown: dict[str, float]
    predicted_species: list[SpeciesEstimate]

class MiningTarget:
    station_name: str
    system_name: str          # コピー用
    parent_body_name: str | None   # 惑星ポートの場合の親天体
    station_type: str
    distance_ls: float
    max_landing_pad: str
    demand: int
    cargo_demand_ratio: float
    listed_price: int
    effective_price: int
    time_breakdown: dict[str, float]
```

重要な制約:

- `system_name` は Journal の `StarSystem` フィールドから直接取得すること。`body_name` からの文字列分割で導出してはならない。`Col 285 Sector` 系や `Synuefe` 系は命名規則が異なり分割が破綻する
- `time_breakdown` は合計値ではなく内訳のまま返す。UIが内訳バーを描画するため

## 22. 到達可能性の判定

積載時ジャンプレンジで到達できない候補を生成段階で除外する。

```text
候補の各ジャンプ区間について:
  segment_distance > laden_jump_range → 候補から除外
```

判定不能な場合は除外せず confidence を下げる。

## 23. 惑星表面のナビゲーション（Phase 3）

`Status.json` の緯度・経度・機首方位を使い、惑星表面でのみ方位表示を提供する。宇宙空間では提供しない（ゲーム内HUDが誘導するため）。

提供する情報:

- 直近の `ScanOrganic` 採取地点から現在地までの距離。同一種で3サンプル取るには種ごとの規定距離（100m〜500m）以上離れる必要があるため
- `Touchdown` 地点（自船）までの距離と方位

提供**しない**情報:

- 生体コロニーの位置。プローブ後の惑星マップにのみ表示され、Journalに書き出されないため取得不可
- 星系マップの軌道配置。Spanshが持つのは到着星からの距離のみで、実際の軌道位置ではない。それらしい図を描くとゲーム内表示と一致せず混乱を招く

## 24. UI要件（Phase 4）

候補カードに以下を含める。

**コピー機能**
- コピー対象は `system_name` のみ。天体名やステーション名は銀河マップの検索欄で使えないため含めない
- コピー後は一時的なトーストではなく、その候補に「コピー済」状態を保持する。ゲームとの往復で見失わないため

**残り手順の表示**
- 星系スキャン / 天体スキャン / プローブ の3段階を、完了・未完了（加算時間付き）・これから の3状態で表示
- `FSDJump` 等のイベント受信時に自動で進行させる

**所要時間の内訳**
- 積み上げバーで表示。合計だけでなく各段階の内訳を出す
- 較正不足のモデルが含まれる場合はバッジを付ける

**相対比較**
- コロニー間隔は絶対値のみでは判断できないため、他属との比較で表示する
- 需要比率は 25% ラインと 80% ラインを引いた上に現在位置を示す

## 25. 制約（再掲）

- ゲームへの入力自動化を実装しない。読み取りと提案のみ
- Mining Anchor / ユーザー指定の帰投先を実装しない
- 取得できないデータを推定で埋めない。`NO_DATA` として扱う
- 推定値と実測値をDB・API・UIで区別する
