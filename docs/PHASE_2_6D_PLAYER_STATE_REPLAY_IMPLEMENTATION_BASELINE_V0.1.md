# EDpj Phase 2-6D Player State Replay Implementation Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/journal_replay.py`新設。既存351テスト+新規9テスト、計360テスト全通過。Exit Criteria全項目達成）
**Date:** 2026-09-05
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §6/§9.4（v0.1, commit `013d92c`）, `docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md` §1（v0.2, commit `c4bbe8e`）, `app/state/reducer.py`, `app/journal/events.py`, `app/db/models/journal.py`, `app/db/models/timing.py`, `app/routing/time.py`, `app/calibration/engine.py`

## 0. スコープ（実装可能性の調査を経て縮小）

### 0.1 発見した制約

`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §6は本人Journal E2E評価として「Journal → State → Candidate → Horizon → Value → Confidence → Recommendation → 実際の結果」を描いているが、実装前調査で以下が判明した。

`app/state/reducer.py`の`build_reduced_state()`は`reduce_events(events)`（journalイベントの純粋な畳み込み）と`reduce_status(status.data)`/`reduce_cargo(cargo.data)`（**現在の**`Status.json`/`Cargo.json`スナップショット）を合成している。位置・ドック状態・船体IDは`reduce_events()`だけで再構成できるが、**`CargoState`（保有貨物量）・`credits`・`fuel`はStatus/Cargo.jsonというその瞬間限りのスナップショットからしか得られず、journalイベントの畳み込みでは再構成できない**。`CargoState`テーブル自体もbackfillのたびに全削除→再挿入される「現在値のみ」のテーブルで、過去の保有量の時系列を一切保持していない。

`_mining_sell_value()`/`_mining_continue_value()`（Value計算）と`has_mining_cargo()`（Candidate Generation, `app/mining/state.py`）はいずれも`CargoState`を直接クエリするため、この制約はCandidate Generation・Value・Score・Ranking・Recommendationの全段階に及ぶ。

理論上は`MiningRefined`/`MarketBuy`/`MarketSell`/`CollectCargo`/`EjectCargo`イベントから保有量を積み上げるevent-sourcingロジックを新規実装すれば解決できるが、これは2-6Dの範囲を大きく超える新機能であり、既存のどのPhaseにも存在しない。

### 0.2 確定（レビューで決定）: PlayerState（位置/ドック/船体）のみのT0再構成に絞る

```text
Journal → State（位置/ドック/船体のみ、T0境界あり） → Horizon計算の妥当性検証
```

**対象外:**

```text
- Candidate Generation（mining系はCargoState依存のため全滅、bio系も含め本Phaseでは扱わない）
- Value / Score / Ranking
- Recommendation E2E
- CalibrationModelのT0境界付き再較正（現行のCalibrationModelは
  Phase 2-1の既存fit/eval splitで較正された「現在の1つのモデル」のみで、
  時点ごとにバージョン管理されていない。これをT0境界で再較正する機能は
  2-6Dの範囲を超える——構築するとPhase 2-1の較正エンジンをまるごと
  時系列対応に作り直すことになる）
```

`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §9.4は元々「2-6Dのデータが不十分なら2-6B/2-6Cのみを確定値の根拠とする」としており、2-6Dの結果は最初から補助的な位置づけである。今回の縮小はこの位置づけと整合する。

## 1. State再構成（新設 `app/backtest/journal_replay.py`）

```python
@dataclass(frozen=True)
class ReplayPlayerState:
    """journalイベントのみからt0境界で再構成したPlayerStateの部分集合。
    cargo/credits/fuel/on_footは意図的に含めない -- これらはStatus.json/
    Cargo.jsonという『今この瞬間』のスナップショットからしか得られず、
    過去のt0時点の値を持たない(§0.1)。`fields`を持たない空dictと
    『確認したところ空だった』を混同しないため、ReducedPlayerState
    (cargo_rows/source_statusを持つ、app/state/reducer.py)を流用せず
    専用の型として定義する。"""
    t0: dt.datetime
    fields: dict  # reduce_events()が設定しうるキーのみ:
                  # current_system, current_system_address, current_body_id,
                  # current_body_name, current_station_id, current_station_name,
                  # docked, landed, current_ship_id


def reconstruct_player_state_at(session: Session, t0: dt.datetime) -> ReplayPlayerState:
    """app.journal.events.STATE_RELEVANT_EVENTSに属し、timestamp <= t0の
    JournalEventのみを対象に、app.state.reducer.reduce_events()を
    無改変で呼ぶ。reduce_events()自体は既にjournalイベントの純粋な
    時系列畳み込みであり、新しいreducerロジックを一切書かない
    -- events.py/reducer.pyの二重実装を避ける。"""
    events = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type.in_(ev.STATE_RELEVANT_EVENTS))
        .filter(JournalEvent.timestamp <= t0)
        .all()
    )
    return ReplayPlayerState(t0=t0, fields=reduce_events(events))
```

## 2. 未来情報リーク防止

2-6A（`docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md` §5のTestFutureLeakagePrevention）と同じ形式のregression testを課す。T0以前/T0ちょうど/T0より未来のJournalEventを混在させたfixtureで`reconstruct_player_state_at()`を呼び、結果を記録した後に大量の未来イベント（別システムへのFSDJump、別stationへのDocked等、fieldsを書き換えうるもの）を追加投入し、再度呼んで結果が変化しないことを確認する。

