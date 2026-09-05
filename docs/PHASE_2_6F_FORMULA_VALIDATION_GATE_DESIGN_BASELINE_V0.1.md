# EDpj Phase 2-6F Formula Validation Gate — Design Baseline

**Version:** 0.1
**Status:** §2/§3 Implemented（`app/backtest/cargo_reconstruction.py`, `app/backtest/formula_validation.py`, `app/backtest/mining_formula_validation.py`、新規29テスト全通過。実データ（`data/edpj.db`）に対して実行し、`INSUFFICIENT`（`total_sell_events=0`）を確認・記録済み。§4/§5は元々新規実装なし/対象外）
**Date:** 2026-09-06
**Depends on:** `docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md`, `docs/PHASE_FORMULA_VALIDATION_AMENDMENT_V0.1.md`, `docs/CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`（以上3件、binding。本書はこれらの実行計画を具体化するのみで、要件そのものを変更しない）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md`, `docs/PHASE_2_6D_...md`, `app/backtest/replay.py`, `app/backtest/journal_replay.py`, `app/scoring/value.py`, `app/db/models/player.py`, `app/state/persist.py`, `app/state/reducer.py`

## 0. 位置づけ

`docs/PHASE_FORMULA_VALIDATION_AMENDMENT_V0.1.md` §3が定義する`Phase 2-6F Formula Validation Gate`を、固定された評価順序（Mining → Bio → Transport/Trade）に沿って具体化する。本書がカバーするのは:

- **2-6F-0（Preconditions）**: Mining Formula Validationを実行可能にするために必要な前提インフラ（§1/§2）
- **2-6F-1（Mining）**: 現行Mining Formula（`_mining_sell_value`/`_mining_continue_value`）の評価フロー設計（§3）
- **2-6F-2（Bio）**: 新規設計は不要——既存の`docs/PHASE_FORMULA_VALIDATION_AMENDMENT_V0.1.md` §2と`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §1.2が既に要件を規定済み。本書では「実行すれば何が起きるか」の確認のみ記録する（§4）
- **2-6F-3（Transport/Trade）**: 本書のスコープ外（§5）

## 1. 構造的ブロッカーの整理（2026-09-06発見、実データで確認済み）

Mining Formula Validationを「今すぐ実行できない」理由は、独立した2つの問題であり、混同してはならない。

**① データ不足（データ量の問題）**: 実Journal（`data/edpj.db`、848イベント、2026-08-26〜09-04）を集計した結果:

```text
MarketSell        0
MiningRefined     0
MarketBuy         0
MarketSnapshot    0
Docked            4  (848件中)
```

