# EDpj Phase 2-6F-T2 Large Price Movement Characterization — Design Baseline

**Version:** 0.1
**Status:** Implemented（`app/backtest/trade_market_persistence.py`に追加、新規28テスト全通過。実データに対して実行し、実測値を記録済み——§5）
**Date:** 2026-09-06
**Depends on:** `docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md`, `docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`, `app/backtest/trade_market_persistence.py`

## 0. 位置づけ

2-6F-T1は「価格がどれだけ持続するか」を集計値（%、中央値）として測定した。本書はその一段先——「大きな価格変動は具体的にどの商品・どのstationで、どれだけの間隔で、どんな状況で起きているか」を、イベント単位（集計する前の個別ケース）で特性化する。ユーザーの狙いは「マーケット最適化を今すぐ作る」ことではなく、**現在の単純な粗利計算（`sell_price - buy_price`等）に対して、実データに基づいたリスク情報を添えられるようにする**こと——「この粗利は理論値である」ではなく「この条件では過去に◯%の確率で30分以内に10%以上動いた」と言えるようにする。

## 1. 分析項目と実データでの可否

| 分析項目 | 実データで計算可能か | 理由 |
|---|---|---|
| 変動幅（いくら下落したか） | ○ | `sell_price`は全行にある |
| 発生頻度（何回に1回起きるか） | ○ | 2-6F-T1の`material_decrease_rate`を商品・station別に再集計するだけ |
| 発生タイミング（観測から何分後か） | ○ | 2-6F-T1の`time_to_first_material_decrease`を個別イベントとして保持し直す |
| 商品別の偏り | ○ | `commodity_name`でgroup by |
| ステーション別の偏り | ○ | `station_id`でgroup by（ただし2-6F-T1で既に確認した通りstation多様性は乏しい——2 stationのみ） |
| Buy/Sellどちらが動くか | **×（構造的INSUFFICIENT）** | `buy_price`は未収集（2-6F-T1 §2/§10、バックフィルDeferred）。`sell_price`側の変動のみ観測可能 |
| Supply/Demand変化との関係 | **Demandのみ○、Supplyは×** | `demand`は全行にある。`supply`は`buy_price`と同じくバックフィル未実施 |
| 観測間隔（変動前後の粒度） | ○ | 各イベントに「t0からの経過時間」と「イベント検出に使った観測のgap」を付随させる |
| 変動後に戻るか継続するか（reversion） | ○ | イベント後の後続観測を追跡すれば計算できる（新規） |

**Buy/Sell側とSupplyは、2-6F-T1で既にDeferredとした同じバックフィル待ちの構造的ギャップである。** 今回のPhaseでも同じ扱い（コードとしては書くが、実行結果はINSUFFICIENTになる）とする——新しいバックフィル判断を作らない。

## 2. 設計

`app/backtest/trade_market_persistence.py`に追加する（新規モジュールを作らない——2-6F-T1のデータ構造・閾値・ヘルパーをそのまま再利用するため）。

### 2.1 `MaterialDecreaseEvent`（個別イベント、集計する前の生データ）

```python
@dataclass(frozen=True)
class MaterialDecreaseEvent:
    station_id: int
    commodity_name: str
    t0: dt.datetime
    t0_price: int
    t0_demand: int
    event_observed_at: dt.datetime
    event_price: int
    event_demand: int
    relative_decrease: float          # (t0_price - event_price) / t0_price
    time_to_event: dt.timedelta
    gap_before_event: dt.timedelta    # event_observed_at - 直前の観測（検出に使えた解像度）
```

`compute_time_to_first_material_decrease()`の内部ロジックをこのイベント抽出に一本化し、既存の`TimeToDecreaseSummary`はこのイベントリストから集計する形にリファクタリングする（公開関数のシグネチャ・返り値は変更しない、既存テストへの回帰は無い）。

### 2.2 商品別・ステーション別breakdown

```python
@dataclass(frozen=True)
class GroupMoveSummary:
    key: str | int                 # commodity_name または station_id
    event_count: int
    median_relative_decrease: float | None
    median_time_to_event: dt.timedelta | None

def summarize_events_by_commodity(events: list[MaterialDecreaseEvent]) -> dict[str, GroupMoveSummary]
def summarize_events_by_station(events: list[MaterialDecreaseEvent]) -> dict[int, GroupMoveSummary]
```

サンプル数が少ない商品/stationも「イベント0件」として結果に含める必要はない（`compute_price_persistence`と同じ、母数に含まれないものは母数から外す）——グループは実際にイベントが発生したものだけ現れる。

### 2.3 Demand変化との相関

```python
@dataclass(frozen=True)
class DemandCorrelationResult:
    event_count: int
    demand_decreased_count: int   # event_demand < t0_demand
    demand_increased_count: int
    demand_unchanged_count: int

def compute_demand_change_at_events(events: list[MaterialDecreaseEvent]) -> DemandCorrelationResult
```

厳密な統計的相関係数（ピアソン等）は計算しない——イベント数が少ない可能性が高く（実データ確認前だが2-6F-T1では690件が34系列に分散）、過度に精緻な統計量は実データの粒度に見合わない。まずは方向性の集計（増えた/減った/変わらない）に留める。

### 2.4 価格の反転（reversion）分析

```python
class ReversionOutcome(str, Enum):
    REVERTED = "REVERTED"        # event後、t0_priceの95%以上まで回復した観測がある
    PERSISTED = "PERSISTED"      # 回復が観測されないまま反転観測ウィンドウが尽きた
    CENSORED = "CENSORED"        # 反転観測ウィンドウ内に後続観測が無い(データが無い、"継続した"と決めつけない)

@dataclass(frozen=True)
class ReversionCase:
    event: MaterialDecreaseEvent
    outcome: ReversionOutcome
    time_to_reversion: dt.timedelta | None  # REVERTEDの時のみ

def compute_price_reversion(
    session: Session, events: list[MaterialDecreaseEvent],
    reversion_window: dt.timedelta = dt.timedelta(hours=24),
    recovery_threshold: float = 0.95,  # t0_priceの95%以上に戻ったら「反転」とみなす
) -> list[ReversionCase]
```

`recovery_threshold=0.95`は、`MATERIAL_DECREASE_RELATIVE_THRESHOLD=0.05`の逆（5%下落を「変動」と呼ぶなら、95%まで戻れば「ほぼ元通り」と呼ぶ）として整合させる——新しい独立した閾値を発明しない。CENSOREDとPERSISTEDを区別する（§2.6F-T1と同じ「観測が無いことを継続の証拠にしない」原則）: `reversion_window`内に後続観測が1件もなければCENSORED、後続観測はあるが95%まで戻っていなければPERSISTED。

### 2.5 Buy/Sell側・Supplyの扱い（構造的INSUFFICIENT）

```python
def compute_buy_side_movement(session: Session) -> PersistenceMeasurementStatus:
    """buy_priceを持つ行が無ければINSUFFICIENT。2-6F-T1のcompute_profit_condition_persistenceと
    同じ構造的ギャップ(バックフィルDeferred)によるもので、新しい判断を作らない。"""
```

## 3. Acceptance Tests

```text
compute_time_to_first_material_decrease()のリファクタリング後も既存9テストが全て通過する(回帰なし)
MaterialDecreaseEventのrelative_decreaseが正しく計算される
summarize_events_by_commodity()が、イベントが1件も無い商品を結果に含めない
compute_demand_change_at_events()が、demand不変のケースをunchangedとして数える
compute_price_reversion()が、95%以上まで回復した観測を見つけたらREVERTEDにし、time_to_reversionを記録する
compute_price_reversion()が、reversion_window内に後続観測が無い場合CENSOREDにする(PERSISTEDにしない)
compute_price_reversion()が、後続観測はあるが回復していない場合PERSISTEDにする
compute_price_reversion()が、reversion_window より後の観測を一切参照しない(future leakage禁止)
```

## 4. Exit Criteria

