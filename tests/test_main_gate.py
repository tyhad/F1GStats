"""End-to-end main(): semua fetch di-mock; yang diuji gerbang validasi dan exit code."""
import sqlite3
import sys

import pytest

import fetch_f1_data as f


def _rows(n_rounds):
    """Data konsisten: 2 driver, tiap round 101 poin tidak mungkin dgn 2 driver -> pakai skala 0 poin."""
    results, drivers = [], []
    for rnd in range(1, n_rounds + 1):
        for pos, abbr in enumerate(("AAA", "BBB"), start=1):
            results.append({
                "season": 2026, "round": rnd, "session": "Race", "driver_abbr": abbr,
                "driver_name": abbr, "team_name": "T", "constructor_id": "t", "grid": pos,
                "position": pos, "position_text": str(pos), "points": 0.0,
                "status": "Finished", "is_classified": 1,
            })
    for pos, abbr in enumerate(("AAA", "BBB"), start=1):
        drivers.append({"position": pos, "driver_name": abbr, "driver_abbr": abbr, "team_name": "T",
                        "points": 0.0, "wins": 0, "podiums": 0, "dnf_dns": 0})
    constructors = [{"position": 1, "team_name": "T", "points": 0.0, "wins": 0, "podiums": 0, "dnf_dns": 0}]
    schedule = [{"season": 2026, "round": r, "race_name": f"R{r}", "has_sprint": 0,
                 "race_start_utc": "2026-03-01T12:00:00Z", "sprint_start_utc": None,
                 "status": "completed"} for r in range(1, n_rounds + 1)]
    return results, drivers, constructors, schedule


@pytest.fixture
def patched_main(monkeypatch, tmp_path):
    state = {"n_rounds": 2}

    def fake_results(ergast, season, session):
        return _rows(state["n_rounds"])[0] if session == "Race" else []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(f.fastf1, "get_event_schedule", lambda *a, **k: [])
    monkeypatch.setattr(f.fastf1.Cache, "enable_cache", lambda *a, **k: None)
    monkeypatch.setattr(f, "Ergast", lambda *a, **k: object())
    monkeypatch.setattr(f, "fetch_circuit_names", lambda *a, **k: {})
    monkeypatch.setattr(f, "fetch_sessions", lambda *a, **k: ([], {}, set(), {}))
    monkeypatch.setattr(f, "build_schedule_full", lambda *a, **k: _rows(state["n_rounds"])[3])
    monkeypatch.setattr(f, "fetch_all_race_results", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(f, "fetch_results_rows", fake_results)
    monkeypatch.setattr(f, "fetch_driver_standings", lambda *a, **k: _rows(state["n_rounds"])[1])
    monkeypatch.setattr(f, "fetch_constructor_standings", lambda *a, **k: _rows(state["n_rounds"])[2])
    monkeypatch.setattr(f, "fetch_starting_grid", lambda *a, **k: [])
    monkeypatch.setattr(f, "fetch_qualifying_rows", lambda *a, **k: [
        {"season": 2026, "round": r, "driver_abbr": d, "position": i + 1}
        for r in range(1, state["n_rounds"] + 1) for i, d in enumerate(("AAA", "BBB"))])
    db = str(tmp_path / "out.sqlite")
    monkeypatch.setattr(sys, "argv", ["f1gstats", "--season", "2026", "--output", db])
    return db, state


def _count(db, table):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_main_ok_run_writes_data_and_health(patched_main):
    db, _ = patched_main
    # 2 driver per round: V6 ok; total poin 0 sah; semua konsisten -> ok
    f.main()
    assert _count(db, "race_results") == 4
    assert _count(db, "qualifying_results") == 4
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM data_health").fetchall() == [("ok",)]
    conn.close()


def test_main_forced_fail_exits_2_and_keeps_old_data(patched_main, monkeypatch):
    db, state = patched_main
    f.main()                                    # run pertama: data bagus tertulis
    assert _count(db, "race_results") == 4

    state["n_rounds"] = 5                       # data baru yang "lebih banyak"...
    monkeypatch.setattr(f, "run_checks", lambda *a, **k: (
        "fail", [{"id": "V3", "status": "fail", "message": "dipaksa gagal"}]))  # ...tapi validasi dipaksa fail
    with pytest.raises(SystemExit) as exc:
        f.main()
    assert exc.value.code == 2

    assert _count(db, "race_results") == 4      # tabel data tidak berubah
    assert _count(db, "qualifying_results") == 4
    assert _count(db, "schedule_full") == 2
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute("SELECT status FROM data_health ORDER BY id")] == ["ok", "fail"]
    conn.close()


def test_main_real_v4_failure_blocks_write(patched_main, monkeypatch):
    db, state = patched_main
    f.main()
    # jadwal bilang 3 round completed tapi hasil Race hanya 2 round -> V4 fail (validasi asli, tanpa paksa)
    schedule_3_rounds = _rows(3)[3]
    monkeypatch.setattr(f, "build_schedule_full", lambda *a, **k: schedule_3_rounds)
    with pytest.raises(SystemExit) as exc:
        f.main()
    assert exc.value.code == 2
    assert _count(db, "schedule_full") == 2     # tetap data lama