# EDpj Phase Plan Amendment — Absolute Formula Validation Gate

**Version:** 0.1  
**Status:** Binding Phase Plan Amendment  
**Date:** 2026-09-05

## 0. Canonical Phase Rule

本書はEDpjのPhase Planに対する拘束力のある改訂である。

**Transport/TradeおよびExobiology/Bioの価値・利益計算式は、歴史データ検証を通過するまで確定・本番採用してはならない。**

現行式を最初に評価し、精度が60%未満なら式またはパラメータを修正して再評価する。最終的にchronological holdoutでも60%以上を満たすことをproduction adoptionの必須条件とする。

## 1. Phase 2 — Mining / Existing Value Formula Validation

Phase 2の既存実装・経験則を確定式として扱う前に、歴史データで検証する。

### 2.x Formula Validation Gate

対象:

- Mining Sell effective price
- Mining Continue expected value
- Mining Start expected value（value calculableになった時点）
- action horizonを含む場合のCr/h計算

手順:

1. 現行Formulaをbaselineとして固定
2. Historical ReplayでT0以前の情報だけから計算
3. T0以後の実績からactual valueを再構成
4. formula_accuracyを算出
5. 60%未満なら原因分析・式修正
6. 同一条件で再評価
7. validationで60%以上を確認
8. holdoutで60%以上を確認
9. production formulaとして採用

Miningの既存effective price補正は経験則であり、公式市場計算式とは扱わない。歴史検証を通過するまで確定式ではない。

## 2. Phase 3 — Bio / Exobiology Formula Validation

Phase 3のBio Value Modelは、実装したこと自体を完了条件としない。

### 2.x External Bio Data Feasibility

`scanorganic/1` および `Journal.ScanOrganic` archiveを用いて、以下を評価する。

- message/day
- unique system/day
- unique (system, body)/day
- Genus/Species coverage
- target-body coverage
- species-value-table JOIN coverage
- observation duplication
- observed_at時系列整合性

既存 `app/collectors/eddn_archive.py` のbz2 streaming + daily archive取得を再利用する。

`saasignalsfound/1` は存在しないため、Phase 3の購読対象・実装・ロードマップから除外する。

### 2.x Current Bio Formula Validation

現行V1:

```text
signal_count × user-calibrated expected value per signal
```

を最初のbaselineとしてHistorical Replayで評価する。

評価で60%未満の場合、species-level実績および静的species valueを利用したFormula等を候補として比較する。ただし新Formulaを作る前にbaseline結果を保存する。

### 2.x Bio Formula Adoption Gate

以下すべてを満たすまでBio Value Formulaを確定しない。

- historical baseline evaluation完了
- formula_accuracy >= 0.60
- chronological validation >= 0.60
- chronological holdout >= 0.60
- minimum data threshold充足
- external data coverageを記録
- leakage regression PASS

## 3. Phase 2-6 — Historical Backtestの位置づけ変更

既存Phase 2-6A〜Eは継続する。

さらに、Phase 2-6はTransport/TradeおよびBio Formula Validationの共通基盤として使用する。

```text
2-6A Historical Replay / Dataset
        ↓
2-6B Volatility evaluation
        ↓
2-6C Freshness evaluation
        ↓
2-6D Recommendation / Ranking diagnostic
        ↓
2-6E Existing model evaluation / adoption decisions
        ↓
2-6F Formula Validation Gate
        ├─ Mining Value Formula
        ├─ Bio Value Formula
        └─ Transport/Trade Value Formula
```

### Phase 2-6F — Formula Validation Gate

**目的:**

「現在実装されている計算式が本当に実績値を説明できるか」を最優先で検証する。

#### 2-6F-1 Baseline

現行Formulaを変更せずに評価する。

#### 2-6F-2 Historical Replay

```text
T0
 ↓
observed_at <= T0 only
 ↓
current formula
 ↓
predicted_value
 ↓
future actual observation
 ↓
actual_value
 ↓
formula_accuracy
```

#### 2-6F-3 Accuracy Gate

```text
relative_error = abs(predicted - actual) / max(abs(actual), epsilon)
hit = relative_error <= 0.40
formula_accuracy = hits / valid_cases
```

**PASS: `formula_accuracy >= 0.60`**

これは「評価ケースの60%以上で、計算値が実績値±40%以内」を意味する。

#### 2-6F-4 Formula Revision

60%未満:

```text
FAIL
 ↓
error analysis
 ↓
formula / parameter revision
 ↓
validation
 ↓
repeat
```

60%未満の式をproductionへ採用してはならない。

#### 2-6F-5 Holdout

Formula変更に使用していない未来期間をholdoutとして固定し、最終式を評価する。

- random split禁止
- chronological split必須
- holdout < 60% → FAIL
- holdout data不足 → INSUFFICIENT

#### 2-6F-6 Insufficient

以下の場合はPASS/FAILを出さず `INSUFFICIENT` とする。

- valid historical cases不足
- actual value再構成不能
- holdout不足
- leakage-free evaluation不能

minimum dataを下げて人工的にPASSを作ってはならない。

## 4. Phase 3 Bio Data Correction

以下を正式訂正する。

### 削除

```text
saasignalsfound/1
```

存在しないschemaとして、仕様・Phase Plan・roadmapから除去する。

### 採用する外部観測

```text
scanorganic/1
Journal.ScanOrganic archive
```

`scanorganic/1`からGenus/Speciesが得られるため、Genus/Species取得のための新規EDDN subscriptionを追加しない。

## 5. Phase 4 — Production Adoption

UI/APIにFormulaを公開する前に、対象Formulaのvalidation statusを確認する。

```text
PROVISIONAL
    ↓ historical validation
VALIDATED >= 60%
    ↓ holdout validation
PRODUCTION
```

`INSUFFICIENT` または `FAIL` のFormulaはProduction Formulaとして表示しない。

## 6. Transport / Trade Phase

現行SPECIFICATIONの「汎用A→B交易ルート検索を作らない」という非目標は、Transport/Tradeを正式対象化するPhaseで改訂する。

Transport/Tradeを実装する際は、Formula Validationを実装より後に置かない。

```text
Transport/Trade scope revision
        ↓
Historical Formula Dataset
        ↓
Current Formula baseline
        ↓
60% validation gate
        ↓
Formula revision if needed
        ↓
Holdout >= 60%
        ↓
Production candidate implementation
```

最低限検証する項目:

- buy price
- sell price
- supply / demand
- cargo capacity / load quantity
- trip profit
- jump count / route
- supercruise
- dock / undock
- one-way / round-trip
- market freshness
- realized actual profit
- profit per hour

## 7. Phase Exit Rule

どのPhaseであっても、対象Value Formulaについて以下を「実装完了」としてはならない。

```text
コードが動く
≠
Formulaが正しい
```

Formulaのproduction adoptionには必ず以下を要求する。

```text
Historical baseline
    ↓
Validation >= 60%
    ↓
Holdout >= 60%
    ↓
Production adoption
```

このGateを満たさない場合、Formulaは `PROVISIONAL` または `INSUFFICIENT` として扱う。
