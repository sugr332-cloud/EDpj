# EDpj Phase 2-5A Market Predictability Implementation Baseline

**Version:** 0.2
**Status:** Design Baseline Fixed（レビューで§5/§9/§7の3点を確定: 観測キャッシュ採用、既定window=14日、demand volatilityは診断情報のみで一次分類には使わない）
**Date:** 2026-09-05
**Depends on:** `docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` (§3.3で取得戦略を確定済み), `app/collectors/eddn.py`（`parse_commodity_message`を再利用）

## 0. スコープ

Phase 2-5Aは以下のみを実装する。

```text
1. Historical EDDN archiveのon-demand取得（§2）
2. station×commodityの時系列統計（volatility, gap）（§5）
3. STABLE/MODERATE/VOLATILE/INSUFFICIENT分類（§6、閾値は暫定値）
4. 派生結果の永続化・問い合わせ関数（§3, §7）
```

**明示的にスコープ外:**

```text
- Model Applicability GateをVolue計算（app/scoring/value.py）へ配線すること
  -- MARKET_PREDICTABILITY_SPEC_V0.1.md §5が「NOT_APPLICABLEの候補をどう
  公開するかはPhase 2-5実装時に確定する」としている通り、配線は
  Phase 2-5B/2-5C（ValueResultへのmarket_observed_ats追加と同じタイミング）
  で行う。2-5Aは「問い合わせ可能なpredictability結果を作る」ところまで。
- STABLE/MODERATE/VOLATILEの閾値の実データによる較正・妥当性検証
  -- MARKET_PREDICTABILITY_SPEC_V0.1.md §8が「実データで検証してから
  named configuration constantsとして固定する」としている通り、これは
  Phase 2-6（Historical Backtest）の仕事。2-5Aでは暫定値を置く。
- CLI（`edpj market predictability ...`）
  -- このプロジェクトにCLI/API層はまだ一切実装されていない
  （app/cli/, app/api/は architecture上の予約のみ）。2-5Aは
  ライブラリ層（app/collectors, app/market, app/db/models）のみ。
```

## 1. データソースの実測結果（実装前検証）

`https://edgalaxydata.space/EDDN/{YYYY-MM}/Commodity-{YYYY-MM-DD}.jsonl.bz2` を実際に確認した。

```text
形式: EDDN commodity/3のraw envelope（{"$schemaRef","header","message"}）が
      1行1メッセージのJSONL、bzip2圧縮
サイズ: 1日あたり約60〜112MB（圧縮後）
期間: 2017年8月〜現在
粒度: station/commodity単位のファイル分割は存在しない
      （1日1ファイルがその日の全銀河・全stationの全commodity観測を含む）
```

**重要な実務上の帰結**: station/commodity単位でのサーバー側フィルタは存在しないため、「1つのstation×commodityの90日分の時系列がほしい」場合でも、**該当90日分のファイルを1つずつ全部ダウンロード＋展開＋走査する以外の方法がない**。フィルタは常にクライアント側（ダウンロード後）でしか行えない。「on-demand」は「ダウンロード量が少ない」という意味ではなく、「取得するのは実際に必要なwindow分のみ・galaxy全体をbulk importして永続DBへ溜め込まない」という意味である（`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` §3.3で確定済み）。

したがって、1つのstation×commodityを分析するコストは**window日数 × 約60〜112MB**のネットワーク転送・展開・走査になる。

**確定: 既定window（`DEFAULT_ANALYSIS_WINDOW_DAYS`）は14日とする（90日ではない）。** 14日でも約840MB〜1.57GBのダウンロードになるが、90日（約5.4〜10.08GB）よりは現実的である。**ただし14日は「統計的に最適な分析期間」ではなく、単なる運用上の初期値（operational default）である。** どのwindow長が実際の将来価格予測に最も有効かは、Phase 2-6のhistorical replayで7日/14日/30日等を比較検証してから決定する——2-5Aの時点でこの数字に統計的な意味を持たせない。

## 2. モジュール構成

