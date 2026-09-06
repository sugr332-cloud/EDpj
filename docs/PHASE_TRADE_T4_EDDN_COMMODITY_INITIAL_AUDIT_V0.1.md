# Phase 2-6F-T4 — EDDN Commodity/3 Audit（T4-A/T4-B）

**Version:** 0.2
**Status:** T4-A: INITIAL AUDIT PASS / DISTRIBUTION UNRESOLVED → T4-Bで解決。T4全体としてはまだPASS/FAIL/INSUFFICIENT未確定（T4-C/T4-D未実施）
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_TRADE_EXTERNAL_MARKET_SOURCE_FEASIBILITY_V0.1.md`（T4の要求項目・deliverable様式の一次情報源）, `docs/DECISION_MARKET_REEVALUATION_V0.2.md`

**Phase breakdown（本セッションで確定した区切り）:**
```text
T4-A  Initial Unfiltered EDDN Commodity/3 Audit（単一日、§1-§6）        → 完了
T4-B  EDDN Commodity Daily Distribution Audit（14日以上、§9）          → 完了
T4-C  Commodity Master / Provenance Audit                              → 未着手
T4-D  Trade Candidate Construction                                     → 未着手
```

## 1. 目的と位置づけ

`ensure_days_fetched_batch`（`app/market/predictability.py`）は、EDDN `commodity/3`アーカイブを1日分丸ごとストリーミングした上で、呼び出し元が渡す`missing_station_ids`という狭いターゲットリスト（過去、プレイヤーの実journal訪問先station由来）でフィルタしていた。これが「EDpjの実測データはstation 2件・commodity重複0件」という結果の直接原因であり、**EDDNというソース自体の限界ではなかった可能性**を検証するため、この絞り込みを外した状態で1日分を実測した。

投機・仮定は一切含まない。以下は全て実データからの実測値（2026-09-06実行、`https://edgalaxydata.space/EDDN/`から取得、投資先DBへの永続化はなし・調査専用）。

## 2. 対象日と取得方法

```text
対象日: 2026-09-04
取得元: https://edgalaxydata.space/EDDN/2026-09/Commodity-2026-09-04.jsonl.bz2
取得方法: app/collectors/eddn_archive.py の iter_commodity_day() をそのまま再利用
         （station/commodityによる絞り込みなし、全メッセージを走査）
所要時間: 約65〜76秒（メッセージ数81,851、commodity行数15,994,698）
```

## 3. 実測結果（§13 deliverable様式に準拠）

```text
source                        = EDDN commodity/3 archive (edgalaxydata.space)
observation_start             = 2026-09-04（同日内。過去混入分は§4.2参照）
observation_end               = 2026-09-04
unique_stations                = 9,316
unique_systems                  = 6,206
unique_commodities（生の値）    = 1,257（§4.1で不正値混入を確認、正規化前）
station_commodity_series        = 1,796,413
buy_observation_count           = 未算出（commodity/3のcommodity単位行にbuyPrice/sellPrice双方が含まれるため、行数=15,994,698がBuy/Sell双方の潜在候補行数）
sell_observation_count          = 同上
commodity_overlap_count         = サンプル2,000ペア中1,922ペアで重複あり（96.10%）
source_destination_pair_count   = 未算出（今回はcommodity重複の有無のみ、具体的なsource/destinationペアの構築は未実施）
median_observation_gap          = 未算出（同一station×commodityの連続観測間隔は今回未計測、次段階の課題）
freshness_distribution          = gatewayTimestamp - observed_at: 中央値2.0秒, p95 6.4秒, 最大530秒
historical_replay_available      = 部分的に確認（少なくとも2019-01-01以降のアーカイブが実在、詳細は§6）。ただしcoverage数値の日次変動が大きいことが判明したため（§6.2）、単一日を代表値として replay 設計に使うことはまだできない
provenance_status                = 未監査
reuse_status                     = 未監査
accuracy_check_status            = 未監査
status                           = IN PROGRESS（PASS/FAIL/INSUFFICIENTのいずれも未確定）
```

## 4. 重要な発見（2件）

### 4.1 commodity名に明確な不正値が混入している（要正規化）

出現頻度上位20件（water: 65,419件、gold: 64,101件 等）は正規のcommodity名で頻度も自然に揃っている。一方、出現1回のみの名前が359/1,257件（28.5%）存在し、その内容は:

```text
mtissuesamplefluid, stissuesamplecells, s9tissuesampleshell, ...  ← Odyssey exobiologyサンプル名の誤送信
$platinum_name;, $palladium_name;, $gold_name; ...                ← 内部codexキーが未解決のまま送信
```

**結論**: 一部のアップローダークライアントがEDDNへ不正なcommodity名を送信している。実在するcommodityは約200種であり、`unique_commodities=1,257`という生の値をそのまま使ってはならない。正規commodity masterとの突合による正規化が必要（ユーザー指摘の通り、「約200へフィルタ」という簡易対応ではなく、正式なmaster照合として設計する）。**次段階の課題として明記、今回は未対応。**

### 4.2 `observed_at`の99.87%は当日、0.12%が30日以上前の混入

```text
同日:        99.8676%
1日前:        0.0005%
2〜7日前:     0.0101%
8〜30日前:    0.0000%
30日超:       0.1218%（19,475/15,994,698件）
```

Bioの`scanorganic/1`調査で見られた同種の異常（1.2%が想定取り込み開始日より前）と同じパターンだが、今回はさらに小さい比率。実用上許容範囲と判断できる（同様のフィルタ・除外ロジックが将来必要になる可能性を記録）。

## 5. ポジティブな結果

- **station間commodity共有率96.1%**（サンプル2,000ペア中、重複ゼロは78ペアのみ）、平均共有commodity数156.37 — 旧EDpjキャッシュ（2 station、重複0）とは全く異なる結果であり、「EDpjの2 stationデータ」≠「EDDN全体のMarket coverage」という`DECISION_MARKET_REEVALUATION_V0.2.md`の指摘を実データで裏付けた。
- **freshnessが極めて良好**（中央値2秒）——EDDNはほぼリアルタイムで市場観測を中継している。

## 6. Historical Depth 調査結果

### 6.1 アーカイブの実在範囲 — コード内の記述誤りを訂正

`app/collectors/eddn_archive.py`のdocstringには「2017-08まで遡る」と記載されていたが、これは**未検証の記述だった**。実際にHEADリクエストで日付を走査した結果:

```text
2017-07-01: 404
2017-08-01: 404
2017-08-15: 404
2017-09-01: 404
2018-01-01: 404
2019-01-01: 200 (24.1MB)  ← 実在確認できた最も古い日付
2020-01-01〜2026-09-05: 全て200
2026-09-06（当日）: 404（当日分はまだアーカイブ化されていない、約1日のラグ）
```

**「2017-08まで遡る」は誤りで、実際には少なくとも2019-01-01以降**（正確な開始日はまだ特定していない、2018-01-01〜2019-01-01の間のどこか）。それでも約7年分の履歴があり、chronological replayに使う分には十分な深さ。コード側のdocstringは本調査結果に合わせて修正済み（コミット時に反映）。

ファイルサイズは年を追うごとに緩やかに増加する傾向（2019年 ~15-28MB → 2025-2026年 ~70-150MB）——EDDNへの参加者・アップロード量が経年で増加していることと整合する。

### 6.2 複数日でのcoverage安定性 — 重大な未解決の外れ値あり

4日分（2026-09-04, 2026-08-06, 2026-06-08, 2025-09-04）を比較した結果:

| 日付 | messages | rows | unique_stations | unique_systems | unique_commodities | station×commodity series |
|---|---:|---:|---:|---:|---:|---:|
| 2026-09-04 | 81,851 | 15,994,698 | 9,316 | 6,206 | 1,257 | 1,796,413 |
| **2026-08-06** | 92,802 | 24,154,383 | **31,259** | **22,864** | 954 | **10,305,219** |
| 2026-06-08 | 70,200 | 12,024,115 | 9,478 | 6,353 | 577 | 1,887,061 |
| 2025-09-04 | 70,314 | 10,165,398 | 10,717 | 7,371 | 572 | 2,061,435 |

**2026-08-06だけが他の3日と比べてstation数が約3倍、station×commodity系列数が約5〜6倍という外れ値である。** これを「良い結果」として無条件に採用せず、原因を調査した:

- 2026-08-06の新規stationサンプル20件を目視確認 → 全て実在の正規なsystem名・station名（`Jaques Station`、`Paxton Landing`等の実在の著名な施設を含む）。破損データやプレースホルダーの兆候はない（1件、`station='$EXT_PANEL_ColonisationShip; Cobb Horizons'`のように未解決の内部ローカライズキーがstation名に混入している例はあったが、これはcommodity名で見た問題と同種の軽微なクライアント不具合であり、station自体は実在する）。
- 1日あたりのmarketId出現回数分布は組織的な重複を示唆しない（p50=2回, p95=5回, 最頻出stationで3,571回——人気ハブが繰り返し観測される自然なパターンと整合）。
- commodity名の「1回のみ出現」junk率は2026-08-06で0.9%（9/954）と、2026-09-04の28.5%（359/1,257）よりむしろ低く、コードの重複読み込みバグ（同じ行を複数回処理している）の兆候も見られない。

**結論: この外れ値の根本原因は特定できなかった。** 破損データ・重複読み込みバグの証拠は見つからなかったため、恐らく実際にEDDNへの参加が特に多かった日（ゲーム内イベント、新規クライアントの普及等）である可能性が高いが、確証はない。**したがって、単一日のCoverage数値（本書§3を含む）を「典型的な1日」として代表値扱いしてはならない。** 今後Coverage/commodity overlap等をT4の正式なPASS判定根拠にする場合は、複数日（できれば2週間以上）のサンプルで分布（中央値・範囲）を示す必要がある——単一の良い数字だけを採用するのは、Bio Value Model検証で戒めた「ミスケースだけを見た錯覚」と同種のリスクを孕む。

## 7. 未実施・次段階

1. **より多くの日のサンプリングによる分布の確定**（本書§6.2の外れ値を踏まえ、単一日ではなく複数日の中央値・範囲でCoverageを再定義する）
2. 正規commodity masterとの照合による`unique_commodities`の正規化
3. Provenance / Reuse conditions（EDDN自体の利用規約確認）
4. Accuracy check（実ゲーム内観測との突合、可能な範囲で）

## 8. 運用上の注意（設計判断ではなく、記録として残す）

1日で約1,600万行という規模はBioの`BioObservation`（14日で12,114行)と比べて3〜4桁大きい。将来的にEDDN commodity/3を広く取り込む設計を行う場合、生ログの逐次INSERTは非現実的であり、集計・重複排除・保持期間の設計が別途必要になる。本書はこの論点を記録するのみで、設計判断は行わない。

## 9. T4-B: EDDN Commodity Daily Distribution Audit（14日間、2026-08-23〜2026-09-05）

### 9.1 目的

§6.2で発見した2026-08-06の外れ値（station数が他日の約3倍）を受け、単一日を代表値として扱うことを避け、**連続14日間**の分布（median/P10/P25/P75/P90/min/max/CV）を確定した。全て無フィルタ・投機なしの実測値。

### 9.2 station数カウント方式の食い違いを発見・解決（reproducibility項目に直結する重要な確認）

分布計算の過程で、同じ2026-09-04を過去（T4-A、§2-3）と今回（T4-B）で別々に取得した結果、`unique_stations`が**9,316（T4-A）と8,221（T4-B）で食い違う**ことに気づいた。これはT4仕様§6「reproducibility（決定論的に再取得・再現できるか）」に直結する重大な懸念のため、放置せず原因を確認した。

```text
HTTPヘッダで同一ファイルであることを確認:
  content-length = 117,963,352バイト（初回HEAD確認時と完全一致）
  last-modified  = Sat, 05 Sep 2026 01:35:07 GMT（変化なし）
```

**アーカイブファイル自体は不変・再現可能だった。** 食い違いの真因はカウント方式の違い:

```text
message-level（メッセージにmarketIdが存在すれば1 station）:  9,316
row-level（commodity行を1件以上持つmessageのみ）:            8,221
差分 = 1,095 station（commoditiesリストが空のメッセージ5,198件に由来）
```

一部のstationはcommodityリストが空のまま報告されている（取引品目データがまだない、または一時的にゼロの状態）。**「station」の定義を「row-level（実際に取引可能なcommodityを1件以上持つ）」に統一する**——Trade候補構築では空のstationは使えないため、この定義がBuy/Sell候補構築の実用上一貫している。T4-Bの14日間は全てrow-level定義で統一済み（内部で矛盾はない）。

### 9.3 14日間の分布（row-level定義で統一）

```text
                                min      P10      P25    median      P75      P90      max     CV
unique_stations                7,429    7,919    8,111    8,266    9,426   10,370   10,589   0.113
unique_systems                 5,494    5,650    5,748    5,974    6,674    7,189    7,694   0.103
unique_commodities（生の値）      590      802      948      972      995    1,257    1,472   0.199
station×commodity series   1,537,000 1,539,000 1,590,000 1,655,000 1,865,000 2,047,000 2,457,000 0.144
buy_rate                     0.6516   0.6519   0.6533   0.6566   0.6703   0.6973   0.7026   0.025
sell_rate                    0.9861   0.9880   0.9885   0.9893   0.9902   0.9925   0.9946   0.002
supply_rate                  0.1151   0.1194   0.1490   0.1657   0.1666   0.1676   0.1677   0.119
demand_rate                  0.4315   0.4373   0.4734   0.5017   0.5038   0.5071   0.5089   0.053
commodity_junk_row_rate*     0.0557   0.0560   0.0563   0.0570   0.0581   0.0596   0.0604   0.026
duplicate_broadcast_rate     0.0484   0.0497   0.0507   0.0564   0.0625   0.0920   0.1018   0.264
malformed_rate                    0        0        0        0        0        0        0   0.000
```
（* commodity_junk_row_rateは`$`始まり・`tissuesample`含有の構造的ヒューリスティックのみ。正規commodity masterによる正式分類はT4-C。）

`new_station_rate`（前日までの累積既知station集合に対する新規率、初日100%を除く）: min=26.82%, median=38.27%, max=59.18% — 14日を通じて累積既知station数は増加し続けており、**単日スナップショットは全体のstation母集団を大きく過小評価する**。

### 9.4 §6.2の外れ値（2026-08-06）の再評価

今回の連続14日間（2026-08-23〜2026-09-05）では、station数はmax 10,589までしか到達せず、2026-08-06のmessage-levelでの31,259という値には遠く及ばない（row-level換算でも同程度に低いと推定される）。**2026-08-06は依然として未解明の外れ値のままであり**、今回の14日間には同種の急上昇は再現されなかった。原因不明のまま「稀に発生しうる外れ値」として記録し、T4-C/T4-D設計では中央値・分布ベースの指標を用いる（単日の最大値・特定1日の数値には依存しない）。

### 9.5 ポジティブな新知見（14日間で確認）

- **`sell_rate`が極めて高く安定**（median 98.93%、CV=0.002）——ほぼ全てのstationがほぼ全commodityを買い取る。
- **`buy_rate`は約65-70%で安定**（CV=0.025）——station×commodity系列の3分の2が実際にBuy可能。
- **`supply_rate`は約15-17%と低い**（CV=0.119）——buy_price>0でもsupply=0（在庫なし）のケースが多数存在する。Trade候補構築では`buy_price>0`だけでなく`supply>0`を明示的に要件化する必要がある。
- **`malformed_rate`は14日間全て0%**——EDDNメッセージのパース自体は極めて安定。
- **`duplicate_broadcast_rate`は5-10%程度**（同一station×timestampの重複配信）——本番取り込み設計では重複排除が必要（BioObservationで既に実装済みの`upsert_if_older`と同種のロジックが転用できる）。

### 9.6 T4-B結論

```text
T4-A: INITIAL AUDIT PASS / DISTRIBUTION UNRESOLVED
        ↓
T4-B: 14日間の分布を確定、station定義の食い違いを解決・統一
        ↓
T4-A/B結論: EDDN commodity/3は広域・複数station・複数systemのMarketデータを
            安定して提供している（reproducibility確認済み、malformed 0%、
            sell_rate/buy_rate安定）。ただし2026-08-06のような未解明の外れ値も
            存在するため、単日ではなく分布（中央値・範囲）に基づく設計とする。
        ↓
次: T4-C（Commodity Master / Provenance Audit）へ
```
