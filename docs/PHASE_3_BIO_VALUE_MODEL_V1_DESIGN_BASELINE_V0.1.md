# EDpj Phase 3 Bio Value Model V1 Design Baseline

**Version:** 0.1
**Status:** Implemented（Phase 3向け新規/更新テストを含め、計438テスト全通過。Exit Criteria全項目達成。実装中に発見した追加バグ1件を修正——詳細は本文末尾の実装後注記を参照）
**Date:** 2026-09-06
**Depends on:** `SPECIFICATION_V0.4.md` §8.5-8.7/§10/§13.2/§21/§22, `IMPLEMENTATION_SPEC_V0.2.md` §8.2/§8.3/§11/§17（Phase 3 exit criteria）, `docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md` §5, `docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md` §4.4/§5, `app/bio/candidates.py`, `app/bio/conditions.py`, `app/scoring/value.py`, `app/scoring/models.py`

## 0. 位置づけ

`app/scoring/value.py`の`calculate_value()`は現在、`bio_current_body`/`bio_next_system`/`bio_return`の3アクション全てに対して`BIO_VALUE_UNAVAILABLE_REASON = "species value model not implemented"`を返し、Valueを一切計算しない。本書はこの境界を埋める**V1**（最小成立モデル）を定義する。

**中心方針（レビューで確定）**: V1は`p(s)`（species確率）を一切予測しない。現在保存されている`BodyBioSignal`（EDDN `fssbodysignals/1`由来、生体シグナルの**個数のみ**、genus/species情報を含まない）だけを入力とし、

```text
expected_value_base = biological_signal_count × expected_value_per_signal
```

という**シグナル数×校正済み平均単価**モデルとする。`expected_value_per_signal`は本人の実`SellOrganicData`/`ScanOrganic`履歴から校正する。

**なぜこの野心度か**: `IMPLEMENTATION_SPEC_V0.2.md` §11.1が定義する`expected_value_base = Σ p(s) × base_value(s)`という式を文字通り実装するには、(a) 未調査天体のspecies確率`p(s)`を予測する機構と、(b) species別の固定売却額表`base_value(s)`が必要だが、**V1着手時点ではこのプロジェクトはどちらも持っていなかった**——genus/species情報は本人の`ScanOrganic`（実際にスキャン後）でしか得られないと当時考えていた。V1は「その時点でのデータ境界の中で成立する最小モデル」として設計した。

**訂正（2026-09-06、Feasibility調査により判明）**: 当初この節は「他プレイヤーのDSS結果は`saasignalsfound/1`で購読できるが未購読」という前提でV2候補を記録していたが、**`saasignalsfound/1`というEDDNスキーマは実在しない**（EDCD/EDDN公式リポジトリ・EDDN Monitor共に該当なし、2026-09-06に直接確認）。誤情報だったためこの記述は削除した。実際には`scanorganic/1`という別の実在スキーマが、`Genus`/`Species`を直接含む形でライブ配信されており、`edgalaxydata.space`に日次アーカイブもされている。V1後の方向性は`docs/CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`に切り出した。

**明示的にスコープ外:**

```text
- genus/species予測（V2、`docs/CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`へ移管）
- 惑星条件からのspecies分布予測（V3、§9で候補として記録するのみ）
- expected_value_best（FD upside）の実装 -- ranking正本ではなく参考値
  （SPECIFICATION_V0.4.md §10）であり、V1では常にNoneのまま
  （§6で明記、fd_multiplierを推測で埋めない）
- DiscoveryState（honked/fss_scanned/dss_scanned）を使ったHorizon側の
  honk/fss/dss時間加算（SPECIFICATION_V0.4.md §21）
  -- これはHorizon側の別の既知ギャップであり、`system_discovery`/
  `body_discovery`テーブル自体が未実装（app/bio/conditions.pyのdocstring
  で既に明記済み）。Value Modelとは独立した作業であり、本書のスコープに
  含めない
- Bio Backtest / 有効性検証（V1実装完了後、独立したPhaseとして実施）
```

## 1. 前提条件の修正: `has_bio_signals`/`find_nearby_bio_signal_bodies`のsignal_typeバグ（発見・要修正）

`app/collectors/eddn.py`の`parse_fssbodysignals_message()`は、`fssbodysignals/1`メッセージの`signals`配列を**signal_typeで一切フィルタせず**そのまま`body_bio_signals`テーブルへ保存する——生体（`$SAA_SignalType_Biological;`）だけでなく地質（`$SAA_SignalType_Geological;`）等も同じテーブルに入る（`signal_type`カラムで区別されるのみ）。

