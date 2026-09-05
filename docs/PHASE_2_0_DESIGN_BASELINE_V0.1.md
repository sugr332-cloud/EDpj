# EDpj Phase 2-0 Design Baseline

**Version:** 0.1
**Status:** Design Fixation (not an implementation phase)
**Date:** 2026-09-05
**Depends on:** `SPECIFICATION_V0.4.md` (content v0.7), `IMPLEMENTATION_SPEC_V0.2.md` (content v0.5), `docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` (v0.1)

## 0. 目的とスコープ

本書はPhase 2実装（Calibration Engine, State Detector, Mining/Bio Candidate, Horizon統合, Confidence, Unified Scoring, Explainability）に着手する前に、共通のDTOとパイプライン順序を固定するための設計書である。**コードは変更しない。設計のみを確定する。**

### 0.1 スコープ外の宣言

`SCREEN_CAPTURE_SPECIFICATION_V0.1.md`（Mission Board OCR + 翻訳オーバーレイ、ED_Japaneseとの関係を定義）は、**Phase 2-0/Phase 2の対象外**とする。EDpjの正本はMining/Exobiologyの次行動決定であり、既存仕様（SPECIFICATION_V0.4.md §3）に明記された「ミッション支援をしない」という非目標とも整合しない領域を含むため、EDpjのPhase 2系列とは完全に切り離された並行仕様として扱う。

```text
EDpj
├─ Phase 1（完了）
├─ Phase 2（本書が対象）
│   Calibration / State / Mining / Bio / Horizon / Confidence / Scoring / Explainability
└─ Screen Capture / Mission OCR（別並行仕様、Phase 2系列に含めない）
```

### 0.2 本書で解決しないこと

本書はPhase 0-Cで確定した「SC移動距離が現行データソースでは取得不能」という制約自体は解決しない。決めるのは**「不明な場合にどう扱うか」というポリシーのみ**である。

```text
現状: SC travel distance 不明 → unavailable → IncompleteCandidate
将来: 実SC距離データソースが決まる → estimated → Recommendation候補へ復帰可能
```

## 1. 既存Phase 0-C実装との照合

### 1.1 confidence定数の置き換え（Phase 2-1着手時に反映）

Phase 0-C実装（`app/routing/time.py`）の暫定値を、Explainability仕様§6の値で置き換える。

```diff
- MEASURED_CONFIDENCE = 0.75
- ESTIMATED_CONFIDENCE_FLOOR = 0.20
- ESTIMATED_CONFIDENCE_CEILING = 0.50  # sample_countで線形スケール
+ MEASURED_CONFIDENCE = 1.00
+ ESTIMATED_CONFIDENCE = 0.85          # 固定値。sample_countスケーリングは廃止
+ UNAVAILABLE_CONFIDENCE = 0.60        # 予約定数。1.3節参照——現Phase 2では未使用
```

### 1.2 `TimeEstimate` = `HorizonComponent`

新規クラスを作らない。`app/routing/time.py`の`TimeEstimate`（`segment_type`/`status`/`seconds`/`confidence`/`basis`）がExplainability仕様の`HorizonComponent`要件と完全一致するため、Phase 2ではエイリアスとして扱う。

```python
HorizonComponent = TimeEstimate  # 型の別名。クラス二重化しない
```

### 1.3 `unavailable=0.60`の位置づけ

Explainability仕様§6の初期confidenceマッピングは以下の3値を定義する。

```text
measured    = 1.00
estimated   = 0.85
unavailable = 0.60
```

ただしPhase 2-0はunavailable componentの扱いとしてOption C（2.3節）を採用するため、**`unavailable=0.60`は将来Option B（明示的fallback）採用時のための予約ポリシー値とし、現Phase 2のRecommendation confidence計算には適用しない**。`IncompleteCandidate`はconfidence計算の対象外（4.2節）であるため、この定数を参照する経路が存在しない。

## 2. DTO確定

### 2.1 Recommendation（Explainability仕様§2をそのまま採用）

