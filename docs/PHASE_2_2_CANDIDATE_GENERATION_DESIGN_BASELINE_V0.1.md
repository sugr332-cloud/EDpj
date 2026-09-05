# EDpj Phase 2-2 Candidate Generation Design Baseline

**Version:** 0.1
**Status:** Design Fixation (not an implementation phase)
**Date:** 2026-09-05
**Depends on:** `SPECIFICATION_V0.4.md` §6/§7/§8, `IMPLEMENTATION_SPEC_V0.2.md` §8/§10/§11/§21/§22, `docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md`

## 1. Scope / Non-goals

Phase 2-2は「現在状態から、評価する価値がある候補を作る」ところまでを対象とする。

```text
Candidate Generation = 候補を作る
Filter               = 評価対象外を落とす
Horizon              = 所要時間を確定する（Phase 2-1のCalibration Engineを消費する側。本書では作らない）
Value                = 期待価値を計算する（本書では作らない）
Score                = credits/hourで比較する（本書では作らない）
```

**Non-goals（本書・Phase 2-2で行わないこと）:**

- `expected_value`/`score_per_hour`の計算（Value/Score、後続フェーズ）
- Horizon構築そのもの（`build_horizon`は既存のまま、Phase 2-2は「どのsegment_typeを要求するか」だけを候補ごとに宣言する）
- どの候補が儲かるかの判断
- Bio種の期待値計算（`predicted_species`の値は本書では確定しない。§11.1のbase value計算は後続フェーズ）

### 1.1 原則: Candidate GenerationはHorizonの可否で候補を除外しない

**Candidate Generatorは、現在のHorizon構築可否（`horizon_complete`）によって候補そのものを生成しない、という判断をしてはならない。**

```text
正しい流れ:
  Mining Sell → 候補として生成 → Horizon構築 → SC unavailable → IncompleteCandidate

やってはいけない流れ:
  SC unavailable → Mining Sellを候補生成の時点でスキップする
```

候補生成の責務は「この状態でこのActionを評価する価値があるか」の判定のみであり、「所要時間が確定できるか」はHorizon Builder（Phase 0-C/2-1）の責務である。この境界を守ることで、将来SC距離モデルが追加されて`supercruise`が`estimated`に昇格した際、Candidate Generator側を一切変更せずに該当候補が自動的に`IncompleteCandidate`から`Recommendation`候補へ復帰できる（9節参照）。現時点で`required_segments`に`supercruise`を含む4種の候補（`mining_sell`/`mining_start`/`bio_next_system`/`bio_return`）も、生成条件（4節・5節）を満たす限り**必ず生成する**。
- confidence合成方法の実装（Phase 2-0で保留のまま）

## 2. 既知のデータギャップ（正直な棚卸し）

候補生成の条件を設計する前に、**現在の実装で実際に取得可能な事実**を棚卸しする。ここを曖昧にすると仕様と実装が乖離する。

| 必要な事実 | 現状 | 備考 |
|---|---|---|
| `is_ore`（cargo中のどれが鉱石か） | ❌ 未実装 | Phase 0-Aの`CargoState`は`commodity_name`/`quantity`のみ。鉱石判定用の静的リストが存在しない |
| `mining_active`（直近MiningRefined） | ❌ 未実装 | `journal_events`に生データはあるが、クエリするdetectorがない |
| `bodies.rings`（静的ring情報） | ❌ 取得不能 | Phase 1でSpanshのsystem dump APIを検証した結果、`gravity`/`radius`/`atmosphere`/`landable`/`rings`は返らないことを確認済み（`app/collectors/spansh.py`のdocstring参照）。§8.1のフォールバック（直近MiningRefined/位置履歴）が**唯一の経路**になる |
| `has_bio_signals`（本人の現在地天体） | ✅ 部分的 | `BodyBioSignal`（EDDN `fssbodysignals/1`）はあるが、自分のJournalの`FSSBodySignals`も同テーブルに`source='journal'`として入れる経路が未実装（Phase 1はEDDN経路のみ実装） |
| `current_body_scanned_by_user`（本人未スキャン判定） | ❌ 未実装 | `system_discovery`/`body_discovery`テーブル（§21で言及）は未作成。現状「本人が既にスキャン済みか」を判定する手段がない |
| `unsold_bio_value`（未売却organic data） | ❌ 未実装 | `ScanOrganic`/`SellOrganicData`イベントのraw保存はあるが、専用テーブル・detectorがない |
| `predicted_species`（bio種の期待値） | ❌ 未実装 | `organic_species`/`organic_conditions`テーブル（SPECIFICATION §12）は未作成 |
| System間の距離（`distance_limit_ly`探索用） | ✅ 利用可能 | `System.x/y/z`（Spansh、Phase 1実装済み）から直線距離を計算可能 |
| Vista Genomics駅の検索 | ✅ 利用可能 | `Station.has_vista_genomics`（Phase 1実装済み） |
| Mining/Bio候補のsegment所要時間 | ✅ 利用可能 | `estimate_segment`（Phase 2-1） |

