# EDpj Market Predictability / Volatility Specification

**Version:** 0.1  
**Status:** Phase 2 Design Baseline  
**Date:** 2026-09-05  
**Target:** `SPECIFICATION_V0.7.md` / `IMPLEMENTATION_SPEC_V0.2.md`  
**Introduced:** Phase 2-5A  
**Revision note (実装前レビュー):** §3.3として取得戦略（on-demand、bulk import禁止）を追記。実データ検証により、外部アーカイブ`https://edgalaxydata.space/EDDN/`が実在し取得可能であることを確認済み（日次`Commodity-YYYY-MM-DD.jsonl`、2017年8月〜現在、非圧縮、1日あたり約0.9GB）。

## 1. Purpose

EDpjの市場価値評価では、他プレイヤーが大量に売却する可能性そのものを直接予測して `score_per_hour` を補正しない。

理由:

- 誰がどの市場に注目しているかは観測できない
- 他プレイヤーの将来行動を直接予測する教師データを安定して取得できない
- 同じ共有サーバー上の市場であっても、観測されない売買行動が存在する

そこで、過去の市場観測から **station × commodity 単位の市場変動性 / 予測可能性** を独立して評価する。

```text
Historical EDDN observations
        ↓
Market Stability / Volatility Analysis
        ↓
「この市場は価格予測モデルを適用できるか？」
        ↓
┌──────────────┬──────────────────┐
│ predictable  │ prediction usable │
│ volatile     │ prediction unsafe │
│ insufficient │ insufficient      │
└──────────────┴──────────────────┘
```

**変動性指標は `score_per_hour` の式に含めない。**

変動が激しく、過去から将来価格を安定して説明できない市場では、価格予測モデルそのものを `unusable` と判定する。

## 2. Scope

対象:

- EDDN archive / historical market observations
- `station_id × commodity_id` の時系列分析
- price volatility
- demand volatility
- forecast errorとの関係検証
- price prediction model applicability判定
- backtest / leakage防止

対象外:

- 他プレイヤー個人の行動予測
- 「大量売却確率」を直接スコアへ加算・減算するモデル
- volatilityを `expected_action_value` の補正係数にすること
- volatilityを `score_per_hour` の乗数にすること
- 将来価格を確定値として扱うこと
- 現行ランキングロジック（Phase 2-4）の変更

## 3. Data Source Policy

### 3.1 EDDN

EDDN本体はlive message brokerであり、過去データの永続アーカイブを正本として提供するものではない。過去データは外部のEDDN archive / data dumpを取得して利用する。

アーカイブ由来データには必ず以下を保持する。

```text
station_id
commodity_id
observed_at
received_at
buy_price
sell_price
supply
demand
source
archive_batch / source_identifier
```

### 3.2 観測欠損

観測が存在しないことを「価格が安定していた」と解釈しない。

EDDNは観測共有であり、観測頻度・参加者・listener downtime等によって欠損する可能性があるため、観測間隔も分析対象メタデータとして保持する。

### 3.3 取得戦略（実装前レビューで追記、確定）

**確定: on-demand取得のみ。全銀河のbulk importは行わない。** アーカイブの1日分ファイルは非圧縮で約0.9GB（`Commodity-YYYY-MM-DD.jsonl`）あり、分析に必要な期間（例: 90日）を丸ごと取り込むと数十GB規模になる——シングルプレイヤー向けCLIツールの規模に対して明らかに過大であり、Phase 1で確立した「Spansh/EDDNはon-demandのみ取得し、bulk importしない」という既存方針とも矛盾する。

```text
候補生成 → Value計算で実際に参照した (station_id, commodity_id)
        ↓
その (station_id, commodity_id) についてのみ
        ↓
必要な観測期間（named configuration、例: 直近90日）分だけ
        ↓
該当日のjsonlをストリーミングで読み、対象station_id/commodity_idの行だけ抽出
        ↓
station×commodityの時系列（3-4節）を構築
        ↓
派生結果（market_predictability、§11）だけ永続化。生のアーカイブ行は保持しない
```

Value計算とHistorical分析の対象を一致させる（「実際にこの候補のValueが依存したMarket観測」だけを分析する）ことで、無関係なstation/commodityのアーカイブを取得する理由がそもそも発生しない。

## 4. Market Time Series

基本単位は:

```text
(station_id, commodity_id)
```

同一marketについて `observed_at` 昇順に並べる。

古い観測から新しい観測への変化を評価し、将来情報を過去時点の特徴量へ混入させない。

### 4.1 Observation gap

隣接観測の時間差が極端に大きい場合、その2点を単純な連続価格変化として扱わない。

初期実装では最大gapをnamed configurationとして定義し、超過した区間はreturn/volatility計算から除外する。

欠損区間を0変動として補間してはならない。

### 4.2 Price change

基本指標は相対変化率とする。

```text
price_return_t = (price_t - price_(t-1)) / price_(t-1)
```

価格が0または無効な観測は変化率計算から除外する。

必要に応じてlog returnを診断用に併記してよいが、MVPの判定基準はrelative changeを正本とする。

### 4.3 Demand change

同様に需要変化を測定する。

```text
demand_delta_t = (demand_t - demand_(t-1)) / max(demand_(t-1), demand_floor)
```

`demand_floor` は0除算防止のnamed configurationとする。

価格と需要は別々に評価する。需要が大きく変動しても価格が安定する市場、またはその逆を区別できるようにする。

## 5. Volatility Indicators

MVPでは単一の「他プレイヤー大量売却確率」を作らず、以下の観測統計を保存する。

```text
sample_count
observation_window
median_abs_price_change
p95_abs_price_change
median_abs_demand_change
p95_abs_demand_change
median_observation_gap
p95_observation_gap
```

必要に応じて:

```text
price_direction_change_rate
large_drop_rate
large_demand_drop_rate
```

を診断情報として追加できる。

### 5.1 Large drop

「大量売却による急落」に近い現象を診断するため、price decrease側のtailも独立して保存する。

```text
price_drop_t = max(0, -price_return_t)
```

ただし、急落が発生した原因を「他プレイヤーの大量売却」と断定してはならない。これは市場変動の観測事実であり、原因推定ではない。

## 6. Predictability is Different from Volatility

単にvolatilityが高いだけでは「価格予測モデルが使えない」と決めない。

Phase 2-5Aでは、次の関係をhistorical replayで検証する。

```text
past-only volatility features at T0
                 ↓
       price prediction at T0
                 ↓
       actual observation after T0
                 ↓
          forecast error
```

目的は:

> 「T0以前に観測できた市場変動性から、その後の価格予測誤差が大きくなることを検証できるか」

である。

つまり、volatility indicatorはそれ自体をscoreへ入れるのではなく、**prediction applicability classifierの説明変数**として扱う。

## 7. Historical Backtest

### 7.1 Replay point

各backtest point `T0` について、入力として使用できるのは `observed_at <= T0` のデータだけとする。

```text
┌────────────── past ──────────────┐│future│
                                T0
                                  ↓
                          prediction input
```

`T0`より後の観測をvolatility feature、model fitting、threshold selectionへ使用してはならない。

### 7.2 Evaluation horizon

未来の評価点は、候補action horizonまたはnamed evaluation horizonに基づいて決定する。

評価点が存在しない場合はそのbacktest sampleを評価対象から除外し、成功扱いにはしない。

### 7.3 Forecast metrics

最低限:

```text
absolute_error = abs(predicted - actual) / actual
signed_error   = (predicted - actual) / actual
median_absolute_error
p95_absolute_error
median_signed_error
```

価格が存在しない、またはinvalidな評価点は`INSUFFICIENT`として扱う。

## 8. Applicability Classification

初期分類は4状態とする。

```text
STABLE
MODERATE
VOLATILE
INSUFFICIENT
```

ただし、**STABLE / MODERATE / VOLATILE の数値境界は先に固定しない。** 実データで以下を検証してからnamed configurationとして固定する。

1. volatility featureとfuture forecast errorの関係
2. low/high volatility群のforecast error分布差
3. high volatility群でprediction failureが再現可能か
4. sample countによる見かけの相関ではないか

### 8.1 Model unusable

以下を満たす市場は、価格予測モデルを適用不可とする。

```text
market_predictability = "unusable"
```

その場合:

- 将来価格予測値を `expected_action_value` の根拠として使用しない
- volatilityを数値補正としてscoreへ混ぜない
- recommendationで「価格予測モデル適用不可」を理由として説明可能にする

**MVPでは「unusable」の閾値を恣意的に決めない。** Backtest結果から閾値を決定する。

## 9. Interaction with Unified Scoring

Phase 2-4で確定したranking式は変更しない。

```text
score_per_hour
 = expected_action_value / action_horizon_hours
```

Market predictabilityは次の位置に入る。

```text
Market observation
       ↓
Value calculation
       ↓
Market Predictability Gate
       ├─ usable      → value/prediction may be used
       └─ unusable    → candidate becomes value-incomplete
                              ↓
                         Recommendation対象外
```

したがって、volatilityを次のようには実装しない。

```python
score *= volatility_factor       # forbidden
expected_value *= stability      # forbidden
confidence *= volatility_factor  # forbidden as a score correction
```

市場予測が使えないなら、**その市場を予測値でランキングすること自体を止める**。

## 10. Confidence / Explainabilityとの境界

Phase 2-5AではvolatilityをRecommendation confidenceへ直接乗算しない。

理由はconfidenceとpredictabilityが異なる概念だからである。

```text
confidence
  = input/data quality / freshness / timing certainty

predictability
  = historical market behaviorから見た価格予測モデルの適用可能性
```

将来、Explainabilityで以下を表示することは可能とする。

```text
Market predictability: VOLATILE
Price prediction: unavailable / not applicable
Reason: historical forecast error is too high for this market class
```

この表示はranking scoreを補正するものではない。

## 11. Persistence

MVPでは既存の`market_snapshots`を保持し、履歴分析用の派生結果は別モデル/テーブルへ分離する。

候補:

```text
market_predictability
----------------------
station_id
commodity_id
sample_count
window_start
window_end
median_abs_price_change
p95_abs_price_change
median_abs_demand_change
p95_abs_demand_change
median_observation_gap
p95_observation_gap
volatility_class
predictability_status
forecast_median_absolute_error
forecast_p95_absolute_error
forecast_sample_count
model_version
computed_at
```

市場観測そのものを上書きしない。派生値は再計算可能な分析結果として扱う。

**Phase 2-5Aでは既存`market_snapshots`のretention約3日方針を、historical analysis用archiveまで同一DBへ保存することを意味するよう拡張しない。** 長期EDDN archiveは分析入力として別保管し、MVPの運用DBへ無期限保存しない。

## 12. CLI

Phase 2-5Aで以下を追加候補とする。

```bash
edpj market predictability analyze --station <station_id> --commodity <commodity_id>
edpj market predictability backtest --from <datetime> --to <datetime>
edpj market predictability status --station <station_id> --commodity <commodity_id>
```

CLIはLLM不要で決定論的に実行できること。

## 13. Test / Exit Criteria

### Unit

- 時系列ソート
- observation gap除外
- 欠損区間を0変動にしない
- price return境界
- demand change境界
- price=0 handling
- demand=0 handling
- p95計算
- sample不足 → `INSUFFICIENT`
- past-only feature生成
- future leakage防止

### Backtest

- T0より後の観測がfeatureに入らない
- model fitとevaluationを時系列分離する
- high volatility群とlow volatility群のforecast errorを比較できる
- prediction unusable判定が再現可能

### Exit

Phase 2-5A完了条件:

- [ ] historical EDDN archiveをon-demandで（対象station×commodity・必要期間分のみ、bulk importせず）分析入力として取り込める
- [ ] station × commodity時系列を再構成できる
- [ ] price / demand volatilityを独立測定できる
- [ ] observation gap / missingnessを正しく扱える
- [ ] past-only replayが実装されている
- [ ] volatilityとfuture forecast errorの関係を評価できる
- [ ] `STABLE / MODERATE / VOLATILE / INSUFFICIENT` の分類基準がデータから決定されている
- [ ] `VOLATILE`市場でprediction modelを`unusable`にできる
- [ ] volatilityをscore_per_hourの式へ入れていない
- [ ] ranking orderを変更していない
- [ ] 既存233 testsが回帰なしで通る

## 14. Phase Integration

現在のEDpj進行は **Phase 2-4 Ranking完了（commit `0fd9182`）** である。

従って、この仕様はPhase 2-4へ遡って実装しない。

次のPhaseを以下へ再編する。

```text
Phase 2-4  Ranking
    ↓ COMPLETE
Phase 2-5A  Market Predictability / Volatility
    ↓ COMPLETE
Phase 2-5B  Confidence / Explainability
    ↓
Phase 2-6  Historical Ranking Backtest / Accuracy Gate
    ↓
Phase 3  Bio
    ↓
Phase 4  UI
```

### Phase 2-5A

目的:

- EDDN historical archiveを利用可能にする
- 市場の変動性を定量化する
- 「価格予測モデルが使える市場 / 使えない市場」を実証的に判定する

**Rankingは変更しない。**

### Phase 2-5B

従来予定していたConfidence / Explainabilityを実施する。

ただし、Market Predictabilityをconfidenceの単純な乗数にはしない。

Recommendationでは必要に応じて:

```text
market_predictability
prediction_applicability
```

を構造化factとして参照できるようにする。

### Phase 2-6

Phase 2-5Aで作ったhistorical replay基盤を使い、EDpj全体のranking accuracyを検証する。

評価対象:

- State Accuracy
- Value Prediction Accuracy
- Horizon Prediction Accuracy
- Ranking Accuracy
- Recommendation applicability

ここで初めて「実際に最も稼げる行動を選べているか」を評価する。

## 15. Design Invariants

1. 他プレイヤーの大量売却確率を直接予測しない。
2. volatilityをscoreの補正係数にしない。
3. volatilityをconfidenceの単純な乗数にしない。
4. 高volatilityでprediction modelが成立しない場合は、予測値を使ったrankingからcandidateを外す。
5. EDDNの観測欠損を安定性と解釈しない。
6. `T0`より未来のデータを`T0`時点の特徴量へ混入させない。
7. volatility classificationの閾値を恣意的に先決定しない。
8. 原因を観測できない場合、「他プレイヤーの大量売却が原因」と断定しない。
9. Phase 2-4の`score_per_hour`とtie-break/ranking orderを変更しない。
10. LLMはpredictability判定、threshold、ranking、value calculationの権限を持たない。
11. Historical EDDN archiveはon-demandでのみ取得する（実際にValue計算が参照したstation×commodity、必要期間分のみ）。全銀河のbulk importは行わない（§3.3）。
