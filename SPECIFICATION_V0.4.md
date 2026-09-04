# EDpj Specification

**Version:** 0.4  
**Status:** Canonical Implementation Baseline  
**Date:** 2026-09-04  
**Previous:** `SPECIFICATION_V0.3.md`

## 1. 目的

Elite Dangerous において、現在のゲーム状態から「次に何をすれば最も時間あたりの期待クレジットが高いか」を算出する。

対象金策は以下に限定する。

- **Mining** — 採掘を継続する、採掘を開始する、または保有鉱石を売却する
- **Exobiology** — 現在天体で生体活動を続ける、次の候補天体へ移動する、または未売却データを売却する

本バージョンの中心原則は **State Driven** である。ユーザーが「帰投先」「Mining Anchor」を指定して次の行動を固定する方式は採用しない。

## 2. 設計原則

### 2.1 現在状態が唯一の基準

Journal / Status.json / Cargo.json 等から得た現在状態を正本とし、その時点で実行可能な候補を生成する。

### 2.2 次の一手を1つだけ選ぶ

Mining と Exobiology の候補を同じスコア体系で比較し、最も高い候補を `hero` / `next_action` とする。

### 2.3 Anchor / 帰投先指定を廃止

以下は v0.4 に存在しない。

- `mining_anchor` テーブル
- Mining Anchor の自動設定・手動設定
- Anchor UI
- Anchor API
- `return_to_anchor` DTO
- 売却後に Anchor へ戻ることを前提とした round-trip score

必要な帰路がある場合でも、それは現在状態から次の候補行動を成立させるための通常のルートとしてモデル化する。

### 2.4 実測時間を優先

移動、スーパークルーズ、ドッキング、採掘サイクル、生体サンプル等は可能な範囲で Journal から実測し、較正モデルを利用する。

## 3. 非目標 / 規約上の制約

- ゲーム入力の自動化をしない
- メモリ読み書きをしない
- Journal / Status / Cargo / Market は読み取り専用
- 汎用A→B交易ルート検索を作らない
- 価格・需要の将来予測をしない
- ミッション支援をしない
- 銀河全体の市場DBを長期維持しない
- 他プレイヤー向け公開サービスを作らない

## 4. 全体アーキテクチャ

```text
Elite Dangerous
   │
   ├─ Journal / Status / Cargo / Market
   │
   ▼
State Collector ───────┐
Journal Watcher ────────┼──► PostgreSQL
EDDN Subscriber ────────┤        │
Spansh Importer ────────┘        ├─ Calibration
                                  ├─ State Detection
                                  └─ Unified Scoring
                                         │
                                      FastAPI
                                         │
                                  React / WebSocket
```

## 5. データソース

| ソース | 用途 |
|---|---|
| Journal | 位置、移動、採掘、生体、売却、実測時間、発見状況 |
| Status.json | 現在位置、状態、Flags/Flags2、燃料等 |
| Cargo.json | commodity別積荷 |
| Market.json | 現在ステーション市場 |
| EDDN | 他ステーションの市場観測 |
| Spansh dumps | システム・天体・ステーション等の静的情報 |

EDDN は観測共有ネットワークであり権威的な現在値ではない。`observed_at` と `received_at` を保持し、freshness と activity を分離する。

## 6. 状態モデル

`GET /api/state` は最低限以下を返す。

```json
{
  "current_system": 12345,
  "current_body_id": 12345001,
  "current_station_id": 67890,
  "current_ship": {},
  "cargo": [
    {"commodity": "platinum", "qty": 720, "is_ore": true}
  ],
  "docked": true,
  "landed": false,
  "on_foot": false,
  "has_bio_signals": false,
  "unsold_bio_value": 0,
  "mining_context": {
    "has_mining_cargo": true,
    "recent_mining_refined": true,
    "last_ring_body_id": 12345001
  },
  "updated_at": "..."
}
```

### 6.1 Mining cargo

`has_mining_cargo = true` は `is_ore=true` の commodity が1t以上存在することを基本条件とする。

ただし、鉱石を持っていることだけでは「現在採掘中」と断定しない。`MiningRefined` や直近の ring body 位置等を `mining_context` として別管理する。

### 6.2 Bio state

以下を分離する。