**方針**: Phase 2-2は「候補が存在するかどうかの判定に必要なdetectorのうち、未実装のものを新規実装する」フェーズも兼ねる。ただし新規テーブル追加は必要最小限とし、種レベルの期待値計算（`organic_species`等）はPhase 2-2の対象外のまま据え置く（`predicted_species`は空リストで許容する。3節参照）。

## 3. Candidate Generation の入出力

候補生成関数のシグネチャは以下を統一する。

```python
def generate_candidates(state: PlayerStateFacts, session: Session) -> list[DraftCandidate]:
    ...
```

```python
@dataclass
class DraftCandidate:
    action: str                          # "mining_sell" | "mining_continue" | "mining_start" |
                                          # "bio_current_body" | "bio_next_system" | "bio_return"
    target: BioTarget | MiningTarget
    required_segments: list[str]         # build_horizonへ渡すsegment_type一覧（9節）
    generation_confidence: float | None  # 候補生成段階で分かる不確実性（例: ring静的データ不在によるフォールバック使用）
```

`DraftCandidate`には`expected_value`/`score_per_hour`/`confidence`（最終値）を含めない。これらはValue/Score段階が付与する。`generation_confidence`は「この候補の存在自体がどれだけ確からしいか」（例: フォールバック判定を使った）を表し、最終confidenceの一構成要素として後段に渡すだけで、本書では合成しない。

## 4. Mining candidate generation

### 4.1 前提: is_ore判定（新規実装が必要）

静的な鉱石commodity一覧を`app/mining/state.py`に定数として保持する（Elite Dangerousの採掘対象commodity、例: platinum, painite, osmium, palladium, gold, silver, low_temp_diamonds等）。この一覧はSpansh/EDDNから動的取得せず、既知のゲーム内カテゴリとしてハードコードする（ゲームバランス値ではなく分類情報なので、§26「推定値を推定で埋めない」には抵触しない）。

```python
has_mining_cargo = any(row.commodity_name in MINABLE_COMMODITIES and row.quantity > 0 for row in cargo_state)
```

### 4.2 mining_active detector（新規実装が必要）

```python
def detect_mining_active(session: Session, lookback: timedelta = timedelta(minutes=15)) -> MiningContext:
    recent_refined = 直近lookback以内のMiningRefinedイベントがjournal_eventsにあるか
    last_ring_location = 直近のMiningRefined、なければ直近のring body上と推定できるLocation/ApproachBody
    return MiningContext(has_mining_cargo=..., mining_active=recent_refined, last_ring_body_id=last_ring_location)
```

`bodies.rings`が使えないため（2節）、「known ring」判定は行わず、`last_ring_body_id`は常に「直近の採掘関連イベントから逆算した天体」とする。

### 4.3 各候補の生成条件

```text
mining_sell:
  条件: has_mining_cargo == true
  target候補: 保有commodityを売却可能なmarket（market_latestにdemand > 0で存在する駅）
  除外しない条件: mining_active == false でも生成する（§16回帰要件: mining_sellはmining_activeを必須としない）

mining_continue:
  条件: mining_active == true
  target: 現在の採掘コンテキスト（現在地そのもの、targetは天体識別情報のみ）

mining_start:
  条件: has_mining_cargo == false
  target候補: 5節参照
```

