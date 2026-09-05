# EDpj Phase 2-6C Freshness Evaluation Implementation Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/freshness_evaluation.py`新設。既存331テスト+新規20テスト、計351テスト全通過。Exit Criteria全項目達成）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §5/§8/§9（v0.1, commit `013d92c`）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`（v0.2, commit `c4bbe8e`）, `docs/PHASE_2_6B_VOLATILITY_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`（v0.1, commit `51d55e9`）, `app/backtest/replay.py`, `app/backtest/volatility_evaluation.py`, `app/market/volatility.py`, `app/scoring/confidence.py`

## 0. スコープと中心原則

**Freshnessが何秒なら良いのかを決めるのではなく、現行システムでFreshnessと予測誤差がどう関係しているかを測定する。** 2-6Bで確立した「測定結果を見て後付けで都合のいい閾値を設定しない」原則をそのまま継続する。順序は

```text
Baseline測定 → 分布確認 → 境界候補の洗い出し → (2-6EでのGo/No-Go)
```

であり、本Phaseは最初の2段階（測定・分布確認）と「境界候補を洗い出せる形の集計」までを実装する。**新しいFRESHNESS_FULL_THRESHOLD/FRESHNESS_FLOOR_THRESHOLD/FRESHNESS_FLOORの値を決定しない。**

Phase 2-6Bは`ReplaySample`を`prediction.volatility_class`でグルーピングした。Phase 2-6Cは同じ`ReplaySample`を**`prediction`が根拠にした観測の鮮度（T0時点でのage）**でグルーピングする——これは別の軸であり、`collect_replay_samples()`が返す1つの`ReplaySampleCollection`を2-6B/2-6Cの両方の集計にそのまま使い回せる（§5）。

**明示的にスコープ外:**

```text
- FRESHNESS_FULL_THRESHOLD/FRESHNESS_FLOOR_THRESHOLD/FRESHNESS_FLOORの
  値そのものを決定・変更すること
  -- 2-6Bの「閾値の再配置は2-6Eの仕事」という境界をそのまま踏襲する。
  本Phaseはbucketごとのforecast error分布を測定できるところまで。
- freshness curveの形状（線形 vs 指数減衰等）そのものを選定すること
  -- 分布を可視化・集計できる形にするが、「どの形状を採用するか」の
  決定は2-6E。
- Market observation以外（Journal-derived state / Calibration model /
  Spansh static data）のfreshness較正
  -- docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md §5.2で
  既にMarket observationのfreshnessのみを対象とする方針が確定済み。
- confidenceのFRESHNESS_FLOOR（0.50という"confidenceの掛け目"）を
  forecast errorの単位と直接比較すること
  -- 両者は次元が異なる（FRESHNESS_FLOORはconfidenceへの乗数、
  forecast_errorは価格の相対誤差）。本Phaseが検証するのは
  「ageが増えるほどforecast errorが単調に悪化するか」という**構造**の
  妥当性であり、0.50という具体的な掛け目の値そのものの妥当性ではない
  （その値の再検討は2-6Eが、この構造検証の結果を材料に行う）。
```

## 1. Age計算（新設 `app/backtest/freshness_evaluation.py`）

```python
def age_at_t0(sample: ReplaySample) -> dt.timedelta:
    """T0時点で、予測の根拠になった観測がどれだけ古かったか
    (= sample.prediction.t0 - sample.prediction.predicted_price_observed_at)。
    predict_naive_persistence()が`observed_at <= t0`のみを対象とするため
    (docs/PHASE_2_6A...§4.1)、この値は構造的に常に0以上であり、負値の
    ハンドリングは不要。app/scoring/confidence.pyのmarket_freshness()が
    `now - observed_at`として計算しているのと同じ量を、T0を`now`の代役
    として計算している。"""
```

SQLiteのtz round-trip問題（`predicted_price_observed_at`はDBから読むとnaive）は`app/backtest/replay.py`の`_naive()`と同じ手法で対処する（モジュールをまたぐ小さなヘルパーであり、既存の複数モジュールでの重複パターンをそのまま継続する——`app/scoring/confidence.py`のコメントが明記する通り、この対処自体が本プロジェクト全体で複数箇所に重複している既存の書き方）。

## 2. Freshness Bucket分類

現行curveの2つの境界（`FRESHNESS_FULL_THRESHOLD`=15分, `FRESHNESS_FLOOR_THRESHOLD`=24時間）をbucket境界に含めつつ、その間を細分化する。**現行curveの3区分（<15分・15分〜24時間・24時間以上）だけでは「本当に線形か」を確認できない**（Design Baseline §5.1点4: 指数減衰等の別形状と比較するには、区間内部の分布が要る）。

```python
AGE_BUCKET_BOUNDARIES: list[dt.timedelta] = [
    FRESHNESS_FULL_THRESHOLD,      # 15分
    dt.timedelta(minutes=30),
    dt.timedelta(hours=1),
    dt.timedelta(hours=3),
    dt.timedelta(hours=6),
    dt.timedelta(hours=12),
    FRESHNESS_FLOOR_THRESHOLD,     # 24時間
]

FRESHNESS_BUCKET_ORDER: list[str] = [
    "<15m", "15m-30m", "30m-1h", "1h-3h", "3h-6h", "6h-12h", "12h-24h", ">=24h",
]


def classify_freshness_bucket(age: dt.timedelta) -> str:
    """AGE_BUCKET_BOUNDARIESに対する線形探索で、ageが属するbucketラベルを
    返す。FRESHNESS_BUCKET_ORDERと1対1対応する決定論的な純粋関数。"""
```

## 3. Bucket集計

```python
@dataclass(frozen=True)
class FreshnessBucketStats:
    freshness_bucket: str
    sample_count: int
    missing_actual_count: int
    median_forecast_error: float | None
    p95_forecast_error: float | None


def aggregate_by_freshness_bucket(samples: list[ReplaySample]) -> dict[str, FreshnessBucketStats]:
    """age_at_t0()でbucketを求め、classify_freshness_bucket()でグループ化する
    以外は app.backtest.volatility_evaluation.aggregate_by_volatility_class()
    と同一の集計ロジック（median_and_p95の再利用、forecast_error=Noneの
    サンプルをmissing_actual_countとしてのみ計上、出現しなかったbucketは
    キーごと省略）。呼び出し先の関数を共通化する案も検討したが、
    グルーピングキーの型(VolatilityClass vs freshness bucket文字列)が
    異なり、無理に共通化すると呼び出し側の型がぼやけるため、2箇所目の
    独立実装として許容する（既存コードに『三行の類似より早すぎる抽象化の
    方が悪い』という方針があり、呼び出し箇所は2箇所のみで3箇所目の
    予定もない）。"""
```

## 4. 単調性の検証

```python
@dataclass(frozen=True)
class FreshnessMonotonicityResult:
    bucket_stats: dict[str, FreshnessBucketStats]
    # FRESHNESS_BUCKET_ORDER上で隣接するbucketペアごとの比較結果。
    # (bucket_a, bucket_b) -> median(bucket_a) <= median(bucket_b) の真偽、
    # どちらかのsample_countがMIN_SAMPLES_FOR_EVALUATION未満ならNone。
    pairwise_non_decreasing: dict[tuple[str, str], bool | None]
    overall_monotonic: bool | None


def evaluate_freshness_monotonicity(
    bucket_stats: dict[str, FreshnessBucketStats],
) -> FreshnessMonotonicityResult:
    """FRESHNESS_BUCKET_ORDERの隣接ペアそれぞれについて、両bucketの
    sample_countが app.backtest.volatility_evaluation.MIN_SAMPLES_FOR_EVALUATION
    以上ならmedian_forecast_errorの非減少(<=)を判定し、そうでなければNone。

    overall_monotonic:
        Noneでないペアが1つもなければNone（判定材料が皆無）。
        Noneでないペアが1つ以上あり、それら全てがTrueならTrue。
        Noneでないペアのうち1つでもFalseがあればFalse。
    どのペアも「別のbucket境界を試す」ことは行わない——2-6Bの
    evaluate_ordering_hypothesis()と同じく、現行のAGE_BUCKET_BOUNDARIES
    のもとでの事実を報告するのみ。"""
```

`MIN_SAMPLES_FOR_EVALUATION`は`app.backtest.volatility_evaluation`から再利用し、同じ概念（「1グループのmedian forecast errorを比較材料として信頼するための最小ReplaySample数」）に対して2つ目の定数を作らない。

## 5. 2-6Bのvolatility sweepとの組み合わせ

`collect_replay_samples()`（2-6A、`app/backtest/replay.py`）が返す1つの`ReplaySampleCollection`は、`.samples`をそのまま`aggregate_by_volatility_class()`（2-6B）と`aggregate_by_freshness_bucket()`（本書）の両方へ渡せる——**sweepは1回で済み、2-6B用と2-6C用に2回T0を走査する必要はない**。両者は同じ`ReplaySample`集合を異なるキーで再グルーピングしているだけであり、データ収集コスト（EDDN archiveアクセス、DBクエリ）を重複させない。