- [x] `MaterialDecreaseEvent`/`summarize_events_by_commodity`/`summarize_events_by_station`/`compute_demand_change_at_events`/`compute_price_reversion`が実装され、§3を満たす(28テスト)
- [x] 実データに対して実行し、商品別・station別の内訳、demand相関、reversion結果を記録する(§5)
- [x] Buy/Sell側・Supplyについては構造的INSUFFICIENTとして明記する(2-6F-T1と同じ扱い、`compute_buy_side_movement_status`が実データでINSUFFICIENTを返すことを確認)
- [x] 既存テストスイートに回帰がない(501テスト全通過、`compute_time_to_first_material_decrease`のリファクタリング後も既存17テストが無変更で通過)

## 5. 実データ実行結果（2026-09-06、`data/edpj.db`、690イベント）

```text
=== 商品別（イベント数上位、抜粋）===
biowaste              events=53  median_decrease=0.500  median_time_to_event=約4日3時間
syntheticfabrics      events=53  median_decrease=0.229
liquidoxygen          events=52  median_decrease=0.250
copper                events=53  median_decrease=0.120
polymers              events=53  median_decrease=0.154
（他の大半は5〜10%程度の下落に集中）

=== station別 ===
3221821952: 685イベント（99.3%）  median_decrease=0.099
3789719552:   5イベント（ 0.7%）  median_decrease=0.060

=== Demand変化との関係 ===
event_count=690
demand_decreased_count=23（3.3%）
demand_increased_count=0（0%）
demand_unchanged_count=667（96.7%）

=== 価格の反転（reversion）===
24時間ウィンドウ: REVERTED=0, PERSISTED=485, CENSORED=205
7/14/30日ウィンドウ: REVERTED=26（3.8%）, PERSISTED=459（66.5%）, CENSORED=205（29.7%）
（7日以降は増えない——実アーカイブの観測期間自体が約14日しかないため）

=== Buy-side movement ===
status = INSUFFICIENT（buy_price未収集、2-6F-T1 §10と同じ理由）
```

**読み取れること（実データ、station多様性の制約あり）**:

1. **`biowaste`のmedian_decrease=0.500は他商品から明確に外れている**——他の大半は5〜25%に収まる中、突出して大きい。個別に調査する価値がある外れ値。
2. **イベントの99.3%が単一station（3221821952）に集中**——2-6F-T1・Market Data Trustworthiness Reevaluationで既に確認済みのstation多様性不足がここでも再現している。station別の傾向差は、station起因の違いなのか、たまたまそのstationにしかデータが無いだけなのかを区別できない。
3. **価格下落の96.7%はdemandの変化を伴わずに発生している**——demand低下が先行/同時に観測されたのはわずか3.3%。これは「demandを見張れば大きな下落を予兆できる」という直感を、少なくともこのデータでは支持しない。
4. **反転はほぼ起きない**——24時間以内の反転はゼロ件（0/690）、7〜30日でも3.8%（26/690）に留まる。**一度material decreaseが観測されると、この実データの範囲内では元の価格に戻らないことが大半である。** これは粗利計算に対する具体的なリスク情報になる：「この商品はこのstationで過去に5%以上の下落が観測されており、その後の反転はほぼ観測されていない」と言える。
5. **`median_time_to_event`がほぼ全商品で「約4日」に揃っている**——これは各商品が独立に4日周期で変動しているのではなく、**観測期間（約2週間）の中に共通する1回の大きな下落イベントが存在し、その手前のT0の大半が同じイベントまでの時間を測っている可能性が高い**（個別イベントではなく、station全体・観測期間全体に影響した1つの構造的な出来事の可能性）。個々の`MaterialDecreaseEvent`の`t0`の分布を見れば検証できるが、本書では速報値として報告するに留め、深追いはしない。

**総括**: 本Phaseの結果は、ユーザーの狙い通り「単純な粗利計算に添えるリスク情報」として使える形になっている——「50 Cr/unitの粗利があるが、この商品はstation Xで過去に約10%の下落が発生しており、その後の反転はほとんど観測されていない」という言い方が、憶測ではなく実データに基づいて可能になった。ただし全ての数値は現在の2 station・690イベントという限られた証拠に基づくものであり、`docs/MARKET_DATA_TRUSTWORTHINESS_REEVALUATION_V0.1.md`と同じ注意——station多様性が改善するまでは「現在取得できている市場データにおける傾向」として扱うべきである。
