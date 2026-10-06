"""Tes write_to_sqlite: transaksi tunggal, replace per season, rollback, schema_version."""
import sqlite3

import pytest

import fetch_f1_data as f

TABLES = (
    "meta", "sessions", "driver_standings", "constructor_standings",
    "starting_grid", "schedule_full", "race_results",
)


def _result(season, rnd, session, abbr, points=0.0, pos=1):
    return {
        "season": season, "round": rnd, "session": session, "driver_abbr": abbr,
        "driver_name": abbr, "team_name": "T", "constructor_id": "t", "grid": pos,
        "position": pos, "position_text": str(pos), "points": points,
        "status": "Finished", "is_classified": 1,
    }


def _payload(season=2026, n_rounds=2, drivers=("AAA", "BBB")):
    sessions = [{"round": 1, "race_name": "R1", "session_type": "Race",
                 "start_time_utc": "2026-03-01T12:00:00Z", "circuit_name": "C",
                 "country_flag": "", "round_relation": "previous"}]
    driver_rows = [{"position": i + 1, "driver_name": d, "driver_abbr": d, "team_name": "T",
                    "points": 10.0, "wins": 1, "podiums": 1, "dnf_dns": 0}
                   for i, d in enumerate(drivers)]
    constructor_rows = [{"position": 1, "team_name": "T", "points": 20.0,
                         "wins": 1, "podiums": 2, "dnf_dns": 0}]
    grid_rows = [{"round": 1, "round_relation": "previous", "position": 1, "driver_name": "AAA",
                  "driver_abbr": "AAA", "team_name": "T", "grid_source": "openf1"}]
    schedule_rows = [{"season": season, "round": r, "race_name": f"R{r}", "has_sprint": 0,
                      "race_start_utc": "2026-03-01T12:00:00Z", "sprint_start_utc": None,
                      "status": "completed"} for r in range(1, n_rounds + 1)]
    results = [_result(season, r, "Race", d, pos=i + 1)
               for r in range(1, n_rounds + 1) for i, d in enumerate(drivers)]
    return dict(season=season, sessions=sessions, driver_rows=driver_rows,
                constructor_rows=constructor_rows, starting_grid_rows=grid_rows,
                schedule_full_rows=schedule_rows, race_results_rows=results)


def _write(db, **kw):
    p = _payload(**{k: v for k, v in kw.items() if k in ("season", "n_rounds", "drivers")})
    for k in ("race_results_rows",):
        if k in kw:
            p[k] = kw[k]
    f.write_to_sqlite(db, **p)


def _snapshot(db):
    conn = sqlite3.connect(db)
    try:
        return {t: sorted(conn.execute(f"SELECT * FROM {t}").fetchall(), key=repr) for t in TABLES}
    finally:
        conn.close()


def _counts(db):
    snap = _snapshot(db)
    return {t: len(rows) for t, rows in snap.items()}


def test_schema_version_is_2(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("2",)
    conn.close()


def test_run_twice_gives_identical_row_counts(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db)
    first = _counts(db)
    _write(db)
    assert _counts(db) == first
    assert first["race_results"] == 4 and first["schedule_full"] == 2


def test_replace_not_upsert_removes_stale_rows(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db, n_rounds=3)
    _write(db, n_rounds=2)  # round 3 hilang dari API -> harus ikut hilang
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT MAX(round) FROM race_results").fetchone() == (2,)
    assert conn.execute("SELECT MAX(round) FROM schedule_full").fetchone() == (2,)
    conn.close()


def test_other_seasons_are_left_alone(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db, season=2025)
    _write(db, season=2026)
    conn = sqlite3.connect(db)
    seasons = dict(conn.execute("SELECT season, COUNT(*) FROM race_results GROUP BY season").fetchall())
    assert seasons == {2025: 4, 2026: 4}
    conn.close()


def test_error_midway_rolls_back_everything(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db, n_rounds=2)
    before = _snapshot(db)

    # Data baru yang valid untuk tabel awal, tapi race_results punya PK ganda
    # -> IntegrityError SETELAH sessions/standings/schedule sudah diganti.
    bad = _payload(n_rounds=5, drivers=("XXX", "YYY", "ZZZ"))
    bad["race_results_rows"] = bad["race_results_rows"] + [bad["race_results_rows"][0]]
    with pytest.raises(sqlite3.IntegrityError):
        f.write_to_sqlite(db, **bad)

    assert _snapshot(db) == before  # semua tabel + meta (termasuk last_fetched_at) tak berubah
