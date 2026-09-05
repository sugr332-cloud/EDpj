# EDpj Absolute Formula Validation Gate

**Version:** 0.1  
**Status:** Binding Product Requirement  
**Date:** 2026-09-05

## 0. 絶対要件

EDpjの **Transport/Trade** および **Exobiology/Bio** の価値・利益計算式は、歴史データによる実証を通過するまで確定式・本番採用式として扱ってはならない。

**絶対条件:**

> まず現行の計算式を歴史データに対して再生し、実績値と比較する。精度が60%未満なら、計算式またはそのパラメータを修正して再評価する。60%以上を満たすまで本番採用してはならない。

新しい予測モデルを先に作って現行式の検証を飛ばしてはならない。

## 1. 適用範囲

### 1.1 Transport / Trade

最低限、以下の計算結果を歴史データ上で検証する。

- 1 tripあたり expected profit
- cargo capacityを考慮した expected trip profit
- route/tripの expected profit per hour
- 必要に応じて round-trip の expected value

実績は、利用可能なJournal/Market/売却等の履歴から再構成する。再構成不能なケースは推測で補完せず `INSUFFICIENT` とする。

### 1.2 Bio / Exobiology

最低限、以下の計算結果を歴史データ上で検証する。

- body/species候補の expected bio value
- sample/scan action単位の expected value
- 必要に応じて value per hour

`scanorganic/1` 等の他プレイヤー観測は候補species・発見実績の補助データとして使用できるが、本人の実績と混同しない。

## 2. 精度の定義

本要件における「計算精度60%以上」は、**実績値に対する相対誤差のhit-rate**として固定する。

各評価ケース `i` について:

```text
relative_error_i
  = abs(predicted_value_i - actual_value_i)
    / max(abs(actual_value_i), epsilon)
```

```text
accuracy_hit_i = 1  if relative_error_i <= 0.40
                 0  otherwise
```

データセット全体の計算精度:

```text
formula_accuracy
  = sum(accuracy_hit_i) / N
```

**PASS条件:**

```text
formula_accuracy >= 0.60
```

つまり、評価ケースの60%以上で、計算値が実績値の **±40%以内** に入ることを要求する。

`actual_value = 0` のケースは相対誤差を定義できないため、別途ゼロ値分類指標として保存し、通常のaccuracy分母 `N` から除外する。ゼロ値ケースが大量に存在して実質的に評価不能となる場合は `INSUFFICIENT` とする。

## 3. Historical Replay規則

評価は必ず時系列Replayで行う。

```text
T0
 ↓
observed_at <= T0 のデータだけで計算
 ↓
現行Formulaで predicted_value を算出
 ↓
T0より後の実績を actual_value として取得
 ↓
relative_error / formula_accuracy を計算
```

**未来情報リークは禁止。** `received_at` をゲーム内観測境界の代用にしてはならない。

同一評価ケースの未来データを、候補生成・価格取得・species value選択・パラメータ選択へ混入させてはならない。

## 4. 現行式を最初に評価する

評価順序は固定する。

1. 現行Formulaをそのまま評価
2. `formula_accuracy` を算出
3. 60%以上ならPASS候補
4. 60%未満なら原因を特定
5. Formula / parameterを修正
6. 同じ評価手順で再評価
7. 60%以上になるまで反復
8. 最後に未使用のholdout期間で再検証

現行式を評価せず、最初から新Formulaへ置換することは禁止する。

## 5. 過学習防止

60%達成だけを目的に評価期間へ合わせ込んではならない。

最低限:

```text
historical data
    ↓ chronological split
FIT / FORMULA DEVELOPMENT
    ↓
VALIDATION
    ↓
HOLDOUT (final)
```

- holdout期間はFormula変更・閾値選択に使用しない
- random splitは禁止。時系列順を維持する
- 複数候補式を比較した場合も、最終採用判断はholdoutで行う
- holdoutが不足する場合はPASSではなく `INSUFFICIENT`

## 6. データ不足の扱い

以下を厳守する。

- データが足りない場合は `INSUFFICIENT`
- 最低観測数を不自然に下げてPASSを作らない
- 未観測値を推測値で実績値として扱わない
- 同じ観測を重複カウントしない
- 将来データをT0入力へ混入させない

最低評価件数は対象Formulaごとに実データの分布を確認してからPhase実装仕様で固定する。最低件数未満は60%未満ではなく `INSUFFICIENT` とする。

## 7. Transport/Tradeのスコープ変更

現行 `SPECIFICATION` の「汎用A→B交易ルート検索を作らない」は、本要件と衝突するため、Transport/Tradeを正式対象へ追加するPhaseで明示的に改訂する。

Transport/Tradeを実装する前に、以下を仕様化すること。

- source station
- destination station
- commodity
- buy price / sell price
- supply / demand
- cargo capacity / load quantity
- jump count / route
- supercruise / dock / undock
- one-way / round-trip
- market freshness
- actual realized profit

**この要件文だけを理由にTransport/Trade実装を開始してはならない。** 先にFormula Validation用の履歴データセットと評価仕様を確立する。

## 8. Bio外部データの扱い

Feasibility調査で確認済みの以下を前提としてよい。

- EDDN `scanorganic/1` はGenus/Speciesを含む実ライブスキーマである
- `edgalaxydata.space` のJournal.ScanOrganic日次アーカイブを利用できる
- EDpj既存の `app/collectors/eddn_archive.py` のbz2ストリーミング＋日次取得パターンを再利用する
- Canonn等の公開species valueデータは静的参照データ候補として調査する
- `saasignalsfound/1` は存在しないため、購読対象・設計・ロードマップに記載してはならない
- EDMC-BioScanは参考資料としてのみ扱い、GPLコードをコピーしない

## 9. 既存Phase 2-6との関係

Phase 2-6のHistorical Replay、Future Leakage Prevention、Volatility/Freshness評価は本要件の基盤として継続利用する。

ただし、Phase 2-6の既存目的に「現行のValue/利益計算式そのものを60%以上の精度で実証する」という絶対ゲートが明示されていなかったため、本書で独立したBinding Requirementとして追加する。

## 10. Acceptance

Transport/TradeおよびBioのFormulaを本番採用するためには、少なくとも以下を満たすこと。

```text
[PASS]
- 現行Formulaのhistorical evaluationを実施済み
- leakage regression test PASS
- formula_accuracy >= 0.60
- holdout evaluation >= 0.60
- 評価件数が事前定義したminimumを満たす
- 結果と使用データ期間・件数・式revisionを保存

[INSUFFICIENT]
- historical data不足
- holdout不足
- actual value再構成不能
- leakage-free評価不能

[FAIL]
- minimum dataを満たすがformula_accuracy < 0.60
- holdout < 0.60
```

`FAIL` の場合はFormulaを修正して再評価する。`INSUFFICIENT` はPASSへ読み替えない。