```text
app/collectors/eddn_archive.py   （新規）— HTTP取得・bz2ストリーム展開・
                                    EDDN envelope解析。app/collectors/eddn.py
                                    の parse_commodity_message() をそのまま
                                    再利用し、schemaの二重実装をしない。
app/market/
    __init__.py
    volatility.py                （新規）— 純粋関数のみ（app/calibration/metrics.py
                                    と同じ「DB/sessionを持たない」方針）。
                                    price/demand change ratio、gap統計、median/p95。
    predictability.py            （新規）— オーケストレーション。
                                    fetch → pairing → volatility → classify → persist。
app/db/models/market.py          （既存ファイルへ追記）— MarketPredictabilityモデル
```

## 3. DBモデル（`app/db/models/market.py`へ追記）

```python
class MarketPredictability(Base):
    __tablename__ = "market_predictability"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "commodity_name", "window_end", name="uq_market_predictability_target_window"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)

    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    median_abs_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_abs_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_abs_demand_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_abs_demand_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_observation_gap_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_observation_gap_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    volatility_class: Mapped[str] = mapped_column(String, nullable=False)  # STABLE|MODERATE|VOLATILE|INSUFFICIENT
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

**仕様との差分（意図的な変更）**: `MARKET_PREDICTABILITY_SPEC_V0.1.md` §11の候補スキーマは`commodity_id`（数値）を使っているが、本プロジェクトの`market_snapshots`/`market_latest`は一貫して`commodity_name`（内部名文字列、例: "platinum"）をキーにしており、`commodity_id`列は「将来のためのnullable列」として存在するだけで実際には埋めていない（`app/db/models/market.py`のdocstring参照）。ここで`commodity_id`を新規に採用すると、既存の`MarketLatest`との結合キーが不一致になる。**`commodity_name`に統一する。**

また、`predictability_status`（usable/unusable/insufficient）は本baselineでは`volatility_class`と別カラムにしない——2-5Aの時点では「VOLATILEならusable判定に使わない」という対応関係をコード側の定数マッピングとして持たせれば十分で、DBに冗長な列を増やす理由がない（Model Applicability Gateの配線自体がPhase 2-5B/Cへ先送りのため、"usable/unusable"という言葉自体をこの段階のスキーマに固定しない）。`forecast_median_absolute_error`等（§7.3のbacktest指標）も同様に、backtestの実装（Phase 2-6）まで見送る——今存在しない機能のための空列を先に作らない。

## 4. Archive Adapter（`app/collectors/eddn_archive.py`）

```python
ARCHIVE_BASE_URL = "https://edgalaxydata.space/EDDN"

class StreamingHttpClient(Protocol):
    """app/collectors/spansh.pyのHttpClient Protocolと同じ思想 --
    テストでは実ネットワークを叩かず、フェイクを注入する。"""
    def stream(self, method: str, url: str) -> ContextManager[StreamResponse]: ...

def iter_commodity_day(date: dt.date, client: StreamingHttpClient) -> Iterator[dict]:
    """1日分のCommodity-*.jsonl.bz2をストリーム取得し、bz2を
    チャンクごとに展開しながら1行ずつEDDN envelopeとしてyieldする。
    ファイル全体をメモリ/ディスクへバッファしない。該当日がまだ
    archiveに存在しない（404）場合は空のiteratorを返す（未来日付や
    今日分がまだ生成されていない場合など、エラーではなく単に0件）。
    """

def fetch_commodity_observations(
    date: dt.date, station_id: int, commodity_name: str, client: StreamingHttpClient
) -> list[dict]:
    """1日分の全銀河envelopeから、対象station_id/commodity_nameに
    一致する行だけを抽出する。既存の app.collectors.eddn.parse_commodity_message()
    をそのまま呼び出し、schemaパース（marketId/commodities[].name等の
    フィールド名）を二重実装しない。マッチしない行は即座に捨てる
    （全体をリストに溜めない）。
    """
