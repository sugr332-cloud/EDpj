# EDpj Bio Species Prediction Backtest — Result Record

**Version:** 0.1
**Status:** PASS（species prediction、Baseline 1）— 固定記録
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md`（設計・実装詳細の一次情報源、本書はその結果を検証レポートとして切り出したもの）, `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §6.1/§7

## 1. 判定

```text
species prediction (Baseline 1, k-nearest neighbors over EDSM body parameters)
    → PASS
```

`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §7のGate定義:

```text
PASS            外部母集団で accuracy >= 60%
FAIL            十分な外部母集団があり accuracy < 60%
INSUFFICIENT_DATA  検証対象数・coverage等が不足
```

Baseline 1のtop-1 accuracyは73.9%（seed 11）/74.3%（seed 23）で、いずれも60%を明確に上回る。coverageも99.0%/99.6%と十分であり、`INSUFFICIENT_DATA`には該当しない。**この判定はspecies predictionモデルについてのみ成立する**——固定種価値（`SpeciesValueMaster`）やvalue formula（`Σ p(s) × base_value(s)`）のPASS/FAILとは独立である（仕様§4.3の分離規律）。

## 2. モデル比較

| Model | 対象 | Top-1 | Top-3 | Coverage | Insufficient率 | 判定 |
|---|---|---:|---:|---:|---:|---|
| Baseline 0（母集団最頻値） | holdout全1,260体 | 29.2%（368/1260） | 55.6%（701/1260） | 100% | 0% | FAIL |
| Baseline 1 / seed 11 | holdout_sample 231体 | 73.9%（170/230） | 90.0%（207/230） | 99.6% | 0.4% | **PASS** |
| Baseline 1 / seed 23 | holdout_sample 208体 | 74.3%（153/206） | 91.7%（189/206） | 99.0% | 1.0% | **PASS** |

Baseline 0→Baseline 1で29.2%→約74%への改善は、body条件（重力・表面温度・大気タイプ・火山活動・天体subType）がspecies予測に強く効くことの直接的な実データ裏付けである。

## 3. 再現性（2つの独立サンプルによる検証）

同一モデル・同一chronological splitに対し、EDSM取得対象システムの無作為抽出シードのみを変えて（seed 11 → seed 23）独立に再実行した。

```text
seed 11: top-1 = 73.9%, top-3 = 90.0%, coverage = 99.6%, holdout件数 = 231
seed 23: top-1 = 74.3%, top-3 = 91.7%, coverage = 99.0%, holdout件数 = 208
```

差は1.1ポイント（top-1）に収まり、単一holdoutサンプルの偶然による結果ではないと判断できる。

## 4. Chronological Split条件

```text
母集団: BioObservation全体（5,440天体、系統的な観測期間: 2025-12-27〜2026-09-04、
        うち63天体(1.2%)がnominalな取り込み開始日2026-08-22より前の
        first_observed_atを持つ——EDDN gatewayTimestampとメッセージ自身の
        timestampのズレ、または一部アップローダーのクロックスキュー起因と
        推定。splitの妥当性を大きく損なう規模ではないため許容）

fit期間:      observed_at <= 2026-08-31 23:59:59  → 4,180天体
holdout期間:  observed_at >  2026-08-31 23:59:59  → 1,260天体

実行時のサンプリング（EDSM取得コストを抑えるため、無料サービスへの配慮）:
  fit側:      300システムを無作為抽出（決定論的シード） → 487〜499体がEDSM取得成功
  holdout側:  150システムを無作為抽出（決定論的シード） → 206〜231体がEDSM取得成功
```

**未来リーク禁止の担保**: fit集合はholdout集合の`observed_at`を一切参照しない。個々のholdout bodyの予測時、そのbody自身の`BioObservation`行（実際に観測されたspecies/genus/variant）はk近傍探索の入力に使われない——予測の答えを入力に混入させない（設計ドキュメント§4.4）。

## 5. 使用したEDSM body parameters

```text
gravity                （重力）
surface_temperature     （表面温度）
atmosphere_type         （大気タイプ、カテゴリカル、完全一致を優先）
volcanism_type          （火山活動タイプ、カテゴリカル、完全一致を優先）
sub_type                （天体subType、カテゴリカル、完全一致を優先）
```

距離計算: 数値2項目（gravity/surface_temperature）をfit集合内のmin-maxで正規化しユークリッド距離、カテゴリカル3項目は不一致1件につき`CATEGORICAL_MISMATCH_PENALTY=10.0`を加算（結果を見る前に固定済み、数値距離の理論上限[√2]より十分大きく、カテゴリカル一致を常に優先させる設計）。近傍数`NEIGHBOR_COUNT=5`。

## 6. 実装中に発見・修正したバグ（実データ実行で判明）

1. **EDSM応答の`"bodyId": null`を見逃す不具合**: 未解決のstar等で`bodyId`キー自体は存在するが値が`null`のレコードが実際に存在した。当初のコード（`"bodyId" not in body`というキー存在チェック）はこれを素通りさせ、主キー列にNULLを挿入しようとして`NOT NULL constraint failed`でクラッシュした。`body.get("bodyId") is None`という値チェックに修正。
2. **新設テーブルの`__init__.py`未登録**: `BioObservation`/`BioObservationFetchLog`/`BodyPhysicalParameters`が`app/db/models/__init__.py`の集約importに含まれておらず、単体の`init_db()`呼び出しではテーブルが作成されない潜在バグがあった（別スクリプトのimportチェーン経由でたまたま動いていたため、テストでは検出されなかった）。登録を追加して修正。

いずれもcommit `c43abe8`で修正済み。

## 7. 次のステップ

本書はspecies predictionのPASSのみを確定する。Bio Value Model全体の60% Gate判定には、これとは独立に**value formula backtest**（`docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md` §5、`expected_value_base = Σ p(s) × base_value(s)`を実観測speciesの実際の価値と比較）が必要——次の実装対象。
