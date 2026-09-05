# EDpj Phase 2-6B Volatility Evaluation Implementation Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/volatility_evaluation.py`新設、`app/backtest/replay.py`へ`generate_t0_checkpoints`/`collect_replay_samples`追加。既存308テスト+新規23テスト、計331テスト全通過。Exit Criteria全項目達成）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §4/§8/§9（v0.1, commit `013d92c`）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`（v0.2, commit `c4bbe8e`）, `app/backtest/replay.py`, `app/market/predictability.py`, `app/market/volatility.py`, `app/calibration/metrics.py`

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
