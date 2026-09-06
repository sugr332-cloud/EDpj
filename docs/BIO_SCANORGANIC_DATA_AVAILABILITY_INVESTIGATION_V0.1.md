# EDpj Bio scanorganic/1 Data Availability Investigation

**Version:** 0.1
**Status:** Investigation only — no code implemented, no accuracy validated. Step 1 of `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9's 7-step order ("EDDN scanorganic/1 archive ingestion" feasibility check).
**Date:** 2026-09-06
**Depends on:** `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md`

## 0. 目的

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の実装順序に従い、**コードを書く前に**、EDDN `scanorganic/1`の実アーカイブデータがどの程度取得できるかを調査した。本人Journalは一切使用していない（§2.1の要求通り、外部・全体母集団のみを対象とする）。

## 1. 手法

`https://edgalaxydata.space/EDDN/YYYY-MM/Journal.ScanOrganic-YYYY-MM-DD.jsonl.bz2`から、**2026-08-22〜09-04の連続14日分**を実際にダウンロード・展開して集計した（Tradeの持続性分析で使った同じアーカイブサイト・同じ形式のファイル、`app/collectors/eddn_archive.py`の既存パターンで取得可能なことも確認済み）。本番コード・DBには一切書き込んでいない——一時ファイルとして分析後に破棄した。

## 2. 実データ集計結果（14日、37,800メッセージ）

```text
総メッセージ数:                37,800（1日あたり平均2,700件、1,869〜3,681件の範囲）
ユニークシステム数:             3,380
ユニーク(system, body)数:       5,440
ユニークgenus数:                   22
ユニークspecies数:                106
必須フィールド欠損:                 0件（SystemAddress/BodyID/Genus/Species全て100%充足）
ScanTypeの内訳:              Sample=25,000 / Log=12,800 / Analyse=0件
```

**station多様性の問題（Trade/Marketで一貫して発生していた制約）が、Bioでは今のところ再現していない。** 3,380システム・5,440天体という広がりは、Tradeで問題になった「実質2 station」とは対照的に、地理的にも母集団的にも分散している——これはEDDNへのアップロードがプレイヤーの実プレイ全体から集まる母集団であり、EDpj自身が特定stationへのDockingを起点にデータを集めていたMarket/Tradeの収集構造とは根本的に異なるため。

## 3. データ品質

```text
重複キー((system,body,species,timestamp)完全一致):  186キー / 37,614ユニークキー中（約0.5%）
重複の影響を受けるメッセージ数:                        372件（全体の約1%）
1天体あたり複数speciesが報告されているケース:          2,931 / 5,440天体（53.9%）
同一天体が複数日にまたがって観測されているケース:        286 / 5,440天体（5.3%）
```

- **重複排除は必要だが、重複率は低く（約1%）、`(system, body, species, timestamp)`の完全一致キーで十分実用的に除去できる**——`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §4.2の`BioObservation`正規化で対応可能な範囲。
- **1天体に複数speciesが報告されるのはむしろ正常**（ゲームメカニクス上、1つのbiological signal天体には通常複数種が生息する）——`P(species | body)`が単一の答えを持たない分布であることの裏付け。
- **同一天体の複数日観測は5.3%と少ない**——ただしこれはBioにとって問題ではない。Tradeの持続性分析とは違い、**天体上のspecies構成はゲームメカニクス上ほぼ静的（時間で変化しない）**ため、「時間経過で価格が変わるか」のような繰り返し観測は本質的に不要——1天体につき1回でも観測があれば「その天体にそのspeciesが存在する」という事実として使える。

## 4. サンプルメッセージ（実データ、フィールド確認用）

```json
{
  "message": {
    "BodyID": 56, "BodyName": "Eorgh Prou DU-Z d425 4 d",
    "Genus": "$Codex_Ent_Fonticulus_Genus_Name;",
    "Species": "$Codex_Ent_Fonticulus_02_Name;",
    "Variant": "$Codex_Ent_Fonticulus_02_G_Name;",
    "ScanType": "Log", "SystemAddress": 14611201790219,
    "StarSystem": "Eorgh Prou DU-Z d425", "StarPos": [...],
    "Latitude": -13.29, "Longitude": -176.35, "timestamp": "2026-08-22T00:03:56Z"
  }
}
```

`Genus`/`Species`に加えて**`Variant`（色/亜種）も判明する**——前回のFeasibility調査時には確認していなかった追加情報。`Value`（種の売却額）はこのスキーマには含まれない——`SpeciesValueMaster`（Tier 3、Canonn等の外部静的表）を別途用意する必要があることが実データでも確認された。

## 5. 結論: scanorganic/1アーカイブの取得可能性

**アーカイブデータの量・多様性・品質は良好であり、`BioObservation`の母集団データソースとして十分実用的である。** Trade/Marketで最終的にネックとなった「station多様性の欠如」に相当する問題は、現時点の14日サンプルでは見られない。

**ただし、これだけでは species prediction のbacktest（`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §6.1）に着手できない。** `P(species | body_conditions, signals, region, ...)`を検証するには、`scanorganic/1`が持たない**天体の物理パラメータ（温度・重力・大気組成・火山活動・恒星クラス等）を別のデータソースと突き合わせる必要がある**——`scanorganic/1`はGenus/Species/Variantと位置情報のみを持ち、その天体がなぜそのspeciesを持つのか（＝予測の入力になる条件）は一切含まれていない。これは仕様§4.3の`BioPrediction`層がそもそも依存する入力データであり、今回の調査範囲外——次の投資判断が必要な、独立した調査項目として残る。

同様に、`SpeciesValueMaster`（Tier 3、複数ソースでの照合）もまだ未着手——`scanorganic/1`単体では固定種価値を一切検証できない。

## 6. 次に必要な調査（本書はここで止める、実装はまだ判断しない）

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の順序に従うなら、次は:

1. **天体物理パラメータの取得可能性調査**——`Journal.Scan`アーカイブ（EDDN `journal/1`の一部、または専用スキーマがあるか要確認)、あるいはSpansh/EDSMのbody data APIで、`scanorganic/1`が報告した5,440天体のうちどれだけ物理パラメータを突き合わせられるか。これが無ければspecies predictionのbacktestは原理的に着手できない。
2. **SpeciesValueMasterの複数ソース照合**——Canonn Biosheet/Bioforge等、公開されているspecies→base value表を実際に取得し、独立した2系統以上で一致を確認できるか。
3. 上記2つが揃って初めて、§6.1/§6.2のbacktest実装に着手できる。

**現時点の結論**: scanorganic/1のデータ可用性という1点に限れば「有用」——ただしBio Value Model全体の実用性判定（60% accuracy gate）には、まだ2つの独立した調査（天体パラメータ、species value master）が残っており、`INSUFFICIENT_DATA`か`PASS`かを判定できる段階には至っていない。