Mining関連の実績イベントが1件も無い。これは**現時点では`INSUFFICIENT`とするのが正しい**——`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §6「最低観測数を不自然に下げてPASSを作らない」に従う。

**② 構造的再現不能（データモデルの問題、データ量が増えても解消しない）**: `app/scoring/value.py`の`_mining_sell_value`/`_mining_continue_value`は`CargoState`を**ライブスナップショットとして無条件にクエリ**する（`session.query(CargoState).all()`）。一方`app/state/persist.py`の`apply_reduced_state()`は自身のコメントで明記している通り、`cargo_state`を「a full-replace snapshot, not an event log」として扱う——過去の`CargoState`の値は毎回削除され、時系列としては一切残らない。これはPhase 2-6D（`journal_replay.py`のdocstring）で既に発見済みの制約（「CargoStateにはどこにも履歴時系列が無く、Candidate/Value/Score/Rankingのreplayは不可能」）の直接の帰結であり、**実績データがどれだけ増えても、この層を追加しない限りMining Formula Validationは実行不能**。

この2つは分離して扱う（レビューで確定した設計原則）:

> Mining Formula Validationは、CargoStateの現在値を過去T0の入力値として使用してはならない。Historical ReplayにおけるMining Sell/Continueのpredicted_value算出には、T0以前のJournalイベントからCargo保有量を再構築するBacktest専用Historical Cargo Reconstructionを使用する。
>
> Historical Cargo Reconstructionが存在しない状態では、Mining Formula Validationを実行可能とはみなさない。
>
> 一方、再構築機構を実装した後も、評価対象となるMarketSell/MiningRefined等の実績観測が不足する場合はINSUFFICIENTとし、データ不足をPASSとして扱ってはならない。

**明示的に選ばない設計**: `CargoState`テーブル自体をevent-sourcing化する（本番の状態管理をイベントログ方式に作り替える）ことは**しない**。これはFormula Validationの要求範囲を超える大改修であり、本番の状態管理（`app/state/persist.py`）とBacktest専用の過去状態復元を無理に一体化する必要はない——Phase 2-6D（`journal_replay.py`の`reconstruct_player_state_at`）が既に確立した「本番state管理とは別に、Backtest専用のread-only reconstruction関数を作る」というパターンをそのまま踏襲する。

## 2. Historical Cargo Reconstruction 設計（2-6F-0）

新設 `app/backtest/cargo_reconstruction.py`。`journal_replay.py`と同じ位置づけ（`JournalEvent`履歴だけを読む、read-only、本番`CargoState`/`app/state/persist.py`には一切触れない）。

### 2.1 実データで確認済みのJournalイベント形状（2026-09-06、`data/edpj.db`から直接確認）

`Cargo`イベントは`Cargo.json`側ファイル（`app/state/reducer.py`が読む、履歴を持たないライブスナップショット）とは**別物**で、Journal本体に恒久的に記録される、`Inventory`配列を伴うチェックポイントであることを実データで確認した:

```json
{"timestamp": "2026-08-29T04:48:28Z", "event": "Cargo", "Vessel": "Ship", "Count": 0, "Inventory": []}
```

Cargo残量に影響するイベント（ゲームのJournal仕様に基づく、実データでは0件のため型のみ既知）:

| イベント | 効果 | 数量の取り方 |
|---|---|---|
| `Cargo`（チェックポイント） | 完全上書き | `Inventory`配列の`Name`/`Count`をそのまま採用 |
| `MiningRefined` | `Type`の量を+1 | 数量フィールドを持たない。既存`app/mining/yield_model.py`の`EXPECTED_REFINED_QUANTITY_PER_EVENT`定数を再利用する（新規定数を作らない——1イベント=1tという既存の前提と矛盾させないため） |
| `MarketBuy` | `Type`の量を`+Count` | `Count`フィールド |
| `MarketSell` | `Type`の量を`-Count` | `Count`フィールド |
| `CollectCargo` | `Type`の量を+1 | 数量フィールドを持たない（カーゴポッド1個=1t固定） |
| `EjectCargo` | `Type`の量を`-Count` | `Count`フィールド |

### 2.2 アルゴリズム

```python
def reconstruct_cargo_at_t0(session: Session, t0: dt.datetime) -> dict[str, int] | None:
    """T0時点で保有していたはずのcargoを、直近のCargoチェックポイント
    ＋そこからT0までの増減イベントの再生で復元する。チェックポイントが
    一件も無ければNone（"空だったと仮定"はしない -- ValueResult/
    calibrationの"Noneで正直に不明を表明する"原則をここでも踏襲）。"""
    checkpoint = _latest_cargo_checkpoint_at_or_before(session, t0)
    if checkpoint is None:
        return None
    quantities = dict(checkpoint.inventory)  # {commodity_name: quantity}
    for event in _cargo_delta_events_between(session, checkpoint.timestamp, t0):
        commodity, delta = _delta_for(event)
        quantities[commodity] = quantities.get(commodity, 0) + delta
        if quantities[commodity] < 0:
            raise CargoReconstructionIntegrityError(...)  # 黙ってclampしない
    return quantities
