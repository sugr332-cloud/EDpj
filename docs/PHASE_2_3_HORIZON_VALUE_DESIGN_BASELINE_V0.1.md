# EDpj Phase 2-3 Horizon / Value Design Baseline

**Version:** 0.4
**Status:** Implemented（Baseline Fixed後、実装完了。既存181テスト+新規23テスト、計204テスト全通過。Exit Criteria全項目達成）
**Date:** 2026-09-05
**Depends on:** `IMPLEMENTATION_SPEC_V0.2.md` §10/§11/§12, `docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md`, `docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md`

## 0. 最重要の発見: 「完全性」は2軸ある

設計を詰める過程で、ご提案の「IncompleteでもValueを計算してよい」を実際に適用しようとすると、**horizon完全性とvalue計算可能性は独立した別の軸である**ことが分かった。理由は単純で、**Bioの種価値モデル（`organic_species`/`organic_conditions`）がまだ存在しない**ため、`bio_current_body`は`horizon_complete=true`（Phase 2-2で確定済み）であっても、`expected_value`を計算する材料が現状ゼロだからである。

用語は`value_calculable`に統一する（`value_complete`は使わない）。

```text
                         value_calculable
                      false             true
                 ┌──────────────┬──────────────┐
horizon_complete │ Incomplete   │ Incomplete   │
false            │              │              │
                 ├──────────────┼──────────────┤
horizon_complete │ Incomplete   │ Score対象    │
true             │              │              │
                 └──────────────┴──────────────┘
```

したがって`IncompleteCandidate`は「horizon不完全」専用ではなく、**「まだScore対象にできない」を表す型全般**として再定義する。

## 1. IncompleteCandidateの拡張

```python
@dataclass
class IncompleteCandidate:
    action: str
    target: BioTarget | MiningTarget
    expected_value: float | None          # 計算できれば保持。できなければNone
    breakdown: dict[str, HorizonComponent]
    blocking_segments: list[str]          # horizon側のブロッカー（例: ["supercruise"]）。なければ[]
    value_unavailable_reason: str | None  # value側のブロッカー（例: "species value model not implemented"）。値が出せていればNone
    reason: str
```

Score計算に進めてよいかどうかの判定（Score対象判定, `is_scoreable()`）を以下に明示する。**この判定はPhase 2-3の責務であり、Recommendation/alternatives選定（Phase 2-4のRanking）とは別物である**——ここで「昇格」しても、複数のScore対象からどれをRecommendationとして選ぶかはPhase 2-4が決める。

```python
def is_scoreable(candidate: IncompleteCandidate) -> bool:
    return (
        candidate.blocking_segments == []
        and candidate.expected_value is not None
        and candidate.value_unavailable_reason is None
    )
```

3つ目の条件は論理的には2つ目と対になる（`expected_value is not None`であれば通常`value_unavailable_reason is None`のはず）が、**2軸モデルとの対応を明示するため冗長でも両方チェックする**。いずれか一つでも欠けていれば`IncompleteCandidate`のまま保持する。`expected_value`が計算できているのに`blocking_segments`が残っているケース（例: `mining_sell`）では、**expected_valueを保持しておく**ことで、将来SCモデルが入った時にValue再計算が不要になる。

## 2. 現時点で判明している6 Actionの実現可能性（重要）

Value計算の実装可能性を洗い出した結果、**Phase 2-3の範囲では、現時点でScore到達可能性があるのは`mining_continue`のみである。ただし、cargo capacity取得が必要**であり、それが揃って初めて実際にScore到達する（本書執筆時点ではまだ揃っていないため、Score対象はまだ0件——これはPhase 2-3の目的が「無理にScore対象を作ること」ではなく「Score対象になれる条件を正しく実装すること」である以上、問題ではない）。以下で詳細を示す（決定事項反映後）。

| Action | horizon_complete | value_calculable | 備考 |
|---|---|---|---|
| `mining_sell` | false (SC) | ✅ 可能 | 市場データは候補生成時点で必須のため既にある |
| `mining_continue` | true | ⚠️ 要新規実装 | commodity/quantityは確定、cargo capacityはLoadoutから取得可能。市場（demand>0）がある場合のみScore到達（4.3節） |
| `mining_start` | false (SC) | ❌ Phase 2-3では実装しない | 4.4節で確定。将来Mining Start Value Modelとして別設計 |
| `bio_current_body` | true | ❌ 不可能 | `organic_species`データ不在（5節） |
| `bio_next_system` | false (SC) | ❌ 不可能 | 同上 |
| `bio_return` | false (SC) | ❌ 不可能 | 同上。`unsold_bio_value`は種価値モデルに依存するため実測値として取得不能と判明（5節） |

