# EDpj Phase 2-4 Ranking / Recommendation Design Baseline

**Version:** 0.2
**Status:** Design Baseline Fixed（レビューで§10の4点すべて確定。NextActionResponseにrejectedフィールドを新設）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md`, `docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md` (v0.5), `IMPLEMENTATION_SPEC_V0.2.md` §12.3/§12.4/§13.2, `docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md` §4

## 0. スコープ

Phase 2-4は**Ranking/Recommendationのみ**を扱う。以下は明示的にスコープ外とし、Phase 2-5へ送る。

```text
Phase 2-4（本書）
  scoreable candidatesの抽出
  confidence thresholdによる足切り
  score_per_hour降順のランキング（tie-break含む）
  Recommendation / alternatives / RejectedCandidate(score) の組み立て
  NextActionResponseの完成

Phase 2-5（対象外）
  confidence = Π(component_confidence) × freshness_factor の実装
  freshness decay curveの新規設計
  Horizon/Value/Score各段階でのReasonFact生成の後付け
  DataSource収集、narration境界
```

Phase 2-4は**`ActionCandidate.confidence`が今どう計算されているか（Phase 2-2の`generation_confidence`そのまま）を変更しない**。confidenceは「既に存在する入力値」として扱うだけである。これにより、Phase 2-5が未着手でもPhase 2-4のRanking構造自体は完成させられる（依存関係を作らない）。

## 1. 入力

Phase 2-3の`generate_and_classify`が返す`CandidatePipelineResult`をそのまま受け取る。

```python
class CandidatePipelineResult:
    complete: list[ActionCandidate]      # is_scoreable()を満たした候補のみ
    incomplete: list[IncompleteCandidate]
    rejected: list[RejectedCandidate]    # category="filter"（Phase 2-2、現状は常に空）
```

`incomplete`はPhase 2-4が一切手を加えず、そのまま`NextActionResponse.incomplete`へ通す。Rankingの対象は`complete`のみ。

## 2. Confidence threshold（IMPLEMENTATION_SPEC_V0.2.md §12.3をそのまま採用）

```python
MIN_ACTION_CONFIDENCE = 0.50

eligible = [c for c in complete if c.confidence >= MIN_ACTION_CONFIDENCE]
below_threshold = [c for c in complete if c.confidence < MIN_ACTION_CONFIDENCE]
```

**confidenceはRanking順序（3節のsort key）に一切混ぜない。** 足切りにのみ使う。`below_threshold`は捨てず、`RejectedCandidate(category="score", reason_code="confidence_below_threshold")`として保持する（6節）。

## 3. Ranking key（tie-break含む、新規決定が必要）

一次キーはscore_per_hour降順で確定している。ただし**score_per_hourが完全に一致するケース**（例: 同一commodityを買う複数stationがたまたま同じeffective priceになる）への規則がこれまで存在しなかった。Pythonの安定ソートに任せると、tie時の順序は「candidate生成順（mining→bio、DBクエリ順）」という偶然の産物になり、決定論的とは言えない。

以下の4段階を提案する。

```text
1. score_per_hour        DESC   (主キー)
2. expected_value        DESC   (同レートなら総額が大きい方を優先)
3. action_horizon_seconds ASC   (同レート・同総額なら所要時間が短い方を優先)
4. target_id              ASC   (完全な決定論のための最終タイブレーク。3節までで同点なら
                                   実質的に「どちらでもよい」状況だが、実行のたびに順序が
                                   変わることは避ける)
```

`target_id`は`RejectedCandidate.target_id`と同じ値を使う（4節）。

## 4. target_idの導出（未定義だったため新規決定）

`RejectedCandidate.target_id: str`は既にPhase 2-0で型として定義されているが、**具体的にどう組み立てるかはこれまで一度も決まっていない**（`app/scoring/filters.py`が現状pass-throughのため使用実績がない）。`BioTarget`/`MiningTarget`にはstation_idはあるがsystem/body由来のものは持たない、`mining_continue`/`mining_start`は`station_id=None`のringターゲットである、という不統一を踏まえ、以下の決定論的な文字列を提案する。

```python
def target_id(action: str, target: BioTarget | MiningTarget) -> str:
    if isinstance(target, MiningTarget):
        if target.station_id is not None:
            return f"{action}:station:{target.station_id}"
        return f"{action}:ring:{target.system_name}"
    return f"{action}:body:{target.system_name}:{target.body_name}"