```

### 2.3 エッジケース（§6のAcceptance Testsに対応）

- T0が「観測している中で最初の`Cargo`チェックポイントより前」→ `None`（復元不能を明示。0だったと推測しない）
- T0以前に複数の`Cargo`チェックポイントが存在する → 直近1件（T0以前で最新のもの）を採用、最初のものではない
- チェックポイント後のイベント再生で、あるcommodityの数量が負になった → 黙って0にclampせず、整合性エラーとして表面化する（journal取り込み漏れ等、実際のデータ欠損のシグナルである可能性が高いため）
- T0**より後**のイベントは一切参照しない（future leakage禁止、Phase 2-6全体の既存原則をそのまま適用）
- `MiningRefined.Type`は内部名形式（`$platinum_name;`）——既存の`_mining_continue_value`が使っているのと同じ解決ロジックを再利用し、新しい変換ロジックを作らない

## 3. Mining Formula Validation Flow（2-6F-1）

`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §2/§3の一般形（`relative_error`/`hit`/`formula_accuracy`/chronological fit-validation-holdout）を、Mining Sellに対して具体化する。

**評価ケースの単位**: 実際に発生した`MarketSell`イベント1件 = 1評価ケース。「このプレイヤーが実際に売却した瞬間」を評価点として使う——予測対象が「もし将来これを売ったら」という仮説的なタイミングではなく、実際に売った瞬間なので、T0の選び方に恣意性がない。

```text
評価ケース i (実際のMarketSellイベント、timestamp = t_sell):
  t0 = t_sell の直前（売却が実行される瞬間の"直前"の状態）
  cargo_at_t0  = reconstruct_cargo_at_t0(session, t0)   -- §2
  market_at_t0 = t0時点で既知のMarketLatest/MarketHistoricalObservation（既存2-6A/2-5A基盤を再利用）
  predicted_value = 現行Mining Sell formulaのT0版
                     （§4.2の効果、cargo_at_t0×effective_priceの合算を
                      "ライブCargoStateではなくcargo_at_t0を引数に取る"
                      形に書き換えたbacktest版で計算する。本番の
                      _mining_sell_value自体は変更しない）
  actual_value = MarketSellイベント自身のペイロードから直接取得
                 （TotalSaleフィールド、または Count × SellPrice）
                 -- これは予測ではなく実際に起きたことなので、
                 別途「未来の観測」を追跡する必要がない
```

`cargo_at_t0 is None`（§2.3のチェックポイント無し）の評価ケースは`valid_cases`から除外し、除外件数を別途記録する（`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §6の「同じ観測を重複カウントしない」「未観測値を推測値で実績値として扱わない」に従う）。

**現時点での実行結果（見込み、実データ確認済み）**: 実`MarketSell`イベントが0件のため、N=0 → `INSUFFICIENT`。これは§2のHistorical Cargo Reconstructionを実装しても変わらない——再構築機構は「評価可能性を回復するための前提インフラ」であって、それ自体が実績データを作り出すわけではない（ユーザー指摘のとおり）。

## 4. Bio Formula Validation（2-6F-2）— 新規設計なし、実行結果の記録のみ

`docs/PHASE_FORMULA_VALIDATION_AMENDMENT_V0.1.md` §2および`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §1.2が既に要件を規定済みであり、本書で新たに設計することはない。

V1の校正関数（`app/bio/value.py`の`calibrate_expected_value_per_signal`）は、既に「実績データが無ければNoneを返す」形で実装済み（Phase 3 V1、`docs/PHASE_3_BIO_VALUE_MODEL_V1_DESIGN_BASELINE_V0.1.md`）。実データ（`ScanOrganic`/`SellOrganicData`ともに0件）に対して実行すれば、Mining同様に`INSUFFICIENT`となることが既に分かっている——これもコード上の欠陥ではなく、正直な結果である。

`scanorganic/1`アーカイブのcoverage測定（message/day, unique system/day, Genus/Species coverage等、Amendment §2.x）は、Mining Formula Validationとは独立した別タスクとして引き続き未着手のまま残る。本書はそれを妨げない。

## 5. Transport/Trade（2-6F-3）— 明示的に対象外

`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §7「この要件文だけを理由にTransport/Trade実装を開始してはならない」に従い、本書では一切扱わない。

## 6. Acceptance Tests

```text
reconstruct_cargo_at_t0() がT0以前にCargoチェックポイントが1件も無い場合Noneを返す
reconstruct_cargo_at_t0() がT0以前の複数チェックポイントのうち最新のものを採用する（最初のものではない）
reconstruct_cargo_at_t0() がチェックポイント後のMiningRefined(+1)/MarketBuy(+N)/
   MarketSell(-N)/CollectCargo(+1)/EjectCargo(-N)を正しく反映する
