# EDpj

Elite Dangerous 用の「次の一手」推奨エンジン。現在のゲーム状態（Journal / Status / Cargo / Market）から、Mining と Exobiology を対象に、時間あたり期待クレジットが最も高い次の行動を算出する。設計原則・API・DB定義の正本は `SPECIFICATION_V0.4.md`（内容はv0.5）、実装への落とし込みは `IMPLEMENTATION_SPEC_V0.2.md`（内容はv0.3）を参照。

## 現在の実装状況

**Phase 0-A（Journal + State Files）実装済み。**

- Journal JSON Lines パーサー（`app/journal/parser.py`） — UTC固定、`(file_name, line_number)` で重複排除
- Status.json / Cargo.json / Market.json 読み取り（`app/collectors/state_files.py`） — 欠損/破損時は `NO_DATA` / `STALE` に落とし、プロセスを止めない
- Docked イベントトリガーの Market.json キャプチャ（`app/journal/extractor.py`）
- State reducer（`app/state/reducer.py`, `app/state/persist.py`） — journal + state files を `player_state` / `cargo_state` singleton へ統合
- backfill CLI（`edpj journal backfill --dir <journal_dir>`）

Phase 0-B（timing較正用イベント抽出）以降は未着手。

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

`backfill` は次を表示する: files scanned / lines scanned / inserted / skipped duplicate / invalid lines / first event / last event。

## テスト

```bash
pytest
```

## リポジトリ構成

`IMPLEMENTATION_SPEC_V0.2.md` セクション2のレイアウトに従う。Phase 0-A時点で存在するのは `app/db`, `app/journal`, `app/collectors`, `app/state`, `app/cli` と `tests/`, `migrations/`, `data/` のみ。`routing/` `mining/` `bio/` `scoring/` `api/` `frontend/` はPhase 1以降で追加する。