- 現在天体に bio signal があるか
- ユーザーが当該天体を探索・スキャン済みか
- 未売却の organic data があるか
- Vista Genomics への売却が必要か

「未探索」は銀河全体に対する未探索ではなく、**本人がまだスキャンしていない**ことを基本意味とする。

## 7. 自動状態判定

### 7.1 Mining

```text
Cargo に ore >= 1t
        ↓
Mining Sell candidate を生成可能
```

さらに、直近 `MiningRefined` または ring body 上の直近 Location があれば `mining_active` を強化する。

鉱石がある場合:

- `mining_sell` — 現在地から最適販売先へ行って売却
- `mining_continue` — 現在の採掘コンテキストで追加採掘

鉱石がない場合:

- `mining_start` — 現在地から候補 ring へ移動し、1採掘サイクルを実行

### 7.2 Bio

現在天体に有効な bio signal がある場合は `bio_current_body` を候補化する。

現在天体にない場合は、`distance_limit_ly` の範囲内で本人未スキャンかつ bio signal が確認できる候補を検索し、`bio_next_system` を生成する。

未売却データが存在する場合は `bio_return` を生成する。近隣 Vista Genomics への帰還が実行可能な場合に限る。

### 7.3 自動モード選択

Mining と Bio の全候補を統一スコアで評価し、最高スコアを `next_action` とする。

ユーザーは MVP で以下の制限を指定できる。

- `mining_enabled=true/false`
- `bio_enabled=true/false`

両方有効な場合のみ自動比較を行う。

## 8. Unified Scoring

### 8.1 基本式

各候補を「現在状態から、その候補が価値を実現するまで」の action horizon で評価する。

```text
score_per_hour = expected_action_value / action_horizon_hours
```

ここで `action_horizon` はユーザー設定の Anchor までの往復時間ではない。

### 8.2 Mining Sell

保有鉱石の数量と候補販売ステーションの最新市場観測から実効売却額を求める。

```text
r = cargo / demand
```

経験則:

```text
r <= 0.25        penalty = 1.00
0.25 < r < 0.80  penalty = 1.00 → 0.45 の線形補間
r >= 0.80        penalty = 0.45

effective_price = listed_price × penalty
```

この補正は経験則であり、公式市場計算式として扱わない。

```text
expected_action_value = Σ(quantity_i × effective_price_i)
action_horizon = current location → sell station + docking/market transaction
```

保有済み鉱石の売却コストは MVP では 0 とする。

### 8.3 Mining Continue

現在採掘コンテキストがある場合、1採掘サイクルで期待される追加鉱石量を経験モデルから推定する。

```text
expected_action_value
  = expected_mined_quantity × expected_effective_sell_price

action_horizon
  = calibrated mining cycle time
```

採掘サイクル時間は `MiningRefined` の時系列から較正する。初期データが不足する場合は候補を低信頼として扱うか、保守的な fallback を使用する。

### 8.4 Mining Start

現在地から候補 ring body への移動時間と採掘1サイクルを評価する。

```text
action_horizon
  = current location → mining ring + mining cycle
```

候補 ring は Journal / Spansh の body 情報および本人の過去採掘実績を利用する。Spansh だけからライブの採掘期待値を推定したことにはしない。

### 8.5 Bio Current Body

現在天体で取得可能な生体候補の期待価値と、着地・移動・サンプル取得に要する実測時間モデルを使用する。

```text
expected_action_value = expected bio value
```

重力、地表条件、歩行距離等を説明変数として利用可能にする。

### 8.6 Bio Next System

現在地から候補 system/body への移動時間 + 生体調査時間を action horizon とする。

本人が未スキャンであることを候補条件とし、First Discovery を確定値として扱わない。

### 8.7 Bio Return

未売却 organic data がある場合、現在地から最寄りの Vista Genomics への移動 + docking/transaction を評価する。

これは「Anchor に戻る」動作ではなく、未売却価値を実現するための独立した候補行動である。

## 9. FSD / Route

`Loadout.MaxJumpRange` は積載時レンジとして直接利用しない。FSD module 情報から mass-dependent component を算出し、Guardian FSD Booster 等の質量非依存加算を別項として扱う。