`mining_sell`のtarget（販売駅）選定: 保有する各commodityについて`market_latest`をfreshness降順→demand降順で検索し、demand<=0の駅は候補から除外（§10.1「需要0以下は候補除外」）。複数commodityを保有する場合、**同一駅で最も多くのcommodityを売却できる駅を優先**する（駅ごとの候補をまとめる。7節）。

### 4.4 Mining Start：候補ring探索方法（本書の中核）

`bodies.rings`が使えない制約下で、以下の優先順位を採用する。

```text
優先度1: 本人の過去実績（MiningRefinedイベントの発生天体）
  → 実際に採掘したことのある天体を「既知のring」として再利用する
  → 直近の採掘実績が最も多い天体を優先

優先度2: Body.body_type/sub_typeから「リングを持ちうる」天体を推測 [confidence低]
  → Spansh dumpのbody typeから恒星の周回天体を絞り込むことはできるが、
    「実際にminableなringが存在するか」は確認できない
  → generation_confidenceを明示的に下げて候補化する（除外はしない）
  → §10.4「ライブyieldをSpansh static dataだけから推定したことにはしない」との整合:
    ring**候補**として提示するのは許容されるが、期待採掘量（yield）はこの情報から計算しない
    （yield計算はValue段階の話であり、Spansh dataから直接値を作らないという制約は維持される）

優先度1が0件の場合、優先度2のみで候補化し、generation_confidenceを最低水準にする。
優先度1・2ともに0件の場合、mining_startは候補を生成しない（IncompleteCandidateにもしない —
これは「horizon不明」ではなく「候補自体が存在しない」ケースであり、5節のフィルタ以前の話）。
```

## 5. Bio candidate generation

### 5.1 bio_current_body

```text
条件: 現在地天体に has_bio_signals == true （BodyBioSignal, EDDN fssbodysignals/1由来）
target: 現在天体そのもの
```

2節の通り、自分のJournal由来のFSSBodySignalsは未統合のため、**現在天体がEDDNで一度も観測されたことがない場合、実際にbio signalがあっても検出できない**。これは既知の制約として明記し、Phase 2-2では解消しない（Phase 1側の追加実装が必要）。

### 5.2 bio_next_system：候補探索方法（本書の中核）

```text
1. 現在地systemの座標（System.x/y/z）を取得
2. distance_limit_ly以内のSystemをローカルDBから検索（直線距離、jump距離ではない）
3. 各候補systemについてBodyBioSignalを検索し、bio signalが存在するbodyを抽出
4. 「本人未スキャン」判定 → 2節の通り検出手段がないため、Phase 2-2では暫定的に
   「除外しない（＝常に未スキャン扱い）」とし、generation_confidenceを下げる
   （本人未スキャンをFalseとして断定的に除外するより、
    未確認のまま候補化してconfidenceで表現する方が安全 — §26「取得できないデータを
    推定で埋めない」の精神に沿い、「未スキャンと断定」も「スキャン済みと断定」もしない）
5. First Discovery upsideは計算しない（§11.1のbest valueはValue段階、本書は候補存在のみ）
```

**重要な制約**: 3節の通り、ローカルDBに存在するSystemは「過去にSpansh解決した/EDDNで観測した」ものだけであり、銀河全体ではない。`distance_limit_ly`以内であっても、ローカルにキャッシュされていないsystemは候補に現れない。これはPhase 1で確立した「オンデマンド・非一括インポート」方針の直接的な帰結であり、Phase 2-2では解消しない（探索範囲が徐々にしか広がらないことを許容する）。

### 5.3 bio_return

```text
条件: unsold_bio_value > 0 （2節の通り未実装 — 新規に app/bio/conditions.py 等でdetector実装が必要）
target: nearest Vista Genomics（Station.has_vista_genomicsで検索、直線距離最小）
```

`unsold_bio_value`検出のための最小実装: `ScanOrganic`イベントの累積カウントから`SellOrganicData`イベントの累積カウントを差し引いた「未売却件数」を保持する簡易detector（金額の期待値計算はValue段階）。

## 6. Deterministic Filters

候補生成 **直後** に適用する決定論的フィルタ（§22到達可能性の判定、§10.1需要フィルタ含む）。

```text
- jump_range_insufficient: 積載時ジャンプレンジで到達不能 → reason_code="UNREACHABLE"
    判定不能な場合は除外せずconfidenceを下げる（§22の通り）
- demand_invalid: mining_sell候補のdemand <= 0 → reason_code="DEMAND_INVALID"
- pad_incompatible: 現在の船のランディングパッドサイズが駅のmax_landing_padを超える
    → reason_code="PAD_INCOMPATIBLE"
- required_data_unavailable: target識別（system_name/station_id等）が確定できない
    → reason_code="DATA_UNAVAILABLE"
```

フィルタで除外された候補は`RejectedCandidate(category="filter", reason_code=...)`へ変換する（10節）。

## 7. Target identity / 重複排除

### 7.1 system_name

§21の制約通り、`system_name`は必ずJournalの`StarSystem`フィールド（または`System.name`）から直接取得し、`body_name`の文字列分割からは導出しない。

### 7.2 候補の重複排除

```text
mining_sell: 同一駅で複数commodityを売却可能な場合、駅単位で1候補にまとめる
             （commodity別に分割しない。effective_price計算はcommodityごとの内訳を保持）
mining_start: 同一天体が優先度1と優先度2の両方に該当する場合、優先度1の結果を採用する
bio_next_system: 同一天体に複数signal_typeがある場合、天体単位で1候補にまとめる
```

## 8. Required Facts（サマリ）

候補生成に必要な事実の取得元を明示する（2節の詳細を集約）。

```text
PlayerStateFacts
├─ current_system_address, current_body_id, current_station_id  (PlayerState, 既存)
├─ cargo: list[(commodity_name, quantity, is_ore)]               (CargoState + 新規MINABLE_COMMODITIES定数)
├─ mining_context: MiningContext                                  (新規 detector, journal_events由来)
├─ current_body_bio_signals: list[BodyBioSignal]                  (既存, ただしEDDN経由のみ)
├─ unsold_bio_count: int                                          (新規 detector, journal_events由来)
├─ nearby_systems: list[System]                                   (既存, distance_limit_ly検索)
├─ market candidates: list[MarketLatest]                          (既存)
└─ laden_jump_range: float                                        (§9.1、Phase 2-2時点では未実装 — 6節フィルタが判定不能時confidence低下で代替)
```

`laden_jump_range`（§9.1 FSD range計算）はRouting/Time Service側の実装であり、Phase 2-2の時点ではまだない。到達可能性フィルタは、これが実装されるまで「常に判定不能」として扱い、`confidence`を下げるが除外はしない（§22の明記通り）。

## 9. Candidate → Horizon interface

候補ごとの`required_segments`（`build_horizon`へそのまま渡す）を固定する。

```text
mining_sell        : ["jump", "supercruise", "dock", "supercruise", "jump"]  # 実質: 往復のjump/SC/dock
                     ※ 同一segment_typeが複数回必要な場合の扱いは10節で扱う
mining_continue    : ["mining_cycle"]                       # 現在地に留まるため移動不要
mining_start       : ["jump", "supercruise", "mining_cycle"]
bio_current_body   : ["descent", "bio_sample", "ascent"]    # 既に軌道上/天体近傍にいる前提
bio_next_system    : ["jump", "supercruise", "descent", "bio_sample", "ascent"]
bio_return         : ["jump", "supercruise", "dock"]
```

**重要な帰結**: `supercruise`は現行データソースの制約により常に`unavailable`（Phase 0-C/2-0確定事項）。したがって、`required_segments`に`supercruise`を含む候補（`mining_sell`/`mining_start`/`bio_next_system`/`bio_return`）は、**Phase 2-2時点では構造的に常にhorizon_complete=falseとなり、IncompleteCandidateにしかなり得ない**。

`horizon_complete=true`（`Recommendation`候補になり得る）のは`mining_continue`と`bio_current_body`の2種類のみである。これはバグではなく、Phase 0-C以来の既存制約の直接の帰結であり、Phase 2-2のExit Criteria（13節）はこれを前提に定義する。

