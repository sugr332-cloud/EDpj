# EDpj Specification

**Version:** 0.7  
**Status:** Canonical Implementation Baseline  
**Date:** 2026-09-05  
**Previous:** 0.6 — §14: Phase 0-Cを実プレイ待ちバッチゲートからAction Horizon Estimator (AHE) インターフェース確立フェーズへ再定義。SC durationはobserved telemetryとして保存するが、候補固有のSC時間予測には現行データソースでは使用できない（arrival_dist_from_star_ls・global medianいずれも説明変数として不採用）

## 1. 目的

Elite Dangerous において、現在のゲーム状態から「次に何をすれば最も時間あたりの期待クレジットが高いか」を算出する。

対象金策は以下に限定する。

- **Mining** — 採掘を継続する、採掘を開始する、または保有鉱石を売却する
- **Exobiology** — 現在天体で生体活動を続ける、次の候補天体へ移動する、または未売却データを売却する

本バージョンの中心原則は **State Driven** である。ユーザーが「帰投先」「Mining Anchor」を指定して次の行動を固定する方式は採用しない。

## 2. 設計原則

### 2.1 現在状態が唯一の基準

Journal / Status.json / Cargo.json / Market.json 等から得た現在状態を正本とし、その時点で実行可能な候補を生成する。

### 2.2 次の一手を1つだけ選ぶ

Mining と Exobiology の候補を同じスコア体系で比較し、最も高い候補を `hero` / `next_action` とする。

### 2.3 Anchor / ユーザー指定帰投先を廃止

以下は v0.4 に存在しない。

- `mining_anchor` テーブル
- Mining Anchor の自動設定・手動設定
- Anchor UI
- Anchor API
- `return_to_anchor` DTO
- ユーザー設定Anchorを前提とした round-trip score

ただし、**復路そのものは禁止しない**。売却後に採掘を再開するために必要な復路は、直近の採掘状態から自動導出した通常ルートとして評価する。これは設定項目ではない。

### 2.4 実測時間を優先

移動、スーパークルーズ、ドッキング、採掘サイクル、生体サンプル等は可能な範囲でJournalから実測し、較正モデルを利用する。

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

### 4.1 Market.json capture

`Market.json` は次回のDockedで上書きされ得るため、`Docked` イベントをトリガーとしてその時点のMarket.jsonを保存する。

保存先は `market_snapshots` とし、`source='journal'` を設定する。EDDN由来の市場観測 (`source='eddn'`) と同一テーブルで保持するが、観測源は必ず区別する。

売却教師データに必要な `listed_price` は、売却直前のDocked時点Market snapshotを優先する。

## 5. データソース

| ソース | 用途 |
|---|---|
| Journal | 位置、移動、採掘、生体、売却、実測時間、本人の発見/スキャン状況 |
| Status.json | 現在位置、状態、Flags/Flags2、燃料等 |
| Cargo.json | commodity別積荷 |
| Market.json | 現在ステーション市場 |
| EDDN | 他ステーションの市場観測、共有観測 |
| Spansh dumps | システム・天体・ステーション等の静的情報 |
| `journal/1` | FSS等の探索観測支援 |
| `fssbodysignals/1` | bodyのbio signal観測支援 |

EDDNは観測共有ネットワークであり権威的な現在値ではない。`observed_at` と `received_at` を保持し、freshnessとactivityを分離する。

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

`has_mining_cargo = true` は `is_ore=true` のcommodityが1t以上存在することを基本条件とする。

ただし、鉱石を持っていることだけでは「現在採掘中」と断定しない。`MiningRefined` や直近のring body位置等を `mining_context` として別管理する。

### 6.2 Bio state

以下を分離する。

- 現在天体にbio signalがあるか
- ユーザーが当該天体を探索・スキャン済みか
- 未売却のorganic dataがあるか
- Vista Genomicsへの売却が必要か

