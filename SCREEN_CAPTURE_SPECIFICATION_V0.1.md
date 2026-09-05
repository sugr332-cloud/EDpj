# EDpj Screen Capture Specification

**Version:** 0.1  
**Status:** Draft  
**Date:** 2026-09-05  
**関連:** `SPECIFICATION_V0.5.md` / `IMPLEMENTATION_SPEC_V0.3.md`

---

## 1. 目的

Elite Dangerous の画面をキャプチャし、OCR結果を2つの用途に分岐させる。

| 用途 | 出力 |
|---|---|
| 翻訳オーバーレイ | 原文行の位置に訳文を重畳表示 |
| ミッション解析 | ミッションボードの掲示内容を構造化してDBへ |

ミッションボードの内容は Journal / CAPI のいずれにも書き出されないため、画面から読む以外の取得手段が存在しない。本仕様はその制約を前提とする。

### 1.1 非目標

- ゲームへの入力自動化。読み取りと表示のみ
- ミッションの自動受注
- ミッションボード以外の画面の構造化解析（翻訳表示は対象）
- 常時稼働。セッション制とする

### 1.2 EDpjとの関係

本仕様は **EDpj に統合する Screen Capture / OCR サブシステム**の仕様である。EDpjは現在、Journal / Status / Cargo / Marketを正本データとして状態復元し、Mining / Exobiologyの次行動をUnified Scoringする設計である。画面OCRはこの状態取得を置き換えず、Journal/CAPI等に存在しないMission Board情報を補完する観測ソースとして扱う。

既存の `ED_Japanese` には同等のCapture/OCR基盤が存在するが、現時点でオーバーレイ更新に未解決の不具合があるため、本機能は当面 **EDpj側に独立実装**する。

```text
Phase A  EDpj側に独立実装（本仕様の対象）
Phase B  ED_Japaneseが安定した時点で共通化を検討
```

共通化する場合も依存方向は一方向とする。EDpjがED_Japaneseの共通基盤へ依存することは許可するが、ED_JapaneseがEDpjの金策・状態推奨機能へ依存してはならない。ED_JapaneseはEDpjなしで動作可能であること。

### 1.3 情報源の責務

```text
Journal / Status / Cargo / Market
    → 確定状態・実測テレメトリ

Mission Board OCR
    → 画面上に表示されたMissionの観測（estimated）

MissionAccepted Journal
    → 実際に受注したMissionの確定（measured）
```

OCR観測を`measured`へ昇格させない。

---

## 2. 全体構成

```text
                  Screen Capture
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
   追従ループ（高頻度）            認識ループ（低頻度）
   ・縦方向ずれ量 dy の算出        ・前処理
   ・オーバーレイ位置の平行移動    ・OCR
   ・再認識トリガの判定            ・行の正規化
        │                               │
        │                               ├──► 翻訳 ──► オーバーレイ
        │                               │
        └──── dy ──────────────────────►├──► ミッション解析 ──► DB
                                        │
                                        └──► 固有名詞解決 ──► 静的DB照会
```

### 2.1 二重ループの根拠

スクロール追従を認識と同じループで行うと、毎フレームOCRが必要になり成立しない。

- スクロールは大半が一様な平行移動である
- 平行移動量の算出はOCRの数百分の一のコストで済む
- 「何が書いてあるか」と「今どこにあるか」を分離する

---

## 3. 追従ループ

### 3.1 処理

```text
frame
  → 縦ストリップ抽出（画面中央の細い縦帯）
  → 前フレームとの位相相関 または テンプレートマッチ
  → dy（縦方向のずれ量）と相関スコア
  → 全オーバーレイ要素を dy 分だけ平行移動
```

OCRは行わない。目標フレームレートは30fps以上。

### 3.2 再認識トリガ

以下のいずれかで認識ループに要求を出す。

| 条件 | 意味 |
|---|---|
| 累積`dy`が閾値超 | スクロールにより新しい行が入った |
| 相関スコアが閾値未満 | 平行移動で説明できない変化。ページ遷移・フィルタ変更・選択 |
| 認識結果の経過時間が上限超 | 保険。既定30秒 |

**時間周期での再認識は行わない。**静止画面ではOCR実行回数が0になるのが正しい状態である。

### 3.3 スクロール中の表示

`|dy|`が閾値を超えている間はオーバーレイを非表示にする。停止検出から100〜200msでフェードイン。

ずれた訳文が流れる状態を避けるため、省略しない。

---

## 4. 認識ループ

### 4.1 処理

```text
frame
  → 前処理（二値化・スケーリング）
  → OCR
  → 行分割・バウンディングボックス取得
  → 正規化
  → 分岐（翻訳 / ミッション解析 / 固有名詞解決）
```

### 4.2 キュー

追従ループから認識ループへの要求キューは**1段のみ**とする。処理中に新しい要求が来た場合、待機中の古い要求を破棄して最新のみを残す。

要求を蓄積するとオーバーレイが古い認識結果を表示し続ける状態になる。

### 4.3 切れ行の除外

キャプチャ領域の上端・下端に接している行は破棄する。

- 翻訳しない
- ミッション解析に渡さない
- 原文のまま淡色で表示する（処理していないことを示す）

スクロール停止後に全体が映るため、取りこぼしにはならない。

### 4.4 前処理の分岐

翻訳と数値解析では要求される精度が異なる。まず共通の前処理で試行し、報酬値の誤読率が実用に耐えない場合にのみ数値領域の別処理を検討する。

初期実装では分岐させない。

---

## 5. 翻訳

### 5.1 テンプレート優先

ミッションボードの文面は定型である。構造抽出に成功したケースではテンプレート差し込みで訳出する。

```text
構造抽出 成功 → テンプレート適用（決定的・出力が揺れない）
構造抽出 失敗 → 既存の翻訳経路へフォールバック
```

商品名・星系名は既存辞書を参照する。

### 5.2 キャッシュ

正規化後の行テキストをキーとして訳文をキャッシュする。スクロールにより同一行が繰り返し再認識されるため、キャッシュがないと同じ文を反復翻訳する。

### 5.3 表示要件

| 要件 | 内容 |
|---|---|
| 単位 | 行単位の不透明ボックス。画面全体の被覆は禁止 |
| 高さ | 原文の行高を超えない。超えると追従時にずれる |
| ウィンドウ | クリック透過の最前面レイヤー（Windows: `WS_EX_LAYERED \| WS_EX_TRANSPARENT`） |
| ゲーム設定 | **ボーダレスウィンドウ必須。**排他フルスクリーンでは重畳できない |

日本語は英字より字幅が広い。実際の行高に収まるかは実機の解像度で検証する。

---

## 6. ミッション解析

### 6.1 セッション制

```text
[監視開始] → キャプチャ・認識 → [監視停止]
```

常時稼働しない。ミッションボードを開いている間のみ実行する。

`MissionSession`は`captured_at`を保持する。ミッションボードは一定時間で更新されるため、古いセッションの候補はconfidenceを下げるか提示しない。

### 6.2 Fingerprint

```text
fingerprint = SHA256(
    mission_type + destination_system + commodity + count + faction
)
```

**`reward`を含めてはならない。**桁区切り・接尾辞・字形（`1`/`7`、`0`/`8`）の誤読が最も起きやすいフィールドであり、1文字の揺れが重複登録を招く。重複排除が失敗すると、実在しない組み合わせをスタッキング候補として推奨する。

`reward`はfingerprintの外に置く。同一fingerprintに対して複数の値が観測された場合、**最多出現値を採用**する。スクロールにより同一ミッションが複数フレームに現れるため、投票のサンプルは自然に集まる。

### 6.3 値の検証

| フィールド | 検証 |
|---|---|
| `count` | 現在の船の積載量以下。超過は`parse_failed` |
| `reward` | 桁数の上限を設定。配送ミッションで7桁超は稀 |

範囲外の値は破棄する。**推測で補完しない。**

### 6.4 データモデル

```sql
CREATE TABLE mission_sessions (
    session_id     BIGSERIAL PRIMARY KEY,
    station_id     BIGINT,
    system_address BIGINT,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ,
    frame_count    INTEGER NOT NULL DEFAULT 0,
    ocr_count      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE mission_observations (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          BIGINT NOT NULL REFERENCES mission_sessions(session_id),
    fingerprint         TEXT NOT NULL,
    mission_type        TEXT,
    destination_raw     TEXT,
    destination_system  BIGINT,
    resolution_status   TEXT NOT NULL,
    commodity_id        TEXT,
    count               INTEGER,
    reward              BIGINT,
    faction             TEXT,
    observed_at         TIMESTAMPTZ NOT NULL,
    raw_text            TEXT NOT NULL
);
CREATE INDEX idx_mission_obs_fp ON mission_observations (fingerprint);

CREATE TABLE mission_records (
    mission_id       BIGINT PRIMARY KEY,
    fingerprint      TEXT,
    mission_type     TEXT NOT NULL,
    faction          TEXT,
    origin_system    BIGINT,
    dest_system      BIGINT,
    commodity_id     TEXT,
    count            INTEGER,
    reward           BIGINT,
    reputation_at_accept TEXT,
    accepted_at      TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ,
    outcome          TEXT NOT NULL
);
```

`raw_text`を保持する。正規化ルールを後から変更して再解析できるようにするためであり、Journalのraw payloadを保持するのと同じ原則である。

### 6.5 精度測定

`MissionAccepted`イベントと`mission_observations`を突き合わせ、OCRの精度を測定する。

- fingerprint一致率
- `reward`一致率
- `count`一致率
- Mission抽出再現率
- 重複登録率

**金策評価に接続する前に、この数字を確認する。**精度が不明なまま接続すると、推奨が外れた際に原因をOCR/Parserと評価モデルに分離できない。

### 6.6 状態

ミッション観測は`measured`にならない。OCR結果は観測であり`estimated`が上限。`MissionAccepted`が発生して初めて確定情報となる。

---

## 7. 固有名詞の解決

### 7.1 3段階

```text
完全一致        → resolved。confidence 1.0
編集距離 ≤ 2    → candidate。確定しない。ユーザー確認または保留
それ以外        → unresolved。情報を出さない
```

曖昧一致を緩めると別の星系に解決する。距離も報酬評価もその星系で計算されるため、誤りが静かに伝播する。

### 7.2 正規化

EDの命名規則を利用する。

- プレフィックス（`HIP` `Col 285 Sector` `Synuefe` 等）は有限。辞書で正規化してから比較する
- 数字部分は誤読が多い。桁数が異なるものは候補から除外する

### 7.3 状態の区別

| 状態 | 意味 | 対処 |
|---|---|---|
| `unresolved` | 名前を解決できない | OCR・正規化の問題 |
| `resolved_no_data` | 解決したが静的DBに情報がない | データの問題。未訪問星系では通常発生する |

座標が判明していれば距離は算出できるが、到着星からの距離やパッドサイズは出せない。両者を混同しない。

---

## 8. 情報表示

### 8.1 画面種別

| 画面 | 表示する情報 |
|---|---|
| ミッションボード | 現在地からのジャンプ数、到着星からの距離、着陸パッド |
| システムマップ・探査 | 重力、大気、生体シグナル |

画面種別の自動判定は行わない。**セッション開始時にユーザーが選択する。**自動判定は誤検出時の挙動が読めない。

### 8.2 行内表示の制約

行内オーバーレイは原文の行高を超えられない。詳細は別パネルに送る。

```text
行内   金 128t を配送 → LTT 9455 · 8J · 12,400 Ls
別パネル  パッドL可 / 実効Cr/h / 過去実績
```

行内にはボードを見ながら足切りできる最小限のみを置く。

---

## 9. フェーズ計画

### Phase A — 静止画

- 単一フレームの前処理・OCR・行分割
- ミッション行の構造抽出
- fingerprint生成

Exit: ミッションボードの静止画から`mission_type` / `commodity` / `count`が安定して抽出できる

### Phase B — 連番フレーム

- 追従ループ（dy算出）
- 差分による再認識トリガ
- 重複排除
- 切れ行の除外

Exit: 連番静止画に対してスクロールを再現し、重複なく全ミッションを抽出できる

### Phase C — オーバーレイ

- クリック透過ウィンドウ
- 行単位の訳文表示
- スクロール中の非表示制御
- 翻訳キャッシュ

Exit: 実機でスクロールしても訳文がずれない

### Phase D — 精度測定

- `MissionAccepted`との突き合わせ
- fingerprint / reward / countの一致率

Exit: 一致率が測定できている。数値の良否によって次に進むかを判断する

### Phase E — 固有名詞解決

- 正規化と3段階の解決
- 解決率の測定

Exit: 解決率が測定できている

### Phase F — 金策評価への接続

Phase DとEの測定値が実用水準にある場合のみ着手する。

---

## 10. テスト

**追従**

- 静止時に`dy`が0で、再認識が発生しない
- 一様スクロールで`dy`が正しく算出される
- ページ遷移で相関スコアが低下し、再認識が走る
- 要求キューが2段以上に積まれない

**ミッション解析**

- `reward`の1文字違いでfingerprintが変化しない
- 同一fingerprintに複数rewardが観測された場合、最多値が採用される
- 積載量を超える`count`が破棄される
- キャプチャ端に接する行が処理されない

**解決**

- 完全一致が`resolved`になる
- 編集距離3以上が`unresolved`になる
- 桁数の異なる数字を含む候補が除外される
- `resolved_no_data`と`unresolved`が区別される

**表示**

- 訳文ボックスが原文の行高を超えない
- スクロール中にオーバーレイが非表示になる
- 切れ行に訳文が表示されない

---

## 11. 設計原則

1. **追従と認識を分離する。**同一ループで処理しない。
2. **時間周期で再認識しない。**変化を検出したときのみ実行する。
3. **誤読しやすいフィールドを同一性の根拠にしない。**rewardはfingerprintに含めない。
4. **推測で補完しない。**検証に失敗した値は破棄する。
5. **切れた行は処理しない。**翻訳もミッション解析も行わない。
6. **曖昧一致で確定しない。**解決できなければ情報を出さない。
7. **精度を測ってから接続する。**OCR精度が不明なまま金策評価に繋がない。
8. **OCR結果は`measured`にならない。**`MissionAccepted`で初めて確定する。
9. **原文を保持する。**正規化ルールを後から変更して再解析できるようにする。
10. **入力自動化を行わない。**読み取りと表示のみ。