**つまり、Phase 2-2で「complete」と確定した`bio_current_body`は、Value軸を追加すると依然として`IncompleteCandidate`のままである。** これはPhase 2-2の判定を覆すものではなく、「horizon」と「value」という別の完全性次元を導入したことの当然の帰結である。

## 3. Horizon Builder（変更なし、確認のみ）

Phase 0-C/2-2で確定済みの6 Action別`required_segments`はPhase 2-3で変更しない。

```text
mining_sell        : ["jump", "supercruise", "dock"]
mining_continue    : ["mining_cycle"]
mining_start       : ["jump", "supercruise", "mining_cycle"]
bio_current_body   : ["descent", "bio_sample", "ascent"]
bio_next_system    : ["jump", "supercruise", "descent", "bio_sample", "ascent"]
bio_return         : ["jump", "supercruise", "dock"]
```

`build_horizon`/`estimate_segment`/`TimeEstimate`（measured/estimated/unavailable）もPhase 0-C/2-1のまま変更しない。

## 4. Mining Value

### 4.1 Effective price（§10.1、そのまま実装可能）

```text
r = cargo / demand
r <= 0.25        penalty = 1.00
0.25 < r < 0.80  linear 1.00 → 0.45
r >= 0.80        penalty = 0.45
effective_price = listed_price × penalty
```

`app/mining/price.py`として実装。`MiningTarget.demand`/`cargo_demand_ratio`/`listed_price`/`effective_price`（Phase 2-2でNoneのまま残していたフィールド）をここで埋める。

### 4.2 Mining Sell value（§10.2、実装可能）

```text
value = Σ(quantity × effective_price)  # 保有commodityごとの合計
```

`quantity`はCargoState、`effective_price`は4.1節。candidate生成時点で既にmarket dataが必須条件になっているため、value計算に必要な入力は既に揃っている。

### 4.3 Mining Continue value（§10.3、実装直前の実データ検証で全面修正）

実装着手前に`MiningRefined`の実ペイロードとcargo capacityの取得可否を検証した結果、v0.3の前提が2点崩れていることが分かった。以下は検証を反映した確定版。

**① `expected_mined_quantity`は統計モデルではなく確定値1.0。** 実際の`MiningRefined`イベントは`{"event": "MiningRefined", "Type": "$platinum_name;"}`の形で、**数量フィールドを持たない**——1イベント = 常に1tというゲーム仕様である（EDCD Journal manual系ドキュメントで確認）。したがって`app/mining/yield_model.py`はCalibration Engineのようなmedian推定を行わず、`EXPECTED_REFINED_QUANTITY_PER_EVENT = 1.0`という確定値を扱う。統計モデルを持ち込まないこと自体が「推測しない」方針の正しい適用である。

**② 次の1tのcommodityは、現在の採掘セッションに属する直近`MiningRefined.Type`を使う。** `mining_continue`候補は既に`context.mining_active`（`DEFAULT_MINING_ACTIVE_LOOKBACK`以内に`MiningRefined`がある）の場合にのみ生成されるため（`app/mining/candidates.py`の`generate_mining_continue_candidates`）、「直近イベントが現在のセッションに属する」という条件は候補生成の時点で既に保証されている。Value計算はその同じイベントの`Type`（`_strip_internal_name`で正規化）を読むだけでよい。

**③ cargo capacityは実は取得可能——Loadout解析が必要という前提が誤りだった。** Phase 0-Aのパーサ/extractor（`app/journal/parser.py`/`app/journal/extractor.py`）は**イベント種別を問わず全行をverbatimで`journal_events`に保存する**設計であり、`Loadout`イベントも例外ではない。実Journalの`Loadout`イベントはトップレベルに`CargoCapacity`（トン数の整数）を直接持つ（EDCD Journal manual系ドキュメントで確認）。したがって`app/mining/cargo_capacity.py`は「Loadout解析」という新機能ではなく、`journal_events`から`event_type='Loadout'`の最新行を取得し`payload["CargoCapacity"]`を読むだけの単純なクエリでよい。`Loadout`が一度も記録されていない場合のみ`None`（`CargoCapacity=0`は有効値であり`None`と区別する）。

**④ 売却市場は、既知market中でeffective_priceが最大の1件を決定論的に選ぶ。** `mining_continue`候補自体は`target=ring`で市場を持たないため、値計算専用に「そのcommodityについて`demand > 0`の`MarketLatest`行の中から、§4.1のeffective_price計算式で最大値を出す1件」をvalue評価用の仮想的な売却先として選ぶ。**これは実際にそこへ移動するという意味ではなく**（移動時間はこのcandidateのhorizonに一切追加しない）、「観測済みmarketの中でモデル上もっとも高いeffective priceを使う」という決定論的な評価基準に過ぎない。既知marketが複数あるほどValueが計算不能になるという逆転現象を避けるため、複数一致時に計算を諦める設計は採用しない。