「未探索」は銀河全体に対する未探索ではなく、**本人がまだスキャンしていない**ことを基本意味とする。

## 7. 自動状態判定

### 7.1 Mining

```text
Cargoにore >= 1t
        ↓
Mining Sell candidateを生成可能
```

さらに、直近 `MiningRefined` またはring body上の直近Locationがあれば `mining_active` を強化する。

鉱石がある場合:

- `mining_sell` — 現在地から最適販売先へ行って売却し、必要なら状態から導出した採掘復帰先へ戻る
- `mining_continue` — 現在の採掘コンテキストで追加採掘

鉱石がない場合:

- `mining_start` — 現在地から候補ringへ移動し、1採掘サイクルを実行

### 7.2 Bio

現在天体に有効なbio signalがある場合は `bio_current_body` を候補化する。

現在天体にない場合は、`distance_limit_ly` の範囲内で本人未スキャンかつbio signalが確認できる候補を検索し、`bio_next_system` を生成する。

未売却データが存在する場合は `bio_return` を生成する。近隣Vista Genomicsへの帰還が実行可能な場合に限る。

### 7.3 自動モード選択

MiningとBioの全候補を統一スコアで評価し、最高スコアを `next_action` とする。

ユーザーはMVPで以下の制限を指定できる。

- `mining_enabled=true/false`
- `bio_enabled=true/false`

両方有効な場合のみ自動比較を行う。

## 8. Unified Scoring

### 8.1 基本式

各候補を「現在状態から、その候補が価値を実現するまで」のaction horizonで評価する。

```text
score_per_hour = expected_action_value / action_horizon_hours
```

action horizonはユーザー設定のAnchorまでの往復時間ではない。

当該候補のscore計算に必要な時間要素のいずれかが `unavailable`（現時点ではsupercruiseが該当しうる）の場合、score_per_hourの算出方法（除外する／別枠で提示する等）はPhase 2の候補選択実装時に決定する（§14 Action Horizon Estimator参照。候補選択ロジックの詳細はIMPLEMENTATION_SPEC_V0.2.md §12.4）。

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
```

売却後に採掘を再開する状態が合理的な場合、`return_target` を以下から自動導出する。

```text
直近の信頼できる MiningRefined の system/body
        ↓ fallback
直近の採掘ring上 Location の system/body
```

`return_target` はDB設定値ではなく、現在のJournal/stateから生成される一時的な計算結果である。

```text
action_horizon
 = current location → sell station
 + docking / market transaction
 + sell station → derived return target
 + mining re-entry / positioning overhead
```

return targetを導出できない場合は `mining_sell` を機械的にAnchorへ補完してはならない。候補は低confidenceとし、reasonに導出不能を明示する。

### 8.3 Mining Continue

現在採掘コンテキストがある場合、1採掘サイクルで期待される追加鉱石量を経験モデルから推定する。

**売却価格の需要比率は現在cargo量ではなく、満載時の評価cargoを使用する。** これにより、現在の少量積荷を使って `r` を計算し、continueの将来価値を過小評価することを防ぐ。

```text
evaluation_cargo
 = expected cargo after one cycle
 = min(current cargo + expected mined quantity, cargo capacity)
```

複数commodityの場合は、本人の過去採掘実績から得た満載時commodity compositionを優先する。

```text
expected_effective_sell_price
 = effective price evaluated using full-capacity / expected post-cycle cargo ratio

expected_action_value
 = expected_mined_quantity × expected_effective_sell_price

action_horizon
 = calibrated mining cycle time
```

採掘サイクル時間は `MiningRefined` の時系列から較正する。初期データが不足する場合は低confidenceとするか保守的fallbackを使用する。

### 8.4 Mining Start

```text
action_horizon
 = current location → mining ring + mining cycle
