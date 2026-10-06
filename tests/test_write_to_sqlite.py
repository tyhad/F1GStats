"""Tes write_to_sqlite: transaksi tunggal, replace per season, rollback, schema_version."""
import sqlite3

import pytest

import fetch_f1_data as f

TABLES = (
    "meta", "sessions", "driver_standings", "constructor_standings",
    "starting_grid", "schedule_full", "race_results", "data_health", "qualifying_results",
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


# --- data_health + gerbang validasi -------------------------------------------------

DETAILS_OK = [{"id": "V1", "status": "ok", "message": "fine"}]
DETAILS_FAIL = [{"id": "V3", "status": "fail", "message": "ANT: hasil 1 vs standings 2"}]


def _split(payload):
    payload = dict(payload)
    return payload.pop("season"), payload


def _health_rows(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT season, status, details_json FROM data_health ORDER BY id").fetchall()
    finally:
        conn.close()


def test_ok_writes_data_and_health_in_same_run(tmp_path):
    import json
    db = str(tmp_path / "x.sqlite")
    season, payload = _split(_payload())
    assert f.write_or_reject(db, season, payload, "ok", DETAILS_OK) == 0
    assert _counts(db)["race_results"] == 4
    rows = _health_rows(db)
    assert len(rows) == 1 and rows[0][:2] == (2026, "ok")
    assert json.loads(rows[0][2]) == DETAILS_OK


def test_warn_still_writes_data(tmp_path):
    db = str(tmp_path / "x.sqlite")
    season, payload = _split(_payload())
    assert f.write_or_reject(db, season, payload, "warn", DETAILS_OK) == 0
    assert _counts(db)["race_results"] == 4
    assert _health_rows(db)[0][1] == "warn"


def test_fail_leaves_data_tables_untouched_and_returns_2(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db, n_rounds=2)
    before = _snapshot(db)
    before.pop("meta")  # last_fetched_at tidak boleh berubah juga; dicek terpisah di bawah
    meta_before = _snapshot(db)["meta"]

    season, payload = _split(_payload(n_rounds=5, drivers=("XXX", "YYY", "ZZZ")))
    assert f.write_or_reject(db, season, payload, "fail", DETAILS_FAIL) == 2

    after = _snapshot(db)
    assert after.pop("meta") == meta_before
    after.pop("data_health", None)
    before.pop("data_health", None)
    assert after == before
    rows = _health_rows(db)
    assert len(rows) == 1 and rows[0][1] == "fail"


def test_fail_on_fresh_database_creates_only_health_row(tmp_path):
    db = str(tmp_path / "fresh.sqlite")
    season, payload = _split(_payload())
    assert f.write_or_reject(db, season, payload, "fail", DETAILS_FAIL) == 2
    counts = _counts(db)
    assert counts["race_results"] == 0 and counts["driver_standings"] == 0
    assert len(_health_rows(db)) == 1


def test_each_run_adds_one_health_row(tmp_path):
    db = str(tmp_path / "x.sqlite")
    season, payload = _split(_payload())
    f.write_or_reject(db, season, payload, "ok", DETAILS_OK)
    f.write_or_reject(db, season, payload, "warn", DETAILS_OK)
    f.write_or_reject(db, season, payload, "fail", DETAILS_FAIL)
    assert [r[1] for r in _health_rows(db)] == ["ok", "warn", "fail"]


def test_error_after_health_insert_rolls_back_health_too(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write(db)
    before_health = _health_rows(db)
    bad = _payload(n_rounds=3)
    bad["race_results_rows"] = bad["race_results_rows"] + [bad["race_results_rows"][0]]  # PK ganda
    season = bad.pop("season")
    with pytest.raises(sqlite3.IntegrityError):
        f.write_or_reject(db, season, bad, "ok", DETAILS_OK)
    assert _health_rows(db) == before_health

# --- qualifying_results ---------------------------------------------------------------

def _q(season, rnd, abbr, pos):
    return {"season": season, "round": rnd, "driver_abbr": abbr, "position": pos}


def _write_q(db, qualifying_rows, season=2026, **kw):
    p = _payload(season=season, **{k: v for k, v in kw.items() if k in ("n_rounds", "drivers")})
    p["qualifying_rows"] = qualifying_rows
    f.write_to_sqlite(db, **p)


def _q_rows(db, season=None):
    conn = sqlite3.connect(db)
    try:
        q = "SELECT season, round, driver_abbr, position FROM qualifying_results"
        args = ()
        if season is not None:
            q += " WHERE season = ?"
            args = (season,)
        return sorted(conn.execute(q + " ORDER BY season, round, position", args).fetchall())
    finally:
        conn.close()


def test_qualifying_rows_are_written(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write_q(db, [_q(2026, 1, "AAA", 1), _q(2026, 1, "BBB", 2)])
    assert _q_rows(db) == [(2026, 1, "AAA", 1), (2026, 1, "BBB", 2)]


def test_qualifying_replaced_per_season_not_upserted(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write_q(db, [_q(2025, 1, "OLD", 1)], season=2025)
    _write_q(db, [_q(2026, 1, "AAA", 1), _q(2026, 2, "AAA", 1)])
    _write_q(db, [_q(2026, 1, "AAA", 2)])   # round 2 hilang dari API -> harus ikut hilang
    assert _q_rows(db, 2026) == [(2026, 1, "AAA", 2)]
    assert _q_rows(db, 2025) == [(2025, 1, "OLD", 1)]  # season lain tidak tersentuh


def test_qualifying_none_leaves_existing_rows_alone(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write_q(db, [_q(2026, 1, "AAA", 1)])
    _write(db)  # pemanggil lama tanpa qualifying_rows
    assert _q_rows(db, 2026) == [(2026, 1, "AAA", 1)]


def test_qualifying_error_rolls_back_with_everything(tmp_path):
    db = str(tmp_path / "x.sqlite")
    _write_q(db, [_q(2026, 1, "AAA", 1)])
    before = _snapshot(db)
    bad = _payload(n_rounds=4)
    bad["qualifying_rows"] = [_q(2026, 1, "ZZZ", 1), _q(2026, 1, "ZZZ", 2)]  # PK ganda
    with pytest.raises(sqlite3.IntegrityError):
        f.write_to_sqlite(db, **bad)
    assert _snapshot(db) == before