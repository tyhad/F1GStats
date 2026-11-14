"""
Phase 8, Step 8: grid OpenF1 yang belum terbit adalah informasi, bukan peringatan.

404 atau daftar kosong dari OpenF1 (sessions atau starting_grid) = grid resmi belum dipublikasikan -> satu baris
[INFO], tanpa [WARN]. Kegagalan sungguhan (timeout, error server, jawaban tak terbaca) tetap [WARN].
Perilaku dan data yang ditulis tidak berubah: grid tetap jatuh ke urutan Qualifying (`qualifying_fallback`).
Semua tes offline: `requests.get` dan Ergast di-mock.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
import requests

import fetch_f1_data as f

INFO_NO_GRID = "[INFO] OpenF1 has no grid for round 18 yet; using the qualifying order, which ignores grid penalties"


# ---------------------------------------------------------------------------
# Jawaban OpenF1 palsu
# ---------------------------------------------------------------------------

def _resp(status=200, data=None, raw=None):
    """requests.Response sungguhan, supaya raise_for_status() dan json() berperilaku seperti aslinya."""
    r = requests.Response()
    r.status_code = status
    r.url = "https://api.openf1.org/v1/test"
    r._content = raw if raw is not None else json.dumps(data if data is not None else []).encode()
    return r


SESSIONS = [{"session_key": 9999}]
GRID = [{"driver_number": 1, "position": 1}, {"driver_number": 12, "position": 2}]
DRIVERS = [
    {"driver_number": 1, "full_name": "MAX VERSTAPPEN", "name_acronym": "VER", "team_name": "Red Bull Racing"},
    {"driver_number": 12, "full_name": "KIMI ANTONELLI", "name_acronym": "ANT", "team_name": "Mercedes"},
]
NOT_FOUND = _resp(404, {"detail": "No results found."})


def _openf1(sessions=None, grid=None, drivers=None):
    """Pengganti requests.get: tiap endpoint menjawab sesuai argumen (objek Response atau exception)."""
    answers = {
        "sessions": _resp(200, SESSIONS) if sessions is None else sessions,
        "starting_grid": _resp(200, GRID) if grid is None else grid,
        "drivers": _resp(200, DRIVERS) if drivers is None else drivers,
    }

    def fake_get(url, params=None, timeout=None):
        answer = answers[url.rsplit("/", 1)[1]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fake_get


def _run_fetch(fake_get, capsys, round_no=18, location="Singapore"):
    """fetch_starting_grid untuk satu round, dengan Qualifying (fallback) dari Ergast palsu."""
    quali = pd.DataFrame([
        {"position": 1, "givenName": "Max", "familyName": "Verstappen", "driverCode": "VER", "constructorName": "Red Bull"},
        {"position": 2, "givenName": "Kimi", "familyName": "Antonelli", "driverCode": "ANT", "constructorName": "Mercedes"},
    ])
    ergast = SimpleNamespace(get_qualifying_results=lambda **kw: SimpleNamespace(content=[quali]))
    with patch.object(f.requests, "get", side_effect=fake_get):
        rows = f.fetch_starting_grid(ergast, 2026, {round_no}, {round_no: "next"}, {round_no: location} if location else {})
    return rows, capsys.readouterr().out


def _lines(out, tag):
    return [line.strip() for line in out.splitlines() if tag in line]


FALLBACK_ROWS = [
    {"round": 18, "round_relation": "next", "position": 1, "driver_name": "Max Verstappen", "driver_abbr": "VER", "team_name": "Red Bull", "grid_source": "qualifying_fallback"},
    {"round": 18, "round_relation": "next", "position": 2, "driver_name": "Kimi Antonelli", "driver_abbr": "ANT", "team_name": "Mercedes", "grid_source": "qualifying_fallback"},
]


# ---------------------------------------------------------------------------
# Belum terbit: [INFO], bukan [WARN]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label, fake", [
    ("starting_grid 404", _openf1(grid=NOT_FOUND)),
    ("starting_grid daftar kosong", _openf1(grid=_resp(200, []))),
    ("sessions 404", _openf1(sessions=NOT_FOUND)),
    ("sessions daftar kosong", _openf1(sessions=_resp(200, []))),
])
def test_missing_grid_is_info_not_warn(label, fake, capsys):
    rows, out = _run_fetch(fake, capsys)

    assert _lines(out, "[WARN]") == [], f"{label}: tidak boleh ada [WARN]\n{out}"
    assert _lines(out, "OpenF1 has no grid") == [f"  {INFO_NO_GRID}".strip()]
    assert rows == FALLBACK_ROWS


def test_info_line_names_the_round_and_appears_once_per_round(capsys):
    quali = pd.DataFrame([{"position": 1, "givenName": "A", "familyName": "Bee", "driverCode": "BEE", "constructorName": "T"}])
    ergast = SimpleNamespace(get_qualifying_results=lambda **kw: SimpleNamespace(content=[quali]))
    with patch.object(f.requests, "get", side_effect=_openf1(grid=NOT_FOUND)):
        f.fetch_starting_grid(ergast, 2026, {17, 18}, {17: "now", 18: "next"}, {17: "Monza", 18: "Singapore"})
    out = capsys.readouterr().out

    info = _lines(out, "OpenF1 has no grid")
    assert info == [
        "[INFO] OpenF1 has no grid for round 17 yet; using the qualifying order, which ignores grid penalties",
        "[INFO] OpenF1 has no grid for round 18 yet; using the qualifying order, which ignores grid penalties",
    ]
    assert _lines(out, "[WARN]") == []


def test_not_published_status_and_no_rows():
    with patch.object(f.requests, "get", side_effect=_openf1(grid=NOT_FOUND)):
        result = f.fetch_openf1_starting_grid(2026, "Singapore")
    assert result.rows is None
    assert result.status == f.GRID_NOT_PUBLISHED


# ---------------------------------------------------------------------------
# Kegagalan sungguhan: tetap [WARN]
# ---------------------------------------------------------------------------

REAL_FAILURES = [
    ("timeout pada starting_grid", _openf1(grid=requests.exceptions.Timeout("read timed out"))),
    ("koneksi putus pada starting_grid", _openf1(grid=requests.exceptions.ConnectionError("reset"))),
    ("500 pada starting_grid", _openf1(grid=_resp(500, {"detail": "boom"}))),
    ("503 pada starting_grid", _openf1(grid=_resp(503, {"detail": "unavailable"}))),
    ("429 pada starting_grid", _openf1(grid=_resp(429, {"detail": "slow down"}))),
    ("timeout pada sessions", _openf1(sessions=requests.exceptions.Timeout("read timed out"))),
    ("500 pada sessions", _openf1(sessions=_resp(500, {}))),
    ("jawaban starting_grid bukan JSON", _openf1(grid=_resp(200, raw=b"<html>gateway error</html>"))),
    ("jawaban starting_grid bukan daftar", _openf1(grid=_resp(200, {"detail": "oops"}))),
    ("jawaban sessions bukan JSON", _openf1(sessions=_resp(200, raw=b"not json"))),
    ("sesi tanpa session_key", _openf1(sessions=_resp(200, [{"unexpected": True}]))),
    ("drivers 404 padahal grid ada", _openf1(drivers=NOT_FOUND)),
    ("drivers 500", _openf1(drivers=_resp(500, {}))),
    ("grid tanpa satu pun driver yang cocok", _openf1(drivers=_resp(200, [{"driver_number": 99, "name_acronym": "ZZZ"}]))),
]


@pytest.mark.parametrize("label, fake", REAL_FAILURES, ids=[label for label, _ in REAL_FAILURES])
def test_real_failure_stays_warn(label, fake, capsys):
    rows, out = _run_fetch(fake, capsys)

    assert _lines(out, "[WARN]"), f"{label}: harus ada [WARN]\n{out}"
    assert _lines(out, "OpenF1 has no grid") == [], f"{label}: bukan 'belum terbit'\n{out}"
    # Perilaku tidak berubah: tetap jatuh ke urutan Qualifying.
    assert rows == FALLBACK_ROWS


def test_failed_status_and_no_rows():
    with patch.object(f.requests, "get", side_effect=_openf1(grid=requests.exceptions.Timeout("t"))):
        result = f.fetch_openf1_starting_grid(2026, "Singapore")
    assert result.rows is None
    assert result.status == f.GRID_FAILED


def test_missing_location_is_a_warning(capsys):
    """Round tanpa lokasi di schedule: data yang kurang, bukan 'belum terbit' -> tetap [WARN]."""
    rows, out = _run_fetch(_openf1(), capsys, location=None)
    assert _lines(out, "[WARN]")
    assert _lines(out, "OpenF1 has no grid") == []
    assert rows == FALLBACK_ROWS


# ---------------------------------------------------------------------------
# Yang tidak berubah
# ---------------------------------------------------------------------------

def test_published_grid_unchanged(capsys):
    rows, out = _run_fetch(_openf1(), capsys)

    assert _lines(out, "[WARN]") == []
    assert _lines(out, "OpenF1 has no grid") == []
    assert _lines(out, "[INFO]") == ["[INFO] Round 18: starting grid dari OpenF1 (actual, post-penalty)"]
    assert rows == [
        {"round": 18, "round_relation": "next", "position": 1, "driver_name": "Max Verstappen", "driver_abbr": "VER", "team_name": "Red Bull Racing", "grid_source": "openf1"},
        {"round": 18, "round_relation": "next", "position": 2, "driver_name": "Kimi Antonelli", "driver_abbr": "ANT", "team_name": "Mercedes", "grid_source": "openf1"},
    ]


def test_data_written_is_the_same_for_not_published_and_failed(capsys):
    """Pesannya beda (INFO vs WARN), datanya persis sama: itu yang dijanjikan Step 8."""
    not_published, _ = _run_fetch(_openf1(grid=NOT_FOUND), capsys)
    failed, _ = _run_fetch(_openf1(grid=requests.exceptions.Timeout("t")), capsys)
    assert not_published == failed == FALLBACK_ROWS


def test_openf1_get_returns_the_list_on_success():
    with patch.object(f.requests, "get", side_effect=_openf1()):
        assert f._openf1_get("sessions", {"year": 2026}) == SESSIONS


def test_openf1_get_404_is_not_found_not_a_generic_http_error():
    with patch.object(f.requests, "get", side_effect=_openf1(grid=NOT_FOUND)):
        with pytest.raises(f.OpenF1NotFound):
            f._openf1_get("starting_grid", {"session_key": 9999})


def test_openf1_get_other_http_errors_stay_http_errors():
    with patch.object(f.requests, "get", side_effect=_openf1(grid=_resp(500, {}))):
        with pytest.raises(requests.HTTPError):
            f._openf1_get("starting_grid", {"session_key": 9999})


def test_info_line_does_not_change_when_qualifying_is_also_missing(capsys):
    """Kalau Qualifying juga belum ada, perilaku lama: tidak ada baris, tidak ada error; INFO tetap sekali."""
    ergast = SimpleNamespace(get_qualifying_results=lambda **kw: SimpleNamespace(content=[]))
    with patch.object(f.requests, "get", side_effect=_openf1(grid=NOT_FOUND)):
        rows = f.fetch_starting_grid(ergast, 2026, {18}, {18: "next"}, {18: "Singapore"})
    out = capsys.readouterr().out
    assert rows == []
    assert len(_lines(out, "OpenF1 has no grid")) == 1
    assert _lines(out, "[WARN]") == []
