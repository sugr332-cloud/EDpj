# EDpj Phase 2-6 Historical Backtest Design Baseline

**Version:** 0.1
**Status:** Design Baseline（策定中。実装未着手）
**Date:** 2026-09-05
**Depends on:** `SPECIFICATION_V0.4.md` v0.7, `IMPLEMENTATION_SPEC_V0.2.md` v0.5, `docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` §8/§14, `docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §6/§7.2（v0.3, commit `a08d416`）, `docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md`（commit `4b4d782`）, `docs/PHASE_2_5D_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md`（commit `a7bb8fd`）, `app/calibration/metrics.py`（Phase 0-C validation_statusパターン）

## 0. 位置づけ

Phase 2-0〜2-5Dは「モデルを作るフェーズ」だった。Phase 2-6は初めての「モデルを評価するフェーズ」であり、性質が異なる。

これまでのPhase 2-5A/2-5Cで置いた以下の値は、すべて**実データを見る前の暫定値**として明示的にマークされている。

```text
app/market/predictability.py
    MIN_SAMPLES_FOR_CLASSIFICATION = 10
    STABLE_MEDIAN_PRICE_CHANGE     = 0.05
    MODERATE_MEDIAN_PRICE_CHANGE   = 0.15
    DEFAULT_ANALYSIS_WINDOW_DAYS   = 14

app/scoring/confidence.py
    FRESHNESS_FULL_THRESHOLD  = 15分
    FRESHNESS_FLOOR_THRESHOLD = 24時間
    FRESHNESS_FLOOR           = 0.50
```

Phase 2-6の目的は、これらを実データで検証・較正し、暫定値から確定値（または再設計）へ移すことである。

**中心原則:** 実装を先に始めて「実装した閾値に合わせて分析する」という逆転を起こさない。評価方法・データリーク防止・較正手順・Go/No-Go基準を、実データを見る前に本書で固定する。

## 1. Historical Backtestの目的

以下4点を検証する。

1. **Market volatility classificationの妥当性** — `STABLE/MODERATE/VOLATILE/INSUFFICIENT`の閾値が、実際のforecast errorと相関しているか
2. **Freshness curveの妥当性** — 現在の「15分まで1.00 → 24時間で0.50に線形減衰」が、実際の価格予測誤差の増加パターンと整合しているか
3. **将来価格予測モデルの適用可否** — VOLATILE市場で予測を使わない方針が、実際に予測誤差を回避できているか
4. **Recommendationのaccuracy / ranking quality** — 過去のゲーム状態に対してEDpjが推薦した行動が、実際の結果と比べてどの程度妥当だったか

## 2. モデル構築と評価の分離

Phase 2-6を「サブフェーズを増やさず、実装計画書の中で内部的に分ける」形で進める。

```text
Phase 2-6A  データセット構築・Historical Replay基盤
        ↓
Phase 2-6B  Volatility threshold評価
        ↓
Phase 2-6C  Freshness curve評価
        ↓
Phase 2-6D  Recommendation / Ranking E2E評価
        ↓
Phase 2-6E  採用値確定
```

2-6B/2-6C/2-6Dはいずれも2-6Aが作るReplay基盤の上に構築される評価ロジックであり、2-6Aより前に着手しない。2-6Eは2-6B〜Dの結果を受けて閾値を確定するのみで、新たな評価ロジックを持たない。

## 3. Phase 2-6A — Historical Replay基盤

### 3.1 EDDN過去データの扱い

- **既定windowは`DEFAULT_ANALYSIS_WINDOW_DAYS=14`日を基準とする。** ただし14日はPhase 2-5Aで明記済みの通り「運用上の初期値」であり統計的根拠を持たない。2-6Aでは7日/14日/30日の3windowを比較し、どのwindow長がforecast errorと最も強く相関するかを評価する（`app/collectors/eddn_archive.py`のarchive取得コストは§1参照——window日数に比例して線形にコストが増えるため、30日windowの評価は対象commodity/station数を絞って実施する）。
- **archive取得・キャッシュは`app/market/predictability.py`の`MarketHistoricalObservation`/`MarketHistoricalFetchLog`をそのまま再利用する。** 新規のキャッシュ層を作らない——Phase 2-5Aで確立した「実際に問い合わせがあったstation×commodityの、実際に一致した行だけをon-demandでキャッシュする」方針を継続する。
- **`observed_at <= T0`の時点境界を厳密に守る。** T0時点のReplayが使ってよいのは`observed_at <= T0`の行のみ。`received_at`はEDDN配信側のタイムスタンプでありゲーム内の観測時刻ではないため、境界判定には使わない（`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §2.4がすでに`observed_at`と`received_at`の混同を禁止している）。