reconstruct_cargo_at_t0() がT0より後のイベントを一切参照しない（future leakage禁止）
reconstruct_cargo_at_t0() が負の数量に到達した場合、黙ってclampせず
   CargoReconstructionIntegrityErrorを送出する
Mining Formula Validationが実MarketSellイベント0件のときINSUFFICIENTを返す
   （0%のformula_accuracyや0件でのFAILにしない）
Mining Formula Validationのpredicted_value計算が、ライブCargoStateを一切
   クエリしないこと（構造的回帰ガード -- backtest版formulaがcargoを
   明示的な引数として受け取ることをテストで確認する）
```

## 7. Exit Criteria

- [x] `app/backtest/cargo_reconstruction.py`が新設され、`reconstruct_cargo_at_t0`が§6のAcceptance Testsを満たして実装されている（14テスト）
- [x] Mining Formula Validationの評価フロー（2-6F-1）が実装され、実データに対して実行し、`INSUFFICIENT`という結果とその根拠（`MarketSell`件数0）が記録されている（`app/backtest/formula_validation.py`が汎用accuracy-gate計算、`app/backtest/mining_formula_validation.py`がMining固有の配線、計15テスト）
- [x] 本番`CargoState`/`app/state/persist.py`に一切変更が無い（構造的境界の保持。`test_predicted_value_never_reads_live_cargo_state`で回帰ガードとしてテスト済み）
- [x] 既存テストスイートに回帰がない（452 → 467テスト、全通過）

### 実データ実行結果（2026-09-06、`data/edpj.db`に対して直接実行）

```text
verdict           = INSUFFICIENT
formula_accuracy  = None
valid_cases       = 0
minimum_cases     = 30  (MINIMUM_MINING_SELL_CASES, volatility_evaluation.pyの
                          MIN_SAMPLES_FOR_EVALUATION=30に倣った暫定値 -- 実データの
                          分布から正式に決めたものではない、§3参照)
total_sell_events = 0
excluded          = {no_cargo_checkpoint: 0, no_market_data: 0, integrity_error: 0}
```

想定通り`INSUFFICIENT`。§1で整理した「①データ不足」がそのまま観測された（`MarketSell`が0件のため`excluded`の内訳すら発生しない）。「②構造的再現不能」は§2のHistorical Cargo Reconstructionの実装により解消済み——実`MarketSell`が発生し次第、このパイプラインはコード変更なしに評価を再開できる。

## 8. 決定事項サマリ

1. **§1 データ不足と構造的再現不能を分離する**: 前者は`INSUFFICIENT`、後者は前提インフラの欠如。両方を同時に解決しようとしない
2. **§1 `CargoState`のevent-sourcing化はしない**: Backtest専用の`reconstruct_cargo_at_t0`をPhase 2-6Dの既存パターン（`reconstruct_player_state_at`）に倣って追加するに留める
3. **§2 Cargoの実復元は「直近チェックポイント＋差分再生」方式**: 実Journalの`Cargo`イベントが恒久的な`Inventory`チェックポイントを持つことを確認済み。チェックポイントが無いT0は復元不能として`None`を返す（0と推測しない）
4. **§3 評価ケースは実際の`MarketSell`イベントを単位とする**: 仮説的なタイミングを選ばず、恣意性を排除する
5. **§3 現時点の実行結果は`INSUFFICIENT`見込み**: 実`MarketSell`が0件のため。これは想定内であり、Historical Cargo Reconstructionの実装価値を否定するものではない（今後実績データが増えた時に即座に評価できる状態を作ることが目的）
6. **§4 Bioは新規設計なし**: 既存binding文書の要件をそのまま実行し、結果を記録するのみ
7. **§5 Transport/Tradeは対象外**: binding文書自身が実装開始を明示的に禁止している
