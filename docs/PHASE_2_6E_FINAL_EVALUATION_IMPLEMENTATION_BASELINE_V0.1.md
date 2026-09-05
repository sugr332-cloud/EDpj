# EDpj Phase 2-6E Final Evaluation Implementation Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/evaluation_run.py`新設。既存360テスト+新規15テスト、計375テスト全通過。Exit Criteria全項目達成。実archive/実Journalへの接続はまだ行っていない — 次の実行ステップで別途行う）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §9（v0.1, commit `013d92c`）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`（v0.2, commit `c4bbe8e`）, `docs/PHASE_2_6B_VOLATILITY_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`（v0.1, commit `51d55e9`）, `docs/PHASE_2_6C_FRESHNESS_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`（v0.1, commit `0c7d070`）, `docs/PHASE_2_6D_PLAYER_STATE_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`（v0.1, commit `0a1c279`）, `app/backtest/replay.py`, `app/backtest/volatility_evaluation.py`, `app/backtest/freshness_evaluation.py`, `app/backtest/journal_replay.py`, `app/market/predictability.py`, `app/scoring/confidence.py`

## 0. 位置づけ

2-6Eは「実データを流すPhase」ではなく、**2-6A〜Dで作った評価結果を使ってVolatility/Freshnessの採用値を正式決定し、Go/No-Goを判定するPhase**である。

```text
2-6A Historical Replay基盤
2-6B Volatility評価ツール
2-6C Freshness評価ツール
2-6D Journal評価ツール（補助証拠）
        ↓
2-6E データセット確定 → 評価実行 → 統計集計 → Go/No-Go → 採用値確定
```

本書が固定するのは以下の3つである。

1. **実データを見る前に決めるデータセット定義**（§1）— どのstation×commodityを対象にするか、T0をどう抽出するか
2. **実データを見る前に決める採用基準**（§3/§4）— 2-6B/2-6Cの評価関数の出力から、どう判定すれば「採用」「不採用」「引き続き暫定」になるか
3. **採用値の反映方法**（§7）— 評価結果から実際に定数を変更する手順そのもの、変更が常にレビュー可能な独立コミットになること

新しい統計ロジックはここでは作らない。2-6B/2-6C/2-6Dの評価関数（`evaluate_ordering_hypothesis`/`evaluate_freshness_monotonicity`/`collect_horizon_diagnostics`）をそのまま使い、複数ターゲットにまたがるオーケストレーションのみを追加する（§9）。

**明示的にスコープ外:**

```text
- 実際にEDDN archiveや本人Journalへ接続してデータを流すこと
  -- 本書の実装（§9）はFakeStreamingHttpClient/合成JournalEventによる
  テストのみで検証する。実データ接続は本書のpush後、別途の実行ステップ
  として行う。
- 2-6B/2-6Cの評価関数に新しい判定ロジックを追加すること
  -- evaluate_ordering_hypothesis()/evaluate_freshness_monotonicity()の
  シグネチャ・挙動は変更しない。
- 閾値を自動で書き換えるコード
  -- §7で明文化する通り、採用は常に人間がレビューする独立コミット。
  評価実行スクリプトがpredictability.py/confidence.pyを書き換える
  コードパスは一切作らない。
```

### 0.1 現在値を「正解」として扱わない（レビュー指摘、構造的保証）

**評価実行コードは、現在の本番定数（`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`/`FRESHNESS_FULL_THRESHOLD`/`FRESHNESS_FLOOR_THRESHOLD`/`FRESHNESS_FLOOR`）を判定の「正解」として扱わない。** 本番定数を変更しないこと（既に上で明文化済み）とは別の要求である——変更しないだけでなく、**判定結果が現在値を有利にするように評価ロジックが書かれていないこと**を保証する。

具体的には以下を満たす。

