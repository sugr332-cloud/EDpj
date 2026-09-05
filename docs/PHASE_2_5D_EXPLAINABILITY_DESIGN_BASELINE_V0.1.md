# EDpj Phase 2-5D Explainability Design Baseline

**Version:** 0.2
**Status:** Implemented（app/scoring/reason_facts.py, app/scoring/data_sources.py実装完了。既存273テスト+新規16テスト、計289テスト全通過。Exit Criteria全項目達成）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md` §2.3/§2.5/§6, `docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` §3/§4/§7, `docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md`（confidence実装済み, commit `a08d416`）

## 0. スコープ

Phase 2-5Dは以下のみを実装する。

```text
1. ReasonFact生成（Horizon/Value/Confidence/Score段階）
2. DataSource収集（実際に使用したMarket/Cargo/Loadout/Calibrationデータ）
3. Recommendation/alternativesへの reasons/data_sources 組み込み
```

**明示的にスコープ外:**

```text
- narrationの実装（LLM呼び出し・post-generation validator）
  -- このプロジェクトにはCLI/API層が一切実装されておらず（app/cli/, app/api/は
  architecture上の予約のみ）、narrationを消費する場所が現状存在しない。
  `Recommendation.narration`は`None`のまま残し、CLI/APIが実装される
  将来phaseで着手する。
- Ranking段階（rank_candidates内の比較）のReasonFact
  -- 「Aがscore_per_hourで1位」という比較自体はRejectedCandidate.reason_code
  （既存, Phase 2-4）で既に表現されており、ReasonFactとして二重化しない（§5）。
- Bio各Action / Mining Start のReasonFact
  -- value_unavailable_reasonで固定文言のまま。value_unavailable時点で
  Recommendation自体が生成されないため、対象がない。
```

## 1. 生成メカニズム（新規決定：各関数の戻り値を増やすか、パイプラインでその場生成するか）

**確定: パイプラインのオーケストレーション（`app/scoring/pipeline.py`）内で、各段階の呼び出し直後にReasonFactを生成する。** `build_horizon`/`calculate_value`/`calculate_confidence`/`calculate_score`自体の戻り値は変更しない。

理由:

```text
案A: 各関数がReasonFactも一緒に返す
  -- build_horizon/calculate_value/calculate_score全てに新しいwrapper
     dataclassが増える（ValueResultに続いてHorizonResult/ScoreResult…）。
     関数のテストにも影響し、churnが大きい。

案B（採用）: pipeline.pyのループが、既に計算された値からその場でReasonFactを組み立てる
  -- 呼び出し側は「この値がいつ計算されたか」を正確に知っている。
     Phase 2-0 §2.3が禁止するのは「Ranking確定後にまとめて後付け生成する」ことで
     あり、「各段階の呼び出し直後、そのループ内で生成する」ことは禁止していない。
     関数シグネチャの変更なしに済む。
```

`app/scoring/reason_facts.py`（新規）に、各段階の値からReasonFactを組み立てる純粋関数を置く。`pipeline.py`はこれらを呼び出し、`ActionCandidate`に新設する`reasons: list[ReasonFact]`フィールドへ蓄積する。

```python
# app/scoring/reason_facts.py

def horizon_reason_facts(components: dict[str, HorizonComponent]) -> list[ReasonFact]: ...
def value_reason_fact(expected_value: float) -> ReasonFact: ...
def confidence_reason_facts(
    generation_confidence: float, horizon_components: dict[str, HorizonComponent], freshness: float
) -> list[ReasonFact]: ...
def score_reason_fact(score_per_hour: float) -> ReasonFact: ...
```

`ActionCandidate`に`reasons: list[ReasonFact] = field(default_factory=list)`を追加し、`IncompleteCandidate`には追加しない（confidence計算対象外なのと同じ理由——reasonsは「なぜこの数字になったか」の説明であり、数字自体が存在しないIncompleteCandidateには適用できない）。

## 2. `effect`（positive/negative）の意味づけ（新規決定）

`ReasonFact.effect: "positive" | "negative"`は`docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` §3で型としては定義されているが、**「何に対して」positive/negativeかが仕様上明記されていない**。本書で以下に確定する。

```text
factor="expected_value"/"score_per_hour"
  -- 常に"positive"固定（これらは「高いほど良い」という前提そのものなので、
     value/scoreの絶対値そのものに正負の解釈は不要。常にpositive）

factor=segment_type（Horizon各要素、例: "mining_cycle"）
  -- 常に"negative"固定（時間はコスト。長いほど不利という一貫した解釈でよい）

factor="confidence"
  -- 常に"negative"固定（レビューで確定・v0.1からの変更点）。
     「confidenceという要因自体が期待値/スコアを減衰させる」という
     フレーミングであり、値が1.00ちょうど（減衰なし）であっても
     "positive"には変えない——effectは値の良し悪しの判定ではなく、
     factorの意味的な役割（コスト側かどうか）を表す

factor="data_freshness"
  -- 同上。常に"negative"固定