一方`app/bio/conditions.py`の`has_bio_signals()`/`find_nearby_bio_signal_bodies()`は、`BodyBioSignal`の行が**1件でもあれば**（signal_typeを問わず）bio signal ありと判定している。既存テスト（`tests/integration/test_bio_conditions.py`の`test_multiple_signal_types_on_same_body_are_grouped`）は地質シグナルが混在するケースを「グルーピングされる」ことまでは確認しているが、**「地質シグナルのみ（生体シグナルなし）の天体が除外されること」を検証するテストは存在しない**。これは既存のPhase 2-2実装（Candidate Generation）に潜在するバグであり、地質シグナルのみの天体に対して誤ってbio候補を生成しうる。

**確定: 本書のスコープとして、この2関数へのsignal_typeフィルタ追加を含める。** Value Model自体が正しいsignal_count（生体のみ）を要求するため、Candidate Generation側のこのバグを放置するとValue側だけ正しくフィルタしても`bio_current_body`/`bio_next_system`候補自体が誤って生成され続ける。

```python
# app/bio/conditions.py への追加
BIOLOGICAL_SIGNAL_TYPE = "$SAA_SignalType_Biological;"

def has_bio_signals(session: Session, system_address: int, body_id: int) -> bool:
    return any(s.signal_type == BIOLOGICAL_SIGNAL_TYPE for s in bio_signals_for_body(session, system_address, body_id))
```

`find_nearby_bio_signal_bodies()`も同様に、`by_body`へ集約する際`signal_type == BIOLOGICAL_SIGNAL_TYPE`の行のみを対象にする。

**未検証事項**: `$SAA_SignalType_Biological;`という正確な文字列は既存テストのfixture（`test_bio_conditions.py`/`test_bio_candidates.py`）で使われている値と一致しており、これはEDDN `fssbodysignals/1`スキーマの実際の値に基づく（本人の実Journalには現時点でBio関連イベントが0件のため、実データでの直接確認はまだできていない——§3の校正データも同じ制約を持つ）。

## 2. `BioTarget`のDTO拡張: `system_address`/`body_id`

Value計算は`BodyBioSignal`を再クエリする必要があるが、現在の`BioTarget`は表示用の`body_name`/`system_name`（文字列）のみを持ち、DBクエリに使える数値IDを持たない。`app/scoring/value.py`の既存原則（`_mining_sell_value`のdocstring: 「候補生成が既に要求した一致を再導出する、キャッシュされた値を信用しない」）に従い、Value側は`BodyBioSignal`をIDで再クエリする——Candidate Generationが数えた値をそのまま信用しない。

```python
@dataclass
class BioTarget:
    ...（既存フィールドは変更しない）
    system_address: int | None = None  # 追加。DB再クエリ用、表示には使わない
    body_id: int | None = None         # 追加。bio_next_systemでは対象bodyが未確定な場合Noneもありうる
```

`generate_bio_current_body_candidates()`は`player_state.current_system_address`/`current_body_id`を、`generate_bio_next_system_candidates()`は`origin.system_address`ではなく候補**先**の`nearby.system.system_address`/`nearby.body_id`（`NearbyBioCandidate`が既に保持している）をそれぞれ設定する——これは「ポリシー変更ではなく実装上必要な配線変更」（Phase 2-3の`ValueResult`導入時と同じ性質）。

## 3. Calibration: `expected_value_per_signal`

新設 `app/bio/value.py`（`app/mining/price.py`/`app/mining/yield_model.py`と同じ、DB読み取りのみの純粋寄りモジュール）。

**重要な意味づけ（レビューで修正）**: この校正値は「species単価」ではない。`SellOrganicData`の売却件数と`ScanOrganic`(Analyse)のスキャン件数は、Journal上で1件ずつ対応づけられる保証がない（どのスキャンがどの売却行に対応するかを示すフィールドは存在しない）。したがって`total_organic_sale_credits() / total_analysed_sample_count()`は「特定speciesの単価」ではなく、**「本人が過去、生体分析1件あたり平均してどれだけの収益を実現してきたか」という履歴ベースの収益率（historical bio revenue per analysed target）** として扱う。関数名・ドキュメント上も「species」という語を使わない——`average_species_value`のような命名は誤解を招くため採用しない。