### 3.2 Historical Replay

```text
T0
 ↓
T0以前のデータ（observed_at <= T0）のみで予測
 ↓
Candidate Generation → Horizon → Value → Confidence → Score → Ranking
 ↓
predicted_action / predicted_value / predicted_horizon
 ↓
T0 + predicted_horizon
 ↓
実際のT1以降の観測値（observed_at > T0）
 ↓
forecast error
```

**未来情報リーク禁止を最重要条件とする。** これは`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §6.2で既に定義済みのReplayフローと同一であり、2-6Aはこれを再定義するのではなく、実装として構築する。

**Exit（Design Exit §13で再掲）:**

- 過去市場データをfixture/実データから再生できる
- `observed_at`順で再現できる
- T0より未来のデータがT0入力へ混入しないことがregression testで保証されている（`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §11の"Future leakage prevention"の実データ版）
- 7日/14日/30日のwindow比較が同一基盤で実行できる

## 4. Phase 2-6B — Volatility threshold評価

現在の`STABLE/MODERATE/VOLATILE/INSUFFICIENT`（`app/market/predictability.py`の`classify()`）を、将来予測誤差との関係から評価する。

### 4.1 手順

1. 2-6Aの基盤で、各`(station_id, commodity_name)`についてT0時点のvolatility classを算出する
2. T0以降の実際の価格変化（`price_change_ratio`と同じ定義）を観測する
3. classごとにforecast error（§8参照）の分布を比較する

### 4.2 評価する仮説

```text
STABLE市場   の forecast error が最も小さい
VOLATILE市場 の forecast error が最も大きい
INSUFFICIENT は判定不能であり「安定」とは主張しない
```

この順序関係が実データで成立するかを検証する。成立しない場合、閾値の再配置（`STABLE_MEDIAN_PRICE_CHANGE`/`MODERATE_MEDIAN_PRICE_CHANGE`の値）で足りるのか、分類ロジック自体の再設計が必要なのかを§9のGo/No-Go基準で判定する。

### 4.3 demand volatilityの扱い

`app/market/predictability.py`の`classify()`は現在price volatilityのみを使い、demand volatilityは診断情報に留めている（Phase 2-5A §7/§10決定3）。2-6Bでは、demand volatilityとforecast errorの相関も独立に測定する。強い相関が確認された場合のみ、分類モデルへの昇格を検討する（Phase 2-5A時点で既に想定されている再評価経路）。

## 5. Phase 2-6C — Freshness curve評価

現在の`app/scoring/confidence.py`のcurve

```text
<15分         1.00
15分〜24時間  1.00 → 0.50（線形）
>=24時間      0.50
```

を実データで検証する。

### 5.1 手順

1. 2-6Aの基盤で、ある観測からage（経過時間）ごとの実際の価格乖離を測定する
2. `_freshness_for_age()`が想定する「ageが増えるほど信頼度が下がる」という単調性が、実際の価格乖離の増加パターンと整合するかを確認する
3. `FRESHNESS_FULL_THRESHOLD`（15分）と`FRESHNESS_FLOOR_THRESHOLD`（24時間）の境界が妥当か、`FRESHNESS_FLOOR`（0.50）という下限値が妥当かを個別に評価する
4. 形状（flat→線形→flat）自体が妥当か、指数減衰など別形状の方が実データに合うかを比較する（現curveは`app/mining/price.py`の`demand_penalty`との一貫性のために選ばれた暫定形状であり、それ自体に統計的根拠はない——`app/scoring/confidence.py`のコメント参照）

### 5.2 評価対象を分離する

`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §7.1がすでに指摘している通り、全sourceへ単一curveを機械的に適用しない方針である。2-6CではMarket observationのfreshnessのみを較正対象とする（Journal-derived stable state / Calibration model / Spansh static dataのfreshnessは別管理であり、本Phaseの対象外——§12参照）。

## 6. Phase 2-6D — Recommendation / Ranking E2E評価

### 6.1 EDDN Replayとの違い

EDDN Replayは「自分がそのActionを実行した利益」を観測できない（`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §6.3）。したがって2-6DはEDDN Replay（2-6B/2-6C、市場予測・分類の妥当性検証）とは独立した評価として扱う。

