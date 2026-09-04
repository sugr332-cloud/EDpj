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
- supercruiseは `SupercruiseEntry` **または** `FSDJump` を起点として扱う（ジャンプ到着直後は通常SupercruiseEntryが発生しないため）。`duration_seconds`（開始→`SupercruiseExit`）はその後の経過に関わらず有効なタイミングサンプルである
- `reached_known_target`（旧`valid_for_distance_model`）は固定120秒フィルタを使わず、`SupercruiseExit` の後に次の `FSDJump`/`SupercruiseEntry` が来る前に `Docked`/`ApproachBody` に到達したかを記録する。これは「既知の目的地で終わったか」のフラグであり、後述の理由により距離モデルの採否フラグではない
- `route_plot` はNavRoute.jsonをDocked/Market.jsonと同じ相関方式（直近の`NavRoute`イベントとの時刻突合）で読み、完全に飛び切ったルートのみサンプル化する（distance/detour_factorの算出はPhase 1の静的座標データ待ち）

**`arrival_dist_from_star_ls` に関する重要な注意（実データ検証で発覚）:**
この値は `Docked` の `DistFromStarLS`（＝そのステーション/天体が恒星から静的に何LS離れているか）から取得しており、`ApproachBody` 終端の場合はそもそもJournalに当該フィールドが存在しないため`NULL`（`NO_DATA`、推定はしない）のままになる。**これは「SC中に実際に移動した距離」ではない。** SC開始地点の位置も分からないため、Journalのみから「SC移動距離 → 所要時間」の較正モデルを作ることは現状できない。`duration_seconds` 自体（全supercruiseサンプルで有効）はPhase 0-Cの所要時間較正にそのまま使えるが、距離ベースのbucket較正（`SPECIFICATION_V0.4.md` §14.3）を成立させるには別の距離ソース（Spansh静的座標＋SC開始位置の復元など）が必要で、これは未決定・未実装。

`edpj journal backfill` 実行時にPhase 0-A/0-Bの両方が走り、`timing_samples` のセグメント別累計件数（＝所要時間サンプル数）と `supercruise` のreached_known_target件数を表示する。

Phase 0-C（calibration）以降は未着手。距離モデルの扱いについて仕様書側（`SPECIFICATION_V0.4.md` §14.3 / `IMPLEMENTATION_SPEC_V0.2.md` §6.3）の改訂を検討中。

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

`backfill` は次を表示する: files scanned / lines scanned / inserted / skipped duplicate / invalid lines / first event / last event / timing samples（セグメント別累計） / supercruiseのreached_known_target件数 / route_plot samples累計。

## テスト

```bash
pytest
```

## リポジトリ構成

`IMPLEMENTATION_SPEC_V0.2.md` セクション2のレイアウトに従う。Phase 0-A時点で存在するのは `app/db`, `app/journal`, `app/collectors`, `app/state`, `app/cli` と `tests/`, `migrations/`, `data/` のみ。`routing/` `mining/` `bio/` `scoring/` `api/` `frontend/` はPhase 1以降で追加する。
