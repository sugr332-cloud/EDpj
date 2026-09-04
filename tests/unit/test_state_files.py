from __future__ import annotations

from pathlib import Path

from app.collectors.state_files import read_cargo, read_market, read_status

FIXTURES = Path(__file__).parent.parent / "fixtures" / "state_files"


def test_read_status_ok():
    result = read_status(FIXTURES)
    assert result.status == "ok"
    assert result.data["Flags"] == 1


def test_read_missing_file_is_no_data(tmp_path):
    result = read_status(tmp_path)
    assert result.status == "no_data"
    assert result.data is None


def test_read_truncated_json_is_stale(tmp_path):
    (tmp_path / "Cargo.json").write_text('{"timestamp": "2026-01-01T12:00:00Z", "Inventory": [', encoding="utf-8")
    result = read_cargo(tmp_path)
    assert result.status == "stale"
    assert result.data is None
    assert result.error is not None


def test_read_market_ok():
    result = read_market(FIXTURES)
    assert result.status == "ok"
    assert result.data["MarketID"] == 128666762
