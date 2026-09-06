# EDpj Bio Species Prediction / Value Formula Backtest — Design Baseline

**Version:** 0.1
**Status:** §2〜§4実装済み・実データでbacktest実行済み。**Baseline 1（k近傍）が60% gateをPASS（実測top-1 accuracy 73.9%/74.3%、2つの独立サンプルで再現確認）**——§4.6参照。§5（value formula backtest）は未着手。
**Date:** 2026-09-06
**Depends on:** `docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md`（binding）, `docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`, `docs/BIO_BODY_PARAMETER_JOIN_INVESTIGATION_V0.1.md`, `docs/BIO_SPECIES_VALUE_MASTER_CROSS_REFERENCE_INVESTIGATION_V0.1.md`

## 0. 位置づけ

3件の調査（scanorganic/1可用性・EDSM天体パラメータ突合・SpeciesValueMaster照合）が全て良好という結果を受け、`docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md` §9のステップ③「外部母集団でspecies prediction / value formulaをbacktest」に進む。**本人Journalは一切使用しない**（§2.1）。

## 1. 全体設計: 3層分離（仕様§4をそのままコード化）

```text
SpeciesValueMaster   species -> fixed base value（静的、複数ソース照合済み）
BioObservation       外部母集団の実観測（system+body+genus+species+variant+observed_at+source）
BioPrediction        P(species | body_conditions, ...) -- 未スキャンbodyのspecies推定
```

固定種価値の誤差とspecies predictionの誤差を混同しない（仕様§4.3）。

## 2. `BioObservation`: 取り込み・重複排除

### 2.1 データモデル

`app/db/models/eddn.py`に追加（既存`BodyBioSignal`と同じEDDN由来テーブル群）:

```python
class BioObservation(Base):
    __tablename__ = "bio_observations"
    __table_args__ = (UniqueConstraint("system_address", "body_id", "species", name="uq_bio_observation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_id: Mapped[int] = mapped_column(Integer, nullable=False)
    star_system: Mapped[str] = mapped_column(String, nullable=False)
    genus: Mapped[str] = mapped_column(String, nullable=False, index=True)
    species: Mapped[str] = mapped_column(String, nullable=False, index=True)
    variant: Mapped[str | None] = mapped_column(String, nullable=True)
    star_pos_x: Mapped[float] = mapped_column(Float, nullable=False)
    star_pos_y: Mapped[float] = mapped_column(Float, nullable=False)
    star_pos_z: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="scanorganic_archive")
```

**一意制約は`(system_address, body_id, species)`**——同じbodyに同じspeciesが複数回報告されても1レコードに集約する（species構成はゲームメカニクス上ほぼ静的な事実であり、`docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md` §3で確認済みの「同一天体・複数species」は正常、「同一(天体,species)の重複報告」だけを排除する）。

### 2.2 重複時は「最も古い観測を残す」

新しい取り込みが既存行より`observed_at`が古い場合のみ更新する（既存の`upsert_if_newer`とは逆方向——`app/db/upsert.py`に`upsert_if_older`を追加する）。理由: 後続の§4のchronological backtestで「そのbodyのspeciesが最初にいつ判明したか」を正しく境界に使うため、後から来た重複報告でtimestampが上書きされてはならない。

### 2.3 取り込み基盤

`app/collectors/eddn_archive.py`の`iter_commodity_day`のストリーミング・展開ロジックを共通化し（`_iter_archive_day(url, client)`）、`iter_scanorganic_day(date, client)`を追加する——`Journal.ScanOrganic-{date}.jsonl.bz2`という既に確認済みのURL形式（2-6F-T1のTrade調査、Bio調査で実データ確認済み）を使う。

`app/bio/observation_ingestion.py`（新規）: `ensure_bio_days_fetched(session, dates, client)` — `BioObservationFetchLog`（`app/db/models/market.py`の`MarketHistoricalFetchLog`と同型、日付単位で取り込み済みかどうかを記録、station/commodityではなく`date`のみがキー——scanorganic/1はギャラクシー全体が対象で特定targetを問わないため）で日付単位の再取り込みを防ぐ。

**実装中に発見した実バグ（実データで実行して判明、修正済み）**: 1日分の実アーカイブは2,000〜3,700件のメッセージを持つため、1回の`INSERT`に含めると（1行11カラム）SQLiteの1ステートメントあたりのバインド変数上限を超えて`OperationalError: too many SQL variables`が発生した。500件ずつのチャンクに分割してupsertするよう修正した（`_UPSERT_CHUNK_SIZE=500`）——挿入されるデータ自体には影響しない、機械的なバッチング上の修正。

### 2.4 実データ取り込み結果（2026-09-06、`data/edpj.db`、14日分）

```text
取り込み日数:                   14日（2026-08-22〜09-04）
BioObservation総行数:           12,114（重複排除後）
ユニークシステム数:               3,380
ユニーク種数:                     106
ユニーク属数:                     22
```

`docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`の速報値（システム数3,380・種数106・属数22）と完全に一致——調査時点のサンプリングと本実装が同じ母集団を正しく捉えていることの追加確認になった。

## 3. `SpeciesValueMaster`: 独自コンパイル（実装済み）

`docs/BIO_SPECIES_VALUE_MASTER_CROSS_REFERENCE_INVESTIGATION_V0.1.md`で発見した10件の不一致の扱い（人間判断、本書で確定）:

- **Fonticulua Fluctus**: EDMC-BioScan側の値（20,000,000）を採用する。Fandom wiki側の`16,777,215`は`2^24-1`という明確なデータ不具合（第3ソースの独立した裏付けあり）。
- **残り9件（Anemone Croceum、Bacterium Nebulus/Scopulum、Brain Tree×5、Tussock Ventusa）**: 現時点でどちらが正しいか判断する根拠が無いため、**Fandom wiki側の値を暫定採用しつつ、`confidence="disputed"`フラグを立てる**——結果を見てから都合よく選んだわけではなく、調査時点（backtestを実行する前）で確定した方針である。

**実装中に発見した11件目**: `app/bio/species_value_master.py`をコンパイルする過程で、`Concha Biconcavis`も`16,777,215`（同じ`2^24-1`不具合）を持っていることが判明した——調査時点では検出できていなかった。独立した第3ソース（`Fonticulua Segmentatus`/`Tussock Stigmasis`と同じ`19,010,800`を支払うという記述）と、既にテーブル内の2種が実際にその値であることから、`19,010,800`に補正した。**この補正はbacktestを一切実行する前に行った**——結果を見てからの後付けではない。

`app/bio/species_value_master.py`（新規、実装済み）: 静的dict、`SpeciesValueEntry(name, value, confidence)`。EDMC-BioScanのコードは一切転記しない——内部codex名↔表示名の対応関係のみをクロスチェック目的で参照し、値そのものは複数ソース照合の結論として独自に記録した（GPLコードのコピーではなく、事実としての数値の記録）。

実データ（`BioObservation`、106種）に対するカバレッジ: **103/106（97.2%）**。未カバー3種（`$Codex_Ent_Vents_Name;`、`$Codex_Ent_Ingensradices_Unicus_Name;`、`$Codex_Ent_Cone_Name;`）は、今回参照した19属のruleset取得範囲に含まれていない、より新しい/珍しい種と考えられる——正直に未カバーとして扱う（0や推測値で埋めない）。

## 4. Species Prediction Backtest

### 4.1 評価単位とchronological split

Market/Tradeと同じ「時系列で区切る」規律をそのまま適用する。ただしBioの場合、天体のspecies構成は時間で変化しない静的事実なので、「価格が時間で動くか」ではなく「**いつそのbodyが初めて母集団に観測されたか**」を境界にする:

```text
BioObservationの取り込み期間全体
        ↓
observed_atの日付で fit期間 / holdout期間 に分割（時系列、ランダム分割は禁止）
        ↓
fit期間に「初めて観測された」bodyの集合 -- 予測モデルの学習母集団
holdout期間に「初めて観測された」bodyの集合 -- 評価対象（このbody自体の観測はモデルに一切見せない）
```

### 4.2 予測モデル: 最も単純なものから評価する（Mining/Tradeと同じ規律）

新しいモデルを最初から作らず、**まず最も単純なbaseline**を評価してから複雑化する。

**Baseline 0（母集団最頻値）**: body条件を一切見ず、fit期間で最も出現頻度の高いspeciesを常に予測する。実データから見て（`docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md`の実測、最頻種で全体の13%程度）、60%には遠く届かないことが予想される——これは失敗を前提にしたテストではなく、「体条件を使わない予測はどれだけ悪いか」を定量化する、正しい最初のステップである。

**Baseline 1（k近傍、体条件ベース）**: 新しいルールテーブルを独自に作る・EDMC-BioScanの分類ルールを模倣するのではなく、**fit期間の実観測（EDSM天体パラメータ付き）そのものを母集団とした最近傍探索**で予測する——temperature/gravity/atmosphereType/volcanismType/body subTypeを正規化した距離空間で、最も近いk件の観測が持つspeciesの最頻値を予測とする。これは独自にデータから学習する方式であり、GPLライセンスのルールを一切参照しない。

### 4.3 精度指標（仕様§6.1をそのままコード化）

```text
top-1 accuracy   = 予測した1種が実際の観測種と一致した割合
top-k hit rate   = 予測上位k件に実際の種が含まれた割合
coverage         = 予測を試みることができたholdout body数 / holdout body総数
                   （EDSMデータが無い、fit期間に十分な近傍が無い等で予測不能なケースを除く）
insufficient率   = 予測不能だったholdout body数の割合
```

`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md`と同じ60% gate（top-1 accuracyで判定）を適用する。

### 4.4 データリーク禁止

- fit期間のモデルは、holdout期間に**初めて**観測されたbodyの情報を一切参照しない。
- EDSM天体パラメータは静的事実として扱う（`docs/BIO_BODY_PARAMETER_JOIN_INVESTIGATION_V0.1.md`で確認済み、discovery.dateが観測より後になるケースは無かった）が、念のためholdout body自身の`BioObservation`行（species/genus/variant）はモデルの入力から除外する——予測対象の答えを予測の入力に混ぜない。

### 4.5 最低サンプル数

`docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md` §6と同じ規律——「60%達成のために最低サンプル数を不自然に下げない」。具体的な数値は実データの分布を見てから固定する（Mining Formula Validationの`MINIMUM_MINING_SELL_CASES=30`と同じ暫定値の扱い方を踏襲）。

### 4.6 実データ実行結果（2026-09-06、`data/edpj.db`、chronological split: fit ≤ 2026-08-31, holdout > 2026-08-31）

`collect_body_population`で母集団を再構成した結果、5,440天体（fit 4,180 / holdout 1,260）。**データ品質メモ**: 63天体（1.2%）が名目上の取り込み開始日（2026-08-22）より前のfirst_observed_atを持っていた——EDDNのgatewayTimestampとメッセージ自身のtimestampのズレ、または一部アップローダーのクロックスキューによるもので、chronological splitの妥当性を大きく損なう規模ではないため、正直に記録した上でそのまま進めた。

**Baseline 0（母集団最頻値、ネットワーク不要、holdout全1,260天体で実行）**:

```text
top1_accuracy   = 29.2%（368/1260）  → FAIL（60%未達）
topk_hit_rate   = 55.6%（701/1260、top-3）
coverage        = 100%
insufficient    = 0%
```

想定通りFAIL——body条件を一切使わない予測では60%に届かないことを実データで確認した（Mining/Tradeの「まず現行の単純な式を評価する」規律と同じ、失敗を前提にしたテストではなく正しい最初の測定）。

**Baseline 1（k近傍、EDSM body parameters使用、fit/holdoutそれぞれ約300/150システムを実サンプリング）**:

```text
1回目（seed=11）: fit_sample=487体, holdout_sample=231体
  top1_accuracy = 73.9%（170/230）  → PASS
  topk_hit_rate = 90.0%（207/230、top-3）
  coverage      = 99.6%
  insufficient  = 0.4%（EDSM未カバーの1体のみ）

2回目（seed=23、再現性確認のため独立した別サンプルで再実行）: fit_sample=499体, holdout_sample=208体
  top1_accuracy = 74.3%（153/206）  → PASS
  topk_hit_rate = 91.7%（189/206、top-3）
  coverage      = 99.0%
  insufficient  = 1.0%
```

**2つの独立したサンプルで73.9%/74.3%とほぼ同じ結果が再現された**——単発の偶然ではなく安定した結果と判断できる。distance計算は仕様通り「カテゴリカル項目（atmosphere_type/volcanism_type/sub_type）の完全一致を数値的な近さより優先する」設計（`CATEGORICAL_MISMATCH_PENALTY=10.0`、結果を見る前に固定済み）。

**60% gate判定: `species prediction (Baseline 1) = PASS`**。Baseline 0からBaseline 1への改善幅（29.2%→73.9%）は、body条件（重力・表面温度・大気タイプ・火山活動・天体subType）がspecies予測に強く効くという、実データによる直接的な裏付けになった。

**実装中に発見・修正した実バグ**: EDSMの実レスポンスに`"bodyId": null`を持つbody（未解決のstar等）が含まれるケースがあり、当初のコード（`"bodyId" not in body`というキー存在チェックのみ）がこれを見逃し、主キー列にNULLを挿入しようとして`NOT NULL constraint failed`で実行時エラーになった。`body.get("bodyId") is None`という値チェックに修正した——実データを実際に流して初めて発見できたバグ。また、新設した`BodyPhysicalParameters`/`BioObservation`関連モデルを`app/db/models/__init__.py`に登録し忘れており、`init_db()`単体では該当テーブルが作成されない潜在バグも発見・修正した（インポートチェーン経由でたまたま動いていたケースがあったため、テストでは検出されていなかった）。

## 5. Value Formula Backtest（仕様§6.2）

Species predictionのbacktestとは独立に評価する（固定種価値の誤差とspecies predictionの誤差を混同しない、仕様§4.3）。

```text
expected_value_base = Σ p(s) × base_value(s)
```

`p(s)`は§4のprediction backtestが出力する確率分布（k近傍のspecies頻度）、`base_value(s)`は§3のSpeciesValueMaster。実際の観測species（ground truth）の`base_value`と、予測期待値を比較し、Mining/Tradeと同じ`relative_error <= 0.40`のhit-rateで`formula_accuracy`を計算する。

## 6. Acceptance Tests

```text
BioObservationが(system_address, body_id, species)で重複排除される
BioObservationが後から来た重複より古いobserved_atを優先して保持する(upsert_if_older)
ensure_bio_days_fetchedが日付単位で既取り込みをスキップする
Baseline 0(母集団最頻値)が実データでの評価結果を正直に報告する(60%を無理に達成させない)
Baseline 1(k近傍)がholdout bodyの自分自身の観測を予測に混入させない
species predictionのtop-1 accuracyがrelative_error/hit-rateと同じ考え方で計算される
coverage/insufficient率が別々に報告される(insufficientをPASSに読み替えない)
value formula backtestがspecies predictionのbacktestと独立したコードパスで実行される
```

## 7. Exit Criteria

- [x] `BioObservation`モデル・`app/bio/observation_ingestion.py`が実装され、§6を満たす（26テスト、実データ14日分12,114件取り込み確認済み）
- [x] `SpeciesValueMaster`が独自コンパイルされ、§3の方針（11件の不一致の扱い、実装中に1件追加発見）が反映されている（実データカバレッジ97.2%）
- [x] Baseline 0/Baseline 1のspecies prediction backtestが実装され、実データで実行される（§4.6、32テスト）
- [ ] value formula backtestが独立して実装・実行される（未着手、次のステップ）
- [x] 60% gateの判定結果（PASS/FAIL/INSUFFICIENT_DATA）が正直に記録される——**species predictionはBaseline 1でPASS（top-1 73.9%/74.3%、2サンプルで再現）、Baseline 0はFAIL（29.2%）**
- [x] 既存テストスイートに回帰がない（529 → 557テスト全通過）