```

DBの主キーではなく、あくまで「同じcandidateを指す文字列が毎回同じになる」ことだけを保証する表示・比較用の識別子。

## 5. DTO確定

### 5.1 Recommendation（Phase 2-0 §2.1のフィールドを維持しつつ、Phase 2-5分をプレースホルダにする）

```python
@dataclass
class Recommendation:
    action: str
    target: BioTarget | MiningTarget
    expected_value: float
    action_horizon_seconds: float
    score_per_hour: float
    confidence: float

    breakdown: dict[str, HorizonComponent]
    data_sources: list[DataSource] = field(default_factory=list)   # Phase 2-5が埋める
    reasons: list[ReasonFact] = field(default_factory=list)         # Phase 2-5が埋める
    rejected: list[RejectedCandidate] = field(default_factory=list) # 6節。alternatives/below-thresholdの写し
    narration: str | None = None                                    # Phase 2-5が埋める
```

`ActionCandidate`から`Recommendation`への変換は単純な1:1（`expected_value`/`action_horizon_seconds`/`score_per_hour`は`is_scoreable()`により非Noneが保証済みなので、ここで`float`型として確定させてよい）。

**確定: 縮小版の別名型は作らない。** Phase 2-0で既に「最終的に返すべきDTO」として`Recommendation`が定義されている以上、`ActionCandidate → ScoredCandidate → Recommendation`のような不要な変換層を挟まず、`ActionCandidate → Recommendation`の1:1変換のみとする。`data_sources=[]`/`reasons=[]`/`narration=None`はPhase 2-4では単に未設定のまま（Phase 2-5が埋める）。

`Recommendation.rejected`（Phase 2-0由来のフィールド）は**Phase 2-4では使わず常に`[]`のまま**とする——canonicalな格納場所は5.3節で新設する`NextActionResponse.rejected`であり、`Recommendation.rejected`の意味づけはPhase 2-5で再検討する。

### 5.2 RejectedCandidate（Phase 2-0のまま、reason_codeの語彙のみ追加）

```text
category="score" の reason_code:
  "lower_score"               -- ranking対象だが1位ではなかった
  "confidence_below_threshold" -- confidence < MIN_ACTION_CONFIDENCE
```

`value`にはその候補の`score_per_hour`、`comparison`には選ばれた1位の`score_per_hour`（`confidence_below_threshold`の場合は`comparison`に`MIN_ACTION_CONFIDENCE`、`value`に実際のconfidence）を入れる。

### 5.3 NextActionResponse（`rejected`フィールドを新設、Phase 2-0から変更）

```python
@dataclass
class NextActionResponse:
    next_action: str | None
    recommendation: Recommendation | None
    alternatives: list[Recommendation]
    incomplete: list[IncompleteCandidate]
    rejected: list[RejectedCandidate]   # 新設 -- category="filter"と"score"の両方をここに集約
    reason: str | None
```

**確定: `RejectedCandidate`のcanonicalな格納場所は`Recommendation.rejected`ではなく`NextActionResponse.rejected`。** `RejectedCandidate`は特定のRecommendationに属する情報ではなく、レスポンス全体の監査対象（「なぜAが選ばれ、B/C/Dが選ばれなかったか」）だからである。

## 6. Alternatives の件数と RejectedCandidate との関係（新規決定が必要）

`docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md §4.2`は「Score-loss records must contain the numeric comparison. They do not need to enumerate every losing candidate in the UI. Phase 2 UI should normally expose only the top few score-loss alternatives while retaining the deterministic records internally」と述べている。これに沿い、以下の2層構造を提案する。

```text
eligible[1:] (confidence>=0.50, 1位を除く全員)
        ↓                              ↓
alternatives                    RejectedCandidate(category="score",
(上位ALTERNATIVES_LIMIT=3件、       reason_code="lower_score")
 Recommendation型で公開)          （eligible[1:]全員 + below_threshold全員、
                                   件数無制限、監査・デバッグ用に保持）
```

`ALTERNATIVES_LIMIT=3`は暫定値（デザイン根拠なし、切りのいい数として提案）。UI要件が固まっていない現時点では調整可能な定数として扱う。

## 7. Recommendation選定に追加の足切りを設けるか（確認済み・確定）

**確定: 設けない。** `eligible`が1件でもあれば、それがどれほど小さいscore_per_hourであっても`ranked[0]`をそのままRecommendationにする。「行動なし」を推奨することはState Driven設計の目的（今できる最善の一手を常に提示する）に反するため、confidence thresholdより上の追加フィルタは導入しない。

## 8. 候補が0件のケース（2種類を区別する）

```text
ケース A: complete が最初から空
  → next_action = None, recommendation = None
  → reason = "有効な候補行動がありません"（IMPLEMENTATION_SPEC §13.2の既存文言を踏襲）

ケース B: complete はあるが、全員 confidence < MIN_ACTION_CONFIDENCE
  → next_action = None, recommendation = None
  → reason = "候補はあるが confidence が閾値未満です"（§12.3の既定文言を踏襲）