```python
def total_organic_sale_credits(session: Session) -> int:
    """本人の実Journal全体からSellOrganicDataイベントを全件読み、
    各BioDataエントリのValue+Bonusを合算する。FD bonusを含めた
    実現額の合計 -- V1はexpected_value_bestを実装しないため(§0)、
    baseとFDを分離せず「本人が過去に実際に得た平均」として扱う
    （このプレイヤーの過去のFD hit率が今後も概ね同程度という前提を
    含む、暗黙の単純化）。"""
    total = 0
    for event in session.query(JournalEvent).filter_by(event_type=SELL_ORGANIC_DATA).all():
        for entry in event.payload.get("BioData", []):
            total += entry.get("Value", 0) + entry.get("Bonus", 0)
    return total


def total_analysed_sample_count(session: Session) -> int:
    """ScanType == Analyse（種を完成させた最終サンプル）の件数。
    detect_unsold_bio_count()と同じANALYSE_SCAN_TYPE定数を再利用するが、
    those は「直近セール以降」に限定するのに対し、本関数はJournal全体
    -- calibrationの母数と、未売却の残数は別の質問なので意図的に
    別実装にする（重複ではなく前提が異なる）。
    total_organic_sale_credits()の分子（売却件数）とこの分母（スキャン件数）は
    Journal上で1件ずつ対応づけられる保証がない -- 本関数は特定の売却と
    特定のスキャンをペアリングしようとせず、単純にJournal全体での
    集計件数を返す。"""
    return sum(
        1
        for event in session.query(JournalEvent).filter_by(event_type=SCAN_ORGANIC).all()
        if event.payload.get("ScanType") == ANALYSE_SCAN_TYPE
    )


def calibrate_expected_value_per_signal(session: Session) -> float | None:
    """None を返す条件は独立した2つ（実装時にテストで発見・追加、後述の
    実装後注記も参照）:
      - total_analysed_sample_count() == 0（分母が立たない）
      - SellOrganicDataイベントが1件も存在しない（分子の0が「organicsの
        価値は0」ではなく「まだ一度も売っていない」ことを意味する場合、
        計算されたcredits合計0をそのままper_signal=0.0として返すと、
        Bio候補が実際には「校正データ不足」であるにもかかわらず
        「価値ゼロ」と誤って評価されてしまう）
    どちらも0除算・0への収束を避け、Mining側のcalibration
    （sample_count_eval==0でinsufficient）と同じ「データが無ければ
    堂々とNoneを返す」原則を踏襲する。

    返り値は「species単価」ではなく「生体分析1件あたりの過去の平均実現収益」
    である（本節冒頭の意味づけ参照）。SellOrganicDataの件数とScanOrganicの
    件数が一致しない実データ（例: 2 sell events, 5 analysed scans）でも
    正しく動作する -- 1:1対応を前提にしたペアリングロジックを一切持たない
    ことをテストで確認する（§6）。"""
    denominator = total_analysed_sample_count(session)
    if denominator == 0:
        return None
    if session.query(JournalEvent).filter_by(event_type=SELL_ORGANIC_DATA).first() is None:
        return None
    return total_organic_sale_credits(session) / denominator
```

**この校正は現時点でこのプレイヤーには適用できない**: 実Journal（`data/edpj.db`、2026-08-26〜09-05）を確認したところ、`ScanOrganic`/`SellOrganicData`イベントは**0件**。したがって`calibrate_expected_value_per_signal()`は実装完了後も当面`None`を返し続け、Bio Value ModelはV1実装後も本人が実際にexobiologyを行うまで`value_unavailable`のままになる——これはモデルの欠陥ではなく、Mining側のPhase 0-C（SC duration samples待ち）と同じ「実データ待ち」の状態であり、想定内である。

## 4. Value計算（`app/scoring/value.py`への追加）

```python
def _biological_signal_count(session: Session, system_address: int | None, body_id: int | None) -> int:
    if system_address is None or body_id is None:
        return 0
    rows = (
        session.query(BodyBioSignal)
        .filter_by(system_address=system_address, body_id=body_id, signal_type=BIOLOGICAL_SIGNAL_TYPE)
        .all()
    )
    return sum(row.count for row in rows)


def _bio_value(target: BioTarget, session: Session) -> ValueResult:
    """bio_current_body/bio_next_system 共通。signal_countをBodyBioSignal
    から再クエリし(§2)、calibrate_expected_value_per_signal()と掛け合わせる。"""
    signal_count = _biological_signal_count(session, target.system_address, target.body_id)
    if signal_count == 0:
        return ValueResult(None, "no_biological_signal_count")  # 通常はCandidate Generation側の
                                                                    # §1修正後は発生しないはずだが、
                                                                    # Valueは自分自身の前提を検証する
    per_signal = calibrate_expected_value_per_signal(session)
    if per_signal is None:
        return ValueResult(None, "insufficient_sell_history")
    return ValueResult(signal_count * per_signal, None)


def _bio_return_value(session: Session) -> ValueResult:
    """spec §8.7/§11.4: 「未売却organic dataの価値」。detect_unsold_bio_count()
    （既存、app/bio/conditions.py）が返す件数を、bio_current_body/
    bio_next_systemと同じper_signal単価で評価する -- V1は
    「既知のspeciesを使った正確な評価」（bio_returnなら実現可能、
    ScanOrganicのGenus/Speciesが既知のため）を意図的に採用しない
    （レビューで確定: BodyBioSignalのみを入力とする方針を3アクション
    で統一する）。known-species-awareな評価はV2以降の候補として
    §9に記録する。"""
    unsold_count = detect_unsold_bio_count(session)
    if unsold_count == 0:
        return ValueResult(None, "no_unsold_bio_data")
    per_signal = calibrate_expected_value_per_signal(session)
    if per_signal is None:
        return ValueResult(None, "insufficient_sell_history")
    return ValueResult(unsold_count * per_signal, None)
```

