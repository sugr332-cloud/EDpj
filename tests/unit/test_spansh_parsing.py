from __future__ import annotations

from app.collectors.spansh import parse_system_record

# Shape verified against the live Spansh API (GET /api/system/10477373803,
# Sol) — trimmed to the fields parse_system_record actually reads.
SOL_RECORD = {
    "id64": 10477373803,
    "name": "Sol",
    "x": 0.0,
    "y": 0.0,
    "z": 0.0,
    "bodies": [
        {
            "id64": 36028807496337771,
            "name": "Mercury",
            "type": "Planet",
            "subtype": "Metal-rich body",
            "distance_to_arrival": 173.944857,
            "is_main_star": None,
        },
        {"name": "no id64 body"},  # missing id64 -> must be skipped
    ],
    "stations": [
        {
            "market_id": 128016384,
            "name": "Daedalus",
            "type": "Orbis Starport",
            "distance_to_arrival": 173.999,
            "small_pads": 10,
            "medium_pads": 13,
            "large_pads": 6,
            "services": ["Dock", "Market", "Vista Genomics", "Shipyard"],
        },
        {"name": "no market_id station"},  # missing market_id -> must be skipped
    ],
}


def test_parse_system_record_system_row():
    system_row, _, _ = parse_system_record(SOL_RECORD)
    assert system_row["system_address"] == 10477373803
    assert system_row["name"] == "Sol"
    assert system_row["x"] == 0.0
    assert system_row["source"] == "spansh"


def test_parse_system_record_body_rows():
    _, body_rows, _ = parse_system_record(SOL_RECORD)
    assert len(body_rows) == 1  # the id64-less body was skipped
    mercury = body_rows[0]
    assert mercury["body_id64"] == 36028807496337771
    assert mercury["system_address"] == 10477373803
    assert mercury["name"] == "Mercury"
    assert mercury["body_type"] == "Planet"
    assert mercury["sub_type"] == "Metal-rich body"
    assert mercury["distance_to_arrival_ls"] == 173.944857
    # Not present in the system-dump endpoint -- NO_DATA, not guessed.
    assert mercury["gravity"] is None
    assert mercury["radius"] is None
    assert mercury["atmosphere"] is None
    assert mercury["landable"] is None
    assert mercury["rings"] is None


def test_parse_system_record_station_rows():
    _, _, station_rows = parse_system_record(SOL_RECORD)
    assert len(station_rows) == 1  # the market_id-less station was skipped
    daedalus = station_rows[0]
    assert daedalus["station_id"] == 128016384
    assert daedalus["name"] == "Daedalus"
    assert daedalus["landing_pad"] == {"small": 10, "medium": 13, "large": 6}
    assert daedalus["has_vista_genomics"] is True
    assert daedalus["is_fleet_carrier"] is False


def test_parse_system_record_no_bodies_or_stations():
    record = {"id64": 1, "name": "Empty", "x": 0.0, "y": 0.0, "z": 0.0}
    system_row, body_rows, station_rows = parse_system_record(record)
    assert system_row["system_address"] == 1
    assert body_rows == []
    assert station_rows == []