`JournalEvent.timestamp <= t0`はSQLレベルのフィルタであり、`app/backtest/replay.py`の`observe_actual_after()`のようなPython側の日時演算（SQLiteのtz round-trip問題）は発生しない——フィルタ自体はSQLAlchemyがバインドパラメータとして処理するため、`_naive()`相当の対処は本関数には不要（対象がPython側の`min()`/`abs()`のような直接比較ではないため）。

## 3. Horizon診断（既存TimingSampleとの突き合わせ、Go/No-Go材料ではない）

### 3.1 位置づけの明確化（重要な限界の明記）

`app/routing/time.py`の`estimate_segment()`は、**現在の**`CalibrationModel`（Phase 2-1の既存fit/evalスプリットで較正済みの、時点非依存の単一モデル）を読む。あるT0時点の`TimingSample`をこのモデルの現在の推定値と突き合わせても、そのサンプルがそもそも現行モデルのfit側スプリットに含まれていた場合、モデルは「そのサンプル自身を見て」較正されているため、比較は楽観的にバイアスされる。**これは2-6A〜Cが厳守してきた未来情報リーク禁止と同じ種類の問題であり、正直に限界として明記する。**

したがって本節が生成する数値は、**Phase 0-C/2-1が既に持つ`CalibrationModel.median_absolute_error`（held-out evalスプリットに基づく、リークのない正式な精度指標）を置き換えるものではない**。あくまで「個々の実測segmentに対して、現行の推定ロジックが実際に妥当な値を返しているか」を突き合わせる診断であり、Exit Criteriaのpass/fail判定には使わない。

### 3.2 診断関数

```python
@dataclass(frozen=True)
class HorizonDiagnosticSample:
    segment_type: str
    start_time: dt.datetime
    actual_duration_seconds: float
    estimate: TimeEstimate  # app.routing.time.estimate_segment()の現在の出力
    relative_error: float | None  # estimate.status != "estimated" ならNone（0埋め・補間しない）


def collect_horizon_diagnostics(session: Session) -> list[HorizonDiagnosticSample]:
    """既存のtiming_samplesテーブル（Phase 0-B/0-Cで収集済み）の各行に
    ついて、その segment_type の現在の estimate_segment() 出力を突き合わせる。
    supercruiseは常にunavailableのため(app/routing/time.py)、
    relative_errorは常にNoneになる -- これは異常ではなく仕様通り。"""
```

`relative_error = abs(estimate.seconds - sample.duration_seconds) / sample.duration_seconds`（`estimate.status == "estimated"`の場合のみ）。

## 4. Acceptance Tests

```text
reconstruct_player_state_at()がt0以前のイベントのみからPlayerStateを再構成する
reconstruct_player_state_at()がt0より後のイベント追加で結果が変化しない
   （future leakage prevention、2-6Aと同形式）
reconstruct_player_state_at()がcargo/credits/fuel/on_footを一切含まない
   （ReducedPlayerStateと型として区別されており、フィールドが存在しない
   ことが構造的に保証されている）
reconstruct_player_state_at()がSTATE_RELEVANT_EVENTS以外のevent_typeを無視する
collect_horizon_diagnostics()がsupercruiseサンプルに対して常にrelative_error=Noneを返す
collect_horizon_diagnostics()がestimate.status="unavailable"の場合にrelative_error=Noneを返し、
   0や補間値にしない
collect_horizon_diagnostics()がTimingSampleの実測値を書き換えない（読み取り専用）
```

## 5. Exit Criteria

- [x] `app/backtest/journal_replay.py`が新設され、`ReplayPlayerState`/`reconstruct_player_state_at`/`HorizonDiagnosticSample`/`collect_horizon_diagnostics`が実装されている
- [x] `reconstruct_player_state_at`が`app.state.reducer.reduce_events`を無改変で再利用している（reducerロジックの二重実装がない）
- [x] `ReplayPlayerState`にcargo/credits/fuel/on_foot相当のフィールドが存在しない（構造的保証）
- [x] future leakage preventionが2-6Aと同形式のregression testで保証されている
- [x] `collect_horizon_diagnostics`が「診断であり、独立したリークのない精度指標ではない」という限界がdocstring・本書双方に明記されている
- [x] 既存351テストに回帰がない

## 6. 決定事項サマリ

1. **§0 Candidate Generation〜Recommendation E2Eは対象外**: `CargoState`に過去の時系列がなく、mining系Candidate Generation・Value計算のいずれもCargoStateに依存するため。位置・ドック状態・船体ID（journalイベントのみで再構成可能な範囲）に限定する
2. **§1 `reduce_events()`を無改変で再利用**: 新しいreducerロジックを書かず、既存のPhase 0-Aの畳み込みをT0境界付きイベント集合に適用するだけ
3. **§1 専用の`ReplayPlayerState`型**: 既存の`ReducedPlayerState`（cargo_rows/source_statusを持つ）を流用せず、cargo/credits/fuelを含まないことを型で保証する
4. **§3 Horizon診断はGo/No-Go材料ではない**: 現行`CalibrationModel`が時点非依存でリークの可能性があるため、この診断は`CalibrationModel.median_absolute_error`を置き換えず、個々のsegmentとの突き合わせという補助的な位置づけに留める
5. **CalibrationModelのT0境界付き再較正は範囲外**: Phase 2-1較正エンジンの時系列対応という別の大きな仕事であり、2-6Dでは着手しない
