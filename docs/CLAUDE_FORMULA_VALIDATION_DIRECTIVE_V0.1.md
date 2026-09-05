# Claude Directive — Formula Validation / External Bio Data

**Version:** 0.1  
**Date:** 2026-09-05  
**Authority:** Binding implementation directive for EDpj

## 1. 最優先指示

EDpjでは、**Transport/TradeおよびBioの価値・利益計算式を、歴史データで検証してから採用することを絶対条件とする。**

現行式を最初に評価すること。新しい予測モデルを先に作って現行式の妥当性確認を飛ばしてはならない。

### PASS条件

```text
formula_accuracy >= 0.60
```

accuracyは、各評価ケースについて「実績値に対して±40%以内」をhitとする割合:

```text
relative_error = abs(predicted - actual) / max(abs(actual), epsilon)
hit = relative_error <= 0.40
formula_accuracy = hits / valid_cases
```

minimum data / holdoutを満たさない場合は `INSUFFICIENT` でありPASSではない。

## 2. 実装順序

Claudeは以下の順序を厳守すること。

1. 現行のMining/Bio Value Formulaと関連テストを実コードから確認
2. Historical ReplayでT0以前だけを入力として現行式を評価
3. 実績値と比較し、formula_accuracyを算出
4. 60%未満なら誤差原因を分類
5. Formulaまたはparameterを修正
6. 同じ評価手順で再評価
7. 60%以上になるまで反復
8. chronological holdoutで最終確認
9. PASSした式だけをproduction formulaとして採用
10. 全結果・式revision・データ期間・件数を記録

未来情報リークは禁止。`observed_at <= T0`のみをT0入力に使用する。

## 3. Transport / Trade

現在のEDpjには汎用A→B Trade candidateが正式実装されていない。既存SPECIFICATIONの「汎用A→B交易ルート検索を作らない」と、今回の「Transport/TradeをFormula Validation対象とする」という要求にはスコープ上の衝突がある。

したがって、**いきなり実装しない。**

先に仕様改訂としてTransport/Tradeを正式な対象に追加し、Formula Validationデータセットを設計する。

最低限必要な変数:

- source station / destination station
- commodity
- buy/sell price
- supply/demand
- cargo capacity / load quantity
- jump count / route
- supercruise / dock / undock
- one-way / round-trip
- market freshness
- realized actual profit

## 4. Bio external data — 検証済み事実

以下はFeasibility調査済みとして扱う。

### 4.1 EDDN scanorganic/1

`scanorganic/1` は実在するlive EDDN schema。

Genus / Speciesに加えてStarSystem / StarPos / SystemAddress / BodyID等を取得できる。したがって、**genus/species取得のための新規EDDＮ購読は不要**。

### 4.2 edgalaxydata.space

Journal.ScanOrganicの日次アーカイブが存在する。

2026-09-01〜2026-09-04を実データ確認済み。

- 1日あたり約2,398〜2,687 messages
- 2026-09-04は約370 unique (system, body)
- ScanTypeはSample / Log。Analyseは確認期間で0件
- Genus / SpeciesはLog時点ですでに確定
- SystemAddress / BodyID / StarPosで既存Bio情報とのJOINが可能

したがって、Analyseを待たなくてもLog/Sampleからspeciesを利用できる。

### 4.3 既存archive取得実装

既存 `app/collectors/eddn_archive.py` のbz2ストリーミング＋日次URL取得パターンを再利用する。新しいarchive取得基盤を作らない。

### 4.4 species value

Canonn Research GroupのBiosheet/Bioforge等の公開species-level base value / occurrence dataを静的参照データ候補として調査する。

ライセンスを確認し、許可されないコード・データのコピーをしない。

### 4.5 誤情報の訂正

`saasignalsfound/1` は存在しない。**設計・仕様・ロードマップから完全に削除する。**

EDMC-BioScanは実在するGPL-2.0プロジェクトだが、ロジックをそのままコピーしない。必要なら考え方のみ参考にして独自実装する。

## 5. Bio V1について

現行V1:

```text
signal_count × user-calibrated expected value per signal
```

を最終式とみなしてはならない。

`scanorganic/1`のspecies-level実績を利用できるため、次の候補としてspeciesベースのvalue計算を検証する。

ただし、species-level外部データのcoverageを実データで測定すること。coverage不足を理由なく推測で埋めない。

## 6. Claudeが必ず行う検証

### A. 現行Formula

- 現行コードの式を特定
- 入力変数を列挙
- historical replayを実施
- formula_accuracyを算出
- 60% gate判定

### B. Bio external data

- `Journal.ScanOrganic` archiveを複数日取得
- schema全体を確認
- Genus/Species densityを集計
- unique system/body数を集計
- 対象bodyへのcoverageを測定
- species value tableとのJOIN coverageを測定
- future leakageがないことをテスト

### C. Formula revision

- 変更前Formulaをbaselineとして保存
- 変更理由を記録
- validation期間とholdout期間を分離
- 60%達成後もholdoutで再確認
- holdout < 60%なら採用不可

## 7. 禁止事項

- 未検証の外部データ源を前提に仕様変更しない
- `saasignalsfound/1`を作らない
- 現行Formulaを評価せず新Formulaへ置換しない
- 60%を達成するためにminimum observation数を不自然に下げない
- future dataをT0入力へ混入させない
- EDDN観測を本人の実績と混同しない
- EDMC-BioScanのGPLコードをコピーしない
- insufficientをPASSにしない

## 8. 完了条件

Claudeからの完了報告には必ず以下を含める。

```text
1. 現行Formula
2. historical dataset期間
3. valid cases / insufficient cases
4. baseline formula_accuracy
5. 修正したFormulaと理由（修正した場合）
6. validation formula_accuracy
7. holdout formula_accuracy
8. leakage regression結果
9. Bio external data coverage
10. saasignalsfound/1削除確認
11. tests count / test result
12. commit SHA
```

**「実装した」だけでは完了ではない。60% gateを実データで通過したことまでを完了条件とする。**