`route_plot` は FSD range と混同しない。実ルートの迂回特性を較正するための観測値である。

Phase 0 では `NavRoute` から過去経路を完全復元することを要求しない。完全な前方収集データのみ route sample として保存し、初期 `detour_factor=1.15` を fallback とする。

## 10. Bio / First Discovery semantics

`organic_sales` に本人による売却記録が存在する species は、本人にとって未確定の First Discovery upside として扱わない。

逆に、売却記録がないことだけを「First Discovery 確定」と解釈しない。

ランキングの正本は保守的な base value とし、FD upside は別の参考情報として返す。

## 11. API

### State

```text
GET /api/state
GET /api/state/ship
GET /api/state/cargo
```

### Unified score

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

候補が存在しない場合:

```json
{
  "next_action": "none",
  "target": null,
  "alternatives": [],
  "reason": "有効な候補行動がありません"
}
```

### Other APIs

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

以下は廃止:

```text
GET /api/mining/anchor
PUT /api/mining/anchor
GET /api/mining/candidates/{id}
```

## 12. Database changes

v0.4 では `mining_anchor` テーブルを作成しない。

主要テーブル:

- `systems`
- `bodies`
- `stations`
- `commodities`
- `market_snapshots`
- `market_latest`
- `station_activity`
- `ships`
- `player_state`
- `cargo_state`
- `timing_samples`
- `calibration_models`
- `sell_observations`
- `organic_species`
- `organic_conditions`
- `organic_sales`
- `organic_scans`
- `body_bio_signals`
- `journal_events`

## 13. Calibration

Journal timestamp は UTC として扱う。

Phase 0-A で Journal + Status/Cargo/Market を処理する。

SC distance は以下を優先して同一 Journal から復元する。

1. `Docked` 対象ステーションに関連付け可能な情報
2. `Scan` の天体情報
3. `ApproachBody` と直前の `Scan`
4. 不明なら NULL

SC distance model sample は `SupercruiseExit` 後 120 秒以内に `Docked` または `ApproachBody` が続く場合を基本条件とする。それ以外は時間統計用に保持できる。

Calibration は時系列 70/30 holdout とし、同一 session を fit/eval に跨がせない。SC sparse buckets は隣接 bucket と統合する。

Go/No-Go の精度判定は eval 側 median absolute error を用い、R² は診断用とする。

## 14. EDDN freshness / activity

市場観測は `observed_at` を基準に stale 判定する。

- freshness = 最新観測からの経過時間
- activity = 1h / 6h / 24h 等の観測頻度

この2つを同一指標として扱わない。

## 15. Retention

- Raw Journal: 長期保存
- market snapshots: 約3日
- market_latest: 継続保持
- calibration / user action history: 必要期間保持

## 16. Phase / Exit Criteria

### Phase 0
Journal parser、Status/Cargo/Market、timing extraction、calibration を成立させる。

最低条件:

- 30h 以上の履歴で再現可能
- jump/SC/dock 等の timing samples を取得
- SC bucket の統合処理が動作
- chronological 70/30 eval が動作
- eval median absolute error が目標値以内

### Phase 1
EDDN + static DB + market latest + state integration。

### Phase 2 Mining

- Mining Sell candidate が現在状態から自動生成される
- effective price が計算できる
- 10件以上の実売却で feedback を取得
- effective price prediction median error ≤10% を目標
- mining cycle calibration が成立
- mining start / continue / sell を統一 score で比較できる
- Anchor に依存しない

### Phase 3 Exobiology

- 10件以上の実地 landing / sample data
- time prediction median error ≤25% を目標
- sold species の FD upside 除外
- current body / next system / return を統一 score で比較

### Phase 4 UI

- hero action を1件表示
- alternatives を表示
- 現在状態とデータ鮮度を表示
- 手動操作のための次行動説明を表示
- Anchor UI を持たない

## 17. Caveats

- FSD 実式は実装時点の最新仕様と照合する
- demand penalty は経験則
- EDDN は観測値
- Spansh は静的/補助データ
- First Discovery は Journal の本人情報だけで確定できないケースがある
- mining expected yield は本人の実績が不足する場合、推定信頼度を明示する
- score は「現在から次の価値実現まで」の比較であり、無期限の収益予測ではない
