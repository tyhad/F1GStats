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


def test_v5_two_names_one_abbreviation_is_fail():
    data = build_cars()
    rows = [r for r in data["race_results_rows"] if r["round"] == 2]
    rows[0]["driver_abbr"] = rows[1]["driver_abbr"]   # dua driver berbeda, satu singkatan
    status, by_id = run(data)
    assert by_id["V5"]["status"] == "fail"
    msg = by_id["V5"]["message"]
    assert rows[1]["driver_abbr"] in msg
    assert rows[0]["driver_name"] in msg and rows[1]["driver_name"] in msg
    assert status == "fail"


def test_v5_same_driver_same_name_in_many_rounds_is_ok():
    assert run(build_cars())[1]["V5"]["status"] == "ok"


def test_v5_rows_without_driver_name_do_not_trigger_duplicate_check():
    # fixture lama (build) tidak punya driver_name; itu bukan pelanggaran
    assert run(build())[1]["V5"]["status"] == "ok"


def test_v5_new_driver_with_derived_abbreviation_still_passes():
    # driver baru: kode kosong di API, singkatan diturunkan dari familyName (mis. 'LIN'); nama unik
    data = build_cars()
    data["race_results_rows"].append({"season": 2026, "round": 2, "session": "Race",
                                      "driver_abbr": "LIN", "driver_name": "Arvid Lindblad",
                                      "team_name": "Team0", "position": 23, "points": 0.0})
    data["driver_rows"].append({"position": 26, "driver_abbr": "LIN", "team_name": "Team0", "points": 0.0})
    assert run(data)[1]["V5"]["status"] == "ok"


def build_cars(n_teams=11, n_standings_drivers=25, rows_per_round=None, sprint=False):
    """Musim buatan: n_teams tim, 2 mobil per tim, standings boleh punya lebih banyak driver
    (driver yang pernah ganti kursi). rows_per_round: {round: jumlah baris Race} (default 2 x tim)."""
    n_cars = 2 * n_teams
    rows_per_round = rows_per_round or {1: n_cars, 2: n_cars}
    abbrs = [f"D{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(n_standings_drivers)]
    gp = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * 40
    results = []
    for rnd, n_rows in rows_per_round.items():
        for i in range(n_rows):
            results.append({"season": 2026, "round": rnd, "session": "Race", "driver_abbr": abbrs[i],
                            "driver_name": f"Name {abbrs[i]}", "team_name": f"Team{i // 2}",
                            "position": i + 1, "points": float(gp[i])})
    if sprint:
        for i in range(n_cars):
            results.append({"season": 2026, "round": 2, "session": "Sprint", "driver_abbr": abbrs[i],
                            "driver_name": f"Name {abbrs[i]}", "team_name": f"Team{i // 2}",
                            "position": i + 1, "points": float([8, 7, 6, 5, 4, 3, 2, 1][i] if i < 8 else 0)})
    totals = {a: 0.0 for a in abbrs}
    for r in results:
        totals[r["driver_abbr"]] += r["points"]
    drivers = [{"position": i + 1, "driver_abbr": a, "team_name": "x", "points": totals[a]}
               for i, a in enumerate(abbrs)]
    team_pts = {}
    for r in results:
        team_pts[r["team_name"]] = team_pts.get(r["team_name"], 0.0) + r["points"]
    constructors = [{"position": i + 1, "team_name": f"Team{i}", "points": team_pts.get(f"Team{i}", 0.0)}
                    for i in range(n_teams)]
    schedule = [{"season": 2026, "round": rnd, "has_sprint": 0, "status": "completed"}
                for rnd in rows_per_round]
    return dict(driver_rows=drivers, constructor_rows=constructors,
                race_results_rows=results, schedule_full_rows=schedule)


def test_v6_more_drivers_in_standings_than_cars_is_ok():
    # 25 driver di standings, 22 baris per round, 11 tim: tidak ada yang salah
    data = build_cars()
    assert len(data["driver_rows"]) == 25
    status, by_id = run(data)
    assert by_id["V6"]["status"] == "ok"
    assert status == "ok"


def test_v6_too_few_rows_in_one_round_is_warn():
    status, by_id = run(build_cars(rows_per_round={1: 22, 2: 19}))
    assert by_id["V6"]["status"] == "warn"
    assert "2" in by_id["V6"]["message"] and "19" in by_id["V6"]["message"]
    assert status == "warn"


def test_v6_too_many_rows_in_one_round_is_warn():
    status, by_id = run(build_cars(rows_per_round={1: 22, 2: 24}))
    assert by_id["V6"]["status"] == "warn"
    assert "24" in by_id["V6"]["message"]


def test_v6_bounds_are_2_below_and_exact_above():
    assert run(build_cars(rows_per_round={1: 20, 2: 22}))[1]["V6"]["status"] == "ok"   # 2 x 11 - 2
    assert run(build_cars(rows_per_round={1: 22, 2: 23}))[1]["V6"]["status"] == "warn"  # 2 x 11 + 1


def test_v6_checks_sprint_rounds_too():
    data = build_cars(sprint=True)
    assert run(data)[1]["V6"]["status"] == "ok"
    data["race_results_rows"] = [r for r in data["race_results_rows"]
                                 if not (r["session"] == "Sprint" and r["position"] > 15)]
    by_id = run(data)[1]
    assert by_id["V6"]["status"] == "warn"
    assert "Sprint" in by_id["V6"]["message"]


def test_v6_uses_constructors_not_drivers():
    # jumlah driver di standings berubah drastis, jumlah tim tetap: V6 tetap ok
    data = build_cars(n_standings_drivers=30)
    assert run(data)[1]["V6"]["status"] == "ok"


def test_v6_without_constructors_is_skipped():
    data = build_cars()
    data["constructor_rows"] = []
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