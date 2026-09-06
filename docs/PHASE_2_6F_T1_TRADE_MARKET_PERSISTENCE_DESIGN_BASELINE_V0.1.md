# EDpj Phase 2-6F-T1 Trade Market Persistence — Design Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/trade_market_persistence.py`、新規25テスト全通過。実データ（1784行）に対して6ウィンドウ全て実行し、実測値を記録済み。`profit_condition_persistence`は構造的`INSUFFICIENT`を確認済み）
**Date:** 2026-09-06
**Depends on:** `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`, `docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md`, `docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md`（以上binding、本書は実行計画を具体化するのみ）, `app/backtest/replay.py`, `app/market/predictability.py`, `app/db/models/market.py`

## 0. 位置づけ

`docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md`が定義する`2-6F-T1`を具体化する。既存の`app/backtest/replay.py`（2-6A）の`observe_actual_after`パターン（T0以降・許容ギャップ内での直近観測を探す、future leakage禁止）を一般化して再利用する——同じ問いを別の粒度・別の指標で問い直すだけであり、新しいクエリ手法を発明しない。

## 1. 実データ確認（2026-09-06、`data/edpj.db`）

MiningのCargo Reconstructionと同じく、実装前に実データの状況を確認した。

```text
MarketHistoricalObservation 行数        1784
distinct (station_id, commodity_name)     34
MarketHistoricalFetchLog 行数            307
```

Mining/Bioとは異なり、**Trade Market Persistence（少なくとも価格持続性の分析）には実データが既に存在する**——`INSUFFICIENT`が確定しているMining/Bioと違い、本書の実装は実際の数値を出せる見込みがある。

## 2. 構造的ギャップの発見: `buy_price`/`supply`/`received_at`が保存されていない

`docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md` §5「profit-condition persistence」は`destination Sell price - source Buy price > 0`の持続性を要求するが、`MarketHistoricalObservation`（Phase 2-5A、`app/db/models/market.py`）は`sell_price`/`demand`しか列を持たない。

`app/collectors/eddn.py`の`parse_commodity_message()`は生のEDDNアーカイブ envelope から`buy_price`/`supply`/`received_at`を**既に抽出している**——`app/market/predictability.py`の`ensure_days_fetched_batch()`がそれらを`MarketHistoricalObservation`へ書き込む直前で**捨てている**（Phase 2-5AがMining Sell専用に絞ったスコープの帰結、当時としては正しい判断だったが、Tradeの`profit_condition_persistence`には不足）。

これはMiningの`CargoState`（そもそも履歴が存在しない）とは性質が異なる**軽微な構造的ギャップ**である——データは既にアーカイブ側にあり、保存する列が無いだけ。対応:

1. `MarketHistoricalObservation`に`buy_price: int | None`/`supply: int | None`/`received_at: dt.datetime | None`をnullableで追加する（既存行は`NULL` = "この列が導入される前の観測では不明"、0や推測値にしない）
2. `ensure_days_fetched_batch()`を、これら3フィールドも保存するよう修正する（今後の新規fetchから反映される）
3. **既存1784行の再取得（バックフィル）は本書のスコープに含めない**——`MarketHistoricalFetchLog`は(station_id, commodity_name, date)が既に「fetch済み」と記録しているため、再取得には約2GBのアーカイブ再ダウンロードが必要になる（メモリ記録済みの規模）。これは実行するかどうかを判断する価値のある独立した決定であり、今回は「今後のfetchから両方の指標を追跡できるようにする」ところまでに留める。

**したがって本書の実装は`price_persistence`（`sell_price`/`demand`のみで計算可能、既存1784行で即座に実行可能）に絞り、`profit_condition_persistence`は構造的に`INSUFFICIENT`として正直に報告する**（バックフィルされるまで）。

## 3. Material-decrease閾値の凍結（結果を見る前に固定、spec §3/§4の要求）

新しい閾値を発明せず、既存の`app/market/predictability.py`の`STABLE_MEDIAN_PRICE_CHANGE = 0.05`（5%）を「material decrease」の相対閾値として再利用する——同じ「5%未満の変化は無視できるほど小さい」という既にレビュー済みの判断を流用する。ここでは方向性を持たせる（下落のみを見る、`STABLE_MEDIAN_PRICE_CHANGE`は絶対値ベースの対称的な閾値だったのに対し、Tradeでは"上昇"ではなく"下落"だけが利益を毀損するため）:

```text
material_decrease(t0_price, t_price) := (t0_price - t_price) / t0_price >= 0.05
```

## 4. `price_persistence(t)` 設計

固定ウィンドウ: `[5, 10, 15, 30, 60, 120]` 分。既存`MAX_OBSERVATION_GAP = 6h`（`app/market/predictability.py`）をそのまま再利用し、`(t0 + window, t0 + window + MAX_OBSERVATION_GAP]`の範囲で直近の観測を"T0+windowでの実測値"として採用する（`replay.py`の`observe_actual_after`と全く同じ考え方、対象ウィンドウの粒度だけが違う）。

```python
def compute_price_persistence(
    session, window: dt.timedelta, unchanged_threshold: float = STABLE_MEDIAN_PRICE_CHANGE
) -> WindowPersistenceResult:
    # 全 (station_id, commodity_name) の全観測をT0候補として走査する
    # 各T0について、(T0+window, T0+window+MAX_OBSERVATION_GAP] 内の直近観測を探す
    # 見つからなければ comparison対象外（除外、母数から外す。0扱いにしない）
    # 見つかれば:
    #   material_decrease か判定(§3)
    #   price_persistence の分子には「material decreaseではない」ケースを数える
```

**未来リーク禁止**: T0候補の抽出、比較対象観測の探索、いずれもT0以前/T0+window以降のデータだけを使う。`replay.py`と同じ規律。

## 5. `time_to_first_material_decrease` 設計

各 (station_id, commodity_name) の観測列を時系列順に走査し、各T0について「§3の基準を満たす最初の後続観測」までの経過時間を記録する。見つからなければ、その系列の最後の観測時刻までを right-censored として記録する（`docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md` §4「decreaseが観測されないことは無限の安定性の証明ではない」）。

## 6. `profit_condition_persistence` — 今回は構造的`INSUFFICIENT`

§2の理由により、`buy_price`が存在する行が0件（バックフィル未実施）である限り、この指標は必ず`INSUFFICIENT`になる。コード自体は実装するが、実データに対して実行した結果は`INSUFFICIENT`として正直に記録する——Miningの`MarketSell=0`と同じ扱い（コードは正しく動いているが、入力データが無い）。

## 6.5 実データ実行結果（2026-09-06、`data/edpj.db`、1784行、34系列）

```text
=== price_persistence per window ===
  5min  eligible=1784 comparison=1462 persistence=0.9904 decrease_rate=0.0096
 10min  eligible=1784 comparison=1492 persistence=0.9906 decrease_rate=0.0094
 15min  eligible=1784 comparison=1492 persistence=0.9906 decrease_rate=0.0094
 30min  eligible=1784 comparison=1492 persistence=0.9906 decrease_rate=0.0094
 60min  eligible=1784 comparison=1492 persistence=0.9853 decrease_rate=0.0147
120min  eligible=1784 comparison=1531 persistence=0.9798 decrease_rate=0.0202

=== time_to_first_material_decrease ===
total cases=1750  event_count=690  censored_count=1060
median_time_to_first_decrease = 4 days, 3:13:53

=== data quality ===
total_observations=1784  unique_series=34
observation_period = 2026-08-21 12:01:41 〜 2026-09-04 17:23:32
median_observation_gap = 4604秒（約76.7分）

=== profit_condition_persistence (15min) ===
status=INSUFFICIENT  eligible_count=0  comparison_count=0  persistence=None
```

**重要な留保（結果を額面通り受け取らないための注記）**: `median_observation_gap`が約77分であるのに対し、価格持続性を5/10/15/30分という短いウィンドウで測っている。`max_gap`（6時間）の許容範囲内で見つかった「直近の後続観測」は、実際にはウィンドウ通りの間隔ではなく、たまたま次に観測された（数十分〜数時間後の）1点であることが多い——つまり5分・10分・15分・30分の結果はほぼ同じ値になっており（comparison=1492が4ウィンドウ共通）、これは**「データがそのウィンドウの粒度で実際に持続した」ことの直接証拠ではなく、「次の観測がたまたまその区間内に収まった」ことの証拠**である。60分・120分になって初めてcomparison対象が変化し始める（1492→1531）。この解像度の限界は本書の結果とともに必ず併記すること——`docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md` §6の「source reliability / data freshness / market persistence」を混同しないという要求そのものであり、ここでの高い`price_persistence`（98〜99%）は「価格が実際に安定している」ことに加え「観測密度が疎いために変化を検出し損ねている」可能性を排除できていない。

