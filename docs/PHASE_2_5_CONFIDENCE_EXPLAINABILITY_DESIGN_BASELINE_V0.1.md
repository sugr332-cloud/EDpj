# EDpj Phase 2-5 Confidence / Explainability Design Baseline

**Version:** 0.3  
**Status:** §7/§7.2で確定したConfidence合成（generation_confidence保持、Market/Cargo=measured=1.00、freshness=MIN集約、`ValueResult`化）を実装完了（`app/scoring/confidence.py`, `app/scoring/value.py`のValueResult化, `app/scoring/pipeline.py`統合）。260→273テスト全通過。ReasonFact/DataSource/narration（§8/§9、本書内部の呼称で「2-5D」）は引き続き未着手。

**用語の補足**: 本書§10が内部的に定義する「Phase 2-5A〜D」という細分ラベルは、`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` §14が定義する「Phase 2-5A（Market Predictability、実装済み・commit `4b4d782`）/Phase 2-5B（本書、Confidence/Explainabilityの設計）」というラベルとは別体系であり、両ドキュメント間で用語が食い違っている（レビューで発見、cleanupは別途）。実装の会話では「Phase 2-5B=本書の設計確定、Phase 2-5C=本書§7.2の具体的決定の実装」という呼称で進めており、本Statusもそれに合わせている。
**Date:** 2026-09-05  
**Depends on:** `SPECIFICATION_V0.4.md` v0.7, `IMPLEMENTATION_SPEC_V0.2.md` v0.5, `docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` v0.1, Phase 2-4 ranking (`0fd9182`)

## 0. 目的

Phase 2-5では、Phase 2-4までに完成した「候補生成 → Horizon → Value → Score → Ranking」を、**どの程度信頼してよいか説明できる状態**へ拡張する。

ただし、Phase 2-5のConfidenceは単なる数値付与ではない。過去のEDDN市場観測を用いて、**そもそも価格予測・市場評価を適用してよい市場なのか**を検証する。

中心原則は以下とする。

> 市場変動が激しく、過去データから見ても将来価格の予測可能性が低い市場では、価格予測モデルを無理に補正して使わない。モデル適用不能として扱う。

市場変動指標を `score_per_hour` の式へ直接組み込まない。

## 1. Phase 2-4からの接続

Phase 2-4は完了済みであり、Ranking自体を変更しない。

```text
CandidatePipelineResult
        ↓
Phase 2-3
Horizon + Value + scoreability
        ↓
Phase 2-4
Ranking / Recommendation
        ↓
Phase 2-5
Confidence / Explainability / Backtest
```

Phase 2-4で確定した以下を変更しない。

- `score_per_hour` の基本式
- confidence threshold `0.50`
- confidenceをranking順序へ混ぜない方針
- tie-break順序
- incomplete candidateの扱い
- alternatives最大3件
- `Recommendation` DTOの基本構造

## 2. Historical EDDN Dataset

### 2.1 目的

市場の変動性を実プレイ待ちだけで評価せず、過去のEDDN観測を利用して統計的に検証する。

EDDN自体はライブ観測ネットワークであり、過去データは外部アーカイブ／集約データから取得する。取得した過去データはEDpjのテスト用Historical Replay Datasetへ取り込む。

### 2.2 データの意味

他プレイヤーが送信した観測であっても、同じElite Dangerousの共有市場に対する実観測であるため、**市場変動性の統計分析には利用可能**とする。

ただし、他プレイヤーの行動そのものを予測するモデルは作らない。

```text
他プレイヤーの行動
        ↓
共有市場の価格 / demand変化
        ↓
過去観測から変動性を測定
```

目的は「他プレイヤーが何人来るか」の推定ではなく、**その市場が過去にどれだけ不安定だったか**の判定である。

### 2.3 Historical Replay Datasetの最低要件

最低限以下を保持する。

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

同一 `(station_id, commodity_id)` の観測を `observed_at` 順に並べ、未来情報が過去の評価へ混入しないよう時系列順序を厳守する。

### 2.4 データ欠損

EDDNは全市場を常時観測するものではないため、観測間隔を明示する。

- 観測が疎な市場を無理に連続時系列として補間しない
- 欠損期間の価格を推測値で埋めない
- observation gapが大きい区間は短時間変動統計から除外可能とする
- `observed_at` と `received_at` を混同しない

## 3. Market Stability / Predictability Analysis

### 3.1 基本単位

原則として `(station_id, commodity_id)` 単位で分析する。

必要に応じて、十分な観測がない場合のみcommodity単位等への集約を検討する。ただし集約は別市場の性質を混ぜるため、MVPではstation×commodityを正本とする。

### 3.2 測定対象

少なくとも以下を別々に測定する。

