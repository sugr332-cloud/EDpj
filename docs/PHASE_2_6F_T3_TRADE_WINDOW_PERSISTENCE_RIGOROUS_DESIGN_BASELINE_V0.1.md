# EDpj Phase 2-6F-T3 Trade Window Persistence (Rigorous Re-analysis) — Design Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/trade_market_persistence.py`に追加、新規15テスト全通過。実データで6ウィンドウ全て実行し、有用性評価まで完了——§5〜§8）
**Date:** 2026-09-06
**Depends on:** `docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md`, `docs/SPECIFICATION_TRADE_SCOPE_AMENDMENT_V0.1.md`, `docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md`, `docs/PHASE_2_6F_T2_LARGE_PRICE_MOVEMENT_CHARACTERIZATION_DESIGN_BASELINE_V0.1.md`, `docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`, `app/backtest/trade_market_persistence.py`

## 0. 位置づけ、および2-6F-T1との既知の矛盾

本書はユーザーからの追加分析指示（2026-09-06）に基づき、2-6F-T1の`compute_price_persistence`が持つ**方法論上の欠陥を修正**する。これはT1の結果を上書き・削除するものではなく、両方を残した上で**矛盾を明示する**（プロジェクトの既存規律: 実データの発見は消さずに記録し続ける）。

**矛盾の内容**: `compute_price_persistence`（2-6F-T1）は、どのウィンドウ（5分・10分・15分・30分・60分・120分）についても一律`MAX_OBSERVATION_GAP=6時間`という許容誤差を使って「T0+window付近の直近観測」を探していた。この結果、5分ウィンドウの「比較」が実際には最大6時間後の観測とマッチしてしまう——「T0=12:00、target=12:30」に対して「実測観測が15:00」だったケースを、そのまま「30分後の比較」として扱ってしまう構造的な問題があった。これは2-6F-T1の実行結果セクションで「5〜30分ウィンドウの結果がほぼ同一になっている」という形で既に兆候が見えていたが（`comparison_count=1492`が4ウィンドウ共通）、今回のユーザー指摘で問題の所在が明確になった。

**方針**: 許容誤差をウィンドウ幅に応じてスケールさせる、新しい基準を導入する（§1）。これは新しいproduction scoring logicではなく、backtest/analysis専用の再計算である。既存の`app/backtest/trade_market_persistence.py`に関数を追加する形で実装し、T1の関数は変更しない（両方の存在自体が「方法論を厳密化したらどう数字が変わったか」を示す資料になる）。

## 1. T0→t分後の対応観測: 許容誤差の凍結（結果を見る前に固定）

**採用する基準**: ウィンドウ`t`分後の比較として有効な観測は、`target = T0 + t`に対して`|observed_at - target| <= t`（許容誤差 = ウィンドウ幅そのもの）を満たすものとする。複数候補があれば`target`に最も近いものを採用する。

```text
例1: T0=12:00, window=30分, target=12:30, 許容誤差=30分 → 有効範囲 (12:00, 13:00]
     観測が12:31 → 採用（gap=1分）
     観測が15:00 → 却下（150分乖離、許容誤差30分を超える）

例2: T0=12:00, window=5分, target=12:05, 許容誤差=5分 → 有効範囲 (12:00, 12:10]
```

**この基準を選んだ理由**: 2-6F-T1の`MAX_OBSERVATION_GAP=6時間`固定という誤りを繰り返さないため、許容誤差をウィンドウ自体に連動させる。「ウィンドウ幅と同じだけの遅延まで許容する」という対称的でシンプルな規則であり、実データを見てから閾値を調整していない。この基準の下で、**現在の実データの観測間隔中央値が約77分（2-6F-T1で既に測定済み）であることから、5/10/15/30分ウィンドウでは比較可能なペアがほとんど見つからないことが予想される**——これは分析の欠陥ではなく、観測密度そのものの限界であり、そのまま結果として報告する（§7で検証）。

## 2. 実装（`app/backtest/trade_market_persistence.py`へ追加、新規モジュールは作らない）

### 2.1 `PriceComparison`（個別の対応ペア）

```python
@dataclass(frozen=True)
class PriceComparison:
    station_id: int
    commodity_name: str
    t0: dt.datetime
    t0_price: int
    window: dt.timedelta
    matched_observed_at: dt.datetime
    matched_price: int
    comparison_gap: dt.timedelta  # matched_observed_at - target（符号付き、早着はマイナス）
```

### 2.2 `WindowPriceStats`（§3/§4/§5/§8の全指標を1つに集約）

```python
@dataclass(frozen=True)
class WindowPriceStats:
    window: dt.timedelta
    eligible_count: int
    comparison_count: int
    censored_count: int                      # eligible - comparison（許容誤差内に観測が無かった)
    unchanged_rate: float | None              # |relative_change| < UNCHANGED_ABS_RELATIVE_THRESHOLD
    decrease_rate: float | None               # relative_change < 0（下落方向、閾値なし）
    median_relative_change: float | None
    p25_relative_change: float | None
    p75_relative_change: float | None
    material_decrease_at_window_rate: float | None      # T0+window時点の対応観測がmaterial decrease
    material_decrease_within_window_rate: float | None  # T0からwindow以内のどこかでmaterial decreaseが発生（別指標、§5で明示的に区別)
    median_observation_gap: dt.timedelta | None  # |comparison_gap|のmedian/p25/p75
    p25_observation_gap: dt.timedelta | None
    p75_observation_gap: dt.timedelta | None
```

`relative_price_change = (price_t - price_0) / price_0`（符号付き、下落はマイナス）。`unchanged`は`STABLE_MEDIAN_PRICE_CHANGE`（0.05）を絶対値に適用——`material_decrease`（既存T1/T2、下落方向のみ）と同じ数値だが意味が違うことをdocstringで明記する。

### 2.3 Trade利益条件（source Buy × destination Sell）

```python
@dataclass(frozen=True)
class ProfitWindowStats:
    window: dt.timedelta
    status: PersistenceMeasurementStatus     # buy_price無しなら常にINSUFFICIENT
    eligible_count: int
    comparison_count: int
    profit_condition_persistence: float | None
    median_source_dest_time_diff: dt.timedelta | None
```

source/destinationの観測時刻差を明示的に記録する（§6の要求）。§1と同じウィンドウ相対許容誤差を、source側・dest側それぞれの「次の観測探索」に適用する。`buy_price`が無ければ`compute_profit_condition_persistence`（T1）と同じ理由で構造的`INSUFFICIENT`。

### 2.4 非対称変動の分解

```python
@dataclass(frozen=True)
class MarginChangeDecomposition:
    status: PersistenceMeasurementStatus
    source_buy_only_changed_count: int
    dest_sell_only_changed_count: int
    both_changed_count: int
    neither_changed_count: int
```

`buy_price`が無ければ構造的`INSUFFICIENT`（新しい判断ではない、T1 §10のバックフィルDeferredの帰結）。

## 3. Acceptance Tests

```text
許容誤差ちょうど(target±window)の境界値が採用される
許容誤差を超える観測(ユーザー例: target=12:30, 観測=15:00, window=30分)が却下される
複数の候補がある場合targetに最も近いものが採用される
unchanged_rateがmaterial_decrease方向と異なる境界(対称)で判定される
material_decrease_at_window_rateとmaterial_decrease_within_window_rateが異なる値になりうるケースをテストで区別する
   (例: window内の途中で一時的に5%下落したが、window終端では回復している場合)
観測gapが符号付きで記録され、統計には絶対値が使われる
profit条件のsource/dest時間差が記録される
buy_priceが無い場合、ProfitWindowStats/MarginChangeDecompositionがINSUFFICIENTを返す
```

## 4. Exit Criteria

- [x] `PriceComparison`/`WindowPriceStats`/`ProfitWindowStats`/`MarginChangeDecomposition`と対応する計算関数が実装され、§3を満たす（15テスト）
- [x] 実データに対し6ウィンドウ全てで実行し、結果を記録する（§5）
- [x] 2-6F-T1の結果との数値差分を明示する（§6）
- [x] A(推薦への有用性)/B(リスク表示への有用性)/C(データ品質)/D(station依存性)の評価を記述する（§7）
- [x] 既存テストスイートに回帰がない（501 → 516テスト全通過）

## 5. 実データ実行結果（2026-09-06、`data/edpj.db`、1784観測、34系列）

```text
window   eligible  comparison(率)      unchanged_rate  decrease_rate  material_at_window  material_within_window  median_gap  censored(率)
 5分       1784     259  (14.5%)          100.00%          0.00%           0.00%                 0.00%              0:02:26   1525 (85.5%)
10分       1784     534  (29.9%)          100.00%          0.19%           0.00%                 0.00%              0:05:09   1250 (70.1%)
15分       1784     703  (39.4%)           99.29%          3.70%           0.71%                 0.00%              0:05:20   1081 (60.6%)
30分       1784     828  (46.4%)           99.40%          3.14%           0.60%                 0.29%              0:10:51    956 (53.6%)
60分       1784    1013  (56.8%)           97.53%          6.32%           2.07%                 0.29%              0:29:23    771 (43.2%)
120分      1784    1288  (72.2%)           97.44%          6.06%           2.25%                 1.66%              0:57:30    496 (27.8%)
```

`undefined_baseline_count = 0`（全ウィンドウ共通、`sell_price<=0`の行は無かった）。`profit_window_stats`は**全ウィンドウでINSUFFICIENT**（`buy_price`未収集、2-6F-T1 §10でDeferred済みのバックフィルに起因、新しい判断ではない）。`margin_change_decomposition`も同じ理由で全てINSUFFICIENT。

**station別内訳（30分・120分ウィンドウ、抜粋）**:

```text
                        30分ウィンドウ                    120分ウィンドウ
station 3221821952:     comparison=820  decrease_rate=3.17%   comparison=1280  decrease_rate=6.09%
station 3789719552:     comparison=  8  decrease_rate=0.00%   comparison=   8  decrease_rate=0.00%
```

**station 3789719552は比較可能サンプルが8件しかなく、統計的に意味を持たない。** 上記の全ウィンドウ集計値は実質的にstation 3221821952（1系列中30 commodityを持つ単一station）のみの傾向である。

## 6. 2-6F-T1との矛盾の明示

| 項目 | 2-6F-T1（旧, 6時間固定許容誤差） | 2-6F-T3（新, ウィンドウ相対許容誤差） | 矛盾の説明 |
|---|---|---|---|
| comparison_count（10/15/30分） | 1492件で**完全に同一** | 534/703/828件で**明確に異なる** | T1は3つの異なるウィンドウが実質同じ1件の後続観測とマッチしていた——ウィンドウごとに区別された測定になっていなかった |
| material_decrease_rate（5分→120分） | 0.96%→2.02%、なめらかに増加 | 0.00%→2.25%、5-10分はゼロ、15分から立ち上がる | T1のなめらかな増加は「時間経過で危険が増す」という尤もらしい形をしていたが、これは6時間許容誤差の中でたまたま拾えた観測が作った見かけ上のパターンだった可能性が高い。T3はより解釈しやすい「短時間ではほぼ検出されない、時間が経つほど検出率が上がる」という、観測密度の限界を反映した形になっている |
| 5〜30分の価格維持率がほぼ同一（T1: 99.04〜99.06%） | T1で発生 | T3では99.40%〜100.00%とウィンドウごとに変化 | 同上、T1は事実上1つの比較対象しか使えていなかったことの帰結 |

**結論**: T1の5〜30分の数値は方法論上の欠陥（固定許容誤差）による**過大な精度の錯覚**であり、そのまま信用すべきではない。T1のドキュメント自体は削除・改変しない（§0で述べた通り、両方を残して矛盾を記録する）が、**5〜30分のTrade判断にT1の数値を使ってはならない**——T3の数値（本書）を使うこと。

`docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`のFreshness NO_GO（12時間〜24時間超で単調性が崩れる）とは時間スケールが重ならないため直接の矛盾ではないが、**「観測密度の粗さが測定精度に直接影響する」という同じ根本原因を、異なる時間スケールから示している**という点で整合している。

## 7. 有用性評価

### A. Trade推薦への有用性

- 5分・10分ウィンドウ: `comparison_count`が全体の14.5%・29.9%しかなく、**censoring率が70〜85%**。ほとんどのT0で「5分後・10分後の状態」を観測データから答えられない。推薦判断に使えるだけのカバレッジが無い。
- 15分・30分ウィンドウ: censoring率が54〜61%までは改善するが、依然として過半数近くが「不明」。
- **60分・120分ウィンドウで初めて、comparison_countが1000件を超え、censoring率が43%・28%まで下がる**。この2つのウィンドウでは価格維持率の差（97.53%→97.44%、ほぼ横ばい）よりも、material_decrease_at_window_rate（2.07%→2.25%）とmaterial_decrease_within_window_rate（0.29%→1.66%）の増加の方が、推薦判断にとって意味のある差になりうる。
- **5〜30分の推薦判断への寄与は現状「無い」に等しい**——数字は出せるが、母数の半分以上が「データが無い」ため、リスク評価としての実用性は低い。

### B. リスク表示への有用性

- 「現在観測された利益：+50 Cr/t」に対して、**利益条件維持率は全ウィンドウでINSUFFICIENT**——source Buy側のデータが無いため、Trade固有の「利益条件がどれだけ続くか」という最も欲しい情報は今のところ一切提供できない。
- 価格維持率（sell側のみ）は60〜120分については「意味のある形」で表示できる: 例えば「過去観測では、この商品はT0から120分後までに約2.25%の確率で5%以上のセル価格下落が観測された（station 3221821952のみ、観測gap中央値57分、比較可能728件中1288件）」という言い方は、実データに基づいた具体的な文章になる。
- ただし5〜30分については「データ不足のため定量化できません」と明示すべきであり、無理に数字を出すべきではない。

### C. データ品質

- **observation density（観測密度）が短時間ウィンドウの測定を根本的に制約している**——median_observation_gapは5分ウィンドウで2分26秒（このウィンドウにしては悪くない）が、比較可能率自体が14.5%しかない。60分・120分では観測gap自体がウィンドウの約半分（29分/57分）を占めており、「ちょうどその時間後」を測っているというより「その時間までのどこか」を測っている、という性質が強くなる。
- censoring（比較対象が見つからない）はウィンドウが短いほど深刻——これは母集団の偏りではなく、そもそも短間隔の観測が少ないという物理的な制約。

### D. station依存性

- **§5で示した通り、比較可能サンプルの98%以上が単一station（3221821952）由来**。もう一方のstation（3789719552）は8件しかなく統計的に無意味。
- したがって本書の全ての数値は、「Trade市場全体の一般的な傾向」ではなく、**「station 3221821952という1つのstationの30 commodityにおける傾向」**として扱わなければならない。他のstationやcommodityに一般化できるという証拠は今のところ無い（`docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`と同じ制約構造）。

## 8. 最終結論

| 経過時間 | 有効T0 | 比較可能 | 価格維持率 | 下落率 | material decrease率 | 利益条件維持率 | median gap | censoring |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5分 | 1784 | 259 (14.5%) | 100.00% | 0.00% | 0.00% | INSUFFICIENT | 0:02:26 | 1525 (85.5%) |
| 10分 | 1784 | 534 (29.9%) | 100.00% | 0.19% | 0.00% | INSUFFICIENT | 0:05:09 | 1250 (70.1%) |
| 15分 | 1784 | 703 (39.4%) | 99.29% | 3.70% | 0.71% | INSUFFICIENT | 0:05:20 | 1081 (60.6%) |
| 30分 | 1784 | 828 (46.4%) | 99.40% | 3.14% | 0.60% | INSUFFICIENT | 0:10:51 | 956 (53.6%) |
| 60分 | 1784 | 1013 (56.8%) | 97.53% | 6.32% | 2.07% | INSUFFICIENT | 0:29:23 | 771 (43.2%) |
| 120分 | 1784 | 1288 (72.2%) | 97.44% | 6.06% | 2.25% | INSUFFICIENT | 0:57:30 | 496 (27.8%) |

1. **このデータで何分後まで信頼性を定量化できるか**: 実用的な下限は概ね**60分**。5〜30分は比較可能率が14.5〜46.4%しかなく、censoring率が過半数（30分でも53.6%）を超えるため、統計として成立していても「実際の判断に足る母数」とは言えない。60〜120分は比較可能率が56.8〜72.2%まで上がり、初めて「定量化できた」と言える水準に達する。
2. **どの時間窓がTrade判断に最も有用か**: **60分・120分**。ただしobservation gap自体がウィンドウの約半分を占めるため、「正確に60分後」ではなく「30分〜90分の間のどこか」を測っていることに注意が必要。
3. **価格維持率と利益条件維持率のどちらが有用か**: 現状は**価格維持率のみ**が計算可能。利益条件維持率はTradeにとって本来最も重要な指標だが、`buy_price`が未収集のため全ウィンドウでINSUFFICIENT——2-6F-T1 §10のバックフィルDeferredがそのまま効いている。
4. **station/commodity偏りによる限界**: 比較可能サンプルの98%以上が単一station由来。**現在の結果はこの1 stationにしか一般化できない。**
5. **実際のTrade推薦UIに表示するなら何を表示すべきか**: 60〜120分については「過去観測ベースで、この商品はこのstationでtに対しX%の確率で5%以上のセル価格下落が観測された（観測件数・観測gapを併記）」という、station限定・観測事実ベースの文言。5〜30分については「データ不足のため定量化できません」と明示する。**「到着時に儲かる確率」「N分は安全」という表現は一貫して禁止**（§9の要求通り）。
6. **現状データでは「有用」と判断できるか、それともINSUFFICIENTか**:
   - 60〜120分の価格維持率: **条件付きで有用**——数字は計算でき、量的な差も見えるが、単一station由来という限界を必ず併記する必要がある。
   - 5〜30分の価格維持率: **実用上はINSUFFICIENTに近い**——計算はできるが、censoring率が高すぎて意思決定の根拠にするには弱い。
   - 利益条件維持率・非対称変動分解: **INSUFFICIENT**（構造的、buy_price未収集）。

**「数字が計算できたこと」と「Trade判断に有用であること」は明確に別**——本書の6ウィンドウ全てで数字自体は計算できたが、有用と言えるのは60〜120分の価格維持率のみであり、それも単一stationの証拠という限定付きである。

