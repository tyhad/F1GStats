"""Tes fetch_qualifying_rows tanpa network: Ergast._get di-mock (JSON ala Jolpica, batas 100 baris)."""
from unittest.mock import patch

import pytest
from fastf1.ergast import Ergast

import fetch_f1_data as f
from test_fetch_results_rows import _mrdata, _paged_server, _race


def _q_result(pos, code, *, q1="1:20.000", q2="1:19.500", q3="1:19.000"):
    return {
        "number": "1", "position": str(pos),
        "Driver": {"driverId": code.lower(), "permanentNumber": "1", "code": code, "url": "u",
                   "givenName": "A", "familyName": code, "dateOfBirth": "2000-01-01",
                   "nationality": "X"},
        "Constructor": {"constructorId": "t", "url": "u", "name": "T", "nationality": "British"},
        "Q1": q1, "Q2": q2, "Q3": q3,
    }


def _fetch(payload):
    with patch.object(Ergast, "_get", return_value=payload):
        return f.fetch_qualifying_rows(Ergast(), 2026)


def test_empty_season_returns_empty_list():
    assert _fetch(_mrdata([])) == []


def test_rows_mapped_per_round():
    payload = _mrdata([
        _race(1, "QualifyingResults", [_q_result(1, "NOR"), _q_result(2, "VER"), _q_result(3, "HAM")]),
        _race(3, "QualifyingResults", [_q_result(1, "PIA")]),
    ])
    rows = _fetch(payload)
    assert rows == [
        {"season": 2026, "round": 1, "driver_abbr": "NOR", "position": 1},
        {"season": 2026, "round": 1, "driver_abbr": "VER", "position": 2},
        {"season": 2026, "round": 1, "driver_abbr": "HAM", "position": 3},
        {"season": 2026, "round": 3, "driver_abbr": "PIA", "position": 1},
    ]


def test_driver_without_q2_q3_still_has_position():
    payload = _mrdata([_race(1, "QualifyingResults", [
        _q_result(1, "NOR"), _q_result(19, "STR", q2="", q3=""), _q_result(20, "BOT", q1="", q2="", q3="")])])
    by_abbr = {r["driver_abbr"]: r["position"] for r in _fetch(payload)}
    assert by_abbr == {"NOR": 1, "STR": 19, "BOT": 20}


def test_pagination_collects_all_rows_even_when_round_is_split():
    codes = [f"{chr(65 + i // 5)}{chr(65 + i % 5)}{chr(65 + i % 3)}" for i in range(22)]
    rounds = [(rnd, [_q_result(i + 1, codes[i]) for i in range(22)]) for rnd in range(1, 7)]  # 132 baris
    with patch.object(Ergast, "_get", side_effect=_paged_server(rounds, "QualifyingResults")):
        rows = f.fetch_qualifying_rows(Ergast(), 2026)
    assert len(rows) == 132
    assert len({(r["round"], r["driver_abbr"]) for r in rows}) == 132  # tidak ada duplikat PK
    per_round = {}
    for r in rows:
        per_round[r["round"]] = per_round.get(r["round"], 0) + 1
    assert per_round == {rnd: 22 for rnd in range(1, 7)}


def test_network_error_is_not_swallowed():
    with patch.object(Ergast, "_get", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            f.fetch_qualifying_rows(Ergast(), 2026)