```python
class Recommendation:
    action: str
    target: BioTarget | MiningTarget
    expected_value: float
    action_horizon_seconds: float   # 常に確定値。horizon不完全な候補はRecommendationにならない
    score_per_hour: float
    confidence: float

    breakdown: dict[str, HorizonComponent]  # キーはsegment_type（2.6節）
    data_sources: list[DataSource]
    reasons: list[ReasonFact]
    rejected: list[RejectedCandidate]
    narration: str | None
```

`Recommendation`は「**score_per_hourを正当に計算できた候補**」専用の型と定義する。

### 2.2 IncompleteCandidate（新設）

```python
class IncompleteCandidate:
    action: str
    target: BioTarget | MiningTarget
    expected_value: float | None     # horizonと無関係な部分が計算できる場合がある
    breakdown: dict[str, HorizonComponent]
    blocking_segments: list[str]     # 例: ["supercruise"]
    reason: str                      # 例: "SC移動時間が推定不能なためscore計算不可"
```

「計算材料が足りずランキングできないが、候補としては存在する」ものを表す。confidence/score_per_hourは計算しない（計算できないため）。

### 2.3 ReasonFact（Explainability仕様§3をそのまま採用）

```python
class ReasonFact:
    factor: str        # score_per_hour | expected_value | action_horizon | travel_time |
                        # market_price | demand_penalty | data_freshness | confidence 等
    effect: str         # positive | negative
    value: float
    comparison: float | None
```

**生成タイミング**: ReasonFactはランキング確定後にまとめて後付け生成するのではなく、**決定論的計算の各段階で、その場で生成する**。

```text
悪い例:
  Value → Confidence → Score → Ranking → （ここで初めてReasonFact生成）

正しい例:
  Value計算時      → ReasonFact("expected_value", ...)
  Horizon計算時    → ReasonFact("travel_time", ...)
  Confidence計算時 → ReasonFact("data_freshness", ...), ReasonFact("confidence", ...)
  Score計算時      → ReasonFact("score_per_hour", ...)
        ↓
  すべて計算完了後、Recommendationへ集約
```

理由: ReasonFactは「LLMに理由を考えさせるもの」ではなく「計算過程そのものから生まれる事実」であるため、計算と同時に発生しなければならない。

### 2.4 RejectedCandidate（Explainability仕様§4のまま、変更なし）

```python
class RejectedCandidate:
    category: str       # filter | score
    action: str
    target_id: str
    reason_code: str
    value: float | None
    comparison: float | None
```

`incomplete`カテゴリは追加しない（前回ドラフトからの訂正）。horizon不完全な候補は`RejectedCandidate`ではなく`IncompleteCandidate`として別リストに保持する（2.2節、3節参照）。

意味の定義:

```text
category="filter"  → 候補として採用されなかった（実行不能）
category="score"    → 実行可能だったが選択されなかった（スコア負け）
```

### 2.5 DataSource（新規提案。仕様に定義がないため補完）

```python
class DataSource:
    name: str                      # 例: "market_snapshot", "timing_samples", "spansh_static"
    observed_at: datetime | None
    received_at: datetime | None
    freshness: float | None        # 実際に適用されたfreshness係数
```

MVPでは`freshness`を`DataSource`に直接持たせる。`FreshnessInfo`（`factor`/`basis`）への分離は将来必要になった時点で検討する — Phase 2-0では構造を複雑化しない方を優先する。

### 2.6 breakdownのキー：segment_type

`breakdown: dict[str, HorizonComponent]`のキーは、Explainability仕様例の複合ラベル（`"travel_to_station"`等）ではなく、**既存segment_type**（`jump`/`supercruise`/`dock`/`undock`/`descent`/`ascent`/`mining_cycle`/`bio_sample`）をそのまま使う。

複合的な表示（例: travel = jump + supercruise + dock）はpresentation/APIアダプタ層で組み立て、coreは独自の分類体系を持たない。

### 2.7 NextActionResponse（新設、トップレベルAPIレスポンス）