```text
1. §3/§4の採用判定（GO/条件付きGO/NO-GO/INSUFFICIENT）は、§9で
   実装する専用の決定関数（decide_volatility_adoption()/
   decide_freshness_adoption()）としてコード化する——散文の判定ルール
   のままでは「本当に現在値を有利に扱っていないか」をテストできない。

2. これらの決定関数は、classify()/AGE_BUCKET_BOUNDARIESが現在の
   station/commodityやbucketをどう分類したかという結果（volatility_class、
   freshness bucket）のみを入力とし、「現在の定数値がいくつか」を
   一切参照しない。判定は forecast error の実測分布のみに基づく。

3. §2-6C（freshness）は特に重要——現在のcurve自体を「評価対象」として
   扱い、「正解」として扱わない。8bucketへの細分化(docs/PHASE_2_6C...§2)
   は、現在の15分/24時間という境界を含みつつ細分化する設計だが、これは
   測定の都合（現行curveの境界点を含めることでその点を直接評価できる）
   であり、その境界が正しいという前提ではない。

4. これを構造的に検証するため、decide_volatility_adoption()/
   decide_freshness_adoption()に対して、現在の定数が実データ上「誤り」
   であるように作られた合成fixture（例: STABLE classのforecast errorが
   VOLATILEより大きい、age bucketの単調性が崩れている）を与え、
   判定がGOではなくNO-GO/不採用になることをテストする（§10）。
   このテストが通ることは、「決定関数が現在値を無条件に追認していない」
   ことの直接証拠になる。
```

## 1. データセット定義（実データを見る前に固定）

### 1.1 EDDN側ターゲット選定

銀河全体のbulk fetchは`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md`が禁止しているため、対象は**本人の`MarketSnapshot`（`source='journal'`）に実際に記録されている(station_id, commodity_name)の集合**から選ぶ。任意の銀河規模サンプリングではなく、このプレイヤーの実際のRecommendationに関係しうる市場に評価を紐づける。

```python
MAX_EVALUATION_TARGETS = 20  # 運用上の制約（アーカイブ取得コスト）。対象の代表性を保証する値ではない。

def select_evaluation_targets(session: Session, max_targets: int = MAX_EVALUATION_TARGETS) -> list[EvaluationTarget]:
    """MarketSnapshot(source='journal')から(station_id, commodity_name)の
    distinct集合を、観測回数の多い順にmax_targets件だけ選ぶ。観測回数が
    多いほど、その市場でのプレイヤー自身の実際の取引タイミングに近い
    T0を多く確保できる。"""
```

**コスト根拠**: `docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md` §1により、1つのstation×commodityの分析コストはwindow日数×約60〜112MB。30日windowなら1ターゲットあたり最大約3.4GB。`MAX_EVALUATION_TARGETS=20`なら最大約68GBが理論上の上限になる——実際には`MarketHistoricalFetchLog`が同一日付を複数ターゲット間で共有しない（station×commodity単位のキャッシュのため）ことに注意し、初回実行のコストとして許容できるかは実行前に確認する。

### 1.2 EDDN側T0抽出

各ターゲットについて、`app/backtest/replay.py`の`generate_t0_checkpoints()`をそのまま使う。

```python
EVALUATION_T0_INTERVAL = dt.timedelta(hours=1)
```

**intervalを1時間にする根拠**: `collect_replay_samples()`が呼ぶ`predict_naive_persistence()`/`observe_actual_after()`は`MarketHistoricalObservation`の読み取りのみで、新たなarchive取得を発生させない（取得は`ensure_days_fetched`が日付単位で1回だけ行う）。したがって1時間間隔にしてもコストは増えない。30日window・1時間intervalで1ターゲットあたり最大720件のT0候補が得られ、`MIN_SAMPLES_FOR_EVALUATION=30`（2-6B/2-6C共通）を満たすのに十分な余裕がある。

### 1.3 本人Journal側

`app/backtest/journal_replay.py`の`collect_horizon_diagnostics()`は`TimingSample`テーブルを直接全件走査する設計であり、**新たなT0 sweepを必要としない**——Phase 0-B/0-Cが既に収集した実segment発生時刻そのものがT0候補になっている。

`reconstruct_player_state_at()`の網羅率を測るためだけに、`TimingSample.start_time`を「意味のあるT0」として使う（§5）。合成的な固定間隔sweepは行わない——実際に何かが起きた瞬間だけを見る方が、存在しない時刻のState再構成を無駄に試みない。

## 2. Target横断のPooling

`aggregate_by_volatility_class()`/`aggregate_by_freshness_bucket()`はどちらも`list[ReplaySample]`を受け取るだけで、ターゲットを区別しない。**単一のstation×commodityの価格推移が数十日でSTABLE/MODERATE/VOLATILEの全クラスをまたぐことは稀**なため、評価に十分なサンプル数を各クラス・各bucketで確保するには、**選定した全ターゲットの`ReplaySampleCollection.samples`を1つのリストへ連結してから集計関数へ渡す**。

```python
all_samples: list[ReplaySample] = []
for target in targets:
    collection = collect_replay_samples(session, target.station_id, target.commodity_name, checkpoints, window_days, horizon)
    all_samples.extend(collection.samples)

volatility_stats = aggregate_by_volatility_class(all_samples)
freshness_stats = aggregate_by_freshness_bucket(all_samples)
```

集計関数自体への変更は一切ない——2-6B/2-6Cが「グルーピングキーがVolatilityClass/freshness bucketである」という以外の前提を持たない設計にしていたことがそのまま活きる。

## 3. Volatility採用基準（2-6E-2）

`evaluate_ordering_hypothesis()`の出力を、新設する`decide_volatility_adoption()`（§9）が次のルールで判定する。`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §9.2/§9.3を具体化したものであり、新しい統計基準は追加しない。**`decide_volatility_adoption()`は`OrderingHypothesisResult`のみを入力とし、`STABLE_MEDIAN_PRICE_CHANGE`等の現在の定数値を一切参照しない（§0.1）——判定は「classがどう振られたか」の結果のみに基づく。**

```text
ordering_holds=True かつ stable_within_mae_threshold=True かつ volatile_exceeds_mae_threshold=True
    → GO（現行のSTABLE_MEDIAN_PRICE_CHANGE/MODERATE_MEDIAN_PRICE_CHANGEを
       暫定から確定へ昇格）

ordering_holds=True だが stable_within_mae_threshold/volatile_exceeds_mae_thresholdの
    どちらかがFalse
    → CONDITIONAL_GO（分類の順序関係は成立しているため構造自体は正しいが、
       境界値の再配置を検討する候補。§9.2が言う「閾値の再配置」を
       ここで初めて実行する——2-6Bはこの再配置を明示的にスコープ外と
       していた）

ordering_holds=False
    → NO_GO。閾値の微調整では解決しない可能性が高いため、
       §9.5の「モデル適用可否gate自体の妥当性」に立ち返り、
       分類ロジックの再設計を検討する（本書では判定のみ行い、
       再設計自体は別Phaseとする）

ordering_holds=None（判定材料不足）
    → INSUFFICIENT。現行値を「引き続き暫定」のまま維持し、
       どのclassでサンプル不足だったかを報告する（§8）
```

7/14/30日の3window全てで`evaluate_ordering_hypothesis()`→`decide_volatility_adoption()`を独立に実行し（§2のpoolingをwindowごとに繰り返す）、**3windowの結論が一致するかどうかも報告する**——一致しない場合、`DEFAULT_ANALYSIS_WINDOW_DAYS`自体をどのwindowにするかも本書の採用判断に含まれる。

## 4. Freshness採用基準（2-6E-3）

`evaluate_freshness_monotonicity()`の出力を、新設する`decide_freshness_adoption()`（§9）が次のルールで判定する。**`decide_freshness_adoption()`も`FreshnessMonotonicityResult`のみを入力とし、`FRESHNESS_FULL_THRESHOLD`/`FRESHNESS_FLOOR_THRESHOLD`/`FRESHNESS_FLOOR`の現在値を一切参照しない（§0.1）——現行の8bucket分割は現行curveの境界点を含む測定上の都合であり、その境界が正しいという前提ではない。**

```text
overall_monotonic=True
    → GO（構造上の妥当性）。ただし数値そのもの
       （FRESHNESS_FULL_THRESHOLD/FRESHNESS_FLOOR_THRESHOLD/FRESHNESS_FLOOR/
       線形形状）は自動的には決まらない——docs/PHASE_2_6C...§0が既に
       明記した通り、forecast_error(価格の相対誤差)とFRESHNESS_FLOOR
       (confidenceへの掛け目)は次元が異なるため、機械的な変換式は存在しない。
       `decide_freshness_adoption()`はGOという構造判定のみを返し、
       各bucketのmedian/p95 forecast errorの分布を見て現行の3区分
       （<15分・15分〜24時間・24時間以上）・線形形状・floor=0.50を
       維持するか調整するかを判断するのは人間のレビュー（§7）——
       決定関数自身が具体的な採用数値を提案することはしない

overall_monotonic=False
    → NO_GO。「ageが増えるほど誤差が悪化する」という前提そのものが
       実データで支持されない。境界値の再配置ではなく、curveの形状の
       再設計を検討する

overall_monotonic=None（判定材料不足）
    → INSUFFICIENT。現行値を「引き続き暫定」のまま維持
```

`pairwise_non_decreasing`のうち、`("<15m", "15m-30m")`と`("12h-24h", ">=24h")`（現行curveの2境界に最も近いペア）を個別に強調して報告する——この2ペアが崩れている場合、境界値そのものの位置が疑わしいという直接的なシグナルになる。

## 5. 2-6Dの扱い（2-6E-4、補助証拠）

`docs/PHASE_2_6D_PLAYER_STATE_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`が既に明記した通り、2-6Dの結果は**§3/§4の採用判断を一切左右しない**。以下を報告するのみ。

```python
@dataclass(frozen=True)
class JournalCoverageReport:
    state_reconstruction_coverage: float  # reconstruct_player_state_at()がfields非空を返した割合
    horizon_diagnostic_coverage: float    # collect_horizon_diagnostics()でrelative_error is not Noneの割合
    diagnostics_by_segment_type: dict[str, list[HorizonDiagnosticSample]]
```

`state_reconstruction_coverage`は各`TimingSample.start_time`で`reconstruct_player_state_at()`を呼び、`fields`が空dictでない割合。`horizon_diagnostic_coverage`は`collect_horizon_diagnostics()`の結果のうち`relative_error is not None`の割合（`supercruise`は構造的に常にNoneなので、この指標はsupercruiseを除いた分母で計算する）。

この2指標が低い場合（例: 実Journalのbackfill期間が短い、キャリブレーション未実施のsegment_typeが多い）、**2-6Dの結果を"reference only"のまま報告する**——`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §9.4が既に定めた通り、2-6D独自のGo/No-Go判断は行わない。

## 6. Go/No-Go統合（2-6E-5）

```text
Volatility        → GO / 条件付きGO / NO-GO / INSUFFICIENT   (§3)
Freshness         → GO / 条件付きGO / NO-GO / INSUFFICIENT   (§4)
Journal evidence  → consistent / inconsistent / insufficient (REFERENCE ONLY, 常に§3/§4をブロックしない)
```

VolatilityとFreshnessは独立した軸であり（`app/market/predictability.py`と`app/scoring/confidence.py`の別々の定数）、両方が同じ結論である必要はない——一方がGO、他方がNO-GOという結果もそのまま報告する。

## 7. 採用値の反映方法（2-6E-6）

**採用は常に、評価実行スクリプトとは独立した、人間がレビューする別コミットで行う。** `app/backtest/`のどのモジュールも`app/market/predictability.py`/`app/scoring/confidence.py`の定数を書き換えるコードパスを持たない——評価結果のレポート（§9のEvaluationRunReport）を人間が読み、Go/No-Goに従って以下のいずれかを手動で行う。

```text
GO の場合:
    該当定数の値を維持または再配置し、コード中のコメント
    "暫定値。Phase 2-6のbacktestで実データの分布・forecast errorとの
    相関を見て再較正する暫定値" を "Phase 2-6E（実行日・レポート参照）に
    より確定" へ更新する

NO-GO / INSUFFICIENT の場合:
    定数は変更しない。コメントを "Phase 2-6Eで評価済み、
    [理由]のため引き続き暫定（レポート参照）" へ更新し、
    再評価に必要な条件（対象拡大、window拡張等）を記録する
```

この手順により、2-6Aで確立した「実装した閾値に合わせて分析する、という逆転を起こさない」という中心原則が、採用の最終段階まで一貫する。

## 8. データ不足時の扱い

`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §9.1/§9.4をそのまま適用する。

- `MIN_SAMPLES_FOR_EVALUATION`（2-6Bで定義、2-6Cで再利用）未満のclass/bucketは、§3/§4のGO/NO-GO判定に一切使わない
- 3windowの一部でのみ十分なサンプルが得られた場合、そのwindowの結果のみを採用判断に使い、他のwindowは"insufficient"として別途報告する
- 対象拡大（`MAX_EVALUATION_TARGETS`を増やす、window長を延ばす）で再評価する余地を常に報告に含める

## 9. 実装するコード（新設 `app/backtest/evaluation_run.py`）

```python
@dataclass(frozen=True)
class EvaluationTarget:
    station_id: int
    commodity_name: str


def select_evaluation_targets(session: Session, max_targets: int = MAX_EVALUATION_TARGETS) -> list[EvaluationTarget]:
    """§1.1"""


AdoptionDecision = Literal["GO", "CONDITIONAL_GO", "NO_GO", "INSUFFICIENT"]


def decide_volatility_adoption(result: OrderingHypothesisResult) -> AdoptionDecision:
    """§3をそのままコード化する。入力はOrderingHypothesisResultのみ --
    STABLE_MEDIAN_PRICE_CHANGE等の現在の定数値をこの関数は一切参照しない
    (§0.1) -- 現在値が実データ上「正解」であるという前提を判定ロジックへ
    混入させない。"""
    if result.ordering_holds is None:
        return "INSUFFICIENT"
    if not result.ordering_holds:
        return "NO_GO"
    if result.stable_within_mae_threshold and result.volatile_exceeds_mae_threshold:
        return "GO"
    return "CONDITIONAL_GO"


def decide_freshness_adoption(result: FreshnessMonotonicityResult) -> AdoptionDecision:
    """§4をそのままコード化する。入力はFreshnessMonotonicityResultのみ --
    FRESHNESS_FULL_THRESHOLD等の現在の定数値をこの関数は一切参照しない
    (§0.1)。CONDITIONAL_GOという区分を持たない
    -- overall_monotonic=Trueは常にGO(構造的妥当性の確認)であり、
    具体的な採用数値の提案はこの関数の責務ではない(§4)。"""
    if result.overall_monotonic is None:
        return "INSUFFICIENT"
    return "GO" if result.overall_monotonic else "NO_GO"


@dataclass(frozen=True)
class EvaluationRunReport:
    generated_at: dt.datetime
    targets: list[EvaluationTarget]
    target_sample_counts: dict[EvaluationTarget, int]            # レビュー指摘: target偏りの確認用
    volatility_by_window: dict[int, OrderingHypothesisResult]    # window_days -> §3
    volatility_decision_by_window: dict[int, AdoptionDecision]   # window_days -> decide_volatility_adoption()の結果
    freshness: FreshnessMonotonicityResult                        # §4（最も広いwindow_daysのサンプルを使う。age_at_t0/forecast_errorはwindow_daysに依存しないため、最も広いwindowのT0 sweepが最も網羅的）
    freshness_decision: AdoptionDecision                          # decide_freshness_adoption()の結果
    journal_coverage: JournalCoverageReport                       # §5


def run_evaluation(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    targets: list[EvaluationTarget],
    window_days_options: tuple[int, ...] = (7, 14, 30),
    t0_interval: dt.timedelta = EVALUATION_T0_INTERVAL,
    horizon: dt.timedelta = dt.timedelta(hours=1),
) -> EvaluationRunReport:
    """§1〜§6をオーケストレーションする。新しい統計ロジックは持たない
    -- 既存の2-6A〜D関数とdecide_volatility_adoption()/
    decide_freshness_adoption()を呼び出し、結果を集約するだけ。
    predictability.py/confidence.pyのいずれのモジュールもimportで
    その定数値を参照する箇所はなく（decide_*関数の引数シグネチャに
    そのための引数がない）、書き換えるコードパスも存在しない。"""
```

`target_sample_counts`は`{target: len(collection.samples)}`をtargetごとに保持する——レビュー指摘の通り、特定targetへのサンプル偏りを最終レポートで確認できるようにする（§2のpoolingは集計の入力を1本化するだけで、target単位の内訳を捨てるわけではない）。

**テスト方針**: `docs/PHASE_2_6A...`以降と同じく、`FakeStreamingHttpClient`と合成`JournalEvent`/`MarketSnapshot`/`TimingSample`のみを使い、**実archive URL・実Journalディレクトリには一切アクセスしない**。本書のExit Criteriaはこのテストで満たされ、実データ接続は本書のpush後の別ステップとする。

## 10. Acceptance Tests

```text
select_evaluation_targets()がMarketSnapshot(source='journal')以外
   （source='eddn'等）を対象に含めない
select_evaluation_targets()が観測回数の多い順にmax_targets件を返す
run_evaluation()が複数ターゲットのReplaySampleを連結してから
   aggregate_by_volatility_class()/aggregate_by_freshness_bucket()へ渡す
   （target単位では集計しないことの確認）
run_evaluation()が7/14/30日windowそれぞれで独立したOrderingHypothesisResultを返す
run_evaluation()がJournalCoverageReportの2指標
   （state_reconstruction_coverage/horizon_diagnostic_coverage）を正しく計算する
run_evaluation()がpredictability.py/confidence.pyのいかなる定数も書き換えない
   （構造的保証 -- run_evaluationの返り値・副作用にDB/定数変更が含まれないテスト）
