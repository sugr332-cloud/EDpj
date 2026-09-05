# EDpj Phase 2-6A Historical Replay Implementation Baseline

**Version:** 0.2
**Status:** Implemented（`app/backtest/replay.py`新設、`app/market/predictability.py`から`_compute_volatility_stats()`抽出。既存289テスト+新規19テスト、計308テスト全通過。Exit Criteria全項目達成。commit `c4bbe8e`）
**Date:** 2026-09-05
**Revision note（レビュー反映）**: v0.1は§4のforecast errorを`price_change_ratio(prev, curr)`の直接転用として設計しており、「予測値」と「実測値」という2つの独立した概念が1つの計算へ暗黙に融合していた（レビュー指摘）。v0.2は§4を全面改訂し、`PredictionInput`（`observed_at <= t0`のみ）と`ActualObservation`（`t0 < observed_at`のみ）を別々の型として明示的に分離した。予測モデル自体（naive last-value forecast）とその他の節（§1〜§3, §5〜§7）の決定は変更していない。
**Depends on:** `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §3/§4/§5（v0.1, commit `013d92c`）, `docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md`（commit `4b4d782`）, `app/market/predictability.py`, `app/market/volatility.py`, `app/db/models/market.py`, `app/collectors/eddn_archive.py`, `tests/conftest.py`（`db_session`フィクスチャパターン）

**命名についての補足**: `docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md`のリクエストでは`_IMPLEMENTATION_SPEC_`という語が使われたが、本リポジトリのdocs/以下の実際の命名規則は`PHASE_2_5A_..._IMPLEMENTATION_BASELINE_V0.1.md`/`PHASE_2_5D_..._DESIGN_BASELINE_V0.1.md`のように一貫して`_BASELINE_`を使っており、`_SPEC_`はプロジェクト横断のトピック仕様（`MARKET_PREDICTABILITY_SPEC`, `RECOMMENDATION_EXPLAINABILITY_SPEC`, ルート直下の`SPECIFICATION_V0.4.md`/`IMPLEMENTATION_SPEC_V0.2.md`）専用の語として予約されている。本書はPhase個別ドキュメントなので既存規則に合わせ`_IMPLEMENTATION_BASELINE_`を採用する。

## 0. スコープ

Phase 2-6Aは以下のみを実装する。

```text
1. T0時点でのvolatility分類の再計算（analyze_market()の既存ロジックをwindow比較用に再利用、§2）
2. window比較（7/14/30日）が本番のMarketPredictabilityテーブルを汚さない形での実装（§3）
3. T0以降の「実際の値」をリークなく取得するクエリ（§4）
4. forecast error算出（naive last-value forecastとしてprice_change_ratioを再利用、§4）
5. 未来情報リーク防止のregression test（§5）
```

**明示的にスコープ外:**

```text
- Candidate Generation → Horizon → Value → Confidence → Score → Rankingの
  フルパイプラインをEDDN Replayへ配線すること
  -- §1で詳述する通り、これは2-6D（本人Journal E2E）の責務であり、2-6Aは
  そのために必要な「T0時点のMarketLatest状態を再構成する」プリミティブを
  提供するに留める。2-6A自身のAcceptance Testはフルパイプラインを呼ばない。
- 2-6B（Volatility threshold評価）自体の判定ロジック・閾値再配置
  -- 2-6Aはforecast errorのサンプルを生成する基盤のみを作る。
  class毎の分布比較・順序関係の検証・閾値の再配置はPhase 2-6Bの仕事。
- 2-6C（Freshness curve評価）自体の較正ロジック
  -- 同上。2-6Aはage毎のforecast errorサンプルを生成できれば十分。
- Historical replayの評価結果を永続化する新規DBテーブル
  -- §3で述べる通り、window比較はMarketPredictabilityへ書き込まない
  compute-onlyパスを使う。2-6B/2-6C/2-6Dが自分の評価結果をどう記録するか
  （レポート出力か、別テーブルか）は各Phase自身が決める。2-6Aの時点で
  「今存在しない機能のための空テーブル」を先に作らない
  （Phase 2-5A §3の方針を継続）。
```

## 1. Design Baseline §3.2の図の具体化（未解決だったギャップの解消）

`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §3.2の図は

```text
T0以前のデータのみで予測
 ↓
Candidate Generation → Horizon → Value → Confidence → Score → Ranking
 ↓
predicted_action / predicted_value / predicted_horizon
```

としているが、これをそのまま2-6Aで実装しようとすると次の問題にぶつかる。