```python
class NextActionResponse:
    next_action: str | None
    recommendation: Recommendation | None
    alternatives: list[Recommendation]      # 完全スコア済みの次点（既存IMPLEMENTATION_SPEC §13.2のalternatives）
    incomplete: list[IncompleteCandidate]   # horizon不完全な候補。捨てない
    reason: str | None
```

## 3. パイプライン確定（Phase 2全体の処理順序として正式採用）

```text
State
 ↓
Candidate Generation
 ↓
Deterministic Filter ────────→ RejectedCandidate(category="filter")
 ↓
Horizon Build
 ├─ incomplete ────────────────→ IncompleteCandidate
 └─ complete
      ↓
      Value計算        → ReasonFact生成
      ↓
      Confidence計算   → ReasonFact生成
      ↓
      Score計算        → ReasonFact生成
      ↓
      Ranking
      ├─ Top 1  → Recommendation（reasons集約 + narration枠）
      └─ 残り   → RejectedCandidate(category="score")
```

## 4. SC unavailableの扱い（確定）

```text
SC travel distance 不明（現行データソースの制約、Phase 0-C確定事項）
        ↓
supercruise segment: status="unavailable"
        ↓
そのsegmentを要求するcandidateはhorizon incomplete
        ↓
IncompleteCandidate へ
        ↓
通常のRecommendation ranking対象外
        ↓
confidence計算も対象外（1.3節）
```

SCを要求しないcandidate（同一天体内のbio_sample等）は、SCが`unavailable`であることに一切影響されず、通常通り`Recommendation`候補になり得る（`horizon_complete`の定義がAction単位であることの帰結、IMPLEMENTATION_SPEC_V0.2.md §12.2）。

## 5. Confidence合成

```text
confidence = Π(component_confidence) × freshness_factor
```

初期マッピング（`Recommendation`/`alternatives`にのみ適用。`IncompleteCandidate`には適用しない）:

```text
measured  = 1.00
estimated = 0.85
```

`unavailable = 0.60`は1.3節の通り現Phase 2では未使用の予約値。

Freshness係数は`observed_at`基準（`received_at`基準ではない）。具体的な減衰カーブ・閾値はPhase 2較正時に決定し、named configuration constantsとして保存する（本書では確定しない）。

## 6. LLM境界（Explainability仕様§7を継承、変更なし）

```text
Recommendation + ReasonFacts + breakdown + data_sources
        ↓
    Claude/AGY（任意）
        ↓
    narration のみ
```

LLMはfact・数値計算・candidate filtering・ranking・confidence・recommendation選定のいずれにも権限を持たない。narrationはpost-generation validatorで数値照合し、失敗時は破棄してdeterministic recommendationのみ表示する。CLIはLLMなしで完全に機能する。

## 7. Phase 2-1着手前のコード変更リスト

1. `app/routing/time.py`: confidence定数を1.00/0.85/0.60に置き換え、estimatedのsample_countスケーリングを削除（1.1節）
2. `app/scoring/models.py`: `ActionCandidate`を`Recommendation`/`IncompleteCandidate`/`RejectedCandidate`/`DataSource`/`NextActionResponse`へ置き換え
3. 既存112テストへの影響確認（`ActionCandidate`を直接参照するのは`tests/integration/test_action_horizon_estimator.py`のみのため、影響範囲は限定的）

## 8. Exit基準（本書の確定条件）

- [x] Recommendation / IncompleteCandidate の分離が定義されている
- [x] TimeEstimateをHorizonComponentとして再利用することが決まっている
- [x] breakdownのキーがsegment_typeであることが決まっている
- [x] RejectedCandidateがfilter/scoreの2categoryのままであることが決まっている
- [x] SC unavailable → IncompleteCandidate → ranking対象外、という扱いが決まっている
- [x] confidence初期値（1.00/0.85/0.60）と、unavailable=0.60が現Phase 2で未使用であることが決まっている
- [x] freshnessがobserved_at基準であることが決まっている（数値は未定のまま据え置き）
- [x] ReasonFactが計算過程内で生成されることが決まっている
- [x] Screen Capture仕様がPhase 2系列から分離されている

本書のExit基準を満たした時点でPhase 2-1（Calibration Engine）実装に着手できる。