`calculate_value()`のbio分岐を、現在の一律`BIO_VALUE_UNAVAILABLE_REASON`から上記3関数の呼び出しへ置き換える。`BIO_VALUE_UNAVAILABLE_REASON`定数自体は削除しない——`_bio_value`/`_bio_return_value`が返す個別の`value_unavailable_reason`（`no_biological_signal_count`/`insufficient_sell_history`/`no_unsold_bio_data`）の方が診断的に有用なため使わなくなるが、他の箇所からの参照有無を実装時に確認する。

## 5. `expected_value_best`（FD upside）は実装しない

`ActionCandidate`/`ValueResult`に`expected_value_best`相当のフィールドを**追加しない**。理由: `fd_multiplier`は種によって大きく異なり（レア種ほど高い）、V1はspeciesを区別できないため、fd_multiplierを「それらしい」定数で埋めることは「推測で埋めない」という本プロジェクト全体の原則に反する。SPECIFICATION_V0.4.md §10自体も「bestは参考値」と位置づけており、ranking正本である`expected_value_base`の実装がV1の目的を満たす。

## 6. Acceptance Tests

```text
has_bio_signals()が以下の5パターンを正しく判定する（§1のバグ修正の直接証拠）:
   生体シグナルのみ           -> True
   地質シグナルのみ           -> False
   生体+地質の混在            -> True
   シグナルなし               -> False
   未知のsignal_type（Biological/Geological以外）のみ -> False
find_nearby_bio_signal_bodies()が地質シグナルのみの天体を候補から除外する
_biological_signal_count()がsignal_type=Geologicalの行を合算に含めない
calibrate_expected_value_per_signal()がSellOrganicData件数とScanOrganic(Analyse)件数が
   一致しない実データ（例: 2 sell events, 5 analysed scans）でも正しく比率を計算する
   -- 1:1ペアリングを試みるロジックを持たないことの直接証拠
_biological_signal_count()がsystem_address/body_idがNoneの場合0を返す
   （bio_next_systemでbody_idが未確定なケースを想定）
total_organic_sale_credits()がSellOrganicDataの全BioDataエントリの
   Value+Bonusを合算する
total_analysed_sample_count()がScanType=Analyseのみを数え、
   Log/Sampleを含めない
calibrate_expected_value_per_signal()がtotal_analysed_sample_count=0のとき
   Noneを返す（0除算しない）
_bio_value()がsignal_count=0のときvalue_unavailable_reason="no_biological_signal_count"を返す
_bio_value()がper_signal=Noneのときvalue_unavailable_reason="insufficient_sell_history"を返す
_bio_value()がsignal_count>0かつper_signal is not Noneのとき、
   signal_count * per_signalを返す
_bio_return_value()がdetect_unsold_bio_count()=0のとき
   value_unavailable_reason="no_unsold_bio_data"を返す
_bio_return_value()がdetect_unsold_bio_count()>0かつper_signal is not Noneのとき
   unsold_count * per_signalを返す
BioTarget.system_address/body_idが未設定時Noneをデフォルトにする
   （既存の全呼び出し箇所が壊れないことの回帰保証）
generate_bio_current_body_candidates()がBioTarget.system_address/body_idを
   player_stateの値で正しく設定する
generate_bio_next_system_candidates()がBioTarget.system_address/body_idを
   候補先bodyの値で正しく設定する（originではない）
```

## 7. Exit Criteria

