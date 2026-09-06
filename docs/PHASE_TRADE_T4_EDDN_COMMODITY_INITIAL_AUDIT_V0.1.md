# Phase 2-6F-T4 — EDDN Commodity/3 Audit（T4-A/B/C/D + Distance/Jump + Calibration + T4-E）

**Version:** 1.4
**Status:** T4-A/B/C/D・Distance/Jump Integration完了（§15）。T4-E: Feature B v2/v3実装（§17-20）。Multi-day Stability Validation実施（§19、persistenceを異常度指標に使うべきでないと判明）。Commodity Absolute Floor Calibration Study実施（§21）——floor=10,000〜20,000CRの範囲に絞り込み（低価格ノイズ100%除去・既知正例保持を両立）。production thresholdは引き続き未確定（範囲の絞り込みに留める）
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_TRADE_EXTERNAL_MARKET_SOURCE_FEASIBILITY_V0.1.md`（T4の要求項目・deliverable様式の一次情報源）, `docs/DECISION_MARKET_REEVALUATION_V0.2.md`

**Phase breakdown（本セッションで確定した区切り）:**
```text
T4-A  Initial Unfiltered EDDN Commodity/3 Audit（単一日、§1-§6）        → 完了
T4-B  EDDN Commodity Daily Distribution Audit（14日以上、§9）          → 完了
T4-C  Commodity Master / Provenance Audit（§10）                       → 完了
T4-D  Trade Candidate Construction（§11-14）                           → 完了（§14、閾値確定は将来課題として保留）
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

## 10. T4-C: Commodity Master / Provenance Audit

### 10.1 C-1: Commodity Master照合 — 結論から言うと「28.5%がjunk」は誤りだった

**架空のマスタを作らず、実在するコミュニティ標準データ（`EDCD/FDevIDs`、EDMC等が実際に使用）を取得して照合した。** EDCDはEDDN自体の運営元でもあるコミュニティ組織。

初回はEDCD/FDevIDsの`commodity.csv`（一般commodity 270種）のみと照合し、`unknown`が27.73%（1日分、541種、576万行）という大きな値が出た。しかし中身を見ると`lavianbrandy`・`karsukilocusts`・`thehuttonmug`等、**全て実在する正規のElite Dangerous commodity**だった——**参照マスタが不完全だった**（レアグッズ/地域特産品カテゴリが`commodity.csv`に含まれていなかった）。

`rare_commodity.csv`（142種）を発見・追加し、common+rare合計412種のマスタで再照合した結果:

```text
対象日: 2026-09-05（distinct commodity名 1,472種、total rows 20,876,334）

KNOWN（common+rareマスタと一致）:  802 distinct名, 20,866,401行（99.952%）
MALFORMED（構造的に不正）:         382 distinct名,      9,357行（0.045%）
UNKNOWN（どちらでもない）:         288 distinct名,        576行（0.003%）
```

**KNOWN分類の802 distinct名がマスタの412種より多い理由**: 大文字小文字の表記ゆれ（同じcommodityを異なるcasingで送るuploaderクライアントが複数存在）。正規化時は小文字化してから照合する必要がある——将来永続化する際の正規commodity名は単一の正規化された表記に統一すべき。

**残る0.003%のUNKNOWN**: `Fruit and Vegetables`のように、内部symbol名（`fruitandvegetables`）ではなく**表示名（display name）**をそのまま`name`フィールドへ送っている少数のクライアントによるもの。件数は各2件のみ（特定の1クライアントによるものと推測）。

**結論**: ユーザー指摘の通り「28.5%をそのままjunkとして扱うのはまだ早い」は正しかった。**参照マスタを正しく（common+rare）揃えれば、実際の不正データ率は0.05%未満**。これは仕様書§C-4のTrade候補構築における実用上の閾値として採用できる。

### 10.2 Reuse conditions（マスタデータのライセンス確認）

`EDCD/FDevIDs`リポジトリのライセンスを確認したところ、**GitHub API上でも`license: None`、READMEにも明示的なライセンス表記なし**。EDCDはEDDN自体の運営母体であり、EDMC等のコミュニティツールで広く使われている実績があるが、正式な再配布・利用許諾条件は明示されていない。

**したがって、Bioの`EDMC-BioScan`（GPL-2.0）と同じ扱いとする**: FDevIDsのCSVをリファレンスとして照合・検証に使うことは問題ないが、EDpjが将来正式な`CommodityMaster`を永続化する場合は、このCSVをそのまま丸ごとvendoring（同梱・再配布）せず、独自にコンパイルする（複数ソースで裏取りする、または最小限必要なsymbol↔category対応のみを独自に整理する）。

### 10.3 C-2: Provenance（追跡可能性の設計確認）

実データで既に確認済みの追跡可能なフィールド（Bio調査で`scanorganic/1`について確認したのと同じenvelope構造）:

```text
header.uploaderID          （匿名化されたアップローダー識別子）
header.softwareName        （アップロードに使われたツール名、例: "EDO Materials Helper"）
header.softwareVersion
header.gatewayTimestamp    （EDDN gateway受信時刻、observed_atとの差分でfreshness計測可能——T4-Aで実施済み）
message.marketId           （station識別子）
message.systemName / stationName
message.timestamp          （ゲーム内Market.json生成時刻 = observed_at）
```

これらを組み合わせれば「いつ・どこから・どのツールで・どのstationについて送られたか」を全て追跡可能。**設計としては十分な情報が揃っている**——実際にDBスキーマへ組み込むのはT4-Dの実装対象とする。

### 10.4 C-3: Duplicate / Replay処理（設計提案、未実装）

T4-Bで確認したduplicate broadcast rate（5-10%）への対処として、以下を設計提案する（コード実装はT4-Dで）:

```text
dedup key候補: (station_id, commodity_name, observed_at)
  同一keyで複数回受信 → broadcast重複として1件に統合（BioObservationの
  upsert_if_olderと同種のロジックが転用できる）

ただし、同一station・同一commodityでもprice/stock/demandが変化していれば
別の実観測として扱う必要がある。単純に(station_id, commodity_name, observed_at)
だけで一意化すると、真に価格が更新された観測を誤って「重複」として捨てて
しまう可能性がある——observed_at（Market.json生成時刻）が変われば別観測、
という現状の設計（BioObservationと同じ「同一(station,commodity)キーで最古を
残す」ではなく、Market価格は時系列データとして全timestampを保持する必要が
あり、Bioのspecies存在有無とは性質が異なる）。
```

### 10.5 C-4: Trade候補としての利用条件（仕様化）

T4-Bの実測結果（`buy_rate`約65-70%、`sell_rate`約98.9%、`supply_rate`約15-17%、`demand_rate`約43-51%）を踏まえ、以下をTrade候補構築の必須条件として仕様化する:

```text
購入可能条件（source station）: buy_price > 0 AND supply > 0
販売可能条件（destination station）: sell_price > 0 AND demand条件（要検証、下記）
```

**`demand=0`の意味論について、ユーザーから「無限需要を意味する場合がある」との指摘があったが、EDDN公式スキーマ（`commodity-v3.0.json`）を直接確認したところ、`demand`は単なる`integer`型としか定義されておらず、0に特別な意味（無限需要）を与える記述は見つからなかった。** `commodity-README.md`にも同様の記述はない。**この主張は現時点で公式ソースから検証できていない未確認情報として扱う**——鵜呑みにせず、T4-Dでのcandidate構築時に実データ（demand=0の実際の観測パターン）で改めて検証する。それまでは保守的に`demand > 0`を販売可能条件とする。

`NonMarketable`（Limpets等）・`legality`による除外はEDDN公式スキーマ（`commodity-README.md`）で明記されており確認済み——ただしJournal由来データではこれらのフィールド自体が既に除外されている可能性があり、EDpj側での追加フィルタが必要かはT4-Dで確認する。

### 10.6 T4-C結論

```text
C-1 Commodity Master照合    → 完了（実際のjunk率0.05%未満、参照マスタ不備が主因と判明）
C-2 Provenance              → 設計確認完了（必要フィールドは全て取得可能）
C-3 Duplicate/replay        → 設計提案完了（未実装、T4-Dで実装）
C-4 Trade候補利用条件        → 仕様化完了（demand=0の意味論は未検証のまま保守的に扱う）
        ↓
次: T4-D（Trade Candidate Construction）へ
```

## 11. T4-D: Trade Candidate Construction — 第1回実証（1 Origin Station）

### 11.1 フィールド対応関係の訂正（実装前に確定）

実装前に、EDDN公式スキーマ（`commodity-v3.0.json`）で正確なフィールド対応を確認した:

```text
buyPrice（"Price to buy from the market"） + stock  → 購入可能条件（Origin/source）
sellPrice（"Price to sell to the market"） + demand → 売却可能条件（Destination）
```

（自プロジェクトのフィールド名では`row["buy_price"]`+`row["supply"]`がOrigin、`row["sell_price"]`+`row["demand"]`がDestinationに対応。T4-C §10.5の定義と一致。）

### 11.2 第1回実装（investigation only、DB永続化なし）: 重大な問題を発見

2026-09-05のアーカイブから、KNOWN commodityを15種以上`buy_price>0 AND supply>0`で持つ最初のstation（`Turing's Folly`, `Col 285 Sector RX-Q a48-3`, 63種）をOriginとし、同commodityについて`sell_price>0 AND demand>0`の全destination候補から**単純に最大profitのdestinationを選ぶ**方式で実装した結果:

```text
fruitandvegetables: origin_buy=172 → dest_sell=40,483（unit_profit=40,311）
tritium:            origin_buy=50,009 → dest_sell=1,538,461（unit_profit=1,488,452）
```

**Fruit and Vegetables（実際の相場は150〜300CR程度）が40,483CRで売れるというのは明らかに非現実的。** 上位候補destinationを個別に調査した結果:

```text
WBV-04T（destination候補の1つ）: 21品目全てbuy_price=0・supply=0、
    かつemergencypowercells/evacuationshelter/buildingfabricators等の
    「建設資材」だけ高値でdemandを示す
Metz Enterprise: 368品目中4品目のみbuy_price>0 AND supply>0
WFY-G1Y:         1品目中0品目
PS00:            31品目中0品目
```

**原因判明: これらは通常のCommodities Marketではなく、「植民地建設船（Colonisation Ship）」型の一方向market**（T4-A §4.1で発見した`station='$EXT_PANEL_ColonisationShip; Cobb Horizons'`という未解決ローカライズキーと同じゲーム内メカニクス）。プレイヤーへの通常販売は一切行わず、建設資材の納品に対して人為的に高い買取価格を提示する——これをそのまま「利益」として扱うと、`max(profit)`という単純な選択方法が系統的にこの種の特殊marketへ吸い寄せられてしまう。**データ破損ではなく、市場種別の混同という設計上の欠陥だった。**

### 11.3 修正: destinationを「通常の双方向market」に限定

「自身の commodity listing のうち`buy_price>0 AND supply>0`が10品目以上あるstationのみをdestination候補として許可する」条件を追加して再実行:

```text
tritium: origin_buy=50,009 → dest_sell=150,622（unit_profit=100,613）
gold:    origin_buy=45,531 → dest_sell=67,793（unit_profit=22,262、+48.9%）
steel:   origin_buy=3,887  → dest_sell=24,023（unit_profit=20,136）
```

Fruit and Vegetables等の極端な事例は解消された。ただし**tritiumの3倍近い価格差、goldの+49%は依然として実在の裏取りができていない**——これはT4のAccuracy checkとして最初から未実施のまま残していた項目そのものであり、ここで初めて具体的に必要性が実証された形になる。**「PASS」とはまだ言えない。**

### 11.4 T4-D Exit Criteriaへの追加項目

ユーザー提示のExit Criteria表に対し、実証を通じて以下を追加する:

```text
Destination market type   通常の双方向market限定（自身の commodity listing の一定割合以上が
                           buy_price>0 AND supply>0であること）。植民地建設船等の
                           一方向depot型marketをdestinationから除外する
Accuracy（未解決）        単一日・単一origin内では検出しきれない極端な価格差
                           （tritium 3倍、gold +49%等）を、複数日・独立ソースとの
                           突合、または該当commodityの母集団価格分布との比較で
                           さらに検証する必要がある
```

### 11.5 T4-D現状

```text
Commodity eligibility  → KNOWN限定、実装済み
Origin condition       → buy_price>0 AND supply>0、実装済み・検証済み
Destination condition  → sell_price>0 AND demand>0 AND 通常双方向market限定、実装済み
Profit計算             → 実装済み、非現実的な値は解消したが完全なAccuracy検証は未完了
Same station除外        → 実装済み
Distance / Jump         → 未実装（次段階）
Provenance保持          → データとしては取得済み、候補構造への統合は未実装
Freshness               → 未実装
Duplicate               → T4-C §10.4の設計のみ、未実装
Replay再現性            → 未検証
```

**結論**: T4-DはOrigin/Destination/Profit計算の基本構造が実データで動作することを実証したが、**まだ本番のTrade Candidate構築として採用できる完成度ではない**。特にAccuracy検証（tritium/gold級の価格差の裏取り）と、Distance/Jump統合が残っている。次にどちらを優先するかは要判断。

## 12. T4-D Accuracy Check: Tritium / Goldの独立検証

### 12.1 外部ソースは両方とも利用不可（正直に記録）

**INARA**: `inara.cz/elite/commodity/`を直接取得したが、返ってきたHTMLに"gold"/"tritium"という文字列が一切含まれていなかった（コンテンツがJavaScriptで動的に読み込まれる構造）。本セッションはブラウザ実行環境を持たないため、この経路での照合は不可能。

**EDData API**（`api.eddata.dev`）: 3回試行して全て`522`（Cloudflare Origin Connection Time-out）——サーバー側が到達不能。一時的な障害の可能性はあるが、今回は利用できなかった。

**したがって、外部ソースとの直接照合は断念し、自データセット内の分布ベース検証に切り替えた。**

### 12.2 分布ベース検証: 両候補とも母集団の絶対最大値（P100）だった

2026-09-05の「通常market」（買取品目10以上）に限定した母集団全体（tritium sell側 n=40,107、gold sell側 n=51,399）の中で、T4-D v2が選んだdestination価格の位置を確認した:

```text
gold:
  origin_buy=45,531  → buy_price分布のP75.6（正常な価格帯）
  dest_sell=67,793   → sell_price分布のP100.0（母集団51,399件中の絶対最大値。P99ですら56,281）

tritium:
  origin_buy=50,009  → buy_price分布のP44.3（正常な価格帯）
  dest_sell=150,622  → sell_price分布のP100.0（母集団40,107件中の絶対最大値。P99ですら61,468）
```

Origin側は完全に正常。**Destination側の両方が、母集団中で唯一無二の極端な最大値**——「たまたま高いが実在する価格」ではなく、統計的に強い異常signalである。

### 12.3 該当2 stationの全listingを直接確認 — 単一commodityの異常ではなく、station全体が系統的に破損

```text
J8V-06B（tritium destination, market_id=3710775808）: 18品目
  上位sell_price: mysteriousidol=300,623, m_tissuesample_nerves=300,473,
                  earthrelics=300,400, p_particulatesample=300,325,
                  ancientkey=300,058
  → 全く無関係なアイテム（探索収集品・exobiologyサンプル名の誤送信混入・
    クエスト系アイテム）が約300,000CR前後にクラスタリング

Heck Silo（gold destination, market_id=4223685123）: 112品目
  rhodplumsite=822,175（実相場約25-30万）, iridium=645,815（実相場約5.5万）,
  platinum=228,661（実相場約4.5-5万）, osmium=207,242（実相場約3-4万）
  → ほぼ全ての高額commodityが実際の相場の約3〜5倍
```

**単一commodityの偶発的な外れ値ではなく、station全体が系統的にデータ破損している。** T4-C §10.3で確認したCommodity Master照合（0.045%のmalformed rate）は「commodity名」の妥当性だけを見ており、**「価格の妥当性」は別次元でチェックされていなかった**——今回のAccuracy Checkで初めてこのギャップが明らかになった。

### 12.4 対比: P95以内で見つかった「もっともらしい」正常な高利益destination

```text
tritium: sell_price=57,840（P95）demand=202,990  station='Many Made This Light'  system='Scorpii Sector GW-W c1-10'
gold:    sell_price=54,779（P95）demand=1,183    station='Cheranovsky City'      system='Ngurii'
```

これらは母集団の分布内（P95以下）に収まっており、少なくとも価格面では「破損データによる特異値」という証拠は見られない——ユーザーのExit Criteria「少なくとも1件の高利益だが正常なTrade」「少なくとも1件の高利益だが特殊Marketなので除外」の両方の具体例が得られた。ただし、これらも外部ソースでの裏取りはできていないため、「正常」の確証度合いはあくまで統計的な相対評価に留まる。

### 12.5 結論: Market Classificationは2軸が必要（station構造 + 価格妥当性）

```text
軸1: station構造（T4-D §11.3で導入済み）
  通常の双方向market / Colonisation Ship等の一方向depot

軸2: 価格妥当性（今回新たに必要性が判明、未実装）
  そのstationのcommodity価格が、同commodityの母集団分布内（例: P95以内）に収まっているか
  station全体で見て、既知の主要commodity（gold/silver等の流動性が高いもの）の価格が
  母集団中央値から大きく乖離していないか
```

**「10品目以上の買取可能listing」という条件だけでは、station構造の異常（Colonisation Ship）は検出できても、価格そのものの破損（今回発見したJ8V-06B・Heck Silo）は検出できない。** ユーザー指摘の通り、これを最終仕様として固定するのは危険であり、**station_type分類と価格妥当性チェックを独立した2つの検証軸として設計する**必要がある。具体的な閾値（P95か、station全体の中央乖離率か等）は、今回1日・2 commodityの実証のみでは確定できず、さらなる検証が必要——次段階の課題とする。

### 12.6 T4-D Accuracy Exit Criteria（判定）

```text
[x] Tritiumの高価格差を独立ソースで確認          → 外部ソース不可、自データセット分布で検証
[x] Goldの高価格差を独立ソースで確認             → 同上
[x] Origin priceの一致確認                      → 正常（P44-P76範囲）
[x] Destination priceの一致確認                  → 異常（P100、母集団の絶対最大値）と判明
[x] stock / demandの整合確認                     → 破損station側もdemand自体は正の値を持つため
                                                    demand単独では異常検出不可と判明
[ ] timestampの鮮度を考慮                        → 未実施
[x] Profit再計算一致                            → 計算自体は正しく再現可能（問題は入力データ側）
[x] 少なくとも1件の「高利益だが正常なTrade」      → 12.4の2例
[x] 少なくとも1件の「高利益だが特殊Marketなので除外」 → 12.3の2例（station構造は正常判定でも価格が破損）
[x] Market Classificationの必要性を判定          → 2軸（構造+価格妥当性）必要と結論、実装は未着手
```

**T4-D Accuracy: 部分PASS——「価格が破損したstationは高利益として誤検出されうる」ことを実証し、原因を特定したが、価格妥当性チェック自体の実装・閾値確定はまだ完了していない。** Distance/Jump統合へ進める前に、この価格妥当性チェックを実装するか、閾値の確定なしに暫定的に進めるかは要判断。

## 13. Price Plausibility特徴量の設計・実証

### 13.1 特徴量設計: station-level median ratio

閾値を先に固定せず、まず「異常価格を検出するための特徴量」を設計した。流動性の高い主要commodity 10種（gold, silver, platinum, palladium, painite, osmium, bertrandite, indite, gallite, tritium）を参照セットとし:

```text
1. 各commodityについて、「通常market」母集団全体でのsell_priceの中央値（global_median）を算出
2. 各stationについて、そのstationが持つ参照commodityごとに ratio = station_price / global_median[commodity] を計算
3. そのstationの ratio群の中央値（station_median_ratio）を、station単位の価格乖離度スコアとする
   （複数commodityが同時に高いか低いかを見る——単一commodityだけの偏りとは区別する設計）
```

**単一commodityではなく複数commodityの中央値を使う理由**: 1商品だけが高い場合は正常な特殊market（真に希少な商品の需給逼迫等）の可能性があるが、**参照commodity全体が同時に高い場合はstation全体のデータ破損である可能性が高い**、という§12.3の発見（Heck Silo/J8V-06Bはgold/tritium単体ではなく全体が異常だった）を直接反映した設計。

### 13.2 実証結果: 母集団分布と、既知の good/bad 4例での検証

```text
母集団（参照commodityを2種以上持つ「通常market」station、n=5,531）:
  min=0.048  P25=0.991  median=1.015  P75=1.127  P95=1.286  P99=1.463  max=3.481
```

**大多数のstationはratio中央値が1.0付近に集中**——多くの通常marketが、実際にglobal市場価格と整合していることを裏付ける。

§12.3/§12.4で個別に発見していた4つの既知例をこの特徴量で評価した結果:

```text
Heck Silo（BAD、gold P100の破損station）:              station_median_ratio=1.499  percentile=99.5%
J8V-06B（BAD、tritium P100の破損station）:               station_median_ratio=2.807  percentile=99.9%
Many Made This Light（GOOD、tritium P95の妥当な高利益）:  station_median_ratio=1.008  percentile=48.9%
Cheranovsky City（GOOD、gold P95の妥当な高利益）:         station_median_ratio=1.240  percentile=91.9%
```

**既知のBAD例2件（P99.5, P99.9）とGOOD例2件（P48.9, P91.9）が、P99付近を境に明確に分離した。** GOOD例は母集団のP95未満に収まり、BAD例はP99を超えている——n=4という少数の検証例ではあるが、この特徴量がstation構造フィルタでは検出できなかった価格破損を捉えられることを実証できた。

（実行中に判明した副次的なバグ: このスクリプトはstationの1日分の重複配信（T4-B §9.5で確認済みのduplicate broadcast、5-10%）を重複除去せずに集計したため、`n_reference_commodities`の表示件数が実際より大きく膨らんだ（例: Heck Silo=182件、本来は7件程度）。ただし重複は同一価格の繰り返しのため、`station_median_ratio`自体の値は歪んでいない——investigation専用スクリプトのため未修正のまま記録するが、正式実装時にはstation×commodityで重複排除してから計算する必要がある。）

### 13.3 現時点の判断: 閾値はまだ「確定」しない

n=4の検証例のみでP99という閾値を本番仕様として固定するのは時期尚早——ユーザーの指摘通り、この段階では「特徴量が機能する」ことの実証に留め、閾値確定にはより多くの正例・負例サンプル（複数日、複数commodityでの追加検証）が必要である。**P99（またはratio>1.3〜1.5付近）が有力な候補である**ことは実データで示せたが、これを固定の本番閾値として仕様書に確定するのは次段階の課題とする。

### 13.4 T4-D Accuracy Check最終状態

```text
External verification        → BLOCKED（INARA: JS動的レンダリング、EDData API: 522到達不能）
Internal distribution check  → PASS WITH FINDINGS（2つの破損station発見、原因特定）
Price Plausibility特徴量      → 設計・実証完了（station_median_ratio、n=4例でP99付近の分離を確認）
閾値確定                     → 未確定（次段階、より多くのサンプルが必要）
Market Classification        → 2軸（構造+価格妥当性）の設計を確立、実装（本番コード化）は未着手
```

## 14. T4-D完了判定

**T4-Dは完了扱いとする。** 判断根拠:

```text
station構造フィルタ（10品目以上の双方向market）        → PASS
price corruption特徴量（station_median_ratio）         → PASS（既知4例で分離実証済み）
production threshold（P99等の本番閾値固定）             → UNRESOLVED（意図的——n=4での確定は時期尚早）
```

`station_median_ratio`を正式な特徴量として採用する。閾値は未確定のまま、Distance/Jump統合パイプラインへ実際に組み込みながら実データを蓄積し、後日Threshold Calibrationとして別途確定する（統合と閾値確定は独立した作業であり、統合を先に進めても後から閾値モデルを差し替え可能な構造にしておけばよい）。

**残課題として記録**（修正タスク、閾値確定と同様に別途対応）: `price_plausibility_feature.py`の重複配信除去バグ——同一station・同一commodityの当日複数回配信を重複除去せずに集計していたため、`n_reference_commodities`等の表示件数が実際より膨らんでいた（例: Heck Silo表示182件、実際は約7件）。計算結果（`station_median_ratio`の値そのもの）は重複が同一価格の繰り返しであるため歪んでいないが、本番実装時には`(station_id, commodity)`単位での重複排除を先に行う必要がある。

```text
次段階: Distance / Jump Integration
```

## 15. Distance / Jump Integration（実装済み）

### 15.1 実装

`app/collectors/spansh_route.py`（`plot_route`）: Bio期のjump-count feasibility investigation（`docs/BIO_JUMP_COUNT_FEASIBILITY_INVESTIGATION_V0.1.md`）で検証済みだったSpansh Galaxy Route Plotter（`POST /api/route` → `GET /api/results/{job}`のpolling）を、初めて再利用可能なモジュールとして実装した。実装前に契約を再度実データで確認（`efficiency=60`はコミュニティ製`EDMC_SpanshRouter`プラグインのデフォルト値を踏襲、独自の値ではない）。

`app/market/trade_candidate.py`（`TradeCandidate`データクラス、`attach_route`）: T4-Dのprofit計算結果に、`distance_ly`・`jump_count`・`profit_per_ly`・`profit_per_jump`を付与する。ルート計算に失敗した場合は`None`のまま返す（distance/jumpを捏造しない）。7テスト + 4テスト、計11テスト追加。

なお、同日GitHubにpushされた`DESTINATION_ETA_SPEC_V0.1.md`/`PHASE_DESTINATION_ETA_V0.1.md`は、**本機能とは別のフィーチャー**（FSDジャンプ後のsystem内Supercruise距離・ETA、Phase 0-C Action Horizon側、Scoringには使わない）であることを確認済み——混同しないよう明記する。

### 15.2 実データでの検証: Distance軸が価格妥当性チェックの結論を独立に裏付けた

T4-D §12-13で得た3つの実候補（origin: Turing's Folly固定、ship_range=25ly）にdistanceを付与した結果:

```text
tritium destination=Tir/J8V-06B（§12.3で破損stationと判定済み）:
  unit_profit=100,613  distance_ly=21,844.08  jump_count=241
  profit_per_ly=4.61   profit_per_jump=417.48

tritium destination=Many Made This Light（§12.4で「妥当」と判定済み）:
  unit_profit=7,831    distance_ly=101.48   jump_count=1
  profit_per_ly=77.17  profit_per_jump=7,831.0

gold destination=Cheranovsky City（§12.4で「妥当」と判定済み）:
  unit_profit=9,248    distance_ly=178.30   jump_count=1
  profit_per_ly=51.87  profit_per_jump=9,248.0
```

**破損stationと判定した`Tir`は241ジャンプ・21,844光年という現実離れした遠方だった一方、価格妥当性チェックで「正常」とした2候補はいずれも1ジャンプで到達可能だった。** 価格妥当性（station_median_ratio、§13）という軸と、距離（今回のjump_count）という全く独立した軸が、同じ結論を指し示している——これは§13の価格妥当性特徴量への追加の裏付けであると同時に、**`profit_per_jump`でランキングするだけでも、破損データによる極端な値をある程度自然に希薄化できる**（417 vs 7,831/9,248という大差）ことを示している。ただし、これは価格妥当性チェックの代替にはならない——`profit_per_jump`ですら417という値自体は依然として「高利益」の範疇に見えてしまう可能性があり、station_median_ratioによる明示的な除外は引き続き必要。

### 15.3 現状

```text
Distance計算（Spansh route API）    → 実装・実データ検証済み
Jump count計算                     → 実装・実データ検証済み
profit_per_ly / profit_per_jump    → 実装済み
TradeCandidateへの統合              → 実装済み（distance/jump欠損時はNone、捏造なし）
production threshold（station_median_ratio） → 未確定（§14の方針通り、今後の実データ蓄積後に確定）
Duplicate除去バグ（§13.2）          → 未修正（別タスクとして記録済み）
本番DB永続化                       → 未実施（investigation/moduleレベルの実装のみ）
```

Distance/Jump統合は実装・実データ検証まで完了。次は、この統合パイプラインを使った実データ蓄積を経てのThreshold Calibration、または総合Trade Rankingへの接続が課題として残る。

## 16. Threshold Calibration — 重要な訂正: 当初の「station全体が破損」という結論は一部誤りだった

### 16.1 重複除去バグ修正後・参照commodity拡張（10→30種）での再計算

`app/market/price_plausibility.py`（重複配信を正しく除去、`dedupe_latest`は`(station_id, commodity)`ごとに最新観測のみ保持）で、参照commodityを流動性の高い30種（元の10種 + water/grain/basicmedicines等の生活必需品、aluminium/copper/steel等の工業金属）に拡張し、2026-09-05を再計算した:

```text
重複除去前のsell観測: 1,498,350件 → 重複除去後: 151,249件（(station,commodity)ペア）
  ※ 重複率は約90%——1つのstationの1日の市場更新が平均して何度も再配信されている
    （T4-B §9.5で確認した5-10%という数字は「メッセージ単位」の重複率であり、
    「(station,commodity)ペアが日内に何回観測されるか」で見るとこれよりずっと多い）

station_median_ratio分布（n=5,769、min_reference_commodities=3）:
  min=0.053  P50=0.996  P90=1.075  P95=1.089  P99=1.107  max=1.692
```

**§13の分布（P99=1.463, max=3.481）よりはるかにタイトになった。** 重複バグ・小さい参照セット（10種）の両方が、以前の分布を実態よりも広く見せていたと考えられる。

### 16.2 既知の「BAD」station、再計算後の実態

```text
J8V-06B: 正しく重複除去すると参照commodity該当数が1種（tritiumのみ）に減り、
         min_reference_commodities=3を満たさず、station_median_ratioの対象外になった
         （§13段階では重複バグにより「2件」とカウントされ、閾値min=2をたまたま満たしていた
         ——つまりバグが偶然この station を検出可能にしていた）

Heck Silo: station_median_ratio = 1.073（P89.3）——★極端な外れ値ではない★
    25参照commodityの内訳（一部抜粋）:
      aluminium=1.07, basicmedicines=0.98, beryllium=1.02, gallite=1.01,
      hydrogenfuel=1.10, lithium=1.06, polymers=1.07, steel=1.07,
      superconductors=1.04, tantalum=1.03, titanium=1.07, tritium=1.07,
      uranium=1.03, water=0.71, grain=0.80          ← 大半は正常範囲
      cobalt=2.08, rutile=2.05, coffee=1.50, tea=1.43, gold=1.42,
      palladium=1.32, silver=1.33                    ← やや高い
      fruitandvegetables=3.78, osmium=4.35, platinum=3.85  ← 明確に高い
```

**§12.3で「ほぼ全ての高額commodityが実際の相場の3〜5倍」と結論したのは誤りだった。** これは「sell_price上位10件」という絶対価格順のサンプルを目視した結果であり、**高額commodity（platinum/osmium等）は元々価格が高いため、異常な倍率のcommodityが上位に来やすいという選択バイアス**があった。実際には25種中の大半（15種程度）は母集団と整合する正常な価格で、一部（5〜8種）だけが実際に高い。station_median_ratioという中央値ベースの特徴量は、この偏ったサンプリングの影響を受けず、正しく「station全体としては極端ではない」（P89.3）と判定していた——**§12.3の manual investigation の結論より、station_median_ratio特徴量の判定の方が正確だった**、という結果になる。

### 16.3 一方、gold単体では依然としてP100の外れ値

```text
gold（重複除去後の母集団、n=5,467）: median=47,663  P95=55,853  P99=56,345  max=67,793
Heck Silo の gold=67,793 → 依然として母集団の絶対最大値（P100）
```

**station全体では正常範囲（P89.3）なのに、gold という1商品だけを見るとP100の外れ値**——station-level median ratioとcommodity単体でのpercentileが食い違うケースが実在することが判明した。

### 16.4 Calibrationにおける結論

1. **station_median_ratio特徴量自体は妥当**——重複バグ・選択バイアスを除去した後も、母集団の大半（P90未満）は1.0付近に集中する健全な分布を示しており、特徴量設計は正しい。
2. **ただし単一の特徴量だけでは不十分**——station全体の中央値が正常でも、特定の1commodityだけがそのcommodity自身の母集団内で極端な外れ値（P100等）になっているケースを検出できない（Heck Silo/gold）。逆に、参照commodityが少なすぎるstation（J8V-06B）は、そもそも判定不能（INSUFFICIENT）になる。
3. **したがって最終的なMarket Classificationには、station-level median ratioとcommodity-level percentileの両方を独立に見る必要がある。** どちらか一方が閾値を超えたら要注意、という設計が妥当と考えられるが、これも今回のn=1事例（Heck Silo/gold）のみでの示唆であり、閾値の確定にはまだ足りない。
4. **§13で「P99付近で既知4例がきれいに分離した」という結果は、重複バグと選択バイアスの影響を受けた状態での結果だった。** 訂正後も特徴量の有用性自体は支持されるが、「P99で綺麗に分離する」という具体的な主張は撤回し、より慎重な評価が必要という結論に修正する。

### 16.5 現時点の判断

**production thresholdはまだ確定しない。** 今回の訂正は、拙速な閾値確定を避けるという§13/§14の判断が正しかったことを裏付けている。次段階として、station-level ratioとcommodity-level percentileの2つの指標を组み合わせた分類ロジックを設計し、より多くの実例（複数日、複数commodityカテゴリ）で検証する必要がある。

## 17. T4-E: Two-Level Price Anomaly Classification

### 17.1 実装

`app/market/price_plausibility.py`に以下を追加（12テスト追加、計612テスト）:

```text
Feature A（station-level）: compute_station_median_ratio（§13、既存）
Feature B（commodity-level）: compute_commodity_percentiles
  各(station, commodity)ペアについて、そのcommodity自身の母集団内での価格の順位（percentile）を計算
PriceAnomalyAssessment: 両特徴量を1 stationにまとめたデータクラス（worst_commodity_percentileはstationが
  持つ参照commodityの中で最も極端なpercentileを採用）
classify(): 2軸の閾値（呼び出し側が渡す、モジュール内には固定しない）でNORMAL/STATION_ANOMALY/
  COMMODITY_ANOMALY/STRONG_ANOMALYの4分類を返す
```

### 17.2 実データ適用（2026-09-05、n=5,769 station）

```text
worst_commodity_percentile分布: min=0.004  P50=0.922  P90=0.996  P99=1.000  max=1.000
```

Heck Siloは`classify()`で明確に`COMMODITY_ANOMALY`（station_median_ratio=1.073は正常域、gold percentile=1.0000のみ異常）に分類され、§16.3の分析と整合した。

### 17.3 新たな問題発見: percentileの同値（tie）処理が低分散commodityで偽陽性を生む

`station_median_ratio<1.2`かつ`worst_commodity_percentile>=0.999`の組み合わせで294件が該当したが、内訳を見ると`gallite`・`indite`・`hydrogenfuel`・`tea`・`polymers`のような**低価格・低分散commodityが異常なほど頻出**していた。原因を確認した:

```text
gallite:       n=4796  distinct_values=1315  max=13829  同一最大価格のstation数=143（2.98%）
indite:        n=4183  distinct_values=1195  max=13470  同一最大価格のstation数=80（1.91%）
hydrogenfuel:  n=5758  distinct_values=58     max=187    同一最大価格のstation数=42（0.73%）
gold:          n=5467  distinct_values=1990   max=67793  同一最大価格のstation数=1（0.02%、Heck Siloのみ）
```

**gallite等では、最大価格を143もの独立したstationが同時に達成しており、これは異常ではなくその商品の自然な上限価格に多数のstationが独立に到達しているだけ**（同一の局所経済条件が広く成立しうる、低価格帯のcommodityでよくある現象）。一方goldは最大値を共有するstationがHeck Silo一件のみであり、真に孤立した外れ値だった。

**現在の`compute_commodity_percentiles`（`count(price<=x)/n`という順位ベースの定義、同値は`<=`でカウント）は、この「多数のstationが同一の自然な上限価格に到達する」ケースと「1 stationだけが真に突出した価格を持つ」ケースを区別できていない。** 単純な percentile>=閾値 という条件だけでは、低分散commodityで大量の偽陽性を生む。

### 17.4 現時点の結論

Feature B（commodity-level）は、**「順位」だけでなく「その価格を共有するstation数（同値の多さ）」も見る必要がある**——例えば「percentile>=0.999」に加えて「同一価格帯のstation数が少数（例: 母集団の1%未満）」という条件を組み合わせる、あるいは値ベースの比率（`station_price / P99値`）を使うなど、複数の設計候補がある。**閾値だけでなく、Feature Bの定義自体をもう一段改善する必要がある**と判明した。これも「拙速に閾値を固定しない」という一貫した方針の正しさを裏付ける結果であり、Feature B改良は次段階の課題として記録する。

```text
T4-E現状:
  Feature A（station_median_ratio）        → 実装・検証済み、健全
  Feature B（commodity percentile、素朴な順位） → 実装済みだが、同値ties問題により低分散commodityで
                                              偽陽性を生むことが判明。定義の改良が必要
  2軸classify()                            → 実装済み、閾値は未確定
  production threshold                     → 未確定（意図的）
```

## 18. Feature B v2: 構成要素を分離した価格妥当性指標

### 18.1 実装

`compute_commodity_percentiles`を廃止し、`compute_commodity_stats`に置き換え（このモジュールは他コードから未参照のため、破壊的変更を許容）。`CommodityPriceStats`データクラスとして以下を**1つのスコアに潰さず個別に保持**:

```text
percentile        : そのcommodity自身の母集団内での順位（v1と同じ定義）
value_ratio       : station価格 / commodity_global_median（倍率そのもの）
max_tie_count     : そのcommodityの最大価格を共有する独立station数
max_tie_share     : max_tie_count / observation_count
observation_count : そのcommodityの母集団サイズ
```

`classify()`のcommodity側判定を、percentile単独ではなく**3条件の論理積**に変更: `percentile>=閾値 AND max_tie_share<=閾値 AND value_ratio>=閾値`（すべて呼び出し側パラメータ、モジュール内に固定値なし）。8テスト追加（うち1件は§17.3のgallite 143件タイ実例を模した**固定回帰テスト**——将来の特徴量変更が「自然な価格上限」を再び異常扱いする退行を検出する）。計17テスト、全体625テスト。

### 18.2 実データでの検証（2026-09-05）

```text
Heck Silo: station_ratio=1.073  worst=gold  percentile=1.0000  tie_share=0.0002（0.02%）  value_ratio=1.422
  → classify() = COMMODITY_ANOMALY（3条件すべて満たす）

gallite（§17.3の143件タイ実例、実データで直接確認）:
  percentile=1.0000  tie_share=0.0298（2.98%、閾値1%を超過）  value_ratio=1.030（閾値1.3を大きく下回る）
  → classify() = NORMAL（tie_shareとvalue_ratioの両方が独立に除外条件を満たしており、二重に安全）
```

**gallite側は、tie_share・value_ratioのどちらか片方だけでも誤検出を防げていた**——2つの追加指標が独立に効いていることが確認できた。

閾値候補3パターンで試算（n=5,769）:

```text
(station>=1.3, pct>=0.99, tie_share<=0.05, value_ratio>=1.3): COMMODITY_ANOMALY 303件（5.25%）
(station>=1.3, pct>=0.99, tie_share<=0.01, value_ratio>=1.3): COMMODITY_ANOMALY 282件（4.89%）
(station>=1.2, pct>=0.995, tie_share<=0.01, value_ratio>=1.2): COMMODITY_ANOMALY 312件（5.41%）
```

いずれの組み合わせでもHeck Siloは一貫してCOMMODITY_ANOMALYに分類され、gallite型の共有天井は一貫してNORMALに分類された——Feature B v2は少なくともこの2つの既知パターンに対して閾値の選び方に対して頑健。ただし該当282〜312件の内訳は未精査（`polymers`で価格比14.9倍のような、個別に裏取りが必要なケースも含まれる）。

### 18.3 現時点の判断

Feature B v2は§17.3で発見した問題を実データで解決したことを確認した。**production thresholdはまだ確定しない**（意図的、方針は§14/§16.5/§17.4から変更なし）。次段階は、282〜312件のCOMMODITY_ANOMALY候補の中身をさらにサンプリング検証すること、複数日での安定性確認、またはこの時点で十分な検証が積み上がったと判断してThreshold Calibrationへ進めることのいずれか。

## 19. Multi-day Stability Validation

### 19.1 実施内容

T4-Bと同じ14日間ウィンドウから7日（2026-08-23, 25, 27, 29, 31, 09-02, 09-04）を抽出し、Feature A/B v2の全パイプラインを日ごとに再計算した。3種類の閾値セット（A: station>=1.3/pct>=0.99/tie<=0.05/ratio>=1.3、B: tie<=0.01に厳格化、C: station>=1.2/pct>=0.995/tie<=0.01/ratio>=1.2）を並行して評価した。

### 19.2 Feature A（station_median_ratio）の分布は極めて安定

```text
日付         n_station  P50      P90      P99      max
2026-08-23   6,780      0.997    1.074    1.112    4.265
2026-08-25   6,008      0.997    1.071    1.108    3.767
2026-08-27   5,824      0.998    1.070    1.108    1.607
2026-08-29   6,744      0.997    1.071    1.112    1.607
2026-08-31   7,711      0.998    1.065    1.096    1.637
2026-09-02   5,289      0.996    1.071    1.109    1.637
2026-09-04   5,844      0.996    1.077    1.110    1.697
```

P50/P90/P99は7日間を通じてほぼ完全に一定（P50は0.996〜0.998、P90は1.065〜1.077、P99は1.096〜1.112）。**Feature Aの母集団分布は日次で安定しており、健全な特徴量であることが多日データでも裏付けられた。**

### 19.3 COMMODITY_ANOMALY件数の日次変動（率で見ると閾値Cが最も安定）

```text
閾値A（tie<=5%）: 269〜423件（母集団に対する比率で見ると4.62%〜7.05%）
閾値B（tie<=1%）: 258〜423件
閾値C（station>=1.2, pct>=0.995, tie<=1%, ratio>=1.2）: 232〜338件（比率で3.86%〜4.94%、最も狭い変動幅）
```

閾値Cが最も日次で安定した比率（約4〜5%）を示した。ただし7日間という限られたサンプルであり、これを「正常な異常率」として確定するのはまだ早い。

### 19.4 最重要の発見: 「持続性」の解釈が当初の想定と逆だった

同一station（`market_id`で追跡）が複数日にわたってCOMMODITY_ANOMALY判定される頻度（閾値B使用）:

```text
7日間で少なくとも1回検出: 1,490 station
  うち2日以上で検出: 458件（30.7%）
  うち7日全てで検出: 10件（0.67%）
持続性の分布: 1日のみ=1,032, 2日=246, 3日=114, 4日=57, 5日=19, 6日=12, 7日=10
```

**「複数日にわたって持続的に検出される station は、より確度の高い破損候補である」という当初の仮説を検証するため、7日全てで検出された10件を個別に調査した。しかし結果は逆だった。**

10件全ての「原因commodity」を特定した結果:

```text
hydrogenfuel（2件）: global_median=80CR → 実価格は約160CR（絶対額としては僅少、比率だけが2倍）
copper（3件）:       global_median=782CR → 実価格は約1,700〜1,750CR
osmium（2件）:       global_median=47,213CR → 実価格は約235,000CR
platinum（1件）:     global_median=59,303CR → 実価格は約281,000CR
painite（1件）:      global_median=55,036CR → 実価格は約200,000CR
superconductors（1件）: global_median=7,407CR → 実価格は約10,450CR
```

osmium/platinum/painiteが原因の4 stationの実際のcommodity listing（§19.5参照）を見ると、いずれも`musgravite`・`benitoite`・`serendibite`・`grandidierite`のような超高額な希少鉱物を大量に扱っており、**実在する希少鉱物の採掘拠点（mining hotspot）における正当な高額買取価格である可能性が高い**——Elite Dangerousには実際にこの種の局所的・持続的な高価格市場（Paesia等の有名な採掘スポット、Thargoid War Zone、Rescue Ship等）が実在する。hydrogenfuel/copperが原因の5 stationは、**そもそも絶対額が小さいcommodityで、比率ベースの閾値（value_ratio）が過敏に反応しているだけ**——経済的にはほぼ無意味な変動である。

**いずれのケースも、Heck Silo/gold型の「無関係な単一commodityが理由不明で突出する」というパターンとは異なる。** むしろ持続的な異常は「実在する安定した局所経済状況」を反映している可能性が高く、**真のデータ破損（Heck Siloのような孤立事例）はむしろ一過性（一日だけ検出される）である可能性の方が高い**、という実データからの示唆が得られた。これは「持続性が高いほど破損の確度が高い」という直感的仮説と正反対の結果であり、正直に記録する。

### 19.5 追加で判明した問題: 低価格commodityでのvalue_ratio閾値の過敏性

`hydrogenfuel`（母集団中央値80CR）や`copper`（782CR）のような低価格commodityでは、絶対額でわずか80〜1,000CR程度の差でも`value_ratio>=1.3`という比率条件を満たしてしまう。**value_ratioは比率ベースのみで絶対額を考慮していないため、経済的に無意味な変動を拾ってしまう。** 今後Feature Bをさらに改良する場合、絶対額の下限（例: 母集団中央値との差が一定CR以上）も条件に加えることが望ましい——これも閾値確定の前に検討すべき設計課題として記録する。

### 19.6 結論

```text
Feature A: 7日間で分布が安定 → 健全
Feature B v2: COMMODITY_ANOMALY比率は閾値Cで比較的安定（3.86〜4.94%）
持続性: 「持続的＝破損の確度が高い」という仮説は否定された。
        持続的異常は実在する局所経済状況（採掘拠点等）である可能性が高く、
        一過性の異常（Heck Silo型）の方が真の破損候補として有力
新たな課題: value_ratioの絶対額下限が未実装（低価格commodityでの過敏な反応）
```

**production thresholdは引き続き未確定。** 次段階は、(a) value_ratioの絶対額下限を追加する設計、(b) 一過性（1〜2日のみ検出）の異常候補を個別に裏取りする、のいずれかを検討する必要がある。

## 20. Feature B v3: value_ratioへの絶対額認識の追加

### 20.1 実装

`CommodityPriceStats`に`value_difference_absolute`（station価格 − commodity母集団中央値、単位はCR）を追加。`classify()`に`commodity_absolute_floor`という**任意（デフォルト`None`＝チェックなし、後方互換）**パラメータを追加し、指定時は`value_difference_absolute >= floor`を追加のAND条件とする。**具体的な閾値はモジュール内に一切固定しない**——呼び出し側が実験的に値を渡す設計。7テスト追加（実データ形状を模したhydrogenfuel型/gold型の対比を含む）、計621テスト。

### 20.2 実データでの検証（2026-09-05、station>=1.3/pct>=0.99/tie<=1%/ratio>=1.3を固定）

```text
floor未指定:     286件
floor=1,000CR:   157件（45%減）
floor=5,000CR:   116件（59%減）
floor=10,000CR:  106件（63%減）
floor=20,000CR:   50件（83%減）
```

**floor=5,000CRで除外された170件の内訳**（原因commodity別）:

```text
hydrogenfuel: 79件, basicmedicines: 45件, tea: 9件, water: 9件, superconductors: 8件,
copper: 6件, grain: 5件, polymers: 4件, fruitandvegetables: 4件, coffee: 1件
```

**いずれも低価格・生活必需品系のcommodityであり、§19.5で指摘した「経済的に無意味な変動」パターンと完全に一致する。** 一方、**Heck Silo（gold、絶対差約20,130CR）はfloor=5,000CRでも一貫して検出され続けた**——既知の正例が絶対額フィルタ導入後も失われないことを確認できた。

### 20.3 現時点の判断

**production thresholdはまだ確定しない**（floor値自体を含め、固定CR・commodity相対・利益影響ベースのどれが最適かは未検証）。ただし、絶対額フィルタの導入自体が「経済的に無意味な低価格commodityのノイズ」を大きく除去しつつ既知の正例を保持することは実データで確認できた——**Feature B v3として設計は有効**と判断する。

残る課題（次段階）:
1. §19で指摘した「persistenceを異常度スコアに昇格させない」方針の実装——`anomaly_days`/`observed_days`のような診断情報としてのみ保持し、分類ロジックには組み込まない設計
2. 一過性（1〜2日のみ検出）候補の個別裏取り——Heck Silo型（真の破損候補）を実際に発見できるか
3. floor値自体（固定CR / commodity相対 / 利益影響ベース）の比較検討

## 21. Commodity Absolute Floor Calibration Study

### 21.1 実施方法

floor候補（None, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 25000, 30000, 50000CR）を、事前に定義した4軸で比較した（低価格commodityの定義`global_median<1000CR`は、除去率を見る前に決定——特定のfloorに有利な後付け定義を避けるため）:

```text
1. 検出数・検出率
2. 既知正例（Heck Silo）の保持有無 ※確認済み正例はこの1件のみ、n=1という証拠の弱さは明記する
3. 低価格commodityノイズの除去率（baseline: 286件中153件=53.5%が低価格commodity起因）
4. 残存候補集合のvalue_difference_absolute中央値・平均値（＝Trade候補としてのprofit影響の代理指標）
```

### 21.2 実データ結果（2026-09-05）

```text
     floor  n_flagged   rate  heck_silo  low_price_removed  removal_rate  median_profit_CR  mean_profit_CR
      None        286  4.96%       True                  0         0.0%             1,516          36,940
      5000        116  2.01%       True                152        99.3%            14,992          89,831
     10000        106  1.84%       True                153       100.0%            17,138          97,561
     15000         58  1.01%       True                153       100.0%           187,032         167,740
     20000         50  0.87%       True                153       100.0%           200,697         191,883
     25000         49  0.85%      False                153       100.0%           201,548         195,388
     30000         49  0.85%      False                153       100.0%           201,548         195,388
```

### 21.3 発見

1. **Heck Silo保持の上限が判明**: floor<=20,000CRまでは保持され、floor>=25,000CRから脱落する——Heck Siloの`value_difference_absolute`（20,130CR）と正確に一致。**floorをこの値より大きく設定すると、唯一の確認済み正例を失う。**
2. **低価格ノイズ除去率はfloor=10,000CRで100%に到達**（153/153件全て除去）。floor=5,000CRでも99.3%とほぼ同等。
3. **profit影響の代理指標に「谷」がある**: floor=10,000CR（中央値17,138CR）からfloor=15,000CR（中央値187,032CR）にかけて急激にジャンプしている。これは母集団が「小〜中規模の変動（〜2万CR）」と「非常に大きな変動（15万CR以上）」に二峰的な構造を持つことを示唆し、**10,000〜20,000CRという範囲が分布上の自然な谷間にあたる**——原理的に閾値を置くのに妥当な位置。

### 21.4 結論

**floor=10,000〜20,000CRの範囲内であれば、低価格ノイズを完全に除去しつつ、既知の唯一の正例（Heck Silo）を保持できる**ことを実データで確認した。**ただし、この範囲を「production threshold確定」とはしない**——確認済み正例が1件のみという証拠の弱さ、複数日での再検証未実施、一過性候補の裏取り未実施という限界があるため。§20.3で挙げた3つの残課題（persistence診断化・一過性候補裏取り・floor比較）のうち3番目が完了し、範囲の絞り込みという形で前進した。次段階は残る2課題（persistence診断情報化、一過性候補の個別裏取り）に進む。