### 9.1 同一segment_typeの複数回出現

`build_horizon`は現在`dict[str, TimeEstimate]`（segment_typeがキー）を返すため、同一segment_typeが経路中に複数回出現する場合（例: mining_sellの往路jump+復路jump）は**現在のシグネチャでは区別できない**。これはPhase 2-2で解消せず、`build_horizon`のシグネチャ拡張（区間ごとのラベル付け、例: `"jump:outbound"`/`"jump:return"`）が必要になった時点で対応する、既知の制約として記録する。Phase 2-2ではひとまず「同一segment_typeは1回分の所要時間を代表値として扱い、複数区間は候補生成側で回数を掛けて概算する」という簡略化を採用する。

## 10. RejectedCandidateへの接続

6節のフィルタで除外された候補は、`filter`カテゴリの`RejectedCandidate`に変換する。9.1節の複数segment制約や、8節のFact不足で候補自体が生成できないケース（4.4節「両優先度0件」等）は、`RejectedCandidate`にもしない — そもそも候補が存在しないため、記録するものがない。

## 11. IncompleteCandidateへの接続

9節の通り、`required_segments`に`supercruise`を含む候補は`build_horizon`の結果`horizon_complete=false`となり、`IncompleteCandidate`（Phase 2-0 DTO）に変換する。`blocking_segments`には常に`["supercruise"]`が入る（Phase 2-2時点での唯一のunavailable要因）。

## 12. Test matrix

```text
Mining:
  - has_mining_cargo判定（is_ore境界値、複数commodity）
  - mining_active detector（MiningRefined lookback境界）
  - mining_sell: mining_activeなしでも生成される（回帰）
  - mining_sell: demand<=0の駅が除外される
  - mining_sell: 複数commodityが同一駅候補にまとまる（重複排除）
  - mining_start: 優先度1（実績）が優先度2（推測）より優先される
  - mining_start: 両方0件なら候補を生成しない

Bio:
  - bio_current_body: has_bio_signalsがEDDN観測なしでは検出できないことの確認（既知の制約テスト）
  - bio_next_system: distance_limit_ly境界
  - bio_next_system: ローカルSystemキャッシュに存在しないsystemは候補に出ない
  - bio_return: unsold_bio_count > 0でのみ生成

Filter:
  - jump_range_insufficient → RejectedCandidate(filter)
  - jump_range判定不能 → 除外せずconfidence低下

Horizon接続:
  - mining_continue / bio_current_bodyがhorizon_complete=trueになり得る
  - mining_sell / mining_start / bio_next_system / bio_returnが常にIncompleteCandidateになる
    （現行制約の回帰テスト — 将来SCモデル追加時にこのテストは意図的に更新する）
```

## 13. Phase 2-2 Exit Criteria

- [ ] Candidate Generatorが`horizon_complete`を一切参照せずに候補を生成する（1.1節の原則が実装レベルで守られている）
- [ ] `MINABLE_COMMODITIES`定数と`is_ore`判定が実装されている
- [ ] `mining_active`/`last_ring_body_id` detectorが実装されている（ring静的データ不在のフォールバックのみ）
- [ ] `unsold_bio_count` detectorが実装されている
- [ ] Mining 3種・Bio 3種の候補生成条件がテストで検証されている
- [ ] Mining Startのring候補が優先度1（実績）→優先度2（推測、confidence低）の順で生成される
- [ ] Bio Next Systemがローカルキャッシュ済みsystemのみを探索することがテストで確認されている
- [ ] 決定論的フィルタ（到達可能性・demand・pad・データ欠如）が`RejectedCandidate(filter)`を生成する
- [ ] `mining_continue`/`bio_current_body`のみが`horizon_complete=true`になり得ることが回帰テストで固定されている
- [ ] 既存131テストに回帰がない
- [ ] Value/Score計算に一切踏み込んでいない（`expected_value`等は`DraftCandidate`に存在しない）

本書のExit Criteriaを満たした時点でPhase 2-2実装に着手できる。
