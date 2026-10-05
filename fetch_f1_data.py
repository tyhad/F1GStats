"""
F1GStats — fetch_f1_data
========================
Mengambil data musim Formula 1 dan menyimpannya ke file SQLite lokal yang
kompatibel dengan skema LiveOverlay Studio.

Data yang di-fetch
------------------
- **Jadwal sesi** (FP1/2/3, Qualifying, Sprint, Race) untuk round
  Previous / Now / Next relatif terhadap waktu saat script dijalankan.
- **WDC standing** (posisi, poin, menang, podium, DNF/DNS).
- **WCC standing** (posisi, poin, menang, podium, DNF/DNS).
- **Starting grid** actual (post-penalty) via OpenF1, dengan fallback ke
  hasil Qualifying dari Ergast jika data OpenF1 belum tersedia.

Sumber data
-----------
- fastf1.get_event_schedule()   : jadwal sesi (kolom *_DateUtc dalam UTC)
- fastf1.ergast.Ergast()        : standings, nama sirkuit, hasil race
- OpenF1 API (api.openf1.org)   : starting grid actual (post-penalty)

Penggunaan
----------
    python fetch_f1_data.py --season 2026 --output ./f1gstats.sqlite
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import fastf1
import requests
from fastf1.ergast import Ergast

# ---------------------------------------------------------------------------
# Konversi negara -> emoji flag
# ---------------------------------------------------------------------------

def country_code_to_flag_emoji(country_code: str) -> str:
    """
    ISO 3166-1 alpha-2 (contoh: "SG", "IT", "JP") -> emoji flag.
    Return "" kalau input tidak valid.
    """
    code = country_code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)


# fastf1.get_event_schedule() mengembalikan nama negara penuh di kolom
# "Country" (contoh: "Singapore", "United Kingdom", "United States").
# Ergast/Jolpica juga memakai nama negara penuh yang gaya penulisannya bisa
# sedikit beda ("UK" utk sirkuit Silverstone, dsb). Mapping di bawah dibuat
# berdasarkan daftar negara yang benar-benar muncul di kalender F1
# (musim-musim modern). Kalau suatu saat ada race di negara baru yang belum
# ada di daftar ini, tambahkan barisnya -- jangan menebak kodenya.
COUNTRY_NAME_TO_ISO2 = {
    "australia": "AU",
    "austria": "AT",
    "azerbaijan": "AZ",
    "bahrain": "BH",
    "belgium": "BE",
    "brazil": "BR",
    "canada": "CA",
    "china": "CN",
    "france": "FR",
    "germany": "DE",
    "hungary": "HU",
    "italy": "IT",
    "italy/imola": "IT",
    "emilia romagna": "IT",
    "japan": "JP",
    "mexico": "MX",
    "monaco": "MC",
    "netherlands": "NL",
    "portugal": "PT",
    "qatar": "QA",
    "russia": "RU",
    "saudi arabia": "SA",
    "singapore": "SG",
    "south africa": "ZA",
    "spain": "ES",
    "turkey": "TR",
    "uae": "AE",
    "united arab emirates": "AE",
    "abu dhabi": "AE",
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "usa": "US",
    "united states": "US",
    "vietnam": "VN",
    "korea": "KR",
    "south korea": "KR",
    "india": "IN",
    "malaysia": "MY",
    "sweden": "SE",
    "switzerland": "CH",
    "argentina": "AR",
    "morocco": "MA",
    "san marino": "SM",
    "luxembourg": "LU",
    "indonesia": "ID",
}


def clean_team_name(raw_team: str) -> str:
    """
    Ergast driverStandings kadang mengembalikan constructorNames sebagai
    representasi list Python dalam string, contoh: "['Mercedes']",
    "['A', 'B']" (driver pindah tim musim ini), atau bahkan varian yang
    kurang rapi seperti "'Red Bull']" (sisa split yang tidak simetris).
    Buang semua tanda kurung siku & kutip dulu, baru split by koma dan
    ambil elemen terakhir (tim terkini).
    """
    if not raw_team:
        return ""
    cleaned = re.sub(r"[\[\]'\"]", "", raw_team).strip()
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    return parts[-1] if parts else cleaned


def country_to_flag(country_name: str) -> str:
    if not country_name:
        return ""
    iso2 = COUNTRY_NAME_TO_ISO2.get(country_name.strip().lower())
    if not iso2:
        print(f"  [WARN] Negara tidak ada di mapping: '{country_name}' "
              f"-> flag dikosongkan. Tambahkan ke COUNTRY_NAME_TO_ISO2 kalau perlu.")
        return ""
    return country_code_to_flag_emoji(iso2)


# ---------------------------------------------------------------------------
# Fetch: schedule
# ---------------------------------------------------------------------------

SESSION_TYPE_MAP = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Qualifying",
    "Sprint": "Sprint",
    "Sprint Qualifying": "Sprint Qualifying",
    "Sprint Shootout": "Sprint Qualifying",
    "Race": "Race",
}


def _weekend_bounds(event):
    """Ambil (waktu_sesi_paling_awal, waktu_sesi_paling_akhir) satu event/round."""
    session_times = [
        event.get(f"Session{i}DateUtc") for i in range(1, 6)
    ]
    session_times = [t for t in session_times if t is not None and str(t) != "NaT"]
    if not session_times:
        return None, None
    return min(session_times), max(session_times)


def select_relevant_rounds(schedule, now_utc: datetime):
    """
    Tentukan round Previous, Now, Next relatif terhadap now_utc, berdasarkan
    rentang weekend tiap round (sesi paling awal s/d sesi paling akhir):

      - Now      = round yang weekend-nya SEDANG BERLANGSUNG saat now_utc
                   (start_weekend <= now_utc <= end_weekend).
      - Previous = round terakhir yang weekend-nya SUDAH SELESAI sebelum now_utc.
      - Next     = round terdekat yang weekend-nya BELUM MULAI setelah now_utc.

    Kalau now_utc di antara dua weekend (tidak ada race yang sedang
    berlangsung), Now akan kosong -- cuma Previous & Next yang terisi.
    """
    schedule = schedule.sort_values("RoundNumber").reset_index(drop=True)
    now_naive = now_utc.replace(tzinfo=None)

    previous_round, now_round, next_round = None, None, None
    previous_end, next_start = None, None

    for _, event in schedule.iterrows():
        round_no = int(event["RoundNumber"])
        start, end = _weekend_bounds(event)
        if start is None:
            continue

        if start <= now_naive <= end:
            now_round = round_no
        elif end < now_naive:
            if previous_end is None or end > previous_end:
                previous_end = end
                previous_round = round_no
        elif start > now_naive:
            if next_start is None or start < next_start:
                next_start = start
                next_round = round_no

    selected_rounds = {r for r in (previous_round, now_round, next_round) if r is not None}
    round_relations: dict[int, str] = {}
    if previous_round is not None:
        round_relations[previous_round] = "previous"
    if now_round is not None:
        round_relations[now_round] = "now"
    if next_round is not None:
        round_relations[next_round] = "next"

    print(f"      -> Previous: round {previous_round} | Now: round {now_round} | Next: round {next_round}")
    print(f"      -> round yang di-load: {sorted(selected_rounds) if selected_rounds else '(tidak ada)'}")

    filtered = schedule[schedule["RoundNumber"].isin(selected_rounds)]
    return filtered, round_relations, selected_rounds


def fetch_sessions(season: int, circuit_names_by_round: dict[int, str], now_utc: datetime):
    schedule = fastf1.get_event_schedule(season, include_testing=False)
    schedule, round_relations, selected_rounds = select_relevant_rounds(schedule, now_utc)
    rows = []
    location_by_round: dict[int, str] = {}
    for _, event in schedule.iterrows():
        round_no = int(event["RoundNumber"])
        race_name = str(event["EventName"])
        country = str(event["Country"])
        flag = country_to_flag(country)
        circuit_name = circuit_names_by_round.get(round_no, str(event["Location"]))
        # Dipakai buat cocokin sesi di OpenF1 API (starting grid actual),
        # yang identifikasi sesi pakai nama lokasi/venue, bukan round number.
        location_by_round[round_no] = str(event["Location"])

        for i in range(1, 6):
            session_label = event.get(f"Session{i}")
            session_utc = event.get(f"Session{i}DateUtc")
            if not session_label or session_utc is None or str(session_utc) == "NaT":
                continue
            session_type = SESSION_TYPE_MAP.get(str(session_label), str(session_label))
            # session_utc sudah dalam UTC (naive timestamp, tanpa tzinfo)
            start_time_utc = session_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append({
                "round": round_no,
                "race_name": race_name,
                "session_type": session_type,
                "start_time_utc": start_time_utc,
                "circuit_name": circuit_name,
                "country_flag": flag,
                "round_relation": round_relations.get(round_no),
            })
    return rows, round_relations, selected_rounds, location_by_round


# ---------------------------------------------------------------------------
# Fetch: circuit names per round (dari Ergast, karena schedule fastf1 cuma
# punya "Location", bukan nama sirkuit resmi)
# ---------------------------------------------------------------------------

def fetch_circuit_names(ergast: Ergast, season: int) -> dict[int, str]:
    resp = ergast.get_race_schedule(season=season)
    result = {}
    for _, race in resp.iterrows():
        result[int(race["round"])] = str(race["circuitName"])
    return result


# ---------------------------------------------------------------------------
# Fetch: hasil tiap race musim ini, dipakai utk hitung podium & DNF/DNS
# ---------------------------------------------------------------------------


def fetch_all_race_results(ergast: Ergast, season: int):
    """
    Return dict:
      driver_abbr -> {"podiums": int, "dnf_dns": int}
      constructor_name -> {"podiums": int, "dnf_dns": int}

    Deteksi finish/DNF pakai `positionText` (field resmi Ergast/Jolpica),
    BUKAN parsing string `status`. `positionText` isinya angka posisi kalau
    finish/classified, atau kode huruf kalau tidak: "R" (Retired),
    "D" (Disqualified), "W" (Withdrawn), "N" (Not classified), "E" (Excluded),
    "F" (Failed to qualify). Cara lama (cek awalan string status seperti
    "Finished"/"+") tidak reliable karena variasi teks status dari API.
    """
    driver_stats: dict[str, dict] = {}
    constructor_stats: dict[str, dict] = {}

    # PENTING: Ergast/Jolpica API punya default page limit yang kecil (klasik:
    # 30 baris per request) kalau parameter `limit` tidak di-set eksplisit.
    # FastF1 TIDAK auto-paginate -- cuma 1x HTTP request. Satu musim F1 bisa
    # 260-500+ baris hasil race (rounds x drivers), jadi tanpa limit besar,
    # cuma sebagian kecil ronde awal musim yang benar-benar kefetch -> podium
    # & DNF/DNS jadi salah/kurang lengkap untuk mayoritas driver.
    resp = ergast.get_race_results(season=season, limit=2000)
    # resp.content adalah list of DataFrame, satu per race (round)
    for race_results in resp.content:
        for _, r in race_results.iterrows():
            d_code = str(r.get("driverCode") or r.get("familyName"))
            c_name = str(r.get("constructorName"))
            position_text = str(r.get("positionText", r.get("position", ""))).strip()

            for key, table in ((d_code, driver_stats), (c_name, constructor_stats)):
                if key not in table:
                    table[key] = {"podiums": 0, "dnf_dns": 0}

            is_finished = position_text.isdigit()
            is_podium = is_finished and int(position_text) <= 3

            if is_podium:
                driver_stats[d_code]["podiums"] += 1
                constructor_stats[c_name]["podiums"] += 1

            if not is_finished:
                driver_stats[d_code]["dnf_dns"] += 1
                constructor_stats[c_name]["dnf_dns"] += 1

    return driver_stats, constructor_stats


# ---------------------------------------------------------------------------
# Fetch: starting grid ACTUAL via OpenF1 (post-penalty), fallback Qualifying
# ---------------------------------------------------------------------------

OPENF1_BASE_URL = "https://api.openf1.org/v1"


def _openf1_get(path: str, params: dict, timeout: int = 10):
    resp = requests.get(f"{OPENF1_BASE_URL}/{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_openf1_starting_grid(season: int, location: str) -> list[dict] | None:
    """
    Ambil starting grid ACTUAL (sudah termasuk grid penalty kalau ada) dari
    OpenF1 API -- BUKAN raw hasil Qualifying. OpenF1 mempublikasikan data ini
    setelah FIA mengumumkan starting grid resmi (setelah semua penalty
    diputuskan, biasanya beberapa jam sebelum race) -- beda dengan Ergast
    yang field "grid"-nya baru terisi SETELAH race selesai (karena itu bagian
    dari race result, bukan data pre-race).

    Return None kalau sesi race untuk lokasi ini belum ketemu di OpenF1, atau
    grid-nya belum dipublish (endpoint ini "sparse/beta", banyak sesi yang
    datanya belum ada) -- caller WAJIB fallback ke Qualifying kalau None.
    """
    try:
        sessions = _openf1_get("sessions", {
            "year": season, "location": location, "session_name": "Race",
        })
    except Exception as exc:
        print(f"  [WARN] OpenF1: gagal cari session untuk lokasi '{location}' {season}: {exc}")
        return None

    if not sessions:
        return None
    session_key = sessions[-1]["session_key"]

    try:
        grid_rows = _openf1_get("starting_grid", {"session_key": session_key})
    except Exception as exc:
        print(f"  [WARN] OpenF1: gagal fetch starting_grid (session_key={session_key}): {exc}")
        return None

    if not grid_rows:
        return None

    try:
        drivers = _openf1_get("drivers", {"session_key": session_key})
    except Exception as exc:
        print(f"  [WARN] OpenF1: gagal fetch drivers (session_key={session_key}): {exc}")
        return None

    drivers_by_number = {d["driver_number"]: d for d in drivers}

    rows = []
    for g in grid_rows:
        driver = drivers_by_number.get(g.get("driver_number"))
        if not driver or g.get("position") is None:
            continue
        rows.append({
            "position": int(g["position"]),
            "driver_name": str(driver.get("full_name", "")).title(),
            "driver_abbr": driver.get("name_acronym", ""),
            "team_name": driver.get("team_name", ""),
        })

    return rows if rows else None


def fetch_starting_grid(ergast: Ergast, season: int, rounds_to_fetch: set[int],
                         round_relations: dict[int, str],
                         location_by_round: dict[int, str]) -> list[dict]:
    """
    Ambil starting grid untuk tiap round yang relevan (previous/now/next).
    Prioritas sumber data:
      1. OpenF1 starting grid ACTUAL (sudah termasuk grid penalty)
      2. Fallback: hasil Qualifying dari Ergast (BELUM termasuk grid penalty
         kalau ada -- cuma dipakai kalau OpenF1 belum punya data round ini,
         mis. round terlalu jauh ke depan / baru saja terjadi & belum
         ke-sync ke OpenF1).

    Kolom `grid_source` disimpan per baris ('openf1' / 'qualifying_fallback')
    supaya kamu bisa cek round mana yang masih pakai fallback.
    """
    rows = []
    for round_no in sorted(rounds_to_fetch):
        location = location_by_round.get(round_no, "")

        openf1_rows = fetch_openf1_starting_grid(season, location) if location else None
        if openf1_rows:
            print(f"  [INFO] Round {round_no}: starting grid dari OpenF1 (actual, post-penalty)")
            for row in openf1_rows:
                rows.append({
                    "round": round_no,
                    "round_relation": round_relations.get(round_no),
                    "position": row["position"],
                    "driver_name": row["driver_name"],
                    "driver_abbr": row["driver_abbr"],
                    "team_name": row["team_name"],
                    "grid_source": "openf1",
                })
            continue

        print(f"  [WARN] Round {round_no}: starting grid OpenF1 belum tersedia "
              f"-> fallback ke hasil Qualifying (BELUM termasuk grid penalty kalau ada)")
        try:
            resp = ergast.get_qualifying_results(season=season, round=round_no, limit=100)
        except Exception as exc:
            print(f"  [WARN] Gagal fetch qualifying round {round_no}: {exc}")
            continue

        if not resp.content:
            continue

        df = resp.content[0]
        if df.empty:
            continue

        for _, q in df.iterrows():
            abbr = str(q.get("driverCode") or "")
            given = str(q.get("givenName", ""))
            family = str(q.get("familyName", ""))
            team = str(q.get("constructorName", ""))
            rows.append({
                "round": round_no,
                "round_relation": round_relations.get(round_no),
                "position": int(q["position"]),
                "driver_name": f"{given} {family}".strip(),
                "driver_abbr": abbr,
                "team_name": team,
                "grid_source": "qualifying_fallback",
            })
    return rows


# ---------------------------------------------------------------------------
# Fetch: standings
# ---------------------------------------------------------------------------

def fetch_driver_standings(ergast: Ergast, season: int, race_stats: dict) -> list[dict]:
    resp = ergast.get_driver_standings(season=season, limit=100)
    df = resp.content[0]  # standings terbaru == elemen terakhir/pertama tergantung query; ambil yg tersedia
    rows = []
    for _, d in df.iterrows():
        abbr = str(d.get("driverCode") or "")
        given = str(d.get("givenName", ""))
        family = str(d.get("familyName", ""))
        team_raw = str(d.get("constructorNames", ""))  # bisa berisi >1 tim kalau driver pindah tim musim ini
        team = clean_team_name(team_raw)
        stats = race_stats.get(abbr, {"podiums": 0, "dnf_dns": 0})
        rows.append({
            "position": int(d["position"]),
            "driver_name": f"{given} {family}".strip(),
            "driver_abbr": abbr,
            "team_name": team,  # tim terakhir/terkini, sudah dibersihkan
            "points": float(d["points"]),
            "wins": int(d["wins"]),
            "podiums": stats["podiums"],
            "dnf_dns": stats["dnf_dns"],
        })
    return rows


def fetch_constructor_standings(ergast: Ergast, season: int, race_stats: dict) -> list[dict]:
    resp = ergast.get_constructor_standings(season=season, limit=100)
    df = resp.content[0]
    rows = []
    for _, c in df.iterrows():
        name = str(c["constructorName"])
        stats = race_stats.get(name, {"podiums": 0, "dnf_dns": 0})
        rows.append({
            "position": int(c["position"]),
            "team_name": name,
            "points": float(c["points"]),
            "wins": int(c["wins"]),
            "podiums": stats["podiums"],
            "dnf_dns": stats["dnf_dns"],
        })
    return rows


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round INTEGER,
  race_name TEXT,
  session_type TEXT,
  start_time_utc TEXT,
  circuit_name TEXT,
  country_flag TEXT,
  round_relation TEXT
);

CREATE TABLE IF NOT EXISTS driver_standings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position INTEGER,
  driver_name TEXT,
  driver_abbr TEXT,
  team_name TEXT,
  points REAL,
  wins INTEGER,
  podiums INTEGER,
  dnf_dns INTEGER
);

CREATE TABLE IF NOT EXISTS constructor_standings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position INTEGER,
  team_name TEXT,
  points REAL,
  wins INTEGER,
  podiums INTEGER,
  dnf_dns INTEGER
);

CREATE TABLE IF NOT EXISTS starting_grid (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round INTEGER,
  round_relation TEXT,
  position INTEGER,
  driver_name TEXT,
  driver_abbr TEXT,
  team_name TEXT,
  grid_source TEXT
);
"""