### 6.2 フロー

```text
Journal
 ↓
EDpj State
 ↓
Candidate
 ↓
Horizon / Value
 ↓
Confidence
 ↓
Recommendation
 ↓
実際の結果（本人のJournalに記録された実績）
```

「過去のゲーム状態から、その時点で何を推薦したか」を再現し、実際に記録されているCredits/Cargo/売却イベントと突き合わせる。

### 6.3 データソース

`[[project_edpj]]`に記録済みの実Journal（`/var/home/hankyuu1/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous/`）を使用する。Phase 0-Cが要求するSC durationサンプル50件のGate（現在28件、`[[project_edpj]]`参照）とは独立した评価であり、2-6Dの着手条件ではない——ただし実プレイデータの絶対量が少ない場合、2-6Dの結果は「参考値」に留め、閾値確定の主根拠にはしない（§9）。

### 6.4 時間評価の位置づけ

`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §6.4の方針を継続する。Action Horizonの時間精度そのものを主目的にせず、「予測したhorizonの後に、実際の価値がどれだけ実現したか」を主要な実用評価とする。

## 7. Non-goals（本Phaseで扱わない再掲・明確化）

`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §12のNon-goalsを継続する。加えて2-6固有のNon-goalsを以下に定める。

- 新しい価格予測モデル（回帰・ML等）の導入 — 2-6は既存の暫定値の較正であり、モデルアーキテクチャの変更ではない
- `score_per_hour`式へのvolatility/freshness補正の追加 — `docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §4の禁止方針は2-6でも維持する。2-6は既存の「モデル適用可否のgate」と「freshness減衰」の閾値較正のみを行う
- Journal-derived state / Calibration model / Spansh static dataのfreshness curve較正 — Market observation freshnessのみが対象（§5.2）
- 他プレイヤー行動の予測モデル化 — `docs/MARKET_PREDICTABILITY_SPEC_V0.1.md` §1の方針を継続

## 8. 評価指標

Phase 2-6B/2-6C/2-6D共通で、少なくとも以下を記録する。

```text
forecast MAE            = median_absolute_error（app/calibration/metrics.pyと同じ定義:
                           abs(predicted - actual) / actual の中央値）
signed error             = median_signed_error（同上、方向バイアス検出用）
ranking correlation      = predicted rank と実際の結果順位の相関（Spearman等）
top-1 recommendation hit rate
                          = predicted_action（1位推薦）が実際にも最良だった比率
score calibration         = predicted score_per_hour と実際のcredits/hourの乖離
confidence calibration    = confidence値が高い候補ほど実際にforecast errorが小さいか
insufficient-data率       = INSUFFICIENT/データ不足で評価不能だった候補の比率
```

`forecast MAE`/`signed error`は`app/calibration/metrics.py`の`median_absolute_error`/`median_signed_error`をそのまま再利用する（同じ指標の二重実装をしない——Phase 0-Cの`validation_status`パターンとの一貫性）。

## 9. Go/No-Go基準

**実データを見る前に、以下を固定する。**

### 9.1 サンプル数の下限

`app/calibration/metrics.py`の`validation_status`パターン（`eval_count > 0`かつ閾値内なら`pass`、閾値外なら`fail`、`eval_count == 0`なら`insufficient`）を踏襲する。2-6B/2-6C/2-6Dのいずれも、評価対象のサンプル数がPhase 2-6A実装時に定める最小件数を下回る場合は`insufficient`とし、閾値変更の根拠にしない。

### 9.2 閾値を変更する条件

- 現行閾値（`STABLE_MEDIAN_PRICE_CHANGE`等、freshness curveのthreshold）での`median_absolute_error`が`app/calibration/metrics.py`の`MAE_THRESHOLD = 0.20`を上回り、かつ再配置後の閾値で`0.20`以下に改善することが確認できた場合、閾値を変更する
- volatility classの順序関係（§4.2）が成立せず、別の閾値配置で順序関係が回復する場合、閾値を変更する

### 9.3 現状維持する条件

- 現行閾値での`median_absolute_error`が既に`MAE_THRESHOLD = 0.20`以下であり、代替閾値を試しても有意な改善が見られない場合、暫定値を確定値へ昇格し、変更しない
- サンプル数が不十分（§9.1）で改善の有無を判定できない場合も現状維持とし、暫定値のまま「引き続き暫定」のステータスを明記する（確定値への昇格はしない）

### 9.4 データ不足時の対応

- 2-6B/2-6C（EDDN Replay）はEDDN archiveの取得量に依存し、原則データ不足になりにくい。データ不足が生じた場合はwindow/対象station×commodity数を拡大して再試行する
- 2-6D（本人Journal E2E）はPhase 0-Cと同じ制約（実プレイ時間に依存）を受ける。サンプル不足の場合、2-6Dの結論は「参考値」に格下げし、確定値の根拠は2-6B/2-6Cのみとする。2-6D独自のGo/No-Go判断は行わない

### 9.5 モデル適用可否gate自体の妥当性

VOLATILE市場で価格予測モデルを不適用とする方針（`docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §5）そのものが実データで裏付けられない場合（つまりVOLATILE判定とforecast errorに相関が見られない場合）、gate自体の設計を見直す。この場合は閾値較正では対応しきれないため、2-6Eでの確定を保留し、別途レビューを行う。

