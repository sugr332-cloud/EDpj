# EDpj

Elite Dangerous 用の「次の一手」推奨エンジン。現在のゲーム状態（Journal / Status / Cargo / Market）から、Mining と Exobiology を対象に、時間あたり期待クレジットが最も高い次の行動を算出する。設計原則・API・DB定義の正本は `SPECIFICATION_V0.4.md`（内容はv0.5）、実装への落とし込みは `IMPLEMENTATION_SPEC_V0.2.md`（内容はv0.3）を参照。

## 現在の実装状況

**Phase 0-A（Journal + State Files）/ Phase 0-B（Timing Extraction）実装済み。**

Phase 0-A:
- Journal JSON Lines パーサー（`app/journal/parser.py`） — UTC固定、`(file_name, line_number)` で重複排除
- Status.json / Cargo.json / Market.json 読み取り（`app/collectors/state_files.py`） — 欠損/破損時は `NO_DATA` / `STALE` に落とし、プロセスを止めない
- Docked イベントトリガーの Market.json キャプチャ（`app/journal/extractor.py`）
- State reducer（`app/state/reducer.py`, `app/state/persist.py`） — journal + state files を `player_state` / `cargo_state` singleton へ統合

Phase 0-B（`app/journal/timing.py`, `app/db/models/timing.py`）:
- セグメント種別: `jump` / `supercruise` / `dock` / `undock` / `descent` / `ascent` / `mining_cycle` / `bio_sample` / `route_plot`
- supercruiseは `SupercruiseEntry` **または** `FSDJump` を起点として扱う（ジャンプ到着直後は通常SupercruiseEntryが発生しないため）
- 距離モデル対象の採否は固定120秒フィルタを使わず、`SupercruiseExit` の後に次の `FSDJump`/`SupercruiseEntry` が来る前に `Docked`/`ApproachBody` に到達したかで判定する
- `distance_ls` は `Docked` の `DistFromStarLS` からのみ取得し、取れない場合は推定せず `NULL`（`NO_DATA`）のままにする
- `route_plot` はNavRoute.jsonをDocked/Market.jsonと同じ相関方式（直近の`NavRoute`イベントとの時刻突合）で読み、完全に飛び切ったルートのみサンプル化する（distance/detour_factorの算出はPhase 1の静的座標データ待ち）

`edpj journal backfill` 実行時にPhase 0-A/0-Bの両方が走り、`timing_samples` のセグメント別累計件数と `supercruise` の距離モデル対象件数（SC interval Go/No-Go判定に使う数値）を表示する。

Phase 0-C（calibration）以降は未着手。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

DB接続は環境変数 `EDPJ_DATABASE_URL` で切り替える（デフォルトは `sqlite:///./data/edpj.db`）。PostgreSQLを使う場合:

```bash
docker compose up -d
export EDPJ_DATABASE_URL=postgresql+psycopg://edpj:edpj@localhost:5432/edpj
alembic upgrade head
```

SQLite利用時は `edpj` コマンド初回実行時に自動でテーブルが作成される（`init_db()`）。

## CLI

```bash
edpj journal backfill --dir <Elite Dangerous journal directory>
edpj state show
```

`backfill` は次を表示する: files scanned / lines scanned / inserted / skipped duplicate / invalid lines / first event / last event / timing samples（セグメント別累計、うちsupercruiseは距離モデル対象件数も） / route_plot samples累計。

## テスト

```bash
pytest
```

## リポジトリ構成

`IMPLEMENTATION_SPEC_V0.2.md` セクション2のレイアウトに従う。Phase 0-A時点で存在するのは `app/db`, `app/journal`, `app/collectors`, `app/state`, `app/cli` と `tests/`, `migrations/`, `data/` のみ。`routing/` `mining/` `bio/` `scoring/` `api/` `frontend/` はPhase 1以降で追加する。