```text
evaluation_cargo = min(current cargo + 1.0, cargo capacity)
best_market = 対象commodityでdemand>0のMarketLatestのうちeffective_price最大の1件
expected_effective_sell_price = best_marketのeffective_price（§4.1）
expected_value = 1.0 × expected_effective_sell_price
```

**確定: 上記いずれかの入力が欠けても近似しない。** 判定順序は以下の通り（cargo capacityは`mining_active`が真である限りcommodityは常に確定しているため、実質的なチェックはcargo capacityとmarketの2つ）。

```text
cargo capacity unknown（Loadout未記録）
    → expected_value = None, value_unavailable_reason = "cargo_capacity_unknown"
対象commodityにdemand>0のmarketが1件も存在しない
    → expected_value = None, value_unavailable_reason = "no_market_target"
両方満たす
    → expected_value を計算する
```

将来「売却先まで含めた移動時間を考慮するモデル」を導入する際も、この節の決定（市場選択は評価用であり移動は含まない）と衝突しない。

### 4.4 Mining Start value（§10.4、Phase 2-3では見送り）

仕様書§10.4はhorizonのみを定義し、value計算式を明記していない。

**確定: Phase 2-3では実装しない。** 4.3節のyield_modelを転用してhistorical ring locationの実績から期待採掘量を独自に定義することは技術的に可能だが、仕様に明記のないValueモデルを実装側の判断で持ち込むことになるため見送る。`mining_start`は常に以下とする。

```text
value_unavailable_reason = "not specified by §10.4 (deferred to a future Mining Start Value Model phase)"
```

将来、独立した「Mining Start Value Model」設計として別途仕様化する。

## 5. Bio Value（実装不可、Bio 3種すべて同一理由で不可）

§11.1 Base valueは`Σ p(s) × base_value(s)`という式を要求するが、これには

- `organic_species`（種ごとのbase_value）
- `organic_conditions`（生息条件からの種確率推定）

という、SPECIFICATION §12のテーブル一覧にはあるが**まだ一切実装されていない**静的データが必要である。Phase 2-2の設計時点で`predicted_species: list = []`として空のまま据え置いた通り、Phase 2-3でもこれは埋まらない。

したがって`bio_current_body`/`bio_next_system`は`value_unavailable_reason="species value model not implemented"`で固定し、Phase 2-3ではBio側のValue計算に着手しない。

**`bio_return`も同一理由で見送る。** レビュー時に「`unsold_bio_value`が既にStateから実測値として取得できるなら、それをそのまま使ってよい」という案が出たが、実装済みの`detect_unsold_bio_count`（Phase 2-2, `app/bio/conditions.py`）を確認したところ、これは**未売却サンプルの「件数」のみ**を返し、**金額（credits）は返さない**ことが分かった。`SellOrganicData`イベントは売却「済み」サンプルの実売却額を記録するが、未売却サンプルの価値を知るには「どの種か」→「その種のbase_value」という変換が必要であり、これは結局`organic_species`（見送り済みの種価値モデル）に依存する。したがって`unsold_bio_value`は現状「実測値として取得できる」状態ではなく、**近似（過去の平均売却額を代用する等）も採用しない**。`bio_return`も`value_unavailable_reason="species value model not implemented"`で`bio_current_body`/`bio_next_system`と統一する。

## 6. パイプライン（更新）

```text
Candidate Generation
        ↓
Filter
        ↓
Horizon Build（変更なし）
        ↓
Value Calculation（新設。horizon_completeを問わず試みる）
        ↓
   ┌────┴────┐
   │         │
horizon_complete かつ value_calculable
   │         │
  YES        NO
   │         │
Score計算   IncompleteCandidate
（§7）      （expected_value/breakdownを保持）
```

Value計算はhorizonの結果を待たずに実行してよい（両者は独立した入力を使うため）。ただし実装上は`build_horizon`の後に呼ぶ形で問題ない（依存はしないが、順序を変える理由もない）。

## 7. Scoreへの接続とRanking（確定: Phase 2-3はScore計算まで、Rankingは含めない）

```text
score_per_hour = expected_value / (action_horizon_seconds / 3600)
```

**確定した関数境界:**

