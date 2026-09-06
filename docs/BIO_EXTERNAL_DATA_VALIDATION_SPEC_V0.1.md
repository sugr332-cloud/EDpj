# EDpj Bio External Data Validation Specification

**Version:** 0.1  
**Status:** Normative / Canonical  
**Date:** 2026-09-05  
**Scope:** Exobiology value calculation and species prediction validation

## 1. Purpose

Bioの価値計算・種予測を実装する前に、**外部・全体母集団データを用いて式の妥当性を検証する**ことを必須とする。

本仕様は、Bioの固定種価値そのものと、body上にどのspeciesが存在するかを推定する予測モデルを明確に分離する。

## 2. 絶対要件

### 2.1 外部・全体データによる検証を必須とする

Bioの式・モデルの統計的な正しさを評価する際、ユーザー本人のJournalデータだけを母集団として使用してはならない。

必ず以下のような**外部・全体母集団データ**を使用する。

- EDDN `scanorganic/1` の履歴アーカイブ
- 必要に応じてCanonn等の公開Bioデータ
- 種の固定価値については複数の独立した公開ソースでクロスチェックした静的マスタ

ユーザー本人のJournalは以下に限定して使用する。

- 個人状態の判定
- 個人向けキャリブレーション
- E2E動作確認
- 実売却額（`SellOrganicData`）との個人データ照合

**本人Journalを外部母集団の統計ベンチマーク、formula accuracyの母集団、species occurrenceの全体分布推定に使用してはならない。**

### 2.2 60% accuracy gate

Bioの価値計算式またはspecies prediction modelを本番採用する前に、外部・全体データによる検証を実施する。

最低基準は **accuracy >= 60%** とする。

60%未満の場合:

1. 式・モデルを採用確定してはならない。
2. 誤差要因を分類する。
3. 係数・条件・確率モデルを再調整する。
4. 再評価し、60%以上を確認する。

十分な外部データが存在しない場合は `INSUFFICIENT_DATA` とし、60%達成扱いにしてはならない。

## 3. データソースの信頼順位

### 3.1 Tier 1 — ゲーム由来の観測

最優先する。

- `Journal.ScanOrganic`
- `Journal.SellOrganicData`
- EDDN `scanorganic/1` の履歴アーカイブ

`ScanOrganic` は実際のプレイヤー観測であり、species / genus / variant / system / body等を持つ。EDDNは公式サービスではなく共有データネットワークであるため、母集団バイアスや未送信データの欠落を明示する。

### 3.2 Tier 2 — 独立したコミュニティ公開データ

Canonn Biosheet / Bioforge等を使用できる。

ただし、これらはゲーム内部の公式DBではないため、**species occurrence / 生息条件 / 出現確率の根拠データ**として利用し、無条件にground truthとはみなさない。

### 3.3 Tier 3 — 静的な種価値表

Species → base payoutについて、複数の独立した公開ソースで一致を確認した値を静的マスタ候補として使用する。

固定種価値は市場価格のように時系列で変動する値ではないため、Bioにおいて比較的信頼性が高い。

ただし、採用時には出典・取得日・ゲームバージョンを記録し、将来の仕様変更に備えてversioned masterとする。

### 3.4 Tier 4 — 予測ツール

EDMC-BioScan、BioInsights、その他のspecies prediction toolは**参考モデル**として扱う。

これらの予測結果をground truthとして採用してはならない。可能な限りEDDN `ScanOrganic` の実観測と比較して精度を検証する。

### 3.5 EDSM

EDSMはsystem/body identity、座標、天体メタデータ等の補助情報に使用する。

EDSMをspecies payoutのground truthとして使用してはならない。

## 4. Bio価値モデルの分離

Bio value calculationは最低でも以下の3層に分離する。

### 4.1 SpeciesValueMaster

```text
species -> fixed base value
```

ここでは固定種価値の正確性を管理する。

### 4.2 BioObservation

外部母集団の実観測。

```text
system + body + genus + species + variant + observed_at + source
```

主データソースはEDDN `scanorganic/1` アーカイブとする。

### 4.3 BioPrediction

未スキャンbodyについて、body conditions等から存在speciesを推定する。

```text
P(species | body_conditions, signals, region, known_observations, ...)
```

ここがBio Value Model V1の主要な不確実性である。

**固定種価値の誤差とspecies predictionの誤差を混同してはならない。**

## 5. 正式な期待値式

既存仕様のsource-of-truthを維持する。

```text
expected_value_base = Σ p(s) × base_value(s)
```

First Discovery等の倍率を考慮した参考値は別系統で保持する。

```text
expected_value_best = Σ p(s) × base_value(s) × fd_multiplier
```

`p(s)` の正しさは外部観測で検証する。`base_value(s)` の正しさは複数の独立ソースで照合し、可能なら実際の`SellOrganicData`でspot-checkする。

## 6. 検証方法

### 6.1 Species prediction validation

EDDN `scanorganic/1` の過去観測から、body conditions / signal情報だけを使って予測可能な時点を構成し、後続の実観測speciesと照合する。

最低限、以下を記録する。

- prediction時点
- body/system identifier
- 入力されたbody conditions
- biological signal count/type
- predicted species set
- 実観測species set
- top-1 accuracy
- top-k hit rate
- coverage
- insufficient-data率

### 6.2 Value formula validation

実観測speciesをground truthとして、formulaが算出した期待値と実際のspecies価値を比較する。

評価はユーザー本人のJournalだけで完結させてはならない。

### 6.3 Personal E2E validation

ユーザー本人のJournal / `SellOrganicData`は、外部母集団評価とは別のE2Eテストとして使用する。

この結果はpopulation accuracyに混ぜない。

## 7. データ不足時の扱い

以下を明確に区別する。

- `PASS`: 外部母集団でaccuracy >= 60%
- `FAIL`: 十分な外部母集団がありaccuracy < 60%
- `INSUFFICIENT_DATA`: 検証対象数・coverage等が不足

`INSUFFICIENT_DATA`を`PASS`へ読み替えてはならない。

本人JournalにScanOrganic / SellOrganicDataが存在しないことだけを理由に、外部検証を中止してはならない。

## 8. 禁止事項

- ユーザー本人の少数Journalを母集団統計として使用すること
- 1サイトだけをground truthとして扱うこと
- EDMC-BioScan / BioInsights等の予測結果を実測ground truthとして扱うこと
- EDSMをspecies payoutのground truthとして扱うこと
- `saasignalsfound/1` が存在すると仮定して実装すること
- 外部データ不足を推測値で埋めてaccuracy達成とみなすこと
- 60%未満の式を「暫定的に本番採用」すること

## 9. Phase / Implementation requirement

Bio Value Model V1の実装フェーズは、まず外部データ取得・検証基盤を完成させる。

順序は以下とする。

1. EDDN `scanorganic/1` archive ingestion
2. BioObservationの正規化・重複排除
3. SpeciesValueMasterの複数ソース照合
4. 外部母集団でspecies prediction / value formulaをbacktest
5. accuracy >= 60%になるまで式・確率モデルを調整
6. 60% gateを通過した後に本番Value Calculationへ接続
7. 最後に本人JournalでE2E / personal calibrationを確認

## 10. Claude/AI implementation instruction

Bio関連の実装・分析を開始する前に、**必ず最新のEDpj仕様書と現在のPhase文書を読み直すこと。過去の会話、記憶、要約だけを根拠に作業を開始してはならない。**

特に以下を毎回確認すること。

- 外部・全体データと本人Journalデータの分離
- 60% accuracy gate
- EDDN `scanorganic/1`を主要な外部実観測ソースとすること
- Species fixed valueとspecies predictionを分離すること
- データ不足時は`INSUFFICIENT_DATA`とすること
- 仕様に存在しないEDDN schemaを仮定しないこと

仕様に未記載の挙動を独自判断で追加してはならない。必要なら先に仕様変更を行う。

## 11. Acceptance criteria

- [ ] 外部・全体母集団と本人Journalがコード・評価レポート上で分離されている
- [ ] EDDN `scanorganic/1` archiveを利用できる
- [ ] SpeciesValueMasterの出典が2系統以上で記録されている
- [ ] species predictionのbacktestが実装されている
- [ ] value formulaのbacktestが実装されている
- [ ] accuracy >= 60%を外部母集団で確認している
- [ ] 不足時に`INSUFFICIENT_DATA`となる
- [ ] 本人Journalはpopulation benchmarkに混入しない
- [ ] `saasignalsfound/1`等の未確認schemaを使用していない
- [ ] 60% gate通過前にproduction value calculationへ接続していない

## 12. Change history

- 2026-09-05: v0.1 — Bio external/global data validation, 60% accuracy gate, source reliability hierarchy, personal-data separationを正式化。