```

候補ringはbody static dataおよび本人の過去採掘実績から生成する。Spanshだけからlive yieldを推定したことにはしない。

### 8.5 Bio Current Body

現在天体で取得可能な生体候補の期待価値と、着地・移動・サンプル取得に要する実測時間モデルを使用する。

```text
expected_action_value = expected bio value
action_horizon = descent / landing / walk / sample
```

重力、地表条件、歩行距離等を説明変数として利用可能にする。

### 8.6 Bio Next System

現在地から候補system/bodyへの移動時間 + 生体調査時間をaction horizonとする。

本人が未スキャンであることを候補条件とし、First Discoveryを確定値として扱わない。

### 8.7 Bio Return

未売却organic dataがある場合、現在地から最寄りのVista Genomicsへの移動 + docking/transactionを評価する。

これはAnchorへ戻る動作ではなく、未売却価値を実現するための独立した候補行動である。

## 9. FSD / Route

`Loadout.MaxJumpRange` は積載時レンジとして直接利用しない。FSD module情報からmass-dependent componentを算出し、Guardian FSD Booster等の質量非依存加算を別項として扱う。

`route_plot` はFSD rangeと混同しない。実ルートの迂回特性を較正するための観測値である。

Phase 0では `NavRoute` から過去経路を完全復元することを要求しない。完全な前方収集データのみroute sampleとして保存し、初期 `detour_factor=1.15` をfallbackとする。

## 10. Bio / First Discovery semantics

`organic_sales` に本人による売却記録が存在するspeciesは、本人にとって未確定のFirst Discovery upsideとして扱わない。

逆に、売却記録がないことだけを「First Discovery確定」と解釈しない。

ランキングの正本は保守的なbase valueとし、FD upsideは別の参考情報として返す。

## 11. API

### 11.1 State

```text
GET /api/state
GET /api/state/ship
GET /api/state/cargo
```

### 11.2 Unified score

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

Responseは `target` と `alternatives` で同じ `ActionCandidate`形状を使用する。

```json
{
  "next_action": "mining_sell",
  "target": {
    "action": "mining_sell",
    "target": {
      "station_id": 99999,
      "commodity": "platinum"
    },
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

### 11.3 Other APIs

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

## 12. Database

主要テーブル:

```text
systems
bodies
stations
commodities
market_snapshots
market_latest
station_activity
ships
player_state
cargo_state
timing_samples
calibration_models
sell_observations
organic_species
organic_conditions
organic_sales
body_bio_signals
journal_events
```

`mining_anchor` は存在しない。

### 12.1 bodies

`bodies` はbody type、sub type、arrival LS、gravity、radius、atmosphere、landable等を保持する。

リング判定を静的body情報から行う場合は `rings JSONB` を保持し、少なくともring type / inner radius / outer radius / composition等を表現可能とする。静的ring情報がない場合、`mining_active` の判定は直近 `MiningRefined` と位置履歴による証拠を優先し、known ringと断定しない。

### 12.2 market_snapshots

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

`market_latest` は `(station_id, commodity_id)` の最新 `observed_at` を保持するnormal tableとする。MVPではmaterialized view refreshに依存せずupsertする。

Snapshots retentionは約3日。

### 12.3 player_state / cargo_state

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

## 13. EDDN / External Data

Phase 1では以下を購読・保存する。

### 13.1 Market

市場観測を `market_snapshots` に保存し、`observed_at` と `received_at` を分離する。

### 13.2 Bio discovery support

Phase 3の本人未スキャン候補生成に必要なため、以下を購読・保存する。

```text
journal/1
fssbodysignals/1
```

観測はsourceとobserved_atを保持し、body/bio signalモデルへupsertする。

市場観測だけでbio候補が存在すると仮定しない。

## 14. Action Horizon Estimator（旧: Calibration）

Action Horizon Estimator (AHE) の責務は「候補のaction_horizonを必ず数値で返すこと」ではなく、**各時間要素（jump / supercruise / dock / undock / descent / ascent / mining_cycle / bio_sample）について `measured` / `estimated` / `unavailable` のいずれかを明示して返すこと**である。

### 14.1 Supercruise time

Journal timestampはUTCとして処理する。

SC区間は以下を開始イベントとして扱う。

```text
SupercruiseEntry
FSDJump
```

終了は `SupercruiseExit`。`duration_seconds`（開始 → `SupercruiseExit`）はJournalから直接観測できる実測値であり、`timing_samples` に **observed telemetry** として保存する。

終了後、別の `FSDJump` / `SupercruiseEntry` を挟まず `Docked` または `ApproachBody` に到達したかを `reached_known_target` として記録する（固定120秒窓は使用しない）。これは「既知の目的地で終わったサンプルか」を示す分類フラグであり、距離の正しさを保証するものでも距離モデルの採否判定でもない。

**この `duration_seconds` の集合を、新規候補のSC時間予測には使用しない。** 理由:

- SC開始地点の位置がJournalから分からないため、SC移動距離の実測値が存在しない
- `arrival_dist_from_star_ls`（`Docked.DistFromStarLS`）は目的地の恒星からの静的距離であり、SC開始地点からの移動距離ではない。「目的地が恒星から300LS」だけでは現在地からの移動距離は分からないため、AHEの説明変数として使用しない（§14.3の探索的分析にのみ利用する）
- 全SCサンプルのglobal median等、単一の統計値も採用しない。候補ごとの所要時間は大きく異なりうる（実データで10秒〜360秒超、36倍の幅）ため、単一値を全候補へ一律適用するとUnified Scoringの候補間比較（§8.1）を歪める

**現行のJournal等のデータソースでは、候補固有のSC移動距離を取得できないため、候補固有のSC時間推定は `unavailable` とする。** 将来、実SC移動距離を取得可能なデータソースが追加された場合は、§14.4の将来モデルとして `estimated` へ拡張可能とする。

### 14.2 Fit/eval（jump / dock / undock / descent / ascent / mining_cycle / bio_sampleに適用）

これらのセグメントは開始・終端が明確で、候補ごとの所要時間が概ね均質と見なせる（1採掘サイクル、1回のドッキング等）ため、引き続き実測較正の対象とする。**supercruiseはこの較正の対象外**（§14.1参照）。

時系列昇順で70/30を基本とし、同一sessionがfit/evalを跨がないよう境界をsession単位で調整する。

evalはモデル選択・bucket選択に使用しない。

### 14.3 arrival_dist_from_star_ls 探索的分析（AHEの入力ではない、Go/No-Go対象外）

`arrival_dist_from_star_ls` はSC移動距離ではなく、目的地の恒星からの静的距離である（§14.1参照）。**AHEのSC時間予測には使用しない。** ただし観測データとしては引き続き記録し、`duration_seconds` との相関・傾向を確認する探索的分析には利用してよい。

```text
0–100 ls
100–1,000 ls
1,000–10,000 ls
10,000–50,000 ls
50,000+ ls
```

対象は `arrival_dist_from_star_ls` が取得できたサンプル（`Docked` 終端かつ `reached_known_target=true`）のみに限る。`ApproachBody` 終端サンプルおよび `reached_known_target=false` のサンプルはこの分析には含めない。ただしいずれも`duration_seconds`はsupercruiseのobserved telemetry（§14.1）として引き続き保存される。

20 samples未満の区分は隣接区分と統合する。統合後のeval件数も検証し、0件の区分は `INSUFFICIENT` とする。**ただしこの分析全体はPhase 0-CのGo/No-Go判定に使用しない。** サンプルが不足する場合は分析自体を省略してよい。「距離データが足りないためPhase 0-Cに進めない」という依存関係は成立しない。

保存（この探索的分析を実施した場合）:

- median_absolute_error
- median_signed_error
- sample_count_fit
- sample_count_eval
- R² (diagnostic)
- residual_stddev
- bucket merge metadata

### 14.4 将来のSC距離モデルへの拡張余地

`timing_samples` の全supercruiseサンプルの `duration_seconds` は、将来SC実移動距離を取得できる別データソースが決まった際の、**モデル構築・検証用のobserved telemetry**として保持する。現時点でこのデータソースの選定は行わない。データソースが決まり次第、§14.1の `unavailable` は `estimated`（さらに実績が積み上がれば `measured`）へ移行可能な設計とする。

## 15. Feedback / Teacher Data

### 15.1 Mining sell

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

`listed_price` は売却直前の `Market.json` snapshotを優先し、Docked時点で保存された `source='journal'` データを利用する。次のDockedによるMarket.json上書きで教師データが失われないようにする。

### 15.2 Effective price calibration

初期経験則をfallbackとし、本人の実測売却データが蓄積されたら区分ごとのpenalty modelを較正する。評価データをモデル選択へ混ぜない。

## 16. Regression / Forbidden Features

以下を実装してはならない。

```text
mining_anchor table
GET /api/mining/anchor
PUT /api/mining/anchor
return_to_anchor DTO
Anchor UI
configured round-trip score
```

ただし、`mining_sell` の復路を禁止するものではない。復路は `MiningRefined` / ring Location等の状態から自動導出する通常ルートであり、ユーザー設定値ではない。

必須回帰条件:

- `mining_sell` は `mining_active` を必須としない
- ore cargoがあればsell candidateを生成できる
- `mining_sell` は片道だけのhorizonを使用しない
- `mining_continue` は現在cargo量だけで価格penaltyを計算しない
- confidence不足候補を無条件にheroへ昇格しない
- sold bio speciesにFD upsideを付与しない
- `app/mining/yield.py` を作らない

## 17. Phase Plan / Exit Criteria

### Phase 0-A — Parser / State

- Journal parser
- raw persistence
- Status/Cargo/Market reader
- Docked時Market snapshot
- state reducer
- backfill CLI

Exit:

- Journal fixtures pass
- Status/Cargo/Market fixtures pass
- Docked Market capture pass
- state reconstruction pass

### Phase 0-B — Timing

- jump timing
- SC timing (`FSDJump` + `SupercruiseEntry` start)
- event-sequence-based `reached_known_target` classification（距離測定ではない。§14.1参照）
- dock/undock
- bio timing
- mining cycle
- route_plot collection

Exit:

- FSDJump-origin SC sampleが抽出できる
- 固定120秒フィルタを使用しない
- intervening FSDJump/SupercruiseEntryがあればそのサンプルは `reached_known_target=false`

### Phase 0-C — Action Horizon Foundation

目的は「実データでSC時間モデルを完成させる」ことではなく、**Unified Scoringが必要とするAction Horizonの時間推定インターフェース（Action Horizon Estimator, §14）を確立する**こと。

- AHEが各時間要素を measured / estimated / unavailable の統一形式で返す
- SC durationはJournalから observed telemetry として取得・保存する（将来のモデル構築・検証用、候補予測には未使用）
- 現行のJournal等のデータソースでは候補固有のSC移動距離を取得できないため、候補固有のSC時間推定は `unavailable` とする（§14.1）。将来、実SC移動距離を取得可能なデータソースが追加された場合は `estimated` へ拡張可能とする（§14.4）
- arrival_dist_from_star_lsをSC時間の説明変数として使用しない
- AHEの不完全なhorizonをActionCandidateへ伝播できる

jump/dock/undock/descent/ascent/mining_cycle/bio_sampleは引き続き§14.2のfit/eval較正の対象とし、約20 samplesを目安とする。

- robust calibration（jump/dock/undock/descent/ascent/mining_cycle/bio_sample対象、supercruise対象外）
- 30h history target
- chronological 70/30 fit/eval
- sparse bucket merge（arrival_dist_from_star_ls分析を実施する場合。§14.3参照、Go/No-Go対象外）
- INSUFFICIENT status

Exit:

```text
measured/estimated/unavailableの3区分がfixtureで検証できる
supercruiseは常に unavailable を返すことをテストで確認する
（他セグメントの較正品質については以下を適用）
median absolute error <= 20%
median signed error between -10% and +10%
R² diagnostic only
```

必要なeval区分に0件があればPASSではなく `INSUFFICIENT`。**実プレイのサンプル数に依存するExit条件は持たない。**

Unified Scoringが不完全なhorizon（`unavailable`区間を含む候補）をどう扱うかは、confidence合成方法と合わせてPhase 2実装時に決定する（候補選択ロジックの詳細はIMPLEMENTATION_SPEC_V0.2.md §12.3/§12.4）。

### Phase 1 — External data / State

- EDDN market
- `journal/1`
- `fssbodysignals/1`
- static DB
- market_latest
- state API

Exit:

- fresh market observation available
- bio signal observation available
- coherent state endpoint

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
- continue price evaluation uses full-capacity / expected post-cycle ratio
- no Anchor implementation

### Phase 3 — Bio

- current body
- next system
- return
- 10 landings / sample observations target
- time prediction median error <= 25%
- sold species FD exclusion

Exit:

- 本人未スキャン候補が実データから生成できる
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

## 18. CLI-first

```bash
edpj journal backfill --dir <journal_dir>
edpj calibration fit
edpj calibration status
edpj state show
edpj mining candidates
edpj score next-action
```

CLIでparser → state → calibration → candidate → unified scoreを確認してからUIを実装する。

## 19. Acceptance Tests

```text
Journal UTC parsing
Duplicate (file,line) handling
Status/Cargo/Market parsing
Docked Market capture
Laden FSD range
Effective price boundary
Full-capacity Mining Continue ratio
FSDJump-origin SC extraction
Event-sequence SC termination
Sparse bucket merge
Zero-eval => INSUFFICIENT
Session-safe split
Mining/Bio state detection
Derived mining return target
Confidence threshold
No-candidate response
Journal → state integration
Market → market_latest integration
journal/1 + fssbodysignals/1 → bio signal
state → candidate integration
candidate → score integration
MarketSell → feedback integration
Forbidden Anchor regression
```

## 20. 用語の統一

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

## 21. 探索状態の管理

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

## 22. ターゲットDTOの構造化

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
    arrival_dist_from_star_ls: float   # 恒星からの静的距離。SC移動距離ではない（§14.1参照）
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
    arrival_dist_from_star_ls: float   # 恒星からの静的距離。SC移動距離ではない（§14.1参照）
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

## 23. 到達可能性の判定

積載時ジャンプレンジで到達できない候補を生成段階で除外する。

```text
候補の各ジャンプ区間について:
  segment_distance > laden_jump_range → 候補から除外
```

判定不能な場合は除外せず confidence を下げる。

## 24. 惑星表面のナビゲーション（Phase 3）

`Status.json` の緯度・経度・機首方位を使い、惑星表面でのみ方位表示を提供する。宇宙空間では提供しない（ゲーム内HUDが誘導するため）。

提供する情報:

- 直近の `ScanOrganic` 採取地点から現在地までの距離。同一種で3サンプル取るには種ごとの規定距離（100m〜500m）以上離れる必要があるため
- `Touchdown` 地点（自船）までの距離と方位

提供**しない**情報:

- 生体コロニーの位置。プローブ後の惑星マップにのみ表示され、Journalに書き出されないため取得不可
- 星系マップの軌道配置。Spanshが持つのは到着星からの距離のみで、実際の軌道位置ではない。それらしい図を描くとゲーム内表示と一致せず混乱を招く

## 25. UI要件（Phase 4）

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

## 26. 制約（再掲）

- ゲームへの入力自動化を実装しない。読み取りと提案のみ
- Mining Anchor / ユーザー指定の帰投先を実装しない
- 取得できないデータを推定で埋めない。`NO_DATA` として扱う
- 推定値と実測値をDB・API・UIで区別する