1. **Price volatility** — 価格の短時間変動
2. **Demand volatility** — demandの短時間変動
3. **Observation density** — 評価可能な観測間隔の十分性

価格だけを見ると、価格が変わらなくてもdemandが急減して売却可能量が崩れるケースを見落とすため、demandを独立指標とする。

### 3.3 変動率

基本の変動率は連続観測間の相対変化として扱う。

```text
price_change_ratio
 = abs(price_t1 - price_t0) / max(price_t0, 1)

demand_change_ratio
 = abs(demand_t1 - demand_t0) / max(demand_t0, 1)
```

ただし、観測間隔が大きく異なるため、短時間変動を評価する場合は許容intervalを定義し、極端なgapを同一母集団へ混ぜない。

MVPでは10分前後の短時間windowを第一候補とするが、最終thresholdはHistorical Datasetの分布を確認して決定する。固定値を先に仮定しない。

### 3.4 統計量

最低限以下を算出する。

```text
sample_count
observation_window
median_price_change
p95_price_change
median_demand_change
p95_demand_change
observation_gap_statistics
```

平均値だけでは急激な市場ショックを捉えにくいため、medianとp95を基本とする。

### 3.5 Classification

初期分類は以下の4状態を使用する。

```text
STABLE
MODERATE
VOLATILE
INSUFFICIENT
```

境界値は実データ分布とバックテスト結果から決定する。任意の経験則を先に固定しない。

`INSUFFICIENT` は「安定している」とは意味しない。観測不足のため判定不能である。

## 4. Market StabilityはScore式に入れない

以下を明示的に禁止する。

```text
score_per_hour
 = expected_value × stability_factor / horizon
```

のような補正は行わない。

また、

```text
expected_value × 0.8
```

のように市場変動性を暗黙の値引きとして入れない。

理由:

- 市場変動性は期待収益そのものではなく、価格モデルの適用可能性を示す診断値である
- arbitraryな補正係数を入れるとscoreの意味が不透明になる
- 「予測モデルが使えない市場」と「予測値は低い市場」を混同するため

## 5. Market Model Applicability Gate

市場が `VOLATILE` と判定され、過去データ上も価格予測誤差が許容できない場合、**価格予測モデルを適用しない**。

これはscoreへのペナルティではなく、モデル適用可否の判定である。

```text
Historical Market Data
        ↓
Stability Analysis
        ↓
Model Applicability
   ┌────┴────┐
   ↓         ↓
 APPLICABLE  NOT_APPLICABLE
   ↓         ↓
通常評価     価格予測モデルを使用しない
```

`NOT_APPLICABLE` の候補をどう公開するかは既存のcandidate incomplete/filter policyと整合させ、Phase 2-5実装時に確定する。少なくとも、予測値を正常な確度であるかのようにRecommendationへ出してはならない。

## 6. Backtest / Historical Replay

### 6.1 目的

「ランキングの単体テスト」と「実際に儲かるか」を分離する。

単体テストは決定論的ランキングの正しさを検証する。Historical Replayは、過去時点の市場状態に対して現在のEDpjを適用し、**推定時間後の実績と比較する**。

### 6.2 Replay

```text
Historical State at T0
        ↓
EDpj Candidate Generation
        ↓
Horizon / Value
        ↓
Ranking
        ↓
predicted_action
predicted_value
predicted_horizon
        ↓
T0 + predicted_horizon
        ↓
Historical observations / player events
        ↓
actual_delta / actual outcome
```

未来のデータをT0の入力へ混入させないことを最重要条件とする。

### 6.3 評価

最低限以下を記録する。

```text
prediction_count
applicable_count
insufficient_count
predicted_value
actual_value / actual_delta
absolute_error
relative_error
rank_at_T0
actual_best_outcome
```

Rankingについては、予測1位が実績でも上位であるかを評価する。

ただしEDDNのみでは「自分がそのActionを実行した利益」は観測できないため、Historical EDDN Replayは**市場予測・ランキング妥当性の検証**として扱う。

本人のJournalが存在する区間では、さらに実際のCredits/Cargo/売却イベントを使ったE2E評価を行う。

### 6.4 時間評価の位置づけ

Action Horizonの時間精度は重要だが、過去データの母数が限られることを考慮し、Phase 2-5では「時間を極限まで正確に予測する」ことを主目的にしない。

むしろ、

> **予測したhorizonの後に、実際の価値がどれだけ実現したか**

を主要な実用評価とする。

## 7. Confidence

Phase 2-4で既にconfidence thresholdを実装済みであるため、Phase 2-5では**候補の信頼性を機械的に説明できるconfidence composition**を完成させる。

```text
confidence
 = Π(component_confidence)
 × freshness_factor
```