- [x] `has_bio_signals()`/`find_nearby_bio_signal_bodies()`がsignal_type=Biologicalのみを対象にするよう修正され、地質シグナルのみの天体を除外することがテストされている
- [x] `BioTarget`に`system_address`/`body_id`が追加され、`generate_bio_current_body_candidates`/`generate_bio_next_system_candidates`が正しく設定する
- [x] `app/bio/value.py`が新設され、`total_organic_sale_credits`/`total_analysed_sample_count`/`calibrate_expected_value_per_signal`が実装されている
- [x] `_bio_value`/`_bio_return_value`が`app/scoring/value.py`に実装され、`calculate_value()`のbio分岐から呼ばれる
- [x] `expected_value_best`/`fd_multiplier`相当のフィールドが追加されていない（構造的保証）
- [x] 校正データ不足（`total_analysed_sample_count=0`、またはSellOrganicDataが1件も無い場合）に0除算・0への誤収束をせず、`value_unavailable_reason="insufficient_sell_history"`を返すことがテストされている
- [x] 既存テストスイートに回帰がない（計438テスト全通過）

### 実装後注記（2026-09-06）

設計時点では`calibrate_expected_value_per_signal()`のNone条件を`total_analysed_sample_count() == 0`のみとしていたが、実装・テスト段階で見落としを発見した: 分析済みスキャンは存在するが`SellOrganicData`が1件も無い場合（例: 1回Analyseしたがまだ売却していない）、分子の`total_organic_sale_credits()`が正当に0を返すため、`0 / 1 = 0.0`という**有効な数値**が返ってしまい、「校正データ不足」ではなく「1シグナルあたりの価値は0」という誤った断定になっていた（`_bio_return_value()`が`unsold_count * 0.0 = 0.0`という偽の確定値を返す形でテストが失敗し発覚）。§3のコード例・docstringを実装に合わせて修正し、「SellOrganicDataが1件も存在しない」ことも独立した条件として追加した。この修正は本書のモデル方針（signal-count generic value、V1スコープ）を一切変更しない、calibration関数内部の"insufficient"判定漏れの修正である。

## 8. V2/V3ロードマップ（本書のスコープ外、記録のみ）

**2026-09-06訂正**: 本節はV1着手時点で「V2はsaasignalsfound/1という新規EDDN購読が必要」と記録していたが、そのスキーマは実在しないことが判明した（§0訂正参照）。V2の正しい方向性・検証要件・受け入れ条件は`docs/CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`に切り出した——本書はV1（signal-count generic value）の実装記録としてのみ確定させ、V2以降の設計はここで凍結せず別文書に一本化する。

V1はV2確立までの間、唯一のfallback baselineとして機能し続ける（Value自体がNoneになるくらいなら、V1の粗いsignal-count推定の方がマシ、という位置づけ）。V1のformulaを最終系として扱わないことは`CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`で明文化した。

## 9. 決定事項サマリ

1. **§0 V1はsignal-count generic value**: `p(s)`予測を一切行わない。`BodyBioSignal`（生体シグナル個数のみ）だけを入力とする
2. **§1 前提バグの修正を含める**: `has_bio_signals`/`find_nearby_bio_signal_bodies`のsignal_type未フィルタは、Value Modelが正しいsignal_countを要求する以上、本書のスコープに含めて同時に直す
3. **§2 `BioTarget`にsystem_address/body_idを追加**: Value側が`BodyBioSignal`をIDで再クエリするための配線変更（ポリシー変更ではない）
4. **§3 校正は本人のJournal全体から**: `SellOrganicData`のValue+Bonus合計 ÷ `ScanOrganic`(Analyse)件数。データ不足時はNone（0除算しない）。現時点でこのプレイヤーには適用データが0件で、実プレイ待ちになる
5. **§5 expected_value_best（FD upside）は実装しない**: fd_multiplierを推測で埋めることを避ける。V1はranking正本（base）のみ
6. **§9 bio_returnも既知species活用を見送る**: bio_returnは技術的にはScanOrganicのGenus/Speciesが既知だが、3アクション間でV1の入力ソースを統一するため、既知species活用はV2以降の検討事項とする
7. **2026-09-06訂正: 「実プレイ待ち」は本人のSellOrganicData/ScanOrganic校正にのみ当てはまり、Bio Value Model全体の話ではない**: 上記4はV1の校正ロジック（本人のJournalのみを見る）の帰結であって、Bio Value Model自体が外部データ不在で行き詰まっているという意味ではなかった。Feasibility調査で`scanorganic/1`（他プレイヤーのGenus/Species付きスキャン結果、EDDNでライブ配信+アーカイブ済み）の存在を確認済み——詳細と今後の要件は`docs/CLAUDE_FORMULA_VALIDATION_DIRECTIVE_V0.1.md`
