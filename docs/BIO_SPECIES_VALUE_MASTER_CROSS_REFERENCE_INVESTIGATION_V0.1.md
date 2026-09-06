# EDpj Bio: SpeciesValueMaster 複数ソース照合調査

**Version:** 0.1
**Status:** Investigation only — コード実装なし。`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の②「SpeciesValueMasterの複数ソース照合」。
**Date:** 2026-09-06
**Depends on:** `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md`（特に§3.3 Tier 3、§8「1サイトだけをground truthとして扱うことの禁止」）、`docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`

## 0. 目的

固定種価値（`base_value(species)`）を、**独立した複数ソースで照合**できるかを実データで検証した。仕様§8が禁止する「1サイトだけをground truthとして扱う」を避けるため、由来の異なる2つの資料を実際に取得し、値の一致率と具体的な不一致を洗い出した。

## 1. 発見した情報源

| ソース | 種別 | 取得方法 |
|---|---|---|
| Elite Dangerous Wiki（Fandom）「Exobiology Sample Values and Details」 | コミュニティ編集wiki、"Vista Genomics redemption values"を出典として明記 | MediaWiki API（`action=parse&prop=wikitext`）で直接取得——通常のHTML取得はCloudflareのbot対策で弾かれたため、API経由に切り替えた |
| EDMC-BioScan（`Silarn/EDMC-BioScan`、GPL-2.0）のruleset内蔵データ | 独立して保守されているツールのソースコード内の静的テーブル、**内部codex名で直接キーされている**（`$Codex_Ent_Stratum_07_Name;`等） | GitHubから19属分のrulesetファイル（`aleoida.py`〜`tussock.py`）を直接取得し、`name`/`value`フィールドを正規表現で抽出 |

**Canonn Biosheet自体は値データを直接持たない**ことも判明した——`canonn.fyi/biosheet`は実際にはGoogle Sheet（属ごとにBioforge/Canonn.Scienceへのリンクを持つポータル）であり、Bioforge（`bioforge.canonn.tech`）は種の出現統計（histogram、`P(species|conditions)`予測用、Tier 2寄り）を提供するAPIであることを確認した——固定価値の直接照合には使えなかった。

**ライセンス上の注意（2026-09-06、レビューで確定した既存方針の再確認）**: EDMC-BioScanはGPL-2.0であり、そのコード・データを直接コピーしてEDpjに組み込むことはできない（`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §8/以前のセッションでの合意通り）。本書では**照合・検証のためだけに数値を読み取り**、EDpj本体への組み込みには使っていない。実際にSpeciesValueMasterを実装する際は、Fandom wiki（コンテンツライセンスはCC-BY-SA系）や、独立に採取した数値から再構築する必要がある。

## 2. 照合結果

### 2.1 名称ベースの突合（属名の語順差を正規化した後）

```text
Fandom wiki掲載種数:                    117
EDMC-BioScanと名称一致:                 106 / 117（90.6%）
   完全一致（値が同じ）:                  96 / 106（90.6%）
   不一致:                               10件
EDMC-BioScanに存在しない種:               11件（Amphora Plant, Bark Mound, Crystalline Shard,
                                              Sinuous Tuber各色等——ダウンロードした19属データセットに
                                              含まれていない属、または新しい種）
```

### 2.2 発見した10件の不一致（生データ、判断は保留）

| 種 | Fandom wiki | EDMC-BioScan | 差 |
|---|---:|---:|---|
| Anemone Croceum | 3,399,800 | 1,499,900 | 約2.27倍 |
| Bacterium Nebulus | 9,116,600 | 5,289,900 | 約1.72倍 |
| Bacterium Scopulum | 8,633,800 | 4,934,500 | 約1.75倍 |
| Brain Tree（5色全て: Aureum/Gypseeum/Lindigoticum/Ostrinum/Puniceum） | 3,565,100 | 1,593,700 | 約2.24倍、**属全体で系統的に同じ比率** |
| Fonticulua Fluctus | 16,777,215 | 20,000,000 | — |
| Tussock Ventusa | 3,277,700 | 3,227,700 | 約1.5%（桁の入れ替わりに見える） |

**Fonticulua Fluctusの`16,777,215`という値は`2^24 - 1`（24bit符号なし整数の最大値）と一致する**——これはゲーム内の実際の価値ではなく、Fandom wiki側の入力・変換過程での不具合（整数オーバーフロー）の可能性が高い。実際、独立した第3のソース（`elitedangerous.net`のフォーラム的ページ、本調査で偶然見つけた別サイト）に「Fonticulua Fluctus which pays 20 million credits」という記述があり、これは**EDMC-BioScan側の2,000万Crと一致**している。この1件については複数ソースでEDMC-BioScan側が支持される。

**Brain Tree属5色全てが同じ約2.24倍の比率で系統的にずれている**のは、単発の入力ミスではなく、**片方のソースがゲームのリバランスパッチ前後どちらかの古い値を保持している**可能性を示唆する——`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §3.3が要求する「出典・取得日・ゲームバージョンの記録」の重要性を裏付ける実例になった。

**これらの不一致をどちらが正しいか、本書では判断しない**——複数ソースでの照合により「一致しない箇所がある」ことを発見するのが本調査の目的であり、どちらを採用するかは実装段階で追加の第3ソース確認（Frontier公式パッチノート、より新しい日付のデータ等）を経て人間が判断すべき事項である。

### 2.3 実データとの突合（最も重要な指標）

`scanorganic/1`アーカイブ実データ（2026-09-04、1日分、78種）に対して、**内部codex名で直接**（名前正規化不要）突合した:

```text
実観測された種コード数:                 78
EDMC-BioScanのvalueテーブルでカバー:     76 / 78（97.4%）
カバーされていない種:                    2件（$Codex_Ent_Cone_Name; ,
                                              $Codex_Ent_Ingensradices_Unicus_Name;）
```

**scanorganic/1が使う内部codex名（`$Codex_Ent_Stratum_07_Name;`等）とEDMC-BioScanのキーが完全に同じ形式であるため、名前のマッピング層が一切不要**——Fandom wiki側（表示名ベース）よりも実装上扱いやすいことが分かった。ただしEDMC-BioScan自体はGPLでありコピー不可のため、**実装時は同じ内部codex名をキーにした独自のSpeciesValueMasterを、複数の一次情報源（Fandom wiki本文、Frontier公式情報、コミュニティ実測値等）から再構築する必要がある**。

## 3. 結論

**SpeciesValueMasterの複数ソース照合は実データで可能であることを確認した。** 2つの独立した資料（Fandom wiki、EDMC-BioScan）を突合した結果、90.6%が名称一致し、その90.6%が値も完全一致——**大半の種価値は複数ソースで裏付けが取れる**。同時に、10件の具体的な不一致（うち1件はwiki側の明確なデータ不具合が疑われ、1件は属全体に及ぶ系統的なバージョン差の可能性）も発見でき、これは仕様§8が求める「1サイトだけをground truthとしない」ことの具体的な価値を実証した。

実観測データとの突合カバレッジも97.4%と高く、**SpeciesValueMasterは実用的な精度でBio Value Modelに接続可能**と判断できる。

## 4. 次のステップ

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の順序に従い、①（scanorganic/1可用性・天体パラメータ突合）②（本書、SpeciesValueMaster照合）が完了したことで、**③ species prediction / value formulaのbacktest実装に着手できる前提条件が揃った**。

実装に進む前に、人間判断が必要な項目:
1. 本書§2.2で見つかった10件の不一致について、どちらの値を採用するか（または第3ソースで再確認するか）
2. SpeciesValueMaster自体をEDpjのどこに、どのライセンスの情報源から独自構築するか（EDMC-BioScanの直接転記は不可）
3. `docs/BIO_JUMP_COUNT_FEASIBILITY_INVESTIGATION_V0.1.md`（並行トラック）の結果と合わせ、`expected_value = Σ p(s) × base_value(s)` → `value_per_jump`という最終形への統合方針
