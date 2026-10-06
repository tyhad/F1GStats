"""Tes validation.run_checks (V1-V6) dengan fixture buatan tangan. Tanpa network."""
import copy

import validation as v

FULL_GP = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1, 0, 0]       # total 101
HALF_GP = [19, 14, 12, 10, 8, 6, 4, 3, 2, 1, 0, 0]        # total 79 (race dipersingkat)
SPRINT = [8, 7, 6, 5, 4, 3, 2, 1, 0, 0, 0, 0]             # total 36
ABBRS = [c * 3 for c in "ABCDEFGHIJKL"]                    # 12 driver, semua ^[A-Z]{3}$
TEAMS = {abbr: f"Team{i // 2}" for i, abbr in enumerate(ABBRS)}  # 6 tim x 2 driver


def build(gp_rounds=None, sprint_rounds=(2,), completed=(1, 2), scheduled=(3,)):
    """Bangun satu set data yang konsisten (standings diturunkan dari hasil)."""
    gp_rounds = gp_rounds or {1: FULL_GP, 2: FULL_GP}
    results, schedule = [], []
    for rnd, pts in gp_rounds.items():
        for i, abbr in enumerate(ABBRS):
            results.append({"season": 2026, "round": rnd, "session": "Race", "driver_abbr": abbr,
                            "team_name": TEAMS[abbr], "position": i + 1, "points": float(pts[i])})
    for rnd in sprint_rounds:
        for i, abbr in enumerate(ABBRS):
            results.append({"season": 2026, "round": rnd, "session": "Sprint", "driver_abbr": abbr,
                            "team_name": TEAMS[abbr], "position": i + 1, "points": float(SPRINT[i])})
    totals = {a: 0.0 for a in ABBRS}
    for r in results:
        totals[r["driver_abbr"]] += r["points"]
    drivers = [{"position": i + 1, "driver_abbr": a, "team_name": TEAMS[a], "points": totals[a]}
               for i, a in enumerate(ABBRS)]
    team_pts = {}
    for a in ABBRS:
        team_pts[TEAMS[a]] = team_pts.get(TEAMS[a], 0.0) + totals[a]
    constructors = [{"position": i + 1, "team_name": t, "points": p}
                    for i, (t, p) in enumerate(team_pts.items())]
    for rnd in list(completed) + list(scheduled):
        schedule.append({"season": 2026, "round": rnd, "has_sprint": 1 if rnd in sprint_rounds else 0,
                         "status": "completed" if rnd in completed else "scheduled"})
    return dict(driver_rows=drivers, constructor_rows=constructors,
                race_results_rows=results, schedule_full_rows=schedule)


def run(data):
    status, details = v.run_checks(**data)
    return status, {d["id"]: d for d in details}


def test_ok_case_all_checks_ok():
    status, by_id = run(build())
    assert status == "ok"
    assert sorted(by_id) == ["V1", "V2", "V3", "V4", "V5", "V6"]
    assert all(d["status"] == "ok" for d in by_id.values())
    assert all(isinstance(d["message"], str) and d["message"] for d in by_id.values())


def test_v1_points_mismatch_is_warn():
    data = build()
    data["constructor_rows"][0]["points"] += 5
    status, by_id = run(data)
    assert by_id["V1"]["status"] == "warn"
    assert status == "warn"
    assert all(by_id[k]["status"] == "ok" for k in ("V2", "V3", "V4", "V5", "V6"))


def test_v2_shortened_race_total_79_is_ok():
    status, by_id = run(build(gp_rounds={1: FULL_GP, 2: HALF_GP}))
    assert by_id["V2"]["status"] == "ok"
    assert status == "ok"


def test_v2_impossible_total_is_warn():
    odd = [25, 18, 15, 12, 10, 8, 6, 4, 2, 5, 0, 0]  # total 105
    status, by_id = run(build(gp_rounds={1: FULL_GP, 2: odd}))
    assert by_id["V2"]["status"] == "warn"
    assert "2" in by_id["V2"]["message"]
    assert status == "warn"


def test_v2_sprint_total_must_be_36_or_0():
    data = build()
    for r in data["race_results_rows"]:
        if r["session"] == "Sprint" and r["driver_abbr"] == "AAA":
            r["points"] = 7.0  # total sprint jadi 35
    status, by_id = run(data)
    assert by_id["V2"]["status"] == "warn"


def test_v3_driver_points_mismatch_is_fail():
    data = build()
    data["driver_rows"][3]["points"] += 1
    status, by_id = run(data)
    assert by_id["V3"]["status"] == "fail"
    assert "DDD" in by_id["V3"]["message"]
    assert status == "fail"


def test_v4_missing_round_is_fail():
    # jadwal bilang round 1-3 selesai, tapi hasil Race baru ada untuk round 1-2
    status, by_id = run(build(completed=(1, 2, 3), scheduled=()))
    assert by_id["V4"]["status"] == "fail"
    assert "3" in by_id["V4"]["message"]
    assert by_id["V3"]["status"] == "ok"
    assert status == "fail"


def test_v4_results_for_round_not_completed_is_fail():
    status, by_id = run(build(completed=(1,), scheduled=(2, 3)))
    assert by_id["V4"]["status"] == "fail"


def test_v5_bad_abbreviation_is_fail():
    data = build()
    for r in data["race_results_rows"]:
        if r["driver_abbr"] == "AAA":
            r["driver_abbr"] = "aa1"
    status, by_id = run(data)
    assert by_id["V5"]["status"] == "fail"
    assert status == "fail"


def test_v5_empty_team_or_null_position_is_fail():
    data = build()
    data["race_results_rows"][0]["team_name"] = ""
    assert run(data)[1]["V5"]["status"] == "fail"

    data = build()
    data["race_results_rows"][5]["position"] = None
    assert run(data)[1]["V5"]["status"] == "fail"


def test_v6_row_count_far_from_standings_is_warn():
    data = build()
    for i in range(5):  # 5 driver tambahan tanpa poin -> 17 di standings vs 12 baris per round
        data["driver_rows"].append({"position": 13 + i, "driver_abbr": f"Z{chr(65 + i)}Z",
                                    "team_name": "TeamX", "points": 0.0})
    status, by_id = run(data)
    assert by_id["V6"]["status"] == "warn"
    assert by_id["V3"]["status"] == "ok"
    assert status == "warn"


def test_v6_within_tolerance_is_ok():
    data = build()
    for i in range(2):  # selisih 2 masih diperbolehkan
        data["driver_rows"].append({"position": 13 + i, "driver_abbr": f"Y{chr(65 + i)}Y",
                                    "team_name": "TeamX", "points": 0.0})
    assert run(data)[1]["V6"]["status"] == "ok"


def test_overall_fail_beats_warn():
    data = build()
    data["constructor_rows"][0]["points"] += 5   # V1 warn
    data["driver_rows"][0]["points"] += 1        # V3 fail
    status, by_id = run(data)
    assert by_id["V1"]["status"] == "warn" and by_id["V3"]["status"] == "fail"
    assert status == "fail"


def test_empty_season_start_is_ok():
    data = dict(driver_rows=[], constructor_rows=[], race_results_rows=[],
                schedule_full_rows=[{"season": 2026, "round": 1, "has_sprint": 0, "status": "scheduled"}])
    status, by_id = run(data)
    assert status == "ok"


def test_run_checks_does_not_mutate_input():
    data = build()
    snapshot = copy.deepcopy(data)
    v.run_checks(**data)
    assert data == snapshot