def _migrate_schema(cur: sqlite3.Cursor) -> None:
    """Tambah kolom baru ke tabel lama kalau skema berubah (idempotent)."""
    cur.execute("PRAGMA table_info(sessions)")
    existing_columns = {row[1] for row in cur.fetchall()}
    if "round_relation" not in existing_columns:
        cur.execute("ALTER TABLE sessions ADD COLUMN round_relation TEXT")

    cur.execute("PRAGMA table_info(starting_grid)")
    existing_grid_columns = {row[1] for row in cur.fetchall()}
    if "grid_source" not in existing_grid_columns:
        cur.execute("ALTER TABLE starting_grid ADD COLUMN grid_source TEXT")


def write_to_sqlite(db_path: str, season: int, sessions, driver_rows, constructor_rows, starting_grid_rows):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    _migrate_schema(cur)

    for table in ("sessions", "driver_standings", "constructor_standings", "starting_grid"):
        cur.execute(f"DELETE FROM {table}")

    cur.executemany(
        "INSERT INTO sessions (round, race_name, session_type, start_time_utc, circuit_name, country_flag, round_relation) "
        "VALUES (:round, :race_name, :session_type, :start_time_utc, :circuit_name, :country_flag, :round_relation)",
        sessions,
    )
    cur.executemany(
        "INSERT INTO driver_standings (position, driver_name, driver_abbr, team_name, points, wins, podiums, dnf_dns) "
        "VALUES (:position, :driver_name, :driver_abbr, :team_name, :points, :wins, :podiums, :dnf_dns)",
        driver_rows,
    )
    cur.executemany(
        "INSERT INTO constructor_standings (position, team_name, points, wins, podiums, dnf_dns) "
        "VALUES (:position, :team_name, :points, :wins, :podiums, :dnf_dns)",
        constructor_rows,
    )
    cur.executemany(
        "INSERT INTO starting_grid (round, round_relation, position, driver_name, driver_abbr, team_name, grid_source) "
        "VALUES (:round, :round_relation, :position, :driver_name, :driver_abbr, :team_name, :grid_source)",
        starting_grid_rows,
    )

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('season', ?)", (str(season),))
    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_fetched_at', ?)", (now_iso,))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch data F1 ke SQLite untuk LiveOverlay Studio")
    parser.add_argument("--season", type=int, required=True, help="Tahun musim, contoh: 2026")
    parser.add_argument("--output", type=str, default="./f1gstats.sqlite", help="Path file SQLite output")
    args = parser.parse_args()

    os.makedirs("./.fastf1_cache", exist_ok=True)
    fastf1.Cache.enable_cache("./.fastf1_cache")

    now_utc = datetime.now(timezone.utc)

    print(f"[1/7] Fetch season schedule {args.season} ...")
    ergast = Ergast()

    print("[2/7] Fetch nama sirkuit resmi per ronde ...")
    circuit_names_by_round = fetch_circuit_names(ergast, args.season)

    sessions, round_relations, selected_rounds, location_by_round = fetch_sessions(
        args.season, circuit_names_by_round, now_utc
    )
    print(f"      -> {len(sessions)} sesi ditemukan (round before/now/after saja)")

    print("[3/7] Fetch hasil tiap race musim ini (untuk podium & DNF/DNS) ...")
    driver_race_stats, constructor_race_stats = fetch_all_race_results(ergast, args.season)

    print("[4/7] Fetch WDC standing ...")
    driver_rows = fetch_driver_standings(ergast, args.season, driver_race_stats)
    print(f"      -> {len(driver_rows)} driver")

    print("[5/7] Fetch WCC standing ...")
    constructor_rows = fetch_constructor_standings(ergast, args.season, constructor_race_stats)
    print(f"      -> {len(constructor_rows)} constructor")

    print("[6/7] Fetch starting grid (OpenF1 actual, fallback Qualifying) round terkait ...")
    starting_grid_rows = fetch_starting_grid(
        ergast, args.season, selected_rounds, round_relations, location_by_round
    )
    print(f"      -> {len(starting_grid_rows)} baris starting grid")

    print(f"[7/7] Tulis ke SQLite: {args.output}")
    write_to_sqlite(args.output, args.season, sessions, driver_rows, constructor_rows, starting_grid_rows)

    print()
    print("=== FETCH SELESAI ===")
    print(f"Season         : {args.season}")
    print(f"Sessions       : {len(sessions)}")
    print(f"Driver standing: {len(driver_rows)}")
    print(f"Constructor    : {len(constructor_rows)}")
    print(f"Starting grid  : {len(starting_grid_rows)}")
    print(f"Output file    : {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[ERROR] Fetch gagal: {exc}", file=sys.stderr)
        sys.exit(1)