EvaluationRunReportの生成が実archiveアクセス・実Journalディレクトリアクセスを
   一切行わない（FakeStreamingHttpClient経由のURLのみが呼ばれることの確認）
decide_volatility_adoption()/decide_freshness_adoption()のシグネチャに
   現在の定数値を渡す引数が存在しない（構造的保証、2-6Bのevaluate_ordering_hypothesis()
   と同じテスト形式）
decide_volatility_adoption()が、STABLE/MODERATE/VOLATILEの順序が実データ上
   崩れているfixture（現行の分類が誤りであるように作った合成データ）に対して
   GOではなくNO_GOを返す（§0.1の「現在値を正解として扱わない」ことの直接証拠）
decide_freshness_adoption()が、単調性が崩れているfixtureに対して
   GOではなくNO_GOを返す（同上）
decide_volatility_adoption()/decide_freshness_adoption()がordering_holds/
   overall_monotonic=Noneの場合にNO_GOではなくINSUFFICIENTを返す
   （不成立と判定不能を混同しない）
EvaluationRunReport.target_sample_countsが各targetの実際のReplaySample数と一致する
   （特定targetへの偏りが最終レポートから確認できることのテスト）
```

## 11. Exit Criteria

- [x] `app/backtest/evaluation_run.py`が新設され、`select_evaluation_targets`/`run_evaluation`/`EvaluationRunReport`/`JournalCoverageReport`/`decide_volatility_adoption`/`decide_freshness_adoption`が実装されている
- [x] target横断poolingが実装され、target単位ではなく全ターゲット結合後に2-6B/2-6Cの集計関数を呼んでいる
- [x] 7/14/30日windowそれぞれの`OrderingHypothesisResult`と`decide_volatility_adoption()`の判定が独立して得られる
- [x] `JournalCoverageReport`の2指標が計算され、2-6Dの結果がGo/No-Go判定に一切使われないことがテストされている
- [x] `run_evaluation`が定数を書き換えるコードパスを一切持たないことが構造的に保証されている
- [x] `decide_volatility_adoption`/`decide_freshness_adoption`が現在の定数値を一切参照しないことが構造的に保証され、かつ「現在の分類/curveが実データ上誤りであるように作ったfixture」でNO_GOを返すことがテストされている（§0.1）
- [x] `EvaluationRunReport.target_sample_counts`でtarget単位の内訳が確認できる
- [x] Fakeクライアント・合成データのみでテストが完結し、実archive/実Journalへのアクセスがないことが確認されている
- [x] 既存360テストに回帰がない
- [ ] 本書がpushされた後で初めて、実EDDN archive・実Journalへの接続を伴う評価実行に進む（本書のExit自体はこの実行を含まない）

## 12. 決定事項サマリ

1. **§1.1 EDDN側ターゲットは本人の実MarketSnapshotから選定**: 銀河規模の任意サンプリングを避け、このプレイヤーのRecommendationに関係する市場に評価を紐づける。`MAX_EVALUATION_TARGETS=20`はコスト上の運用制約であり統計的根拠はない
2. **§1.2 T0 intervalは1時間**: archive取得コストに影響しないため、細かくして問題ない
3. **§1.3 2-6Dは新たなT0 sweepを持たない**: `collect_horizon_diagnostics()`が既に`TimingSample`全件を走査する設計であるため
4. **§2 target横断でpoolingしてから集計**: 単一ターゲットではvolatility class/freshness bucketの全区分をカバーできないため
5. **§3/§4 採用基準は2-6B/2-6Cの評価関数の出力にそのまま従う**: 新しい判定ロジックを追加しない。閾値の再配置（2-6Bが明示的にスコープ外としていたもの）はここで初めて実行する
6. **§5 2-6Dは常にreference only**: Journal evidenceがVolatility/Freshnessの採用判断をブロックすることは構造的にない
7. **§7 採用は常に独立したレビュー可能なコミット**: 評価実行コードが定数を自動書き換えすることは一切ない
8. **§0.1 現在値を正解として扱わない（レビュー指摘）**: `decide_volatility_adoption()`/`decide_freshness_adoption()`は評価結果のみを入力とし、現在の定数値を一切参照しない。これを「現在の分類/curveが実データ上誤りであるように作ったfixtureでNO_GOを返す」というテストで直接証明する
9. **§9 target単位の内訳を保持（レビュー指摘）**: `EvaluationRunReport.target_sample_counts`で、pooling後も特定targetへのサンプル偏りを確認できるようにする