```

`comparison`フィールドは、比較対象がある場合のみ埋める（例: 他候補との比較はRankingで生成しない——本書のスコープ外、§0参照。confidence/freshnessの`comparison`には該当する閾値、例えば`MIN_ACTION_CONFIDENCE`や`FRESHNESS_FULL_THRESHOLD`をそのまま入れることを提案する）。

## 3. DataSource収集（新規決定）

`DataSource(name, observed_at, received_at, freshness)`を、実際に候補のValue/Confidence計算が使用したデータソースごとに1件作る。

```text
name="market_latest"     -- calculate_value()がValueResultで返すmarket_observed_ats
                            それぞれについて1件。observed_atはそのまま、
                            freshnessはconfidence.pyのmarket_freshness()を
                            個々の観測に対して計算した値（集約前のper-observation値）
name="cargo_state"       -- Mining Continue/Sellがcargo capacityや保有量を
                            参照した場合。observed_atはCargoState.updated_at
name="loadout"           -- get_cargo_capacity()が参照した最新Loadoutイベント。
                            observed_atはそのJournalEvent.timestamp
name="calibration_model" -- 各HorizonComponentのestimated値のもとになった
                            CalibrationModel。observed_atはCalibrationModel.fitted_at
```

**確定1**: `DataSource.received_at`はMarket由来の行では常に`None`のまま（`MarketSnapshot`へのJOINは行わない）。`received_at`はfreshness計算にもRankingにも使われておらず（Phase 2-0 §5で「Freshness係数は`observed_at`基準」と既に確定済み）、このためだけに追加JOINを行う理由がない。

**確定2**: `name="calibration_model"`のDataSourceを含める。`CalibrationModel`は「観測」ではなく「較正済みモデル」なので、`observed_at`/`received_at`/`freshness`はすべて`None`のまま（時系列観測データではないことを明示する）。

## 4. Recommendation/alternativesへの組み込み

`app/scoring/ranking.py`の`_to_recommendation()`を変更し、`ActionCandidate.reasons`/`data_sources`をそのまま`Recommendation.reasons`/`data_sources`へコピーする（現在は空リストのまま固定されている）。

```python
def _to_recommendation(candidate: ActionCandidate) -> Recommendation:
    return Recommendation(
        ...,
        reasons=candidate.reasons,
        data_sources=candidate.data_sources,
    )
```

`Recommendation.rejected`は引き続き`[]`のまま（Phase 2-4 v0.2で確定済み、`NextActionResponse.rejected`がcanonical）。

## 5. RejectedCandidateとReasonFactは統合しない（確認済み・確定）

`RejectedCandidate.reason_code`（例: `"lower_score"`, `"confidence_below_threshold"`）は既にPhase 2-4で「なぜ選ばれなかったか」を表現しており、ReasonFactの`factor`/`effect`/`value`/`comparison`という形へ変換する必要はない。両者は別の対象（RejectedCandidate=負けた候補、ReasonFact=選ばれた候補自身の内訳）を説明するものであり、混同しない。

## 6. narrationは対象外（確認済み・確定）

`Recommendation.narration`は`None`のまま。CLI/API層（`app/cli/`, `app/api/`）が実装されておらず、narrationを表示する消費者が存在しないため、LLM呼び出し・post-generation validatorの実装は将来phase（CLI/API実装時）へ送る。`docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` §7のLLM境界（narration専用、fact/ranking/confidenceの決定権を持たない）は設計として維持されるが、コードとしては何も実装しない。

## 7. Exit Criteria

- [x] `ActionCandidate`/`Recommendation`に`reasons: list[ReasonFact]`が追加され、`IncompleteCandidate`には追加されていない
- [x] `app/scoring/reason_facts.py`が各段階のReasonFactを組み立て、`pipeline.py`が各段階の呼び出し直後にそれらを蓄積する（Ranking確定後の後付け生成ではない）
- [x] `effect`（positive/negative）が§2の規則通りに決定論的に決まることがテストされている
- [x] `DataSource`が実際にValue/Confidenceが使用したMarket/Cargo/Loadoutデータのみを反映し、使っていないデータソースを含まないことがテストされている
- [x] `Recommendation.reasons`/`data_sources`が対応する`ActionCandidate`の内容と一致することがテストされている
- [x] `Recommendation.narration`は常に`None`のままであることが確認されている（未実装であり、フィールドが誤って埋まらない）
- [x] 既存273テストに回帰がない（273 → 289、新規16件はすべてPhase 2-5D関連）

## 8. 決定事項サマリ（レビューで確定）

1. **生成メカニズム**: パイプラインのオーケストレーション（`pipeline.py`）内で各段階の呼び出し直後にReasonFactを生成する。計算関数（`build_horizon`/`calculate_value`/`calculate_confidence`/`calculate_score`）自体の戻り値は変更しない（§1）
2. **effect**: `expected_value`/`score_per_hour`=常に`positive`、Horizon各segment=常に`negative`、`confidence`/`data_freshness`=値によらず常に`negative`固定（§2）
3. **DataSource**: `received_at`はMarket由来の行では常に`None`（`MarketSnapshot`へのJOINはしない）。`calibration_model`をDataSourceの対象に含め、`observed_at`/`received_at`/`freshness`はすべて`None`（時系列観測ではないことを明示）（§3）
