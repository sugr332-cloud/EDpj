# EDpj Market Data Trustworthiness — Re-evaluation

**Version:** 0.1
**Status:** Diagnostic finding recorded. No production constant changed — adoption remains a separate human decision (same discipline as Phase 2-6B/E)
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_2_6B_VOLATILITY_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`, `docs/PHASE_2_6C_FRESHNESS_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`, `docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md`, `docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md`, `app/backtest/evaluation_run.py`, `app/backtest/model_validation.py`, `app/scoring/confidence.py`, `app/market/predictability.py`

## 0. 目的

「EDpjが取得しているMarketデータを、意思決定の根拠としてどこまで信用してよいのかを定量的に評価する」という問いに、**新しいコードを一切書かず**、既存のPhase 2-6B/C/E評価ツール（`compute_backtest_results`/`decide_volatility_adoption`/`decide_freshness_adoption`）を、蓄積済みの現在の実データ全量に対して再実行することで答える。前回（2-6E本文）のRunは5 targetのpilotだったが、今回は**現在キャッシュされている全34 (station, commodity)系列、5478サンプル**を使う——これは新規ネットワークアクセスなしで実行できる（後述§1）。

## 1. 手法: 既存データのみ、新規fetchゼロ

`MarketHistoricalFetchLog`を調べたところ、現在キャッシュされている34系列全てに共通する日付範囲は**2026-08-28〜09-04（8日間）**だった。この範囲を`now=2026-09-04 18:00 UTC`, `window_days_options=(7,)`で指定すれば、`ensure_days_fetched_batch`は全ての(station, commodity, date)が既に`MarketHistoricalFetchLog`に記録済みと判定し、**新規のアーカイブダウンロードを一切発生させない**。これを実際に「呼ばれたら例外を出すダミーHTTPクライアント」を渡して検証した——実行中に例外は一度も発生せず、ゼロ新規ネットワークアクセスでの再評価であることを構造的に確認済み。

対象34系列は`MarketHistoricalObservation`テーブルの全distinct (station_id, commodity_name)。station別内訳:

```text
station 3221821952 (Hoffman Installation想定): 30 commodities, 54〜82 observations/commodity
station 3789719552 (Ross Silo想定):             4 commodities,  6 observations/commodity
```

**station多様性は依然として乏しい**——2 stationのみ、うち1つが系列数の88%（30/34）を占める。この制約は§5で結果の解釈に必ず反映する。

## 2. Volatility再評価: 依然として`INSUFFICIENT`

```text
5478サンプル中:
  STABLE       : 3060サンプル（median_forecast_error=0.0, p95=0.0001）
  INSUFFICIENT :  380サンプル（median=0.023, p95=0.613）
  MODERATE     :    0サンプル
  VOLATILE     :    0サンプル

decide_volatility_adoption() → INSUFFICIENT
```

サンプル数が前回の数十件規模から5478件へ大きく増えたにもかかわらず、**MODERATE/VOLATILEクラスは1件も出現しなかった**。これはサンプル不足の問題ではなく、`docs/PHASE_2_6B_...md` §17.2で既に特定した通り、**現在の実データの station多様性そのものが構造的に不足している**ことの再確認である——station 3221821952の30 commodityの大半は`STABLE_MEDIAN_PRICE_CHANGE=0.05`を下回る変動しかしないため、閾値の妥当性自体を検証するデータが増えていない。

## 3. Freshness再評価: 新規に`NO_GO`（前回はサンプル不足で判定不能だった）

```text
bucket        sample_count  missing  median_error  p95_error
<15m                   304       60         0.0        0.0
15m-30m                154       90         0.0        0.104
30m-1h                 278       68         0.0        0.0
1h-3h                  946      346         0.0        0.00047
3h-6h                  616      354         0.0        0.0001
6h-12h                 634      438         0.0        0.0
12h-24h                330      534         0.025      0.613
>=24h                  178      148         0.0        0.038

pairwise_non_decreasing:
  <15m → 15m-30m       True
  15m-30m → 30m-1h     True
  30m-1h → 1h-3h       True
  1h-3h → 3h-6h        True
  3h-6h → 6h-12h       True
  6h-12h → 12h-24h     True
  12h-24h → >=24h      False   ← ここで単調性が崩れる
overall_monotonic = False

decide_freshness_adoption() → NO_GO
```

**現行`app/scoring/confidence.py`のfreshness curveが前提とする「観測が古いほど価格誤差が悪化する」という単調性の仮定が、最後の1区間（12h-24h → 24h以上）で崩れている**——p95誤差が0.613から0.038へ、median誤差が0.025から0.0へ、どちらも古い方が改善している。これは前回（2-6Eの5-targetパイロット）では単一stationのデータが縮退していたためにそもそも判定不能（実質`INSUFFICIENT`相当）だったのに対し、**今回は明確に`NO_GO`という結論が出た**、という違いがある。

**この結果を過大評価しないための注記**: 12h-24hバケットは534件、24h以上バケットは148件が`missing_actual_count`（比較対象の実測値が見つからなかった候補）であり、それぞれのバケットの過半数が除外されている。有効サンプル数（330件・178件）自体は小さくないが、`MAX_OBSERVATION_GAP`（6時間）の許容範囲内に収まる長期間の比較ペアは、データがまばらな中で偶然生き残った少数派である可能性が高く、station多様性の乏しさ（§1）とも合わせて、**「常にこうなる」という一般則の証明ではなく、「現在の限られた実データでは単調性を支持できなかった」という具体的な反証**として扱うべきである。

## 4. Trade Market Persistence（2-6F-T1）との統合

`docs/PHASE_2_6F_T1_...md`で既に確定済みの結果を、同じ「市場データの信頼性」という問いの一部として再掲する:

- price_persistence: 5〜120分の全ウィンドウで98〜99%——ただし観測間隔の中央値が約77分であるため、5/10/15/30分の結果はほぼ同一（`comparison_count`が4ウィンドウとも1492件で固定）であり、**「短時間で価格が変化しないこと」の直接証拠ではなく「次の観測がその範囲内にたまたま収まったこと」の証拠**という限界を持つ（同文書§6.5で既に明記）。
- time-to-first-material-decrease: 中央値約4日3時間。690件のイベント、1060件の右打ち切り。

## 5. 総合結論: 「意思決定の根拠としてどこまで信用してよいか」

| 指標 | 判定 | 現状の解釈 |
|---|---|---|
| Volatility分類（STABLE/MODERATE/VOLATILE） | `INSUFFICIENT` | 閾値の妥当性を検証するデータが構造的に無い。分類自体を信用も否定もできない |
| Freshness単調性（古いほど誤差が悪化） | `NO_GO` | 実データ上、最も古い区間で仮定が崩れる。ただし少数のstationに由来する限定的な証拠 |
| Trade価格持続性（5〜120分） | 98〜99%（観測解像度の限界あり） | 短時間での価格安定は否定されないが、観測密度が粗く断定はできない |
| Trade利益スプレッド持続性 | `INSUFFICIENT` | `buy_price`未収集（バックフィルDeferred） |

**現時点でEDpjの本番スコアリング（`app/scoring/confidence.py`のfreshness係数、`app/market/predictability.py`のvolatility分類）が依拠する市場データの信頼性は、実データによって積極的に裏付けられてはいない。** Freshnessについては明確な反証（`NO_GO`）が出ており、Volatilityについては検証データそのものが構造的に不足している（`INSUFFICIENT`）。これは「間違っている」という証明ではなく、「正しいという裏付けが無い」という状態である——Phase 2-6Bの結論（PAUSED）と同じ位置づけを、Freshnessについても明示的に共有する。

## 6. 本書が変更しないもの

- `app/scoring/confidence.py`の`FRESHNESS_FULL_THRESHOLD`/`FRESHNESS_FLOOR_THRESHOLD`/`FRESHNESS_FLOOR`
- `app/market/predictability.py`の`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`

**いずれも変更しない**——本書は診断結果の記録であり、採用可否（本番定数を変更するかどうか）は別途人間の判断を要する、Phase 2-6B/Eを通じて一貫している原則。

## 7. 再現方法

新規コードは一切追加していない。既存の`app/backtest/evaluation_run.py`の`compute_backtest_results`/`decide_volatility_adoption`/`decide_freshness_adoption`を、`MarketHistoricalObservation`の全distinct (station_id, commodity_name)を対象に、`now=2026-09-04T18:00Z`, `window_days_options=(7,)`, `horizon=1h`で呼び出すだけで再現できる（ネットワークアクセスなし、キャッシュ済みデータのみで完結する）。

## 8. 次に考えられるオプション（本書では未決定、記録のみ）

1. station多様性が改善するまで待つ（Phase 2-6Bと同じ「実プレイで新しいstationをDockする」を待つ方針を、Freshnessにもそのまま適用する）
2. `app/scoring/confidence.py`のfreshness curveの形状自体を見直す独立したPhaseを起こす（今回のNO_GOが具体的にどの区間から来ているかは§3で特定済みなので、着手する場合の出発点は明確）
3. 何もしない（現行の freshness/volatility 定数は「未検証」のまま本番で使い続け、次に実データが増えたタイミングで再評価する）

どれを選ぶかは人間の判断であり、本書はその材料を提供するのみで決定しない。