初期値:

```text
measured    = 1.00
estimated   = 0.85
unavailable = 0.60  # 現Option CではRecommendationに適用しない予約値
```

`unavailable` を含む候補は現在のOption CではIncompleteCandidateであり、Recommendation confidenceへ無理に落とし込まない。

### 7.1 Freshness

freshnessは原則 `observed_at` を基準とする。

ただしデータ種別によって寿命が異なるため、全sourceへ単一curveを機械的に適用しない。

少なくとも:

- Market observation: 短いfreshness window
- Journal-derived stable state: 長いfreshness windowまたは別扱い
- Calibration model: 通常の市場freshnessとは別管理
- Spansh static data: market freshnessとは別管理

具体的curve、threshold、capはPhase 2-5実装時にHistorical Datasetと整合させて決定する。

### 7.2 Component confidenceの実装決定（実装前レビューで確定、Phase 2-5C）

現在Scoreへ到達しうる唯一のActionは`mining_continue`である（`mining_sell`はsupercruiseが常にunavailableなためhorizon_completeにならない — docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md v0.5 §2）。以下は主に`mining_continue`を想定するが、他Actionが将来Score到達可能になった時にも一般化できる形で定義する。

**確定1: `generation_confidence`（Phase 2-2由来）はcomponent_confidenceの積から除外しない。** これまでのPhase 2-2/2-3では`ActionCandidate.confidence`が実質`generation_confidence`のコピーだったため見えにくかったが、`generation_confidence`（例: MiningContextがbody_contextを伴わずmining_activeと判定した場合の0.75）はHorizon/Marketとは独立した不確実性であり、落とすと情報が失われる。

```text
component_confidence_product
  = generation_confidence
  × Π(HorizonComponentごとのconfidence)
  × 1.00 (Market観測 -- 常にmeasured。EDDN/journalの実測値でモデル推定ではない)
  × 1.00 (Cargo/Loadout -- 常にmeasured。現在のship stateを直接読むだけ)
```

Market/Cargoの項は常に1.00（積の単位元）なので、実装では明示的な乗算コードを書かず、コメントでその理由を説明するに留める（存在しない乗算を書く意味がないため）。

**確定2: 複数Market観測を持つ候補（`mining_sell`型）のfreshness集約はMIN。** PRODUCTだと観測数が多いcandidateほど機械的にconfidenceが下がり、「扱うcommodity種類が多いだけ」の候補が構造的に不利になる。MINは「一番古い観測に見合った信頼度」という直感と一致し、観測数に対して中立。

```text
candidate_freshness_factor = min(freshness_factor(observed_at) for each Market row actually used in Value計算)
```

**確定3（実装上必須の変更）: `calculate_value()`の返り値を`ValueResult`に変更し、実際に使った`MarketLatest.observed_at`のリストを含める。** Confidence計算がValue計算と別クエリで「使われたはずの行」を再導出すると、Value側の選択ロジックが将来変わった時にConfidenceが実際には使われていない行のfreshnessを参照してしまうリスクがある（同じ選択ロジックの二重実装は禁物）。

```python
@dataclass
class ValueResult:
    expected_value: float | None
    value_unavailable_reason: str | None
    market_observed_ats: list[datetime]  # 空リスト = このcandidateはMarket観測を使っていない
```

`app/scoring/value.py`（`_mining_sell_value`/`_mining_continue_value`/`calculate_value`）と`app/scoring/pipeline.py`の呼び出し側、および既存テストの全呼び出し箇所（タプル2値アンパック）に影響する。Phase 2-3で`MiningTarget`に`station_id`/`commodity_name`を追加した時と同じ「ポリシー変更ではなく実装上必要な配線変更」である。

**暫定decay curve（15節参照、Historical Datasetでの較正が本来必要）**: `FRESHNESS_FULL_THRESHOLD=15分`未満は1.00、`FRESHNESS_FLOOR_THRESHOLD=24時間`以上は`FRESHNESS_FLOOR=0.50`、その間は線形補間。`app/mining/price.py`の`demand_penalty`と同じ「フラット→線形→フラット」形状を、既存パターンとの一貫性のために採用する（根拠はこれ以上強くない——指数減衰等が望ましければPhase 2-5A/2-5Bのbacktest結果を踏まえて修正する）。

## 8. ReasonFact / DataSource

ReasonFactはpost-hoc生成しない。

```text
Horizon → time facts
Value   → value / market facts
Confidence → freshness / confidence facts
Score   → score facts
Ranking → comparison facts
```

`DataSource` は少なくとも以下を保持する。

```text
name
observed_at
received_at
freshness
```

Market Stabilityについても、Recommendationがその市場データを使用した場合は、診断結果とデータ期間を追跡可能にする。

