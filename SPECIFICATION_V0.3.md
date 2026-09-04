# edProject Specification

**Version:** 0.3  
**Status:** Draft / Implementation Baseline  
**Updated:** 2026-09-04  
**前版:** Elite Dangerous 交易・マーケット分析基盤 v0.2

> Historical Elite Dangerous specification migrated from `sugr332-cloud/evProject`.
> This document is retained as the v0.3 baseline. The canonical current design is `SPECIFICATION_V0.4.md`.

## 1. 目的

Elite Dangerous において、自分の現在地・装備・積荷・実測時間モデルを使い、「今この瞬間、どこへ行って何をすると最も時間あたりのクレジットが高いか」を算出する。

対象とする金策は次の2つに限定する。

| モード | 内容 | 優位性 |
|---|---|---|
| **Mining Sell** | 採掘した鉱石の売却先決定 | 需要に対する積載量による実効価格補正 |
| **Exobiology** | 生体スキャン対象の天体決定 | 実測時間モデル、重力・距離、個人の発見済み情報を利用 |

両者は自機状態管理・時間較正・スコアリングの共通コア上で評価する。

## 2. スコープ / 非目標

### スコープ
- Mining Sell
- Exobiology
- Journal / Status / Cargo / Market による自機状態取得
- EDDN による市場観測
- Spansh static data
- 実測時間による較正
- 時間あたりクレジットによるランキング

### 非目標
- ゲームへの入力自動化
- 汎用A→B交易ルート検索
- 価格・需要の将来予測
- ミッション支援
- 銀河全体の市場DB
- 他プレイヤー向け公開サービス

## 3. 全体構成

```text
Elite Dangerous
      │
      ├─ Journal / Status / Cargo / Market
      ▼
 Journal Watcher ──────┐
 EDDN Subscriber ──────┼──► PostgreSQL
 Spansh Importer ──────┘          │
                                  ├─ Calibration
                                  └─ Scoring
                                       ├─ Mining Sell
                                       └─ Exobiology
                                             │
                                          FastAPI
                                             │
                                          Web UI
```

Backend は Python/FastAPI、DB は PostgreSQL 16+、Frontend は React + Lucide、配信は WebSocket、実行環境は Bazzite Linux とする。

## 4. データソース

| ソース | 用途 |
|---|---|
| Journal | 自機状態、実測時間、売却実績 |
| Status.json | 現在値、燃料、状態 |
| Cargo.json | 現在積荷 |
| Market.json | 現在ドック中市場 |
| EDDN | 他ステーションの市場観測 |
| Spansh dumps | システム・天体・ステーション等の静的情報 |

EDDN は観測共有ネットワークであり現在状態の権威データではない。`observed_at` と `received_at` を分離し、鮮度と活動度を別々に扱う。

## 5. 自機状態

主な Journal イベント:

- 位置・移動: `Location`, `StartJump`, `FSDJump`, `SupercruiseEntry`, `SupercruiseExit`, `ApproachBody`, `LeaveBody`, `Touchdown`, `Liftoff`, `Docked`, `Undocked`, `NavRoute`
- 船・装備: `Loadout`, `ShipyardSwap`, `ModuleBuy`, `ModuleSell`, `ModuleRetrieve`, `SuitLoadout`
- 積荷・取引: `Cargo`, `MiningRefined`, `MarketBuy`, `MarketSell`, `Market`
- Exobiology: `Scan`, `FSSBodySignals`, `SAASignalsFound`, `ScanOrganic`, `SellOrganicData`

Journal の timestamp は UTC ISO8601 として扱う。

## 6. 積載時ジャンプレンジ

`Loadout.MaxJumpRange` を積載時レンジとして直接利用しない。FSD module 情報、total mass、optimal mass、fuel limit、engineering 等から実式に基づき算出する。Guardian FSD Booster 等の質量非依存加算は別項として扱う。

## 7. Mining Sell

需要に対する積載量比 `r = cargo / demand` を利用して実効価格を算出する。v0.3 の経験則:

```text
r <= 0.25        penalty = 1.00
0.25 < r < 0.80  penalty = 1.00 → 0.45 を線形補間
r >= 0.80        penalty = 0.45

effective_price = listed_price × penalty
required_demand = cargo / 0.25
```

これはゲーム公式式ではなく、実測に基づく経験則として扱う。

v0.3 では Mining Anchor を使った売却後の復路を含む採掘ループを評価する設計だった。これは v0.4 で廃止し、現在地から次の行動を評価する方式へ変更する。

## 8. Exobiology

種ごとの期待値を確率分布と基本価値から計算する。

```text
expected_value_base = Σ p(s) × base_value(s)
expected_value_best = Σ p(s) × base_value(s) × fd_multiplier
```

ランキングは基本値を正本とし、best は上振れ参考値とする。既に本人が売却した species は First Discovery 上振れ候補から除外する。

## 9. 較正

Timing samples は `jump`, `supercruise`, `dock`, `undock`, `descent`, `ascent`, `bio_sample` 等に分ける。SC は距離帯別に扱い、各区分が20サンプル未満の場合は隣接区分と統合する。

評価は時系列 70/30 holdout とし、eval 側の median absolute error を主要指標とする。R² は診断用とする。

## 10. 保存方針

- Raw Journal: 長期保存
- market snapshots: 約3日
- market latest: 継続保持
- stale 判定: 最新 `observed_at`
- EDDN activity と freshness は別管理

## 11. API 概要

```text
GET /api/state
GET /api/state/ship
GET /api/state/cargo
GET /api/mining/candidates
GET /api/mining/multi
GET /api/bio/system/{system_address}
GET /api/bio/body/{body_id}
GET /api/bio/unsold
GET /api/calibration
POST /api/calibration/refit
GET /api/calibration/samples
WS  /ws/state
```

v0.4 では Mining Anchor API は廃止され、`POST /api/score/next-action` に統合される。

## 12. v0.3 の位置付け

本書は v0.3 の履歴として保持する。実装の正本は `IMPLEMENTATION_SPEC_V0.2.md` とし、現在の仕様は `SPECIFICATION_V0.4.md` を対象とする。