## 7. Acceptance Tests

```text
compute_price_persistence()が、T0+window+MAX_GAP以内に観測が無い場合そのT0を比較対象から除外する（0扱いにしない）
compute_price_persistence()がmaterial decreaseの閾値ちょうど5%を「material decrease」として扱う（境界値、<=ではなく>=)
compute_price_persistence()がT0より前・T0+window+MAX_GAPより後のデータを一切参照しない（future leakage禁止）
compute_price_persistence()が複数(station,commodity)ペアを正しく分離する(異なるペアの観測を混在させない)
time_to_first_material_decrease()が、下落が一度も観測されない系列をright-censoredとして扱う(無限安定性として扱わない)
time_to_first_material_decrease()が、複数の下落候補のうち時系列で最初のものだけを採用する
profit_condition_persistence相当の計算が、buy_priceがNoneの行しかない場合INSUFFICIENTを返す(0や偽の値を作らない)
profit_condition_persistenceが、同一station内の売買を交易ルートとして扱わない
MarketHistoricalObservationの新規列(buy_price/supply/received_at)が全てnullableで追加され、既存行の読み込みに影響しない
ensure_days_fetched_batchが、envelope自身のheader.gatewayTimestampをreceived_atとして保存する
ensure_days_fetched_batchが、gatewayTimestampが無い場合received_atをNoneにする(dt.datetime.now()にフォールバックしない)
compute_data_quality_reportが、1系列のみで観測が1件しかない場合median_observation_gapをNoneにする(0ではない)
```

## 8. Exit Criteria

- [x] `MarketHistoricalObservation`に`buy_price`/`supply`/`received_at`（nullable）が追加され、`ensure_days_fetched_batch`が今後これらを保存する（`received_at`はアーカイブ経路では`header.gatewayTimestamp`から取得——実装中に発見: 従来「バックフィル実行時刻」を誤って保存する経路になっていたバグを合わせて修正、§8.5実装後注記参照）
- [x] `app/backtest/trade_market_persistence.py`が新設され、`compute_price_persistence`/`compute_time_to_first_material_decrease`/`compute_profit_condition_persistence`/`compute_data_quality_report`が§7を満たして実装されている(25テスト)
- [x] 実データ（1784行）に対して6ウィンドウ全てを実行し、結果（eligible_count/comparison_count/price_persistence/material_decrease_rate/median_time_to_first_decrease/censored_count/median_observation_gap）が記録されている（§6.5）
- [x] `profit_condition_persistence`は構造的`INSUFFICIENT`として実行・記録されている(バックフィルは別途決定、eligible_count=0)
- [x] 既存テストスイートに回帰がない（469 → 490テスト、全通過）

### 実装後注記（2026-09-06）

実装中に、`ensure_days_fetched_batch`が`received_at`にアーカイブ処理を実行した「今」の時刻（`dt.datetime.now()`）を渡していたことを発見した——アーカイブ由来の観測に対してこれは意味を持たない（同じバックフィル実行内の全行がほぼ同一時刻になり、「EDDNが実際にいつ受信したか」を全く表さない）。アーカイブenvelope自身の`header.gatewayTimestamp`を代わりに使うよう修正した（欠落・不正な形式の場合は`None`——推測しない）。ライブリスナー経路（`app/collectors/eddn.py`の`ingest_message`相当）は元々ほぼリアルタイムなので変更していない。

## 9. 決定事項サマリ

1. **§1 Tradeの価格持続性は実データで即座に評価可能**——MiningやBioと異なり実観測1784行が既に存在する
2. **§2 profit_condition_persistenceは列不足で構造的にブロックされている**——ただしMiningのCargoState問題とは異なり、原因はアーカイブ側の情報を捨てていたことであり、今後のfetchから直せる軽微な修正。既存データのバックフィル（~2GB再ダウンロード）は別途判断が必要な独立した決定として保留する
3. **§3 material decrease閾値は既存の`STABLE_MEDIAN_PRICE_CHANGE=0.05`を再利用**——新しい閾値を結果を見る前に発明しない、既存のレビュー済み判断を流用する
4. **§6 profit_condition_persistenceはコードとしては実装するが、実行結果は正直に`INSUFFICIENT`**——コードが動くことと指標が計算できることは別