## 9. Explainability

Recommendationには少なくとも以下を説明可能にする。

```text
Why selected?
- score_per_hour
- expected_value
- action_horizon

Why trusted?
- component confidence
- market freshness
- market stability / model applicability

Why not others?
- filter rejection
- score loss
- confidence threshold
```

市場が `VOLATILE` / `NOT_APPLICABLE` の場合、LLMに「たぶん価格が下がる」等の推測をさせない。決定論的に「過去観測から価格予測モデルの適用条件を満たさない」と説明する。

## 10. Phase 2-5実装順序

### Phase 2-5A — Historical Market Dataset

- EDDN historical archive/import adapter
- Replay Dataset schema/fixture
- station×commodity時系列再構成
- observation gap handling
- future leakage regression test

Exit:

- 過去市場データをfixture/実データから再生できる
- observed_at順で再現できる
- T0より未来のデータがT0入力へ混入しない

### Phase 2-5B — Market Stability / Model Applicability

- price volatility metrics
- demand volatility metrics
- observation density
- STABLE/MODERATE/VOLATILE/INSUFFICIENT classification
- model applicability gate
- Historical Replayによる分類妥当性評価

Exit:

- 変動性が高い市場を再現可能なルールで検出できる
- `INSUFFICIENT` と `STABLE` を混同しない
- stability factorをscore式へ入れない
- VOLATILE市場で価格予測モデルを正常な予測値として使用しない
- 過去データでVOLATILE判定市場の予測誤差が増えることを確認できる、または相関が確認できず判定基準を再設計する

### Phase 2-5C — Confidence / Freshness

- component confidence composition
- source-specific freshness rules
- market stability/model applicabilityとの接続
- confidence ReasonFact

Exit:

- identical input produces identical confidence
- freshness calculation is deterministic
- source-specific freshness is explicit
- confidence threshold 0.50 remains ranking policy unchanged

### Phase 2-5D — Explainability / Backtest Reporting

- ReasonFact propagation
- DataSource propagation
- recommendation explanation
- Historical Replay report
- optional LLM narration boundary/validator

Exit:

- CLIのみでRecommendationを完全説明できる
- prediction vs actual reportを生成できる
- ranking outcomeを過去データで評価できる
- narrationがなくても意思決定情報が失われない

## 11. Acceptance Tests

追加する必須テスト:

```text
Historical EDDN ordering
Future leakage prevention
Observation gap handling
Price volatility calculation
Demand volatility calculation
Insufficient observation classification
Stable/Moderate/Volatile classification determinism
Volatile market model applicability gate
Stability does not alter score formula
Replay prediction at T0
Actual observation lookup at T0 + predicted horizon
Prediction vs actual delta calculation
Prediction error metrics
Ranking outcome evaluation
Market freshness calculation
Source-specific freshness behavior
Confidence product calculation
ReasonFact generation at calculation stage
DataSource propagation
Identical input => identical confidence/explanation
```

## 12. Non-goals

Phase 2-5では以下を行わない。

- 他プレイヤー数・行動の予測
- 価格の将来値そのものを高精度に予測する新規MLモデルの構築
- volatilityをscoreへ直接掛ける補正
- 銀河全体の恒久的な市場DBサービス化
- EDDN観測だけで「自分が実際に得た利益」を確定すること

## 13. Design Exit

この設計を実装へ進める条件:

- [x] Phase 2-4 Rankingが完了している
- [x] 市場変動性をscore式へ入れない方針が確定している
- [x] 過去EDDNをHistorical Replay Datasetとして利用する方針が確定している
- [x] 他プレイヤーの行動予測ではなく市場結果の変動性を見ることが確定している
- [x] VOLATILE市場では価格予測モデルを適用不能とする方針が確定している
- [x] `STABLE/MODERATE/VOLATILE/INSUFFICIENT` の4状態を採用する
- [x] EDDN Replayと本人Journal E2Eを別評価にする
- [x] 推定時間後の実績値を主要な実用評価とする方針が確定している
- [x] Phase 2-5A実装（`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md`のラベルでの実装。commit `4b4d782`。本書内部ラベルの「2-5A（Historical Market Dataset）」「2-5B（Market Stability分類）」相当を含むが、Model Applicability Gateの配線・Historical Replayによる閾値較正は未着手のまま）
- [x] Phase 2-5B/2-5C実装（本書§7/§7.2のConfidence合成。`app/scoring/confidence.py`新設、`calculate_value()`の`ValueResult`化、`app/scoring/pipeline.py`統合。260→273テスト）
- [ ] Phase 2-5D実装（ReasonFact retrofit / DataSource propagation / narration / Recommendation explanation — §8/§9、未着手）