```text
Phase 2-3で実装する:
    calculate_value()    # Mining Sell/Continue、§4
    calculate_score()    # score_per_hour = expected_value / horizon_hours
    is_scoreable()        # Score対象判定（本節）——Recommendationという名前はPhase 2-3に持ち込まない

Phase 2-4へ切り出す:
    rank_candidates()
    select_recommendation()
    build_alternatives()
    confidence合成（Π(component_confidence) × freshness_factor、Phase 2-0で保留中）
```

理由は2節の通り、実装完了時点でもScore到達可能性があるのは`mining_continue`（対象commodityにdemand>0のmarketが存在する場合のみ到達する）のみであり、Rankingを今実装しても比較対象が実質1種類しかない可能性が高いため。

Phase 2-3の`ActionCandidate.confidence`は、Phase 2-2までと同様に`generation_confidence`をそのまま引き継ぐ暫定値のままとする（Phase 2-0/2-1で確定した最終合成式は未適用）。

## 8. Phase 2-3 Exit Criteria

- [x] `IncompleteCandidate`が`blocking_segments`/`value_unavailable_reason`の2軸で「不完全」を表現できる（用語は`value_calculable`で統一）
- [x] Score対象判定条件（`is_scoreable()`: `blocking_segments == [] AND expected_value is not None AND value_unavailable_reason is None`）が実装されている（`app/scoring/models.py`）
- [x] Mining Sellのeffective price/valueが実装され、テストで検証されている（`app/mining/price.py`, `app/scoring/value.py`, `tests/integration/test_candidate_pipeline.py`）
- [x] `app/mining/yield_model.py`が`expected_mined_quantity=1.0`を確定値として扱い（統計モデルを持ち込まない）テストされている
- [x] `app/mining/cargo_capacity.py`が最新`Loadout`イベントの`CargoCapacity`を返し、`Loadout`未記録時のみ`None`（`cargo_capacity_unknown`）を返すことがテストされている
- [x] Mining Continueの売却市場が「対象commodityでdemand>0のMarketLatestのうちeffective_price最大の1件」として決定論的に選ばれ、該当marketが1件もない場合は`value_unavailable_reason="no_market_target"`となることがテストされている
- [x] Mining Startはvalue計算を実装せず、常に`value_unavailable_reason="not specified by §10.4 ..."`であることがテストされている
- [x] Bio 3種（current_body/next_system/return）すべてが`value_unavailable_reason="species value model not implemented"`で一貫していることがテストされている
- [x] `mining_sell`が「expected_valueは分かるがhorizonが不明」という状態でIncompleteCandidateとして保持され、値が失われないことがテストされている
- [x] `calculate_score()`（`expected_value / horizon_hours`）は実装するが、`rank_candidates`/`select_recommendation`/`build_alternatives`はPhase 2-4へ持ち越し、実装しない（`app/scoring/value.py`にrank/select/build系関数は一切存在しない）
- [x] 既存181テストに回帰がない（181 → 204、新規23件はすべてPhase 2-3のValue関連）

## 9. 決定事項サマリ（レビュー2巡目で確定）

1. **cargo capacity不明時**: 保守的近似はしない。`value_unavailable_reason="cargo_capacity_unknown"`
2. **Mining Start value**: Phase 2-3では実装しない。独立した「Mining Start Value Model」として将来設計する
3. **Bio Return value**: 近似しない。`unsold_bio_value`は実測値として取得不能（種価値モデルに依存するため）と判明し、Bio 3種すべてを`value_unavailable_reason="species value model not implemented"`で統一する
4. **Score/Ranking境界**: `calculate_value()`/`calculate_score()`はPhase 2-3、`rank_candidates()`/`select_recommendation()`/`build_alternatives()`/confidence合成はPhase 2-4
5. **（レビュー4巡目, 実装直前の実データ検証で追加）Mining Continueのexpected_mined_quantity**: `MiningRefined`に数量フィールドは存在せず、1イベント=1tの確定値。統計的yield modelは作らない
6. **（同上）Mining Continueのcommodity**: `mining_active`判定に使われた直近`MiningRefined.Type`をそのまま使う（候補生成時点で「現在のセッションに属する」ことは既に保証されている）
7. **（同上）Mining Continueのcargo capacity**: `journal_events`の最新`Loadout`イベントの`CargoCapacity`から取得可能（Loadout解析という新機能は不要、既存のverbatim保存アーキテクチャで既に取得できる）
8. **（同上）Mining Continueの売却市場**: 対象commodityでdemand>0のMarketLatestのうちeffective_price最大の1件を、移動を伴わない評価専用の仮想売却先として決定論的に選ぶ。該当なしなら`value_unavailable_reason="no_market_target"`

この4点の確定と、`value_calculable`への用語統一・Score対象判定条件（`is_scoreable()`）の明示（1節）をもって、本書はPhase 2-3実装のBaselineとして確定する。
