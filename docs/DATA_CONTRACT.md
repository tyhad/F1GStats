# Data Contract: `f1gstats.sqlite`

**Owner of this contract:** this repo (F1GStats is the producer).
**Consumers:** LiveOverlay Studio (existing tables) and To the Flag (new tables). The `to-the-flag` repo mirrors this in its `SPEC.md`. When this file changes, update both.
**Rule:** changes are additive only. Never rename or drop existing tables or columns.

`meta.schema_version`: `1` (implicit, before Phase 0) → `2` (Phase 0). Consumers check this on open.

---

## 1. Existing tables (unchanged)

| Table | Columns |
|---|---|
| `meta` | `key`, `value` (keys: `season`, `last_fetched_at`, and new: `schema_version`) |
| `sessions` | `round, race_name, session_type, start_time_utc, circuit_name, country_flag, round_relation` (only previous / now / next round) |
| `driver_standings` | `position, driver_name, driver_abbr, team_name, points, wins, podiums, dnf_dns` |
| `constructor_standings` | `position, team_name, points, wins, podiums, dnf_dns` |
| `starting_grid` | `round, round_relation, position, driver_name, driver_abbr, team_name, grid_source` |

## 2. New tables (Phase 0)

```sql
CREATE TABLE IF NOT EXISTS schedule_full (
  season INTEGER NOT NULL, round INTEGER NOT NULL, race_name TEXT,
  has_sprint INTEGER NOT NULL,        -- 0 or 1
  race_start_utc TEXT, sprint_start_utc TEXT,   -- ISO 8601 UTC, e.g. 2026-10-11T12:00:00Z
  status TEXT NOT NULL,               -- completed | scheduled (time-based: race start + 3h < now)
  PRIMARY KEY (season, round)
);

CREATE TABLE IF NOT EXISTS race_results (
  season INTEGER NOT NULL, round INTEGER NOT NULL,
  session TEXT NOT NULL,              -- Race | Sprint
  driver_abbr TEXT NOT NULL, driver_name TEXT,
  team_name TEXT, constructor_id TEXT,
  grid INTEGER, position INTEGER, position_text TEXT,
  points REAL NOT NULL, status TEXT,
  is_classified INTEGER NOT NULL,     -- 1 if position_text is a number
  PRIMARY KEY (season, round, session, driver_abbr)
);

CREATE TABLE IF NOT EXISTS data_health (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  season INTEGER NOT NULL, checked_at TEXT NOT NULL,   -- ISO 8601 UTC
  status TEXT NOT NULL,               -- ok | warn | fail
  details_json TEXT NOT NULL          -- list of {id, status, message}
);

-- Optional (Step 7): only needed for countback level iv
CREATE TABLE IF NOT EXISTS qualifying_results (
  season INTEGER NOT NULL, round INTEGER NOT NULL,
  driver_abbr TEXT NOT NULL, position INTEGER,
  PRIMARY KEY (season, round, driver_abbr)
);
```

`team_name` uses the same cleaning (`clean_team_name`) as the standings tables so joins match.

## 3. Write semantics

- All tables are written in **one SQLite transaction**. Any error → rollback, exit 1.
- `schedule_full` and `race_results` are **replaced per season** inside that transaction (`DELETE ... WHERE season = ?` then insert). One API call returns the whole season, so replacing also picks up post-race corrections and removed rows. Do not upsert.
- `data_health` gets one row per run.
- Validation runs **before** the transaction opens. On `fail`, the data tables are not touched.

## 4. Domain rules (FIA 2026 Sporting/General Provisions, Section A Issue 02, Art. A2.1 and A2.2)

GP points depend on the share of scheduled distance completed by the leader. No points unless the leader completed at least two complete, consecutive laps without a Safety Car or VSC.

| Position | ≥ 2 laps (< 25%) | ≥ 25% | ≥ 50% | ≥ 75% (full) |
|---|---|---|---|---|
| P1 | 6 | 13 | 19 | 25 |
| P2 | 4 | 10 | 14 | 18 |
| P3 | 3 | 8 | 12 | 15 |
| P4 | 2 | 6 | 10 | 12 |
| P5 | 1 | 5 | 8 | 10 |
| P6 | – | 4 | 6 | 8 |
| P7 | – | 3 | 4 | 6 |
| P8 | – | 2 | 3 | 4 |
| P9 | – | 1 | 2 | 2 |
| P10 | – | – | 1 | 1 |
| **Total** | 16 | 52 | 79 | 101 |

- No fastest-lap point.
- Sprint: leader completed ≥ 50% of sprint distance → 8-7-6-5-4-3-2-1 (P1–P8, total 36); otherwise 0. No partial scale.
- Points follow the final classification (penalties and disqualifications apply).
- Dead heat: points for tied positions are shared equally (half points possible).
- Only Competitions that actually took place count. Round and driver counts vary; never hardcode.
- Countback (consumers apply it): most first places in a race, then second places, and so on; then the same on qualifying results. Sprints do not count.

## 5. Validation (runs before writing)

| ID | Check | On failure |
|---|---|---|
| V1 | Sum of driver points = sum of constructor points | warn |
| V2 | Each completed GP total ∈ {101, 79, 52, 16, 0}; each sprint total ∈ {36, 0} | warn |
| V3 | For every driver: sum of `race_results.points` (Race + Sprint) = `driver_standings.points` | fail |
| V4 | Rounds that have Race results = rounds in `schedule_full` with `status = completed` | fail |
| V5 | `driver_abbr` matches `^[A-Z]{3}$`; `team_name` non-empty; `position` not null | fail |
| V6 | Rows per Race round = number of drivers in standings (±2) | warn |

Notes:
- V2 can legitimately be lower than 101 when fewer than 10 drivers are classified.
- V3 and V4 will fail right after a race while the API has not published results or standings yet. That is expected: the old data stays, and re-running later fixes it.
- Overall status: `fail` if any fail, else `warn` if any warn, else `ok`.

## 6. Exit codes

| Code | Meaning |
|---|---|
| 0 | ok or warn (data written) |
| 1 | unexpected error (nothing written) |
| 2 | validation failed (data tables untouched, `data_health` recorded) |