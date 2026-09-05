# EDpj Phase 2-6B Volatility Evaluation Implementation Baseline

**Version:** 0.2
**Status:** ツール実装Implemented（v0.1/v0.2、420テスト全通過）／**探索的評価：継続保留**（§17.2）— コードは完成・実データで動作確認済みだが、候補stationが3件（うち実質1件のみ価格変動あり）に限られるため`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`の採用判断には進めない。本人の新規station Docked（`MarketSnapshot`蓄積）を待って再開する
**Date:** 2026-09-05
**Revision note（v0.2、実データ20×7 Model Validation Runで発見）**: `median_abs_price_change`（現行`classify()`の分類基準）が、隣接観測ペアの過半数が無変化の場合に構造的に0へ張り付くこと、およびforecast_errorとのSpearman相関がN=20で`median=0.806`に対し`p95_abs_price_change`/`nonzero_change_ratio`/`max_abs_price_change`が`0.90〜0.94`と有意に強いことを実測で発見した（`pair_n`単体は`-0.126`でほぼ無相関——観測数の多さが相関の交絡ではないことも確認済み）。v0.2は「p95をそのまま新閾値に採用する」のではなく、**指標選定→閾値感度分析→分類→forecast error評価**という評価プロセスそのものを追加する（§16）。§0〜§15の既存決定・既存関数（`classify()`, `aggregate_by_volatility_class()`, `evaluate_ordering_hypothesis()`, `MIN_SAMPLES_FOR_EVALUATION`等）は変更しない。
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §4/§8/§9（v0.1, commit `013d92c`）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`（v0.2, commit `c4bbe8e`）, `docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`（v0.2, commit `43f2604`、実データ20×7 Model Validation結果）, `app/backtest/replay.py`, `app/market/predictability.py`, `app/market/volatility.py`, `app/calibration/metrics.py`

## 0. スコープ

Phase 2-6Bは以下のみを実装する。

```text
1. T0を複数生成するsweep（2-6Aは単一T0の評価のみ提供）
2. sweepしたReplaySampleをvolatility_classごとに集計（median/p95 forecast error）
3. STABLE < MODERATE < VOLATILE の順序関係（Design Baseline §4.2）の検証
4. STABLE/VOLATILEをMAE_THRESHOLD（app/calibration/metrics.py既存定数）と比較する評価
```

**明示的にスコープ外:**

```text
- 閾値の再配置そのもの（STABLE_MEDIAN_PRICE_CHANGE/MODERATE_MEDIAN_PRICE_CHANGEの
  値を変える探索）
  -- docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md §4.2は
  「この順序関係が実データで成立するかを検証する」までを2-6Bの仕事とし、
  「成立しない場合にどう再配置するか」は§9のGo/No-Go基準に基づく決定で
  あり、2-6Bは判定材料（順序関係が成立するかどうかの事実）を作るだけ。
  再配置の探索・実行はPhase 2-6E（採用値確定）の仕事。
- demand volatilityとforecast errorの相関測定
  -- Design Baseline §4.3が定義する評価だが、本書は§4.2の順序関係
  （price volatility側）に絞る。demand側は必要になった時点で別途
  Implementation Baselineを立てる（今存在しない機能を先に作らない）。
- 実データに対する実行・Go/No-Go判定そのもの
  -- 本Phaseはツール（測定・集計・検証コード）を作るところまで。
  実際にEDDN archiveへ接続してreal dataを流し、結果を見てGo/No-Go判定を
  下すのはPhase 2-6E。
- score_per_hour式への補正の追加（既存のNon-goals継続）
```

## 1. `app/backtest/replay.py`への追加（T0 sweep）

2-6Aは単一T0の評価（`evaluate_forecast_at`）のみを提供する。2-6Bは複数T0にわたる評価が必要（Design Baseline §4.1: 「各(station_id, commodity_name)についてT0時点のvolatility classを算出する」を複数T0で繰り返す）。2-6Cも同じsweepを別の集計軸（age別）で使うため、sweep自体はvolatility_class集計から独立した`app/backtest/replay.py`（2-6Aのモジュール）へ追加し、volatility_class固有の集計は新設の`app/backtest/volatility_evaluation.py`（本書）に置く。

```python
# app/backtest/replay.py への追加

def generate_t0_checkpoints(
    window_start: dt.datetime, window_end: dt.datetime, interval: dt.timedelta
) -> list[dt.datetime]:
    """window_startからwindow_endまでintervalおきのT0候補を生成する純粋関数。
    観測のobserved_atに依存しない固定間隔サンプリングを使う -- 観測タイミング
    に同期させると常に「直前の観測からの経過時間がほぼ0」のT0だけを評価する
    ことになり、predict_naive_persistenceが実際に晒される多様なfreshness
    (2-6Cが検証する範囲)をsweepできない。"""


@dataclass(frozen=True)
class ReplaySampleCollection:
    samples: list[ReplaySample]
    checkpoints_without_prediction: int  # evaluate_forecast_at()がNoneを返した回数


def collect_replay_samples(
    session: Session, station_id: int, commodity_name: str, checkpoints: list[dt.datetime],
    window_days: int, horizon: dt.timedelta,
) -> ReplaySampleCollection:
    """各T0についてevaluate_forecast_at()を呼ぶだけの薄いループ。Noneは
    samplesに含めず、件数だけcheckpoints_without_predictionに積算する
    -- 「T0以前に観測が1件もなかった」ことと「実測が見つからずforecast_error=None
    だった」ことは別の意味であり(spec §4.3)、後者はReplaySample自体は
    samplesに含まれ、forecast_error=Noneとして残る。"""
```

## 2. Volatility Class集計（新設 `app/backtest/volatility_evaluation.py`）

```python
@dataclass(frozen=True)
class ClassForecastErrorStats:
    volatility_class: VolatilityClass
    sample_count: int  # forecast_errorがNoneでないReplaySampleの数
    missing_actual_count: int  # このclassでforecast_error=NoneだったReplaySampleの数
    median_forecast_error: float | None
    p95_forecast_error: float | None


def aggregate_by_volatility_class(samples: list[ReplaySample]) -> dict[VolatilityClass, ClassForecastErrorStats]:
    """samplesをprediction.volatility_classでグルーピングし、
    forecast_errorがNoneでないものだけからmedian/p95を計算する。
    median/p95の計算はapp.market.volatility.median_and_p95()をそのまま
    再利用する -- app/calibration/metrics.pyの median_absolute_error() は
    "1つの予測値 vs 複数の実測値" という別の形状(1つのcalibrated estimateを
    複数のheld-outサンプルで検証する)であり、本書が扱う"複数の独立した
    (predicted, actual)ペアそれぞれの相対誤差の分布"とは前提が異なるため
    使わない -- median_and_p95()はまさにこの形状(app/market/predictability.py
    のprice_change_ratio値のリスト)を対象に既に使われている関数。"""
```

**確定: volatility_classが1つも出現しなかった場合、そのclassのキーは返り値の辞書に含めない**（`ClassForecastErrorStats(sample_count=0, ...)`を人工的に作らない — 「0件だった」と「INSUFFICIENT判定だった」を混同しないため、存在しないキーとして表現する）。

## 3. 順序関係の検証（Go/No-Go判定材料の生成）

```python
@dataclass(frozen=True)
class OrderingHypothesisResult:
    class_stats: dict[VolatilityClass, ClassForecastErrorStats]
    ordering_holds: bool | None
    stable_within_mae_threshold: bool | None
    volatile_exceeds_mae_threshold: bool | None


MIN_SAMPLES_FOR_EVALUATION = 30  # 暫定値。2-6Eで実データの母数を見て再検討する


def evaluate_ordering_hypothesis(
    class_stats: dict[VolatilityClass, ClassForecastErrorStats],
) -> OrderingHypothesisResult:
    """Design Baseline §4.2の順序関係(median(STABLE) < median(MODERATE) < median(VOLATILE))
    と、§9.2のMAE_THRESHOLD比較(app.calibration.metrics.MAE_THRESHOLD = 0.20)を
    まとめて評価する。

    ordering_holds:
        STABLE/MODERATE/VOLATILEの3クラス全てがsample_count >= MIN_SAMPLES_FOR_EVALUATION
        を満たす場合のみ True/False を返す。1クラスでも満たさなければ None
        (判定不能 -- 「順序関係が成立しない」と「データ不足で判定できない」
        を混同しない、Design Baseline §9.1のvalidation_statusパターンと
        同じ考え方)。

    stable_within_mae_threshold:
        STABLEのsample_count >= MIN_SAMPLES_FOR_EVALUATION なら
        (median_forecast_error <= MAE_THRESHOLD)、そうでなければ None。

    volatile_exceeds_mae_threshold:
        VOLATILEのsample_count >= MIN_SAMPLES_FOR_EVALUATION なら
        (median_forecast_error > MAE_THRESHOLD)、そうでなければ None。

    このいずれも、Design Baseline §9.2が要求する「別の閾値配置を試す」
    ことはしない -- 現行のclassify()閾値のもとでの事実を報告するだけ。
    """
```

**この関数はGo/No-Go判定そのものではない**。§9.2/§9.3の実際の「閾値を変更する/維持する」という決定は、実データにこの関数を適用した結果を人間（または2-6E）が読んで下す。`evaluate_ordering_hypothesis`自体は決定論的な事実の集計であり、恣意的な閾値の後付け変更を許さない（Design Baseline §0の中心原則の繰り返し）。

### 3.1 `MIN_SAMPLES_FOR_EVALUATION`の位置づけ

`app/market/predictability.py`の`MIN_SAMPLES_FOR_CLASSIFICATION = 10`と混同しない。前者は「1つの`(station_id, commodity_name, window)`のvolatility classificationを信頼するための価格観測ペア数」、`MIN_SAMPLES_FOR_EVALUATION`は「1つのvolatility classについて、forecast errorのmedianを比較材料として信頼するためのReplaySample数」であり、対象が異なる別の閾値。30という値は一般的な最小サンプルサイズの経験則であり、Design Baseline §9.1と同じく「実データの母数を見てから再検討する暫定値」と明記する。

## 4. Acceptance Tests

```text
generate_t0_checkpoints()がwindow_start/window_end/intervalから決定論的にT0列を生成する
   （境界値: window_start自身を含む/含まないの挙動が明示されている）
collect_replay_samples()がNoneを返したT0をcheckpoints_without_predictionへ計上し、
   samplesには含めない
collect_replay_samples()がforecast_error=NoneのReplaySampleをsamplesに含める
   （missing_actual_countの元データとして必要）
aggregate_by_volatility_class()がvolatility_classごとに正しくグルーピングする
aggregate_by_volatility_class()がforecast_error=Noneのサンプルをmedian/p95計算から除外し、
   missing_actual_countとしてのみ計上する
aggregate_by_volatility_class()が一度も出現しなかったclassをキーに含めない
evaluate_ordering_hypothesis()がSTABLE/MODERATE/VOLATILE全てにMIN_SAMPLES_FOR_EVALUATION
   以上のsample_countがある場合にのみordering_holdsをTrue/Falseで返す
evaluate_ordering_hypothesis()がいずれかのclassでsample_count不足の場合、
   対応するフィールドをNoneにする（0件を「False」や「順序不成立」と混同しない）
evaluate_ordering_hypothesis()がmedian(STABLE) < median(MODERATE) < median(VOLATILE)の
   人工的なfixtureでordering_holds=Trueを返す
evaluate_ordering_hypothesis()が順序が崩れたfixtureでordering_holds=Falseを返す
median_and_p95()の再利用によりp95計算ロジックが二重実装されていない
   （app.market.volatility.median_and_p95と同一関数であることの参照テスト）
```

## 5. Exit Criteria

- [x] `app/backtest/replay.py`に`generate_t0_checkpoints`/`collect_replay_samples`/`ReplaySampleCollection`が追加され、既存の`evaluate_forecast_at`/`compare_windows`に回帰がない
- [x] `app/backtest/volatility_evaluation.py`が新設され、`ClassForecastErrorStats`/`aggregate_by_volatility_class`/`OrderingHypothesisResult`/`evaluate_ordering_hypothesis`が実装されている
- [x] `aggregate_by_volatility_class`が`app.market.volatility.median_and_p95`を再利用し、median/p95計算を二重実装していない
- [x] `evaluate_ordering_hypothesis`が閾値の再配置を一切行わず、現行`classify()`のもとでの事実のみを報告することがテストされている
- [x] `MIN_SAMPLES_FOR_EVALUATION`未満のclassについて`ordering_holds`/`stable_within_mae_threshold`/`volatile_exceeds_mae_threshold`が`None`になり、`False`と区別されることがテストされている
- [x] 一度も出現しなかったvolatility_classが`aggregate_by_volatility_class`の返り値に人工的な0件エントリとして現れないことがテストされている
- [x] 既存308テストに回帰がない

## 6. 決定事項サマリ

1. **§1 T0 sweepは2-6Aのモジュール（`app/backtest/replay.py`）へ追加**: volatility_class集計から独立した汎用機能であり、2-6Cも同じsweepを別の集計軸で再利用するため
2. **§2 median/p95は`app.market.volatility.median_and_p95`を再利用**: `app.calibration.metrics.median_absolute_error`は「1予測値 vs 複数実測値」という別の形状のため使わない。二重実装を避けるため既存の`median_and_p95`（同じ「相対誤差の分布」形状）を採用
3. **§3 閾値の再配置は2-6Bのスコープ外**: `evaluate_ordering_hypothesis`は現行閾値のもとでの事実（順序関係が成立するか、STABLE/VOLATILEがMAE_THRESHOLDのどちら側か）を報告するのみ。閾値変更の探索・実行は2-6E
4. **§3 データ不足はNoneで表現**: `MIN_SAMPLES_FOR_EVALUATION`未満のclassは`False`ではなく`None`を返し、「順序不成立」と「判定不能」を混同しない

## 16. Metric Selection & Threshold Sensitivity（v0.2で追加）

### 16.1 発見した問題（実測）

`docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md` §15のDiverse Selectorで得た実データ20×7 Model Validation Runで、`_compute_volatility_stats`の`median_abs_price_change`（現行`classify()`の分類基準）がHoffmanの16 targetすべてで**正確に0.00000**になった——隣接観測ペアの過半数が無変化（sell_priceが1件も動かない）の場合、中央値という統計量は構造的に0へ張り付く。

同じデータでtargetごとのforecast_error（median）とのSpearman相関（N=20）を計測したところ：

```text
pair_n（生観測数）        -0.126  （ほぼ無相関 -- 観測数の多さが交絡ではないことの確認）
zero_ratio                0.194  （弱い）
median_abs_price_change   0.806  （現行の分類基準。構造的欠陥ありだが無相関ではない）
nonzero_change_ratio      0.941
p95_abs_price_change      0.941
max_abs_price_change      0.941
```

Volatilityとforecast errorの関係自体は実在する（`pair_n`の無相関が交絡でないことを裏付ける）。ただし現行の`median_abs_price_change`はこの関係を捉える力が相対的に弱い。

### 16.2 中心原則: 「p95が高相関だった」を即座に閾値へ採用しない

**やってはいけないこと**: 「p95_abs_price_changeがforecast errorと相関した」という結果を、そのまま`STABLE_MEDIAN_PRICE_CHANGE`を`p95`ベースの値へ置き換える根拠にすることはしない。相関の確認と閾値の採用は別工程であり、混同すると「都合の良い指標を選んでから、その指標が効くことを確認しただけ」になる。

v0.2で追加するのは**プロセスそのもの**である。

```text
16.1 指標評価（相関）    -- 済み。§16.1の表がその結果
        ↓
16.2 閾値感度分析        -- 候補閾値ごとに分類結果を機械的に生成
        ↓
16.3 Classification      -- 各閾値候補でのSTABLE/MODERATE/VOLATILE/INSUFFICIENT分布
        ↓
16.4 Forecast Error評価  -- 既存のevaluate_ordering_hypothesis()をそのまま再利用
        ↓
16.5 採用判定            -- 人間のレビュー。ここでもdecide_volatility_adoption()等の
                            自動判定は行わない
```

この一連の処理は`app/market/predictability.py`の`classify()`/`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`を一切参照・変更しない——本番の分類ロジックとは完全に独立した評価専用コードとして実装する（§0の「実装した閾値に合わせて分析する逆転を起こさない」原則の継続）。

### 16.3 候補指標（固定）

```text
CANDIDATE_METRICS = (
    "median_abs_price_change",  # 現行。比較対象として残す
    "p95_abs_price_change",     # 第一候補（primary） -- 外れ値1件に引っ張られるmaxより頑健、
                                 # medianの0張り付きを回避、相関0.941
    "nonzero_change_ratio",     # 第二候補（activity） -- 「価格が変化する頻度」であり
                                 # 変動の大きさそのものとは異なる概念、相関0.941
    "max_abs_price_change",     # 診断用（diagnostic） -- 相関は強いが1回の異常値に敏感、
                                 # 採用候補というよりp95の妥当性を確認する補助指標
)
```

`nonzero_change_ratio`と`p95_abs_price_change`は意図的に別々の特徴量として評価する——前者は「変化の頻度」、後者は「変化の大きさ」であり、一つの指標に混ぜない。

### 16.4 実装するコード（新設 `app/backtest/volatility_metric_evaluation.py`）

```python
@dataclass(frozen=True)
class TargetMetrics:
    station_id: int
    commodity_name: str
    pair_count: int
    median_abs_price_change: float | None
    p95_abs_price_change: float | None
    nonzero_change_ratio: float | None
    max_abs_price_change: float | None
    forecast_error_median: float | None
    forecast_error_sample_count: int


def collect_target_metrics(
    session: Session, targets: list[tuple[int, str]],
    window_start: dt.datetime, now: dt.datetime,
    checkpoints: list[dt.datetime], window_days: int, horizon: dt.timedelta,
) -> tuple[list[TargetMetrics], dict[tuple[int, str], list[ReplaySample]]]:
    """targetごとにMarketHistoricalObservationを読み、
    app.market.volatility.pair_observations/price_change_ratioを再利用して
    4指標を計算する（app.market.predictability._compute_volatility_statsは
    呼ばない -- MarketPredictabilityへの依存を作らず、評価コードを本番から
    完全に独立させる）。collect_replay_samples()の結果もtargetごとに返す
    -- §16.2のsweep_metric_thresholds()がcheckpoint単位の再分類に
    再利用するため、二重にサンプル収集しない。"""


def spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    """依存追加を避けるための素朴な実装（順位変換 + statistics.correlation）。
    4件未満はNone -- 暫定的な最小件数であり統計的根拠はない。"""


def compute_metric_correlations(target_metrics: list[TargetMetrics]) -> dict[str, float | None]:
    """§16.1の表を再現可能にする。診断のみ、指標選定の自動判断は行わない。"""


def classify_by_metric(
    value: float | None, sample_count: int,
    stable_threshold: float, moderate_threshold: float,
    min_samples: int = MIN_SAMPLES_FOR_CLASSIFICATION,
) -> VolatilityClass:
    """app.market.predictability.classify()の汎用版。任意の指標値・
    閾値ペアを受け取る。本番コードからは一切呼ばれない。"""


@dataclass(frozen=True)
class ThresholdSweepResult:
    metric_name: str
    stable_threshold: float
    moderate_threshold: float
    class_stats: dict[VolatilityClass, ClassForecastErrorStats]  # 2-6Bの既存型をそのまま再利用
    ordering: OrderingHypothesisResult  # evaluate_ordering_hypothesis()をそのまま再利用


def sweep_metric_thresholds(
    target_metrics: list[TargetMetrics],
    samples_by_target: dict[tuple[int, str], list[ReplaySample]],
    metric_name: str,
    threshold_candidates: list[tuple[float, float]],
    min_samples: int = MIN_SAMPLES_FOR_CLASSIFICATION,
) -> list[ThresholdSweepResult]:
    """§16.2/16.3/16.4。各(stable_threshold, moderate_threshold)候補について、
    targetをclassify_by_metric()で再分類し、そのtargetに属する
    ReplaySampleのforecast_errorをまとめてclass別に集計する
    （checkpoint単位の粒度を保つ -- targetの中央値だけを比較するより
    統計的に妥当）。集計結果はapp.market.volatility.median_and_p95で
    計算し、evaluate_ordering_hypothesis()（2-6Bの既存関数、無改変）へ
    そのまま渡す。決定は行わない -- 結果はThresholdSweepResultのリストとして
    返すのみで、どの閾値を採用するかの自動判断はしない（§16.5）。"""
```

**閾値候補の初期セット（暫定、統計的根拠なし）**: `p95_abs_price_change`について、現行閾値の比（STABLE:MODERATE = 1:3）を維持しつつ、

```text
STABLE_THRESHOLD_CANDIDATES = [0.01, 0.02, 0.03, 0.05, 0.10]
# 対応するMODERATE_THRESHOLDは3倍: [0.03, 0.06, 0.09, 0.15, 0.30]
```

### 16.5 採用判定は本書のスコープ外

`sweep_metric_thresholds()`の出力は、どの`(metric, threshold)`が「良い」かを機械的に選ばない。`ThresholdSweepResult`のリストを人間がレビューし、

- 各class（STABLE/MODERATE/VOLATILE）に`MIN_SAMPLES_FOR_EVALUATION`以上のサンプルがあるか
- `ordering.ordering_holds`が実際にTrueになるか
- class間でmedian forecast errorが単調に悪化するか

を確認したうえで、`docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md` §7の採用手順（独立したレビュー可能コミット）に従って初めて本番定数を検討する。本書のExitはこの採用判断自体を含まない。

### 16.6 Acceptance Tests

```text
collect_target_metrics()がpair_observations/price_change_ratioを再利用し、
   独自の価格ペアリングロジックを持たない
collect_target_metrics()がMarketPredictability/app.market.predictability.classify()を
   一切参照しない（構造的保証）
spearman_correlation()が4件未満の入力でNoneを返す
compute_metric_correlations()がCANDIDATE_METRICSの4指標全てについて相関を返す
classify_by_metric()がsample_count不足時にINSUFFICIENTを返す
   （thresholdの値に関わらず）
sweep_metric_thresholds()が閾値候補ごとに独立したThresholdSweepResultを返す
sweep_metric_thresholds()がevaluate_ordering_hypothesis()を無改変で呼んでいる
   （二重実装がないことの参照テスト）
sweep_metric_thresholds()がapp.market.predictability.STABLE_MEDIAN_PRICE_CHANGE等の
   本番定数を一切参照しない（構造的保証）
sweep_metric_thresholds()がいかなる自動採用判断（GO/NO_GO等）も返さない
   （ThresholdSweepResultに*_decisionフィールドが存在しない）
```

### 16.7 Exit Criteria

- [x] `app/backtest/volatility_metric_evaluation.py`が新設され、`TargetMetrics`/`collect_target_metrics`/`spearman_correlation`/`compute_metric_correlations`/`classify_by_metric`/`ThresholdSweepResult`/`sweep_metric_thresholds`が実装されている
- [x] 4指標（median/p95/nonzero_ratio/max）すべてが`app.market.volatility`の既存関数（`pair_observations`/`price_change_ratio`/`median_and_p95`）を再利用し、価格ペアリングロジックを二重実装していない
- [x] `classify_by_metric()`/`sweep_metric_thresholds()`が`app.market.predictability`の本番定数・`classify()`を一切参照しないことが構造的に保証されている
- [x] `sweep_metric_thresholds()`が`evaluate_ordering_hypothesis()`を無改変で再利用している
- [x] 採用判定（GO/NO_GO相当の自動判断）を返す関数が存在しないことが構造的に保証されている
- [x] 既存403テストに回帰がない

### 16.8 決定事項サマリ

1. **§16.1 相関確認と閾値採用は別工程**: p95等の高相関を即座に新閾値へ採用しない。指標選定→閾値感度分析→分類→forecast error評価というプロセス自体を追加する
2. **§16.3 候補指標を4つに固定**: median（現行、比較用）/p95（primary）/nonzero_ratio（activity、別軸として維持）/max（diagnostic）
3. **§16.4 評価コードは本番から完全独立**: `MarketPredictability`/`classify()`/`STABLE_MEDIAN_PRICE_CHANGE`等を一切参照しない新規モジュールとして実装する
4. **§16.5 採用判定は本書に含まない**: `sweep_metric_thresholds()`は事実（分布・順序関係）を返すのみで、どの閾値を採用するかの決定は2-6E §7の手順に従う人間のレビュー

## 17. 探索結果（中間結論、実データ20×7 Diverse Selection）

**Status:** 探索段階の中間結論。閾値・指標の正式採用ではない。

`docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md` §15のDiverse Selectorで選定した実データ20 target × 7日windowに`compute_metric_correlations()`/`sweep_metric_thresholds()`を適用した結果、以下を**確定してよい**。

```text
1. median_abs_price_changeよりp95_abs_price_changeの方がforecast errorとの
   関係が強い（Spearman相関: median=0.806, p95=nonzero_ratio=max=0.941）
2. p95_abs_price_changeの閾値(0.03, 0.09)で初めてSTABLE/MODERATE/VOLATILE
   の3クラスが出現し、median forecast errorが 0 → 0.034 → 0.060 と
   単調増加した
3. ただしMODERATE(n=3)/VOLATILE(n=3)ともMIN_SAMPLES_FOR_EVALUATION=30に
   遠く及ばず、ordering_holdsはNone（判定材料不足）のまま
```

**未確定のまま残すべきこと**:

```text
- (0.03, 0.09)という具体的な閾値ペアが「唯一の正解」なのか、
  「p95≈0.03/0.09付近に分類境界が存在する」という近傍全体を指すのか
- 別データセットでも同じ3クラス分離・単調増加パターンが再現するか
- 3クラス（STABLE/MODERATE/VOLATILE）という現行の分類粒度自体が適切か、
  それとも「STABLE vs 高変動」の2値分類の方が実データに合うか
  （追加データでMODERATE区間にサンプルが集まらない場合に検討する）
```

### 17.1 次のステップ: 追加データでの再現性確認

**Diverse Selectorの設計は変更しない**——p95が高いcommodityを優先選択するような変更は、2-6B自身が測ろうとしている量（forecast errorとp95の関係）でtarget選定を汚染する選択バイアスになる（§16.2の原則の直接的な帰結）。station diversity・activity filter（`MIN_DISCOVERY_OBSERVATIONS`/`latest_supply > 0`）による現行の`select_diverse_model_validation_targets()`をそのまま使う。

**target数の上限に関する制約（実測）**: 本人の実Docked実績は現在3station（Gcobani/Hoffman/Ross Silo）のみで、そのうちactivityフィルタを満たすeligible commodityは合計30件（Hoffman 26 + Ross Silo 4 + Gcobani 0）——`max_targets`を50に設定しても、現在のcandidate stationプールでは30件で頭打ちになる。50件へ到達するには本人の実プレイでDocked stationを増やすか、`MIN_DISCOVERY_OBSERVATIONS`（現在3）を緩めるかのいずれかが必要——ただし後者は「活性フィルタを弱める」ことであり、「volatilityで選ぶ」こととは異なる別軸の変更である。まずは現在到達可能な30件で再評価する。

再評価で確認する項目（§16.2〜16.4と同一の分析を30 targetで再実行）:

```text
1. 各classのsample数（class不均衡がどの程度緩和されるか）
2. class別median/p95 forecast error
3. Ordering hypothesis（ordering_holdsがTrue/Falseに determinateになるか）
4. (0.03, 0.09)近傍の閾値ペアで結果が安定しているか
   （0.025/0.075, 0.035/0.105等、近傍の閾値でも同様の3クラス分離が
   得られるかを比較する）