```

両方とも`recommendation=None`という結果は同じだが、`reason`文言を分けることで「そもそも候補がない」のか「候補はあるが信頼できない」のかをUI/ログで区別できるようにする。

## 9. 関数境界（Phase 2-3 §7で予約された名前を実装）

```python
# app/scoring/ranking.py（新規）

def rank_candidates(
    candidates: list[ActionCandidate], min_confidence: float = MIN_ACTION_CONFIDENCE
) -> tuple[list[ActionCandidate], list[ActionCandidate]]:
    """Returns (eligible_sorted, below_threshold). Sort key: 3節の4段階tie-break。"""

def select_recommendation(eligible_sorted: list[ActionCandidate]) -> Recommendation | None:
    """ranked[0]をRecommendationへ変換。空ならNone。"""

def build_alternatives(eligible_sorted: list[ActionCandidate], limit: int = ALTERNATIVES_LIMIT) -> list[Recommendation]:
    """eligible_sorted[1:limit+1]をRecommendationへ変換。"""

def build_score_rejections(
    eligible_sorted: list[ActionCandidate], below_threshold: list[ActionCandidate]
) -> list[RejectedCandidate]:
    """eligible_sorted[1:]全員 + below_threshold全員をRejectedCandidate(category="score")へ。"""

def assemble_next_action_response(result: CandidatePipelineResult) -> NextActionResponse:
    """上記4関数 + 8節の空ケース分岐を束ね、NextActionResponseを組み立てる。
    response.rejected = [*result.rejected, *build_score_rejections(...)]
    -- filter rejectionsを先に、score rejectionsを後に並べる（確定、10節）。
    score rejections内部の順序は build_score_rejections の返り値の並び
    （eligible_sorted[1:] → sorted(below_threshold, 同じtie-breakキー)）を
    そのまま使う -- 結果として lower_score が confidence_below_threshold より
    先に来るが、これは意図的なグルーピングではなくRanking由来の順序の帰結。"""
```

**候補生成の不変条件（本書が前提とする既存の性質）**: 同一の`action`+`target`を指すcandidateは、候補生成段階（Phase 2-2）で重複生成されない。したがって`target_id(action, target)`は同一ランキング内での候補の決定論的な一意識別子として機能する。

## 10. 決定事項サマリ（レビューで確定）

1. **Recommendation DTO**: Phase 2-0の型をそのまま使用する。縮小版の別名型（`ScoredCandidate`等）は作らない。`ActionCandidate → Recommendation`の1:1変換のみ
2. **`ALTERNATIVES_LIMIT`**: 3件で確定。Rankingそのものを3位までに制限するのではなく、**公開するalternativesの件数**を3件に制限する（4位以降は`RejectedCandidate(category="score")`として全件保持し、情報は失わない）
3. **RejectedCandidateの格納場所**: `NextActionResponse.rejected`を新設し、こちらをcanonicalとする。`Recommendation.rejected`はPhase 2-4では常に`[]`（Phase 2-5で意味を再検討）
4. **tie-break**: `score_per_hour DESC → expected_value DESC → action_horizon_seconds ASC → target_id ASC`で確定
5. **rejectedの並び順**: `NextActionResponse.rejected`は`[*filter rejections, *score rejections]`の順。score rejections内部はRanking由来の順序（lower_score群→confidence_below_threshold群という結果になるが、reason_codeでの明示的グルーピングではない）

## 11. Phase 2-4 Exit Criteria

- [ ] `MIN_ACTION_CONFIDENCE=0.50`によるconfidence足切りが実装され、Rankingの並び順には一切影響しないことがテストされている
- [ ] score_per_hour完全同点時、3節のtie-break順で決定論的に順序が確定することがテストされている
- [ ] `eligible`が0件（complete自体が空）と、`eligible`が0件（全員below threshold）の2ケースで異なる`reason`文言が返ることがテストされている
- [ ] Recommendation選定に confidence threshold 以外の追加フィルタがないことがテストされている（極小score_per_hourでも1位ならRecommendationになる）
- [ ] `alternatives`が`ALTERNATIVES_LIMIT`件に制限され、それを超えた分は`RejectedCandidate(category="score")`としてのみ保持されることがテストされている
- [ ] `below_threshold`の候補が`RejectedCandidate(category="score", reason_code="confidence_below_threshold")`として保持され、単純に捨てられないことがテストされている
- [ ] `IncompleteCandidate`がRankingに一切影響されず、そのまま`NextActionResponse.incomplete`へ通ることがテストされている
- [ ] `NextActionResponse.rejected`が`[*filter rejections, *score rejections]`の順で構築され、`Recommendation.rejected`は常に`[]`であることがテストされている
- [ ] 既存215テストに回帰がない