`app/scoring/value.py`の`_mining_sell_value`/`_mining_continue_value`は`MarketLatest`だけでなく`CargoState`（保有量）・`get_cargo_capacity()`（Loadoutから導出）も直接クエリする。`app/mining/candidates.py`/`app/bio/candidates.py`（Candidate Generation）も`PlayerState`（現在位置等）に依存する。これらは**EDDN historical archiveには存在しない**——EDDNは市場観測のみを配信し、特定プレイヤーの位置・貨物・船体情報は一切含まない。

つまり「T0時点のCandidate Generation → Ranking」を成立させるには、市場データだけでなく**T0時点のプレイヤー状態**（自分のJournalから再構成）が必要であり、これは`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §6が既に2-6Dとして分離している「本人Journal E2E評価」そのものである。

**確定: 2-6Aはフルパイプラインを配線しない。** 2-6Aが作るのは「T0時点の市場状態を、本番の`MarketLatest`テーブルを汚さずに再現できる」プリミティブのみであり、これは2-6B/2-6C（市場のみでforecast errorを測る、プレイヤー状態不要）が直接使い、2-6D（本人Journal + T0時点の市場状態を組み合わせてフルパイプラインを走らせる）が間接的に再利用する（§1.1）。

`docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md` §3.2の図はPhase 2-6A〜Dを合成した概念図として維持し、変更しない——本書が「その図のうちどの矢印をどのPhaseが実装するか」を明確化する。

### 1.1 2-6Dのための布石（実装はしないが、2-6Aのプリミティブが再利用可能である設計であることの確認）

2-6Dが実装される際は、`tests/conftest.py`の`db_session`フィクスチャと同じパターン（`make_engine("sqlite:///:memory:")` + `Base.metadata.create_all()`）で使い捨てのreplay用DBを作り、そこへ

```text
1. 2-6Aの§2が提供するMarketLatest再構成プリミティブでT0時点の市場状態を書き込む
2. 本人のJournalをT0まで再生してPlayerState/CargoState/Loadout由来の状態を書き込む
3. app.scoring.pipeline.generate_and_classify()を無改変で呼ぶ
```

という手順を踏めば、`calculate_value`/`generate_and_classify`のロジックを一切複製せずにフルパイプラインのReplayが実現できる。2-6Aはこの1番（MarketLatest再構成）だけを提供する。

## 2. モジュール構成

```text
app/backtest/                  （新規パッケージ）
    __init__.py
    replay.py                  （新規）— T0境界を守った市場データ取得・
                                 forecast error算出・window比較。
                                 DB書き込みは§3の compute-onlyパスのみ
                                 （本番テーブルへの書き込みはしない）。

app/market/predictability.py   （既存ファイルへの変更）— analyze_market()の
                                 本体を _compute_volatility_stats() として
                                 抽出し、永続化しない呼び出し元
                                 （app/backtest/replay.py）と永続化する
                                 呼び出し元（analyze_market自身）の両方が
                                 同じ計算ロジックを使う（§3）。
```

### 2.1 `_compute_volatility_stats()`抽出（`app/market/predictability.py`のリファクタ）

`analyze_market()`の「rowsクエリ → pair_observations → 統計算出 → classify()」の部分（現在の§predictability.py 119-144行相当）を、副作用なしの内部関数へ切り出す。

```python
@dataclass(frozen=True)
class VolatilityComputation:
    sample_count: int
    median_abs_price_change: float | None
    p95_abs_price_change: float | None
    median_abs_demand_change: float | None
    p95_abs_demand_change: float | None
    median_observation_gap_seconds: float | None
    p95_observation_gap_seconds: float | None
    volatility_class: VolatilityClass


def _compute_volatility_stats(
    session: Session, station_id: int, commodity_name: str, window_start: dt.datetime, now: dt.datetime
) -> VolatilityComputation:
    """analyze_market()の計算部分そのもの。DBへの書き込みは行わない
    （読み取りのみ）。analyze_market()自身と app/backtest/replay.py の
    両方がこれを呼ぶことで、"どちらの経路でも同じclassify()ロジックを
    通る"ことを保証する（value.py の ValueResult 導入時と同じ
    「選択ロジックの二重実装をしない」原則、docs/PHASE_2_5_CONFIDENCE_
    EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §7.2確定3）。"""
    ...


def analyze_market(session, station_id, commodity_name, client, window_days=..., now=None) -> MarketPredictability:
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=window_days)
    dates = [...]
    _ensure_days_fetched(session, station_id, commodity_name, dates, client)
    computation = _compute_volatility_stats(session, station_id, commodity_name, window_start, now)
    upsert_preserve_columns(session, MarketPredictability, [{... computation の各フィールド ...}], [...], preserve_columns=set())
    session.commit()
    return session.query(MarketPredictability)...one()
```

`analyze_market()`の公開シグネチャ・返り値・永続化の挙動は変更しない（既存233→260テストへの回帰を起こさない）。`_ensure_days_fetched`は変更しない。

## 3. window比較はMarketPredictabilityへ書き込まない

### 3.1 発見した制約違反

`MarketPredictability`のUnique制約は`(station_id, commodity_name, window_end)`のみで、`window_days`（≒`window_start`）を含まない（`app/db/models/market.py` L146-150）。

`window_end`は`now`（=T0）そのものなので、**同一T0に対して`window_days=7`, `14`, `30`で`analyze_market()`を3回呼ぶと、`upsert_preserve_columns`が同じ行を3回上書きし、最後に呼んだwindowの結果しか残らない。** これは2-6Aの「7/14/30日を同一基盤で比較する」という要件と正面から矛盾する。

### 3.2 確定: window比較はcompute-onlyパスを使い、本番テーブルへ書き込まない

`app/backtest/replay.py`は`analyze_market()`を呼ばず、`_compute_volatility_stats()`を直接呼ぶ。

```python
def compare_windows(
    session: Session, station_id: int, commodity_name: str, now: dt.datetime,
    window_days_options: list[int] = [7, 14, 30],
) -> dict[int, VolatilityComputation]:
    """analyze_market()を経由しない -- MarketPredictabilityのUnique制約
    (station_id, commodity_name, window_end)がwindow_daysを区別できず、
    同一T0に対する複数window呼び出しが互いを上書きするため(§3.1)。
    本番のMarketPredictabilityテーブルへは一切書き込まない -- これは
    Phase 2-5B/2-5CのModel Applicability Gateが将来参照する本番データ
    であり、backtestのwindow-sweepノイズで汚してはならない。"""
    return {
        window_days: _compute_volatility_stats(
            session, station_id, commodity_name, now - dt.timedelta(days=window_days), now
        )
        for window_days in window_days_options
    }
```

**注記（スキーマ変更をしない理由）**: `MarketPredictability`へ`window_days`列を足してUnique制約を拡張する案も検討したが、採用しない。これは`get_predictability()`（現在`order_by(computed_at desc).first()`で1件だけ返す、本番のconfidence配線が将来使う想定の関数）の呼び出し元に「どのwindow_daysの行を選ぶか」という新しい曖昧さを持ち込む。2-6Eで最終的な`DEFAULT_ANALYSIS_WINDOW_DAYS`が確定した後であれば1列足す価値があるかもしれないが、それは2-6Eの仕事であり、2-6Aが先回りしてスキーマを変更しない（本書§0の「今存在しない機能のための空列を先に作らない」と同じ理由）。

### 3.3 fetchキャッシュとの関係

`compute_windows()`は`MarketHistoricalObservation`/`MarketHistoricalFetchLog`への書き込み（＝実際のarchive取得）を行わない——読み取り専用。呼び出し前に対象期間（最大の`window_days`、通常30日分）が`analyze_market()`または`ensure_days_fetched()`（§3.4で公開化）で事前にキャッシュ済みであることを呼び出し側の責務とする。

### 3.4 `_ensure_days_fetched`の公開化

`app/backtest/replay.py`が独自にarchive取得のオーケストレーションを持たず、`app/market/predictability.py`の既存キャッシュ機構をそのまま再利用できるよう、`_ensure_days_fetched`から先頭アンダースコアを外し`ensure_days_fetched`として公開する（シグネチャ・実装は変更しない）。`analyze_market()`内部の呼び出し箇所も新名称に合わせて更新する。

## 4. Forecast Error 算出

**レビュー指摘（v0.1からの修正）**: v0.1は`price_change_ratio(prev, curr)`をそのまま「forecast_error」として使う設計だった。数値としては後述の通り等価だが、「予測値」（prediction）と「実測値」（actual）という2つの独立した概念が1つの計算へ暗黙に融合しており、2-6Bが検証したい「volatility classは将来のforecast errorと相関するか」という問いにとって、何を予測誤差と呼んでいるのかが名前を通じて説明できなかった。本節はこの2つを明示的に分離した`PredictionInput`/`ActualObservation`という別々のデータとして定義し直す。

### 4.1 PredictionInput（予測値）

2-6Aで導入する予測モデルは**naive last-value forecast**（「T0時点の最新観測価格が、そのままhorizon後も続く」という最も単純な予測）である。新しい価格予測モデルを2-6Aで作らない（Design Baseline §7 Non-goals）ため、これは適切な最小構成だが、**その予測値を独立した名前付きの値として明示する。**

```python
@dataclass(frozen=True)
class PredictionInput:
    """T0時点で知りえた情報のみから作った予測値。T0より後のデータを
    一切参照しない -- _compute_volatility_stats()と同じ境界
    (observed_at <= t0) を共有する。"""
    t0: dt.datetime
    predicted_price: float
    predicted_price_observed_at: dt.datetime  # predicted_priceの根拠になった観測のobserved_at（<= t0）
    volatility_class: VolatilityClass
    sample_count_at_t0: int


def predict_naive_persistence(
    session: Session, station_id: int, commodity_name: str, t0: dt.datetime, window_days: int,
) -> PredictionInput | None:
    """t0以前の最新観測（observed_at <= t0のうち最大のもの）のsell_priceを
    predicted_priceとする。volatility_class/sample_count_at_t0は
    _compute_volatility_stats(..., window_start=t0-window_days, now=t0)から
    そのまま転記する（§2.1のcompute-onlyパスを再利用し、分類ロジックを
    二重実装しない）。t0以前に観測が1件もなければ None。"""
```

### 4.2 ActualObservation（実測値）

```python
@dataclass(frozen=True)
class ActualObservation:
    """t0より後にのみ存在する観測。PredictionInputとは別のクエリ経路で
    取得し、t0以前のデータを一切参照しない（§4.4）。"""
    observed_at: dt.datetime  # t0 < observed_at
    actual_price: float


def observe_actual_after(
    session: Session, station_id: int, commodity_name: str, t0: dt.datetime, horizon: dt.timedelta,
    max_gap: dt.timedelta = MAX_OBSERVATION_GAP,  # app/market/predictability.pyの既存定数を再利用
) -> ActualObservation | None:
    """t0 + horizon に最も近い観測を (t0, t0 + horizon + max_gap] の範囲から
    探す。範囲内に観測が1件もなければ None を返す -- 欠損区間を補間しない
    という既存方針(docs/MARKET_PREDICTABILITY_SPEC_V0.1.md §4.1)をここでも
    守る。"""
```

### 4.3 ForecastError（予測値と実測値の比較）

`PredictionInput.predicted_price`と`ActualObservation.actual_price`という2つの明示的な値が揃って初めてforecast_errorを計算する。式自体は`app/market/volatility.py`の`price_change_ratio`と同じ相対誤差だが、**呼び出し側では常に「predicted」「actual」という名前のついた値同士を比較する形で書き、2値をただの`prev`/`curr`として渡さない。**

```python
@dataclass(frozen=True)
class ReplaySample:
    prediction: PredictionInput
    actual: ActualObservation | None  # None = observe_actual_after()がNoneを返した(§4.2)
    horizon: dt.timedelta
    forecast_error: float | None  # actual is None の場合は常にNone。0や補間値で埋めない


def evaluate_forecast_at(
    session: Session, station_id: int, commodity_name: str, t0: dt.datetime,
    window_days: int, horizon: dt.timedelta,
) -> ReplaySample | None:
    """PredictionInputがNone（t0以前に観測がない）ならNoneを返す。
    forecast_error = price_change_ratio相当
        = abs(actual.actual_price - prediction.predicted_price) / prediction.predicted_price
    ただしactualがNoneならforecast_errorもNone（§4.2のNone伝播をそのまま保つ）。"""
```

### 4.4 予測側・実測側のクエリ境界とリーク防止

`evaluate_forecast_at()`が呼ぶ2つの関数は、経路もクエリ条件も完全に分離されている。

```text
predict_naive_persistence()  --  observed_at <= t0                       のみ参照
observe_actual_after()       --  t0 < observed_at <= t0 + horizon + max_gap のみ参照
```

両者が同じ関数・同じクエリを通らないことは意図的である——予測側は「T0時点で知りえた情報」、実測側は「backtest評価者だけが知る未来」であり、これを1つの関数やタプルの`(prev, curr)`のような無名の組で扱うと、将来どちらの引数がどちらの役割かを取り違えるリスクがある。`PredictionInput`/`ActualObservation`という別々の型として区別することで、コンパイル時点（型チェック）でも取り違えを防ぐ。

### 4.5 horizon候補

市場のみのReplay（2-6B/2-6C）にはCandidate由来の`predicted_horizon`が存在しない（§1参照）。`app/scoring/confidence.py`の`FRESHNESS_FULL_THRESHOLD`（15分）/`FRESHNESS_FLOOR_THRESHOLD`（24時間）と同じ境界値をhorizon候補として使う。

```python
DEFAULT_REPLAY_HORIZONS = [
    dt.timedelta(minutes=15),
    dt.timedelta(hours=1),
    dt.timedelta(hours=6),
    dt.timedelta(hours=24),
]
```

理由: 2-6C（Freshness curve評価）はこれらの境界そのものを検証対象とするため、同じ値をhorizon候補に使うことで「ageがX経過した時点の価格乖離」という同じ測定を2-6B（classごとの比較）と2-6C（curveの形状評価）の両方で再利用できる（新しい任意のhorizon値を発明しない）。

## 5. Acceptance Tests

```text
_compute_volatility_stats()がanalyze_market()と同一の入力に対して同一のVolatilityComputationを返す
   （リファクタが計算結果を変えていないことの回帰保証）
compare_windows()が同一T0に対し7/14/30日で異なる結果を返しうる
   （MarketPredictabilityへの書き込みが発生しないことも確認）
compare_windows()の呼び出し後もMarketPredictabilityの既存行が変更されていない
predict_naive_persistence()がt0以前の観測のみからPredictionInputを構築する
   （t0より後にしか観測がないfixtureで確実にNoneを返すことを含む）
observe_actual_after()がt0以前の観測を一切参照しない
   （t0以前にしか観測がないfixtureで確実にNoneを返すことを含む）
evaluate_forecast_at()のPredictionInput/ActualObservationがそれぞれ独立したクエリ経路から
   構築されており、forecast_errorがt0より後の観測のみをactual側として使っている
   （future leakage prevention の実データ相当のregression test）
observe_actual_after()がNoneを返した場合、evaluate_forecast_at()のforecast_errorも
   Noneになり、0や補間値で埋めない
predict_naive_persistence()がNoneを返した場合、evaluate_forecast_at()全体がNoneを返す
ensure_days_fetched()（公開化後）が既存の_ensure_days_fetchedと同じ振る舞いを保つ
DEFAULT_REPLAY_HORIZONSの各値がFRESHNESS_FULL_THRESHOLD/FRESHNESS_FLOOR_THRESHOLDと一致する
   （2-6Cが同じ境界を再利用できることの保証）
```

## 6. Exit Criteria

- [x] `app/market/predictability.py`から`_compute_volatility_stats()`が抽出され、`analyze_market()`が同一結果を返すことに回帰がない
- [x] `app/backtest/replay.py`が新設され、`compare_windows()`が7/14/30日の結果を同時に得られる
- [x] `compare_windows()`が`MarketPredictability`テーブルへ一切書き込まないことがテストされている
- [x] `PredictionInput`（`observed_at <= t0`のみ参照）と`ActualObservation`（`t0 < observed_at`のみ参照）が別々の型・別々のクエリ関数として実装され、`evaluate_forecast_at()`がこの2つを取り違えようがない構造になっている
- [x] ホライズン内に実測観測がない場合に`forecast_error=None`となり、0や補間値で埋めないことがテストされている
- [x] `ensure_days_fetched`が公開化され、`app/backtest/replay.py`が独自のarchive取得ロジックを持たない
- [x] `DEFAULT_REPLAY_HORIZONS`が`app/scoring/confidence.py`のfreshness閾値と同じ値を参照している（値のハードコード重複がない）
- [x] 既存289テストに回帰がない

## 7. 決定事項サマリ

1. **§1 フルパイプラインは配線しない**: 2-6AはT0時点の市場状態プリミティブのみを提供する。Candidate Generation〜Rankingの配線は2-6Dの責務（本人Journalが必要なため）
2. **§2 `_compute_volatility_stats()`抽出**: `analyze_market()`と`compare_windows()`が同じ計算ロジックを共有し、classify()の二重実装を避ける
3. **§3 window比較は非永続化**: `MarketPredictability`のUnique制約（`window_days`を含まない）に既存の3window比較要件が抵触するため、window比較はDBへ一切書き込まないcompute-onlyパスを使う。スキーマ変更は2-6Eへ先送り
4. **§4 予測値と実測値を明示的に分離（v0.2でのレビュー修正）**: `PredictionInput`（`observed_at <= t0`のみ）と`ActualObservation`（`t0 < observed_at`のみ）を別々の型として定義し、`price_change_ratio`と同じ相対誤差の式は使うが、無名の`(prev, curr)`としてではなく常に「predicted」「actual」という名前を持つ値同士の比較として計算する。予測モデル自体はnaive last-value forecast（新しい予測モデルは作らない、Design Baseline §7 Non-goals）のまま変更しない
5. **§4.5 horizon候補はfreshness閾値と共有**: 15分/1時間/6時間/24時間とし、15分・24時間は`app/scoring/confidence.py`の既存定数と同じ値を使うことで2-6B/2-6C間で測定基盤を共有する
