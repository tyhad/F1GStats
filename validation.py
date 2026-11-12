"""
Validasi data F1GStats (V1-V6 dari docs/DATA_CONTRACT.md, bagian 5).

Modul ini MURNI: tanpa network, tanpa import FastF1, tanpa akses database.
Semua fungsi menerima list[dict] dan mengembalikan hasil; jangan menambah efek samping.

run_checks(...) -> (overall_status, [{"id", "status", "message"}, ...])
  overall_status: "fail" kalau ada yang fail, else "warn" kalau ada yang warn, else "ok".
"""

import re

GP_TOTALS = (101.0, 79.0, 52.0, 16.0, 0.0)   # total poin GP yang sah (skala 25/50/75% + tanpa poin)
SPRINT_TOTALS = (36.0, 0.0)                   # sprint: 8-7-6-5-4-3-2-1 atau 0
ABBR_RE = re.compile(r"^[A-Z]{3}$")
ROW_COUNT_SHORT_TOLERANCE = 2                 # V6: boleh kurang paling banyak 2 baris dari 2 x tim
_TOL = 1e-6
_MAX_LISTED = 5


def _result(check_id: str, status: str, message: str) -> dict:
    return {"id": check_id, "status": status, "message": message}


def _close(a: float, b: float) -> bool:
    return abs(a - b) < _TOL


def _fmt(x: float) -> str:
    return f"{x:g}"


def _listed(items: list[str]) -> str:
    shown = "; ".join(items[:_MAX_LISTED])
    extra = len(items) - _MAX_LISTED
    return shown + (f"; ... +{extra} lagi" if extra > 0 else "")


def _rounds_with(race_results_rows, session: str) -> set[int]:
    return {int(r["round"]) for r in race_results_rows if r["session"] == session}


def _session_totals(race_results_rows, session: str) -> dict[int, float]:
    totals: dict[int, float] = {}
    for r in race_results_rows:
        if r["session"] == session:
            rnd = int(r["round"])
            totals[rnd] = totals.get(rnd, 0.0) + float(r["points"])
    return totals


# V1 ---------------------------------------------------------------------------
def check_v1(driver_rows, constructor_rows) -> dict:
    d = sum(float(r["points"]) for r in driver_rows)
    c = sum(float(r["points"]) for r in constructor_rows)
    if _close(d, c):
        return _result("V1", "ok", f"Total poin driver = total poin konstruktor ({_fmt(d)}).")
    return _result("V1", "warn",
                   f"Total poin driver {_fmt(d)} != total poin konstruktor {_fmt(c)}.")


# V2 ---------------------------------------------------------------------------
def check_v2(race_results_rows) -> dict:
    bad = []
    for rnd, total in sorted(_session_totals(race_results_rows, "Race").items()):
        if not any(_close(total, t) for t in GP_TOTALS):
            bad.append(f"GP round {rnd} total {_fmt(total)}")
    for rnd, total in sorted(_session_totals(race_results_rows, "Sprint").items()):
        if not any(_close(total, t) for t in SPRINT_TOTALS):
            bad.append(f"Sprint round {rnd} total {_fmt(total)}")
    if not bad:
        return _result("V2", "ok", "Total poin tiap GP dan sprint sesuai skala poin yang sah.")
    return _result("V2", "warn", "Total poin di luar skala yang sah: " + _listed(bad) + ".")


# V3 ---------------------------------------------------------------------------
def check_v3(driver_rows, race_results_rows) -> dict:
    from_results: dict[str, float] = {}
    for r in race_results_rows:
        from_results[r["driver_abbr"]] = from_results.get(r["driver_abbr"], 0.0) + float(r["points"])
    from_standings = {r["driver_abbr"]: float(r["points"]) for r in driver_rows}

    bad = []
    for abbr in sorted(set(from_results) | set(from_standings)):
        a, b = from_results.get(abbr, 0.0), from_standings.get(abbr, 0.0)
        if not _close(a, b):
            bad.append(f"{abbr}: hasil {_fmt(a)} vs standings {_fmt(b)}")
    if not bad:
        return _result("V3", "ok", "Poin Race + Sprint tiap driver sama dengan driver_standings.")
    return _result("V3", "fail", f"{len(bad)} driver tidak cocok dengan standings: " + _listed(bad) + ".")


# V4 ---------------------------------------------------------------------------
def check_v4(race_results_rows, schedule_full_rows) -> dict:
    have = _rounds_with(race_results_rows, "Race")
    expected = {int(r["round"]) for r in schedule_full_rows if r["status"] == "completed"}
    missing, extra = sorted(expected - have), sorted(have - expected)
    if not missing and not extra:
        return _result("V4", "ok", f"Round dengan hasil Race = round completed di jadwal ({len(have)} round).")
    parts = []
    if missing:
        parts.append(f"round completed tanpa hasil Race: {missing}")
    if extra:
        parts.append(f"hasil Race untuk round yang belum completed: {extra}")
    return _result("V4", "fail", "; ".join(parts) + ".")


# V5 ---------------------------------------------------------------------------
def _duplicate_abbreviations(race_results_rows) -> list[str]:
    """Singkatan yang dipakai dua driver berbeda (driver_name berbeda). Baris tanpa nama dilewati."""
    names: dict[str, list[str]] = {}
    for r in race_results_rows:
        abbr = str(r.get("driver_abbr") or "")
        name = str(r.get("driver_name") or "").strip()
        if not abbr or not name:
            continue
        seen = names.setdefault(abbr, [])
        if name not in seen:
            seen.append(name)
    return [f"{abbr} dipakai oleh {' dan '.join(seen)}"
            for abbr, seen in sorted(names.items()) if len(seen) > 1]


def check_v5(race_results_rows) -> dict:
    bad_abbr, bad_team, bad_pos = set(), 0, 0
    for r in race_results_rows:
        if not ABBR_RE.match(str(r.get("driver_abbr") or "")):
            bad_abbr.add(str(r.get("driver_abbr")))
        if not str(r.get("team_name") or "").strip():
            bad_team += 1
        if r.get("position") is None:
            bad_pos += 1
    duplicates = _duplicate_abbreviations(race_results_rows)
    problems = []
    if bad_abbr:
        problems.append(f"driver_abbr tidak valid: {sorted(bad_abbr)[:_MAX_LISTED]}")
    if duplicates:
        problems.append("singkatan ganda: " + _listed(duplicates))
    if bad_team:
        problems.append(f"{bad_team} baris tanpa team_name")
    if bad_pos:
        problems.append(f"{bad_pos} baris dengan position null")
    if not problems:
        return _result("V5", "ok", "driver_abbr, team_name, dan position valid di semua baris; tidak ada singkatan ganda.")
    return _result("V5", "fail", "; ".join(problems) + ".")


# V6 ---------------------------------------------------------------------------
def check_v6(constructor_rows, race_results_rows) -> dict:
    """Jumlah baris tiap round Race dan Sprint dibandingkan dengan 2 x jumlah konstruktor
    (bukan jumlah driver di standings: driver yang ganti kursi membuat standings lebih panjang)."""
    counts: dict[tuple[str, int], int] = {}
    for r in race_results_rows:
        if r["session"] in ("Race", "Sprint"):
            key = (r["session"], int(r["round"]))
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return _result("V6", "ok", "Belum ada hasil Race; pengecekan jumlah baris dilewati.")
    n_teams = len(constructor_rows)
    if n_teams == 0:
        return _result("V6", "ok", "Standings konstruktor kosong; pengecekan jumlah baris dilewati.")
    cars = 2 * n_teams
    low = cars - ROW_COUNT_SHORT_TOLERANCE
    bad = [f"{session} round {rnd}: {n} baris" for (session, rnd), n in sorted(counts.items(), key=lambda kv: (kv[0][1], kv[0][0]))
           if n < low or n > cars]
    if not bad:
        return _result("V6", "ok", f"Jumlah baris per round Race dan Sprint sesuai {n_teams} tim ({low}-{cars} baris).")
    return _result("V6", "warn", f"{n_teams} tim berarti {low}-{cars} baris per round, tapi " + _listed(bad) + ".")


# Gabungan ---------------------------------------------------------------------
def overall_status(results: list[dict]) -> str:
    statuses = {r["status"] for r in results}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def run_checks(driver_rows, constructor_rows, race_results_rows, schedule_full_rows):
    """Jalankan V1-V6. race_results_rows berisi Race + Sprint. Return (status, details)."""
    results = [
        check_v1(driver_rows, constructor_rows),
        check_v2(race_results_rows),
        check_v3(driver_rows, race_results_rows),
        check_v4(race_results_rows, schedule_full_rows),
        check_v5(race_results_rows),
        check_v6(constructor_rows, race_results_rows),
    ]
    return overall_status(results), results