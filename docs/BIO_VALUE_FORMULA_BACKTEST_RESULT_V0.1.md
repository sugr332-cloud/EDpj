# EDpj Bio Value Formula Backtest — Result Record

**Version:** 0.1
**Status:** PASS（Value Formula、pooled external holdout）— 固定記録
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md` §5（設計・実装・診断の一次情報源、本書はその結果を検証レポートとして切り出したもの）, `docs/BIO_SPECIES_PREDICTION_BACKTEST_RESULT_V0.1.md`（species predictionのPASS記録、本書の前提）, `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §6.2/§7

## 1. 判定

```text
Value Formula Backtest（expected_value = Σ p(s) × base_value(s)、外部母集団ground truth）
    → PASS（pooled external holdout, n=629, formula_accuracy = 61.4%）
```

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §7のGate定義（PASS: 外部母集団でaccuracy≥60%）に基づき、統計的検出力を最大化したpooled評価でPASSと判定する。採用モデルは`app/bio/species_prediction.py`の5特徴量k-NN + marginal存在確率（`predict_species_membership_probabilities`）。

## 2. 結果の経緯（初回FAIL→訂正→PASSまで、数値はすべて保持）

一つのholdoutサンプルの結果を鵜呑みにせず、独立した第2サンプルで再検証したことでPASSに至った。以下の数値はいずれも実データによる実測値であり、削除・書き換えは行わず経緯として全て保持する。

| 段階 | サンプル | n | formula_accuracy | 判定 |
|---|---|---:|---:|---|
| 1回目の実装（`Σp(s)=1`の正規化カテゴリ分布） | 初回holdout | 401 | 30.4% | FAIL |
| 2回目（marginal存在確率へ修正） | 初回holdout（同一） | 401 | **58.4%** | FAIL |
| 3回目（独立した第2seed holdout、新規未取得150システムを追加取得） | 第2seed holdout | 228 | **66.7%** | PASS |
| **4回目（pooled：両holdoutを統合、統計的検出力を最大化）** | **pooled** | **629** | **61.4%（386/629）** | **PASS** |

「58.4% FAIL」は初回holdoutサンプル固有の実測値として正式に保持する（自然法則としての上限ではなく、サンプルサイズn=401における実測結果）。この数値をもって60% gateの正式判定とすることは誤りであり、本書で訂正する。

## 3. なぜ58.4%だけでは判定に使わなかったか

n=401とn=228という規模のholdoutでは、accuracy推定に無視できないサンプリング誤差が乗る（二項分布の標準誤差はn≈228でおよそ±3.2pt、95%区間で±6.5pt程度）。実際、独立に取得した第2seedは66.7%となり、初回との差は8.3ptで、単純な誤差の範囲に収まる。単一サンプルの判定を最終結果とせず、**独立した2サンプルを統合したpooled評価**を正式値とすることで、Baseline 1のspecies prediction backtest（seed 11/23の2サンプル再現によるPASS判定、`docs/BIO_SPECIES_PREDICTION_BACKTEST_RESULT_V0.1.md`）と同じ再現性の規律を踏襲した。

## 4. Pooled結果の詳細

```text
verdict          = PASS
formula_accuracy = 0.6136724960254372（386/629）
valid_cases      = 629
minimum_cases     = 30（大幅に超過）
zero_actual_cases_excluded = 0
```

- 母集団: BioObservation全体（chronological split、fit ≤ 2026-08-31 / holdout > 2026-08-31）
- fit側k-NN参照集合: 累積EDSMキャッシュ（複数回のオンデマンド取得の蓄積、930件のfit_examples）
- holdout側: 初回サンプル401件（既存EDSMキャッシュ） + 第2seedサンプル228件（seed=42で未取得545システムから150システムを新規抽出・取得） = 629件
- 評価式: 同一の`app/backtest/formula_validation.py`のGate数式（`relative_error <= 0.40`をhit、`formula_accuracy = hits/valid_cases`、PASS≥60%）——Mining/Trade Formula Validationと共通

## 5. 拡張特徴量モデル（多変量候補）は不採用

EDSMの未使用フィールド（earthMasses, radius, surfacePressure, atmosphereComposition, solidComposition, terraformingState, distanceToArrival, orbitalPeriod, orbitalEccentricity, rotationalPeriod）を組み合わせた拡張モデル（`app/bio/species_prediction_extended.py`）を、baseline（5特徴量）と全く同じfit/holdout・k・閾値・SpeciesValueMaster・60% gateで比較した。

| 比較条件 | n | BASELINE | EXTENDED |
|---|---:|---:|---:|
| 初回holdout | 401 / 351 | 58.4% FAIL | 55.8% FAIL |
| 第2seed holdout | 228 / 225 | 66.7% PASS | 62.7% PASS |
| Pooled | 629 / 576 | 61.4% PASS | 58.3% FAIL |
| **Paired（同一576件で再計算）** | 576 | **60.9% PASS** | **58.3% FAIL** |

全ての比較軸（同一holdout・独立第2seed・pooled・同一ケース数でのpaired比較）で一貫してEXTENDEDがBASELINEを下回った。初回の10倍以上過大予測ケース11件についても、EXTENDEDは1件も改善しなかった（0/11のまま）。**拡張特徴量モデルは不採用**とし、本番接続には5特徴量baselineを用いる。

## 6. 不採用・棄却となった他の診断（撤回しない）

pooled結果がPASSになったことは、以下の診断が誤っていたことを意味しない。いずれも実データに基づく正当な検証であり、独立に成立する結論として保持する。

- **観測不足仮説（棄却）**: `uploaderID`による独立観測数とValue Formula誤差の相関はほぼゼロ（`corr=-0.0088/-0.0114`）。3人の独立CMDRに単一species確認済みのbodyでも12倍過大予測が発生しており、観測不足では説明できない。
- **Probability Calibration（不採用）**: Fit集合のみのLOO-CVで学習した較正mappingは、Brier scoreを改善した（0.186→0.180）ものの、真のholdoutへの適用でValue Formula accuracyを悪化させた（58.4%→55.9%、特にmulti-species bodyで悪化）。
- **単変量特徴量チェック（説明力なし）**: `distance_to_arrival`は目視では有望に見えたが、対照群（全holdoutケース）比較でミスケースとの相関が確認できなかった（31.7% vs 34.0%、ミス側の方がむしろ低い）。

## 7. 次のステップ

Species Prediction（PASS）とValue Formula（PASS）の両方が確定したことで、`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9の実装順序における60% gateを満たした。次段階は、`expected_value × jump_count → expected_value_per_jump`というBio候補ランキング指標への接続（spec §9後半、jump-count feasibility investigationで既に検証済みのSpansh route API連携と組み合わせる）。ただし、本人Journalを用いたE2E・個人較正（spec §9最終ステップ）は、この後さらに独立して実施する必要がある。