```python
collection = collect_replay_samples(session, station_id, commodity_name, checkpoints, window_days, horizon)
volatility_stats = aggregate_by_volatility_class(collection.samples)      # 2-6B
freshness_stats = aggregate_by_freshness_bucket(collection.samples)       # 2-6C
```

## 6. Acceptance Tests

```text
age_at_t0()がpredicted_price_observed_at <= t0を前提として常に非負を返す
age_at_t0()がSQLiteのnaive round-trip後でも正しく計算できる（tz混在fixture）
classify_freshness_bucket()がAGE_BUCKET_BOUNDARIESの境界値（ちょうど15分、
   ちょうど24時間等）で決定論的に一方のbucketへ属する
   （境界が両側のbucketに二重計上されない）
aggregate_by_freshness_bucket()がforecast_error=Noneのサンプルを
   median/p95計算から除外し、missing_actual_countとしてのみ計上する
aggregate_by_freshness_bucket()が一度も出現しなかったbucketをキーに含めない
aggregate_by_freshness_bucket()のmedian/p95がapp.market.volatility.median_and_p95と
   一致する（二重実装されていないことの参照テスト）
evaluate_freshness_monotonicity()が単調非減少なfixtureでoverall_monotonic=Trueを返す
evaluate_freshness_monotonicity()が単調性が崩れたfixtureでoverall_monotonic=Falseを返す
evaluate_freshness_monotonicity()がサンプル不足のbucketペアをNoneとし、
   Falseと混同しない
evaluate_freshness_monotonicity()が評価可能なペアが1つもない場合に
   overall_monotonic=Noneを返す
evaluate_freshness_monotonicity()にbucket境界を再配置する引数が存在しない
   （構造的保証、2-6Bのevaluate_ordering_hypothesis()と同じテスト形式）
collect_replay_samples()の同一ReplaySampleCollectionが
   aggregate_by_volatility_class()とaggregate_by_freshness_bucket()の
   両方に渡せる（統合テスト、2回sweepしないことの確認）
```

## 7. Exit Criteria

- [x] `app/backtest/freshness_evaluation.py`が新設され、`age_at_t0`/`classify_freshness_bucket`/`FreshnessBucketStats`/`aggregate_by_freshness_bucket`/`FreshnessMonotonicityResult`/`evaluate_freshness_monotonicity`が実装されている
- [x] `AGE_BUCKET_BOUNDARIES`の両端が`app/scoring/confidence.py`の`FRESHNESS_FULL_THRESHOLD`/`FRESHNESS_FLOOR_THRESHOLD`と同じ値を参照している（値のハードコード重複がない）
- [x] `aggregate_by_freshness_bucket`が`app.market.volatility.median_and_p95`を再利用している
- [x] `evaluate_freshness_monotonicity`が`MIN_SAMPLES_FOR_EVALUATION`未満のbucketペアで`None`を返し、`False`と区別されることがテストされている
- [x] `evaluate_freshness_monotonicity`がbucket境界の再配置を一切行わないことが構造的に保証されている（シグネチャにその手段がない）
- [x] `collect_replay_samples()`の同一出力が2-6B/2-6C双方の集計関数へ渡せることが統合テストで確認されている
- [x] 既存331テストに回帰がない

## 8. 決定事項サマリ

1. **§0 Freshnessの値そのものは決めない**: 測定・分布確認までが本Phase。閾値の決定・形状の選定は2-6E
2. **§1 ageは`t0 - predicted_price_observed_at`**: `app/scoring/confidence.py`の`market_freshness()`が計算する量と同じ定義を、`now`の代わりに`t0`で計算する
3. **§2 bucketは現行curveの2境界を含みつつ細分化**: 3区分のままでは形状（線形 vs 指数減衰）を判別できないため、8bucketに分ける
4. **§3 集計ロジックは2-6Bと意図的に別実装**: グルーピングキーの型が異なり、呼び出し箇所も2箇所のみのため、共通化による抽象化コストの方が高いと判断
5. **§4 `MIN_SAMPLES_FOR_EVALUATION`は2-6Bの定数を再利用**: 同じ概念に2つ目の定数を作らない
6. **§5 sweepは1回で2-6B/2-6C両方に使う**: `collect_replay_samples()`の出力を2つの集計関数へそのまま渡し、EDDN archiveアクセス・DBクエリを重複させない