```

この結果を見て、2-6E §7の採用判断（p95ベース分類を採用候補にするか、3クラスではなく2値分類を検討するか、あるいはさらなるデータ拡大が必要か）を次に決める。**本番のVolatility閾値（`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`）はこの段階でも変更しない。**

### 17.2 30 targetでの再評価結果 → 探索的評価：継続保留

実際に`select_diverse_model_validation_targets(max_targets=30)`を実行し、§17.1の再評価を行った。

```text
                20 target    30 target
median相関       0.806        0.367
p95相関          0.941        0.783
STABLE           326          526（+200）
MODERATE           3            3（不変）
VOLATILE           3            3（不変）
```

**追加した10 targetは全てHoffman由来**（Ross Siloのeligibleは4件で20 target時点で既に使い切っていた）。10件とも既存のHoffman commodityと同様に静的で、STABLEにのみ積み増しされ、**MODERATE/VOLATILEは1件も増えなかった**。相関係数の低下も、静的なHoffman commodityが希釈的に加わったことで説明できる。

**この結果が確定させたこと**: `MODERATE`/`VOLATILE`のサンプルは事実上Ross Silo（`nonlethalweapons`/`reactivearmour`）由来のみで構成されており、そのeligible poolは4件で頭打ちである。**「target数を増やせば解決する」という仮説はこれで棄却された**——同一station群内でcommodityを増やしても市場状態の多様性は増えない。真のボトルネックは**station多様性**であり、現在の候補station（本人の実Docked実績3件）そのものが狭すぎることが実データで確定した。

**結論（レビューで確定）: 2-6Bをここで一旦クローズし、状態を「探索的評価：継続保留」とする。**

```text
Volatility indicator
    ↓
p95_abs_price_change（medianより有望、相関0.78〜0.94）
    ↓
forecast errorとの関係: 再現性あり（20/30 targetの両方で確認）
    ↓
しかし市場状態の多様性不足（候補stationが3件、うち実質1件のみ変動あり）
    ↓
threshold adoption: 不可（MODERATE/VOLATILEのサンプル数が構造的に増えない）
```

- **本番のVolatility classification（`app/market/predictability.py`の`classify()`/`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`）は現行仕様のまま変更しない。**
- **`(0.03, 0.09)`は「採用候補」ではなく「次回検証時の候補閾値」として本書に保存する**（§17.1に記載済み）。
- **`MIN_DISCOVERY_OBSERVATIONS=3`は今は変更しない**——「候補observation数が少なくとも3程度はないと、そのcommodityの価格変動を評価する意味が薄い」というデータ品質上の意味を持つ値であり、これを緩めてtarget数を水増ししても、同一station内のcommodityが増えるだけでノイズが増える可能性が高い（§17.2で実証済みのパターン）。
- **再開条件**: 本人の実プレイで新しいstationへDockし、Commodities Marketを開いて`MarketSnapshot(source='journal')`が記録される（候補stationが増える）まで、2-6Bの追加評価は行わない。評価のためだけにプレイする必要はなく、通常プレイで自然に条件が満たされるのを待つ。候補stationが増えた時点で、`select_diverse_model_validation_targets()`を再実行し、§16.2〜16.4/§17.1と同じ分析を繰り返す。
- **Bio（生体サンプル探査）の有効性検証はこの市場Volatility検証とは別ライン**であり、Bio Value Model実装後に独立したBacktest/Go-No-Goを設ける。本書のクローズはBio側の作業に影響しない。
