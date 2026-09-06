# EDpj Bio: scanorganic/1 × 天体物理パラメータ 突合可能性調査

**Version:** 0.1
**Status:** Investigation only — コード実装なし、本人Journal未使用。`docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`の続き（①「予測に必要な入力データを本当に作れるのか」の検証）。
**Date:** 2026-09-06
**Depends on:** `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md`, `docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`

## 0. 目的

`scanorganic/1`（system + body をキーに持つ）と、species prediction（`P(species | body_conditions, ...)`）の入力になる天体物理パラメータ（温度・重力・大気・天体タイプ等）を、実際に突合できるかを検証した。EDSM（本仕様§3.5で「system/body identity・座標・天体メタデータの補助情報として使用可」と明記されている）とSpanshの2つを実データで確認した。

## 1. 手法

1. `edgalaxydata.space`の`Journal.ScanOrganic`アーカイブ7日分（2026-08-29〜09-04）を再取得し、ユニークな(SystemAddress, BodyID)ペアを抽出（2,803ペア、1,792システム）。
2. 決定論的シード（`random.seed(42)`）で150システムをサンプリング。
3. サンプルした各システムについて、EDSM `api-system-v1/bodies`（`systemName`クエリ）を実際に呼び出し（0.35秒間隔でスロットリング、公開APIへの配慮）、返ってきたbody一覧を`bodyId`でscanorganicの`BodyID`と突合。
4. 突合できたbodyについて、`gravity`/`surfaceTemperature`/`atmosphereType`/`volcanismType`/`type`/`subType`の充足率を集計。
5. EDSMの`discovery.date`（そのbodyが最初にEDSMへ報告された日時）と、scanorganic観測のtimestampを比較し、**discovery.dateが観測より後になっているケース（時系列逆転＝リーク疑い）が無いか**を確認。
6. 比較としてSpanshの`api/system/{id64}`（EDpjの既存Spanshコレクタ`app/collectors/spansh.py`と同じエンドポイント形式）も同じシステムで試した。

本番DB・コードには一切書き込んでいない。ダウンロードしたアーカイブファイル・APIレスポンスは分析後に破棄した。

## 2. 結果

```text
サンプルしたシステム数:                          150
  EDSMにbodyデータが存在:                        148（98.7%）
  EDSMにbodyデータが無い:                          2（1.3%）
  APIエラー:                                       0

突合対象の(system, body)ペア:                    251
  EDSMのbodyレコードとbodyId一致:                251（100.0%）
  不一致（systemは分かるがbodyIdが無い）:           0

物理パラメータ充足率（突合できた251件中）:
  gravity:              251/251 (100.0%)
  surfaceTemperature:   251/251 (100.0%)
  atmosphereType:       251/251 (100.0%)
  type:                 251/251 (100.0%)
  subType:              251/251 (100.0%)
  volcanismType:        249/251 (99.2%)

時系列チェック（discovery.dateとscanorganic観測timestampの比較）:
  比較可能だったbody数:                            188
  discovery.dateが観測より後（リーク疑い）:            0件
```

## 3. Spanshとの比較

`app/collectors/spansh.py`が既に使っている`SYSTEM_DUMP_URL_TEMPLATE`（`https://www.spansh.co.uk/api/system/{id64}`）を同じDeciat系で試したところ、bodyオブジェクトには`type`/`subtype`/`terraforming_state`/`distance_to_arrival`等はあるが、**`gravity`/`surfaceTemperature`/`atmosphereType`/`volcanismType`は含まれていなかった**（このエンドポイントはランドマーク・経済価値中心のダンプで、生体予測に必要な物理パラメータの粒度を持たない）。**species predictionの入力データとしては、EDSMの方が明確に適している。** Spanshは既存のシステム座標・station情報取得という現在の用途のままで良く、Bioの物理パラメータ取得に追加で使う必要は無い。

## 4. 結論

**「予測に必要な入力データを本当に作れるのか」という問いに対する答えは「作れる」——EDSMとの突合で、サンプルした天体の実質100%について、species predictionに必要な物理パラメータ（重力・表面温度・大気タイプ・天体type/subType）が揃っている。** これは`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §4.3の`BioPrediction`層（`P(species | body_conditions, signals, region, ...)`）の入力データセットが実際に構築可能であることの実証である。

**時系列の観点でも、データリークの兆候は見られなかった**（discovery.dateが観測より後になるケースがゼロ）——これはゲームメカニクス上、生体サンプリングの前に必ずFSS/DSSによる天体スキャンが完了している必要があるという実際のプレイフローとも整合する。ただし、この`discovery.date`チェックは「そのbodyが最初にEDSMへ報告された日」を見ているに過ぎず、EDSMの`updateTime`（各フィールドの最終更新時刻）までは検証していない——本格的なbacktest実装時には、`updateTime <= 観測timestamp`という、より厳密な基準の採用も検討する価値がある（本書のスコープ外、次のフェーズで判断）。

**注意点（本調査の限界）**: 150システム・251 bodyというサンプルであり、5,440天体全数を検証したわけではない。ただし決定論的な無作為抽出であり、結果の一貫性（100%近い充足率）から見て、全数調査でも大きく異なる結果にはならないと考えられる——ただし念のため、実際にbacktest実装に進む段階で、より広いサンプル（または全数）での再確認を推奨する。

## 5. 次のステップ

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の順序に従い、次は**②SpeciesValueMasterの複数ソース照合**（Canonn Biosheet/Bioforge等の実データ取得・複数ソースでの一致確認）。これが完了して初めて、③species prediction / value formulaのbacktestに着手できる状態になる。

**現時点のまとめ**: scanorganic/1データの可用性（前回調査）、天体物理パラメータとの突合可能性（本調査）は両方とも「有用」——BioPredictionの入力データセット構築は実データで裏付けられた。残るはSpeciesValueMaster（固定種価値）の照合のみである。