## 10. Phase 2-6E — 採用値確定

2-6B/2-6C/2-6Dの結果を受けて、以下を確定する。

```text
app/market/predictability.py
    MIN_SAMPLES_FOR_CLASSIFICATION
    STABLE_MEDIAN_PRICE_CHANGE
    MODERATE_MEDIAN_PRICE_CHANGE
    DEFAULT_ANALYSIS_WINDOW_DAYS

app/scoring/confidence.py
    FRESHNESS_FULL_THRESHOLD
    FRESHNESS_FLOOR_THRESHOLD
    FRESHNESS_FLOOR
```

新たな評価ロジックは持たない。§9のGo/No-Go基準に従って各定数を「確定値」または「引き続き暫定値」としてコード上のコメントを更新するのみ。

## 11. Acceptance Tests

追加する必須テスト:

```text
Real-data window comparison (7/14/30 days) produces comparable metrics
Future leakage prevention against real EDDN archive data
Volatility class ordering hypothesis evaluation (STABLE < MODERATE < VOLATILE forecast error)
Demand volatility correlation measurement (diagnostic, non-gating)
Freshness curve monotonicity check against real price deviation
Freshness threshold boundary sensitivity (15min / 24h)
Journal-derived E2E replay reproduces historical recommendations deterministically
Recommendation vs actual outcome delta calculation
insufficient-data rate does not silently get treated as a pass
Go/No-Go decision reproducible from recorded metrics (no manual override without logged rationale)
```

## 12. Non-goals（再掲・全体）

- 新しい価格予測モデルの構築
- `score_per_hour`式へのvolatility/freshness補正の追加
- Journal-derived state / Calibration model / Spansh static dataのfreshness curve較正
- 他プレイヤー行動の予測モデル化
- 銀河全体の恒久的な市場DBサービス化
- narration（LLM層）の実装 — `docs/PHASE_2_5D_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md` §6の方針を継続、CLI/API実装時まで先送り

## 13. Design Exit

この設計を実装（Phase 2-6A着手）へ進める条件:

- [ ] モデル構築フェーズ（Phase 2-0〜2-5D）と評価フェーズ（Phase 2-6）を分離する方針が確定している
- [ ] Phase 2-6A〜Eを内部サブフェーズとして扱い、正式Phaseを増やさない方針が確定している
- [ ] `observed_at <= T0`の時点境界と未来情報リーク禁止が明文化されている
- [ ] 7/14/30日のwindow比較を2-6Aで実施する方針が確定している
- [ ] EDDN Replay（2-6B/2-6C）と本人Journal E2E（2-6D）を独立した評価として扱う方針が確定している
- [ ] 評価指標（MAE/signed error/ranking correlation/top-1 hit rate/score calibration/confidence calibration/insufficient-data率）が確定している
- [ ] Go/No-Go基準（閾値変更条件・現状維持条件・データ不足時の対応・モデル適用可否gate自体の妥当性判定）が実データを見る前に確定している
- [ ] `app/calibration/metrics.py`の指標・パターンを再利用し、二重実装しない方針が確定している
- [ ] 較正対象の定数（`predictability.py`のvolatility閾値群、`confidence.py`のfreshness curve群）が明示されている