```

## 5. 生観測のローカルキャッシュ（レビューで確認したい新規決定）

**背景**: 同じstation×commodityを2回以上分析する場合（例: 同じ候補が複数回のRecommendation計算で参照される、あるいはbacktest中に同じ対象を繰り返し評価する）、素朴な実装だとその都度§1のコスト（window日数×60〜112MB）を払うことになる。

**提案**: 実際にarchiveから抽出できた行（そのstation×commodityに一致した行のみ、全銀河分ではない）を、小さな専用テーブルへキャッシュする。

```python
class MarketHistoricalObservation(Base):
    __tablename__ = "market_historical_observations"
    __table_args__ = (
        UniqueConstraint("station_id", "commodity_name", "observed_at", name="uq_market_historical_observation"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sell_price: Mapped[int] = mapped_column(Integer, nullable=False)
    demand: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
```

これは`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md`が禁止する「galaxy全体のbulk import」ではない——**実際に問い合わせがあったstation×commodityの、実際に一致した行だけ**が入る、完全にon-demandかつ狭い範囲のキャッシュである。

**確定: 追加する。**

**確定（レビューで追加指摘）: 「行がある＝取得済み」という判定だけでは不十分。** その日にマッチする観測が0件だった場合（その市場がその日EDDNへ一切報告されなかった等）、`MarketHistoricalObservation`に行が増えないため、「まだ取得していない」と誤認して毎回その日を再取得してしまう。**取得済みかどうかを独立して記録するfetch logを追加する。**

```python
class MarketHistoricalFetchLog(Base):
    # (station_id, commodity_name, date) が既にarchiveから走査済みで
    # あることを記録する。0件だった日も「取得済み」として記録することで、
    # 次回問い合わせ時の無駄な再取得を防ぐ -- MarketHistoricalObservationの
    # 行数だけでは0件だった日を判別できないため、これを別テーブルで持つ。
    __tablename__ = "market_historical_fetch_log"
    __table_args__ = (
        UniqueConstraint("station_id", "commodity_name", "date", name="uq_market_historical_fetch_log"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

`predictability.py`のオーケストレーションは、window内の各日付について、まず`MarketHistoricalFetchLog`にその(station_id, commodity_name, date)の記録があるか確認する。あれば（0件だった日も含めて）スキップし、なければarchiveから取得して`MarketHistoricalObservation`へ行を追加（0件でもよい）した上で、`MarketHistoricalFetchLog`へ記録する。

## 6. Volatility統計（`app/market/volatility.py`、純粋関数）

```python
@dataclass(frozen=True)
class Observation:
    observed_at: dt.datetime
    price: int
    demand: int

def pair_observations(
    observations: list[Observation], max_gap: dt.timedelta
) -> tuple[list[tuple[Observation, Observation]], list[dt.timedelta]]:
    """observed_at昇順に並んだ観測を隣接ペアにする。ペア間隔が
    max_gapを超える場合はそのペアを price/demand volatility の対象から
    除外する（§4.1「欠損区間を0変動として補間しない」）が、gapの値
    自体はgap統計（median/p95）には含める。戻り値は
    (volatility対象ペア, 全ペアのgap一覧)。"""

def price_change_ratio(prev: Observation, curr: Observation) -> float | None:
    """price<=0の観測は計算対象外（§4.2）。"""

def demand_change_ratio(prev: Observation, curr: Observation, demand_floor: int) -> float:
    """0除算防止のfloor。"""

def median_and_p95(values: list[float]) -> tuple[float | None, float | None]:
    """空リストなら (None, None)。p95は線形補間ではなく
    `statistics`標準ライブラリの決定論的な実装を使う。"""
```

## 7. Classification（`app/market/predictability.py`、暫定閾値）

```python
MIN_SAMPLES_FOR_CLASSIFICATION = 10          # 暫定値。Phase 2-6のbacktestで見直す
STABLE_MEDIAN_PRICE_CHANGE = 0.05            # 暫定値
MODERATE_MEDIAN_PRICE_CHANGE = 0.15          # 暫定値
# VOLATILE = MODERATE_MEDIAN_PRICE_CHANGE以上

def classify(
    sample_count: int, median_abs_price_change: float | None
) -> Literal["STABLE", "MODERATE", "VOLATILE", "INSUFFICIENT"]:
    if sample_count < MIN_SAMPLES_FOR_CLASSIFICATION or median_abs_price_change is None:
        return "INSUFFICIENT"
    if median_abs_price_change < STABLE_MEDIAN_PRICE_CHANGE:
        return "STABLE"
    if median_abs_price_change < MODERATE_MEDIAN_PRICE_CHANGE:
        return "MODERATE"
    return "VOLATILE"
```

**この閾値は`docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` §8の「実データで検証してから固定する」という方針に対する一時的な違反である。** 何らかの初期値がないと分類関数自体をテストできないため、named constantとして明示し、コード上に「Phase 2-6のbacktestで実データの分布・forecast errorとの相関を見て再較正する暫定値」と明記する。この閾値を**そのまま最終値として扱わない**ことをExit Criteriaにも明記する（§9）。

**確定: `classify()`はprice volatilityのみで一次分類する。demand volatilityは分類に使わず、診断情報として`MarketPredictability.median_abs_demand_change`/`p95_abs_demand_change`に保持するに留める。** 理由: 「価格が安定/需要が激しく変動」と「価格が激しく変動/需要が安定」という異なる市場状況を、需要変動込みの単一classificationへ混ぜると、「価格予測モデルを使ってよいか」という本来の判定目的（§4）がぼやける。将来、Phase 2-6のbacktestで需要変動もforecast failureと強く相関すると分かれば、その時点で分類モデルへ昇格させる。

## 8. 問い合わせ関数（配線はまだしない）

```python
def get_predictability(
    session: Session, station_id: int, commodity_name: str
) -> MarketPredictability | None:
    """直近のcomputed_atを持つ行を1件返す。存在しなければNone
    （まだ分析されていない、という意味 -- INSUFFICIENTとは違う）。
    app/scoring/value.pyからの呼び出しはPhase 2-5B/Cで追加する。"""
```

## 9. Exit Criteria

- [ ] `app/collectors/eddn_archive.py`が実archiveから1日分を取得・展開・フィルタでき、`app/collectors/eddn.py`の`parse_commodity_message`を再利用している（schemaパースを二重実装していない）
- [ ] 存在しない日付（404）がエラーではなく0件として扱われる
- [ ] `pair_observations`が`max_gap`超過ペアをvolatility計算から除外しつつ、gap統計自体には含めることがテストされている
- [ ] price=0/demand境界（floor）が0除算を起こさないことがテストされている
- [ ] `sample_count`不足時に`INSUFFICIENT`になり、`STABLE`と混同されないことがテストされている
- [ ] `MarketPredictability`が`commodity_name`（`commodity_id`ではない）で`MarketLatest`と同じキー体系になっている
- [ ] 分類閾値がnamed constantとして明示され、コード上に「暫定値、Phase 2-6で再較正」と明記されている
- [ ] `classify()`がdemand volatilityを一切参照せず、price volatilityのみで判定していることがテストされている
- [ ] `MarketHistoricalFetchLog`により、0件だった日が「未取得」として毎回再取得されないことがテストされている
- [ ] `DEFAULT_ANALYSIS_WINDOW_DAYS=14`がnamed constantとして明示され、コード上に「運用上の初期値であり統計的最適値ではない」と明記されている
- [ ] 既存233テストに回帰がない

## 10. 決定事項サマリ（レビューで確定）

1. **§5 観測キャッシュ**: 採用する。加えて`MarketHistoricalFetchLog`で「0件だった日」も取得済みとして記録し、無駄な再取得を防ぐ
2. **§1 既定window**: `DEFAULT_ANALYSIS_WINDOW_DAYS=14`（運用上の初期値。統計的最適値はPhase 2-6のhistorical replayで決定する）
3. **§7 demand volatility**: 一次分類には使わない。診断情報としてのみ保持し、price volatilityのみでSTABLE/MODERATE/VOLATILE/INSUFFICIENTを判定する

この3点の確定をもって、本書はPhase 2-5A実装のBaselineとして確定する。
