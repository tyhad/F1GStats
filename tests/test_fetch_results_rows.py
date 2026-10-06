"""Tes fetch_results_rows tanpa network: Ergast._get di-mock dengan JSON ala Jolpica."""
from unittest.mock import patch

import pytest
from fastf1.ergast import Ergast

import fetch_f1_data as f


def _mrdata(races):
    return {"MRData": {
        "xmlns": "", "series": "f1", "url": "x", "limit": "2000", "offset": "0", "total": "0",
        "RaceTable": {"season": "2026", "Races": races},
    }}


def _result(pos, code, pts, *, grid=1, status="Finished", text=None, team="McLaren"):
    return {
        "number": "1", "position": str(pos), "positionText": text or str(pos), "points": str(pts),
        "Driver": {"driverId": code.lower(), "permanentNumber": "1", "code": code, "url": "u",
                   "givenName": "A", "familyName": code, "dateOfBirth": "2000-01-01",
                   "nationality": "X"},
        "Constructor": {"constructorId": team.lower(), "url": "u", "name": team,
                        "nationality": "British"},
        "grid": str(grid), "laps": "20", "status": status,
    }


def _race(rnd, key, results):
    return {
        "season": "2026", "round": str(rnd), "url": "u", "raceName": f"R{rnd}",
        "Circuit": {"circuitId": "c", "url": "u", "circuitName": "C",
                    "Location": {"lat": "0", "long": "0", "locality": "L", "country": "C"}},
        "date": "2026-03-01", "time": "12:00:00Z", key: results,
    }


def _fetch(payload, session):
    with patch.object(Ergast, "_get", return_value=payload):
        return f.fetch_results_rows(Ergast(), 2026, session)


def test_sprint_empty_returns_empty_list():
    assert _fetch(_mrdata([]), "Sprint") == []


def test_sprint_rows_mapped_per_round():
    payload = _mrdata([
        _race(2, "SprintResults", [
            _result(1, "NOR", 8),
            _result(2, "VER", 7),
            _result(3, "HAM", 0, status="Retired", text="R"),
        ]),
        _race(6, "SprintResults", [_result(1, "PIA", 8)]),
    ])
    rows = _fetch(payload, "Sprint")

    assert [(r["round"], r["driver_abbr"]) for r in rows] == [
        (2, "NOR"), (2, "VER"), (2, "HAM"), (6, "PIA"),
    ]
    assert {r["session"] for r in rows} == {"Sprint"}
    assert {r["season"] for r in rows} == {2026}

    nor = rows[0]
    assert nor["position"] == 1 and nor["is_classified"] == 1 and nor["points"] == 8.0
    assert nor["constructor_id"] == "mclaren" and nor["team_name"] == "McLaren"

    ham = rows[2]  # tidak diklasifikasi
    assert ham["position"] is None and ham["is_classified"] == 0
    assert ham["position_text"] == "R" and ham["points"] == 0.0


def test_sprint_points_sum_per_round():
    pts = [8, 7, 6, 5, 4, 3, 2, 1]
    payload = _mrdata([_race(2, "SprintResults",
                             [_result(i + 1, f"D{chr(65 + i)}{chr(65 + i)}", p) for i, p in enumerate(pts)])])
    assert sum(r["points"] for r in _fetch(payload, "Sprint")) == 36


def test_sprint_network_error_is_not_swallowed():
    with patch.object(Ergast, "_get", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            f.fetch_results_rows(Ergast(), 2026, "Sprint")


def test_race_uses_race_results_key():
    payload = _mrdata([_race(1, "Results", [_result(1, "NOR", 25)])])
    rows = _fetch(payload, "Race")
    assert len(rows) == 1 and rows[0]["session"] == "Race" and rows[0]["points"] == 25.0


def test_invalid_session_raises():
    with pytest.raises(ValueError):
        f.fetch_results_rows(Ergast(), 2026, "Qualifying")


def _paged_server(rounds, key, max_limit=100):
    """Meniru Jolpica: limit dipotong ke max_limit, hasil dipotong per offset (bisa di tengah round)."""
    flat = [(rnd, res) for rnd, results in rounds for res in results]

    def _get(url, params):
        limit = min(int(params.get("limit") or 30), max_limit)
        offset = int(params.get("offset") or 0)
        chunk = flat[offset:offset + limit]
        grouped = {}
        for rnd, res in chunk:
            grouped.setdefault(rnd, []).append(res)
        payload = _mrdata([_race(r, key, rs) for r, rs in grouped.items()])
        payload["MRData"].update({"limit": str(limit), "offset": str(offset), "total": str(len(flat))})
        return payload

    return _get


def test_pagination_collects_all_rows_even_when_round_is_split():
    # 6 round x 22 driver = 132 baris -> halaman 1 (100) berhenti di tengah round 5
    codes = [f"{chr(65 + i // 5)}{chr(65 + i % 5)}{chr(65 + i % 3)}" for i in range(22)]
    rounds = [(rnd, [_result(i + 1, codes[i], 0) for i in range(22)]) for rnd in range(1, 7)]
    with patch.object(Ergast, "_get", side_effect=_paged_server(rounds, "Results")):
        rows = f.fetch_results_rows(Ergast(), 2026, "Race")

    assert len(rows) == 132
    per_round = {}
    for r in rows:
        per_round[r["round"]] = per_round.get(r["round"], 0) + 1
    assert per_round == {rnd: 22 for rnd in range(1, 7)}
    keys = {(r["round"], r["driver_abbr"]) for r in rows}
    assert len(keys) == 132  # tidak ada duplikat PK


def test_fetch_all_race_results_counts_across_pages():
    # 6 round x 22 driver = 132 baris -> halaman 1 (100 baris) berhenti di tengah round 5.
    # Driver AAA selalu P1 (podium), BBB selalu P22 dan DNF ("R"), sisanya P2..P21.
    def grid(rnd):
        rows = [_result(1, "AAA", 25, team="Alpha")]
        for pos in range(2, 22):
            rows.append(_result(pos, f"D{pos:02d}", 0, team="Beta"))
        rows.append(_result(22, "BBB", 0, status="Retired", text="R", team="Beta"))
        return rows

    rounds = [(rnd, grid(rnd)) for rnd in range(1, 7)]
    with patch.object(Ergast, "_get", side_effect=_paged_server(rounds, "Results")):
        driver_stats, constructor_stats = f.fetch_all_race_results(Ergast(), 2026)

    assert driver_stats["AAA"] == {"podiums": 6, "dnf_dns": 0}
    assert driver_stats["BBB"] == {"podiums": 0, "dnf_dns": 6}
    assert driver_stats["D02"] == {"podiums": 6, "dnf_dns": 0}   # P2 tiap round
    assert driver_stats["D03"] == {"podiums": 6, "dnf_dns": 0}   # P3 tiap round
    assert driver_stats["D04"] == {"podiums": 0, "dnf_dns": 0}
    # konstruktor: Alpha 6 podium (P1); Beta 12 podium (P2+P3) dan 6 DNF
    assert constructor_stats["Alpha"] == {"podiums": 6, "dnf_dns": 0}
    assert constructor_stats["Beta"] == {"podiums": 12, "dnf_dns": 6}