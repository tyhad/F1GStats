# Phase 0: Data tasks

Branch: `phase-0-data`. One commit per step. After each step: run the fetcher, run the check, commit.
Step 1 (baseline) is done. Read `docs/DATA_CONTRACT.md` first.

## What the current code does (do not guess)

- `fetch_sessions` calls `fastf1.get_event_schedule`, then `select_relevant_rounds` keeps only previous / now / next. The `sessions` table must stay exactly like this (LiveOverlay depends on it).
- `fetch_all_race_results` makes one Ergast call (`limit=2000`) and returns only aggregates (podiums, dnf_dns). It does not keep per-round rows.
- `write_to_sqlite` already uses one connection: `DELETE` then `INSERT`, then `commit()`.
- `__main__` prints errors but exits with code 0.

---

## Step 2: `schedule_full`

**Goal:** every round of the season, unfiltered.

**Change:**
- Fetch the schedule once in `main()`. Pass the same DataFrame to `fetch_sessions` (which keeps filtering as before) and to a new `build_schedule_full(schedule, season, now_utc)`.
- Row fields: `season, round, race_name, has_sprint, race_start_utc, sprint_start_utc, status`.
- `has_sprint` = any of `Session1..Session5` is labelled "Sprint". `race_start_utc` = the session labelled "Race". `sprint_start_utc` = the "Sprint" session, else NULL.
- `status` = `completed` if `race_start + 3h < now`, else `scheduled`.
- Add the table to `SCHEMA_SQL`; insert in `write_to_sqlite`.

**Check:**
```powershell
py -c "import sqlite3;c=sqlite3.connect('f1gstats.sqlite');print(c.execute('select count(*),sum(has_sprint) from schedule_full').fetchall())"
```
Count = number of rounds FastF1 lists for the season; sprint weekends look right; `sessions` is identical to the baseline.

**Commit:** `feat: add schedule_full table`

## Step 3: `race_results` (Grand Prix)

**Goal:** one row per driver per completed GP.

**Change:**
- New function `fetch_results_rows(ergast, season, session)` returning `list[dict]`. For `"Race"` use `ergast.get_race_results(season=season, limit=2000)`.
- The round number comes from `resp.description` (one row per DataFrame in `resp.content`). Print both once to confirm they align.
- Print `df.columns` once, then map: `driver_abbr` ← `driverCode`, `driver_name` ← `givenName` + `familyName`, `team_name` ← `constructorName` through `clean_team_name`, `constructor_id` ← `constructorId`, `grid`, `position`, `position_text` ← `positionText`, `points`, `status`, `is_classified` ← `positionText.isdigit()` (same rule the podium/DNF code uses).
- Leave `fetch_all_race_results` behavior unchanged.

**Check:**
```powershell
py -c "import sqlite3;c=sqlite3.connect('f1gstats.sqlite');print(c.execute(\"select round,count(*),sum(points) from race_results where session='Race' group by round\").fetchall())"
```
Each round has one row per driver; full races sum to 101.

**Commit:** `feat: store per-round Grand Prix results`

## Step 4: Sprint results

**Goal:** same table, `session = 'Sprint'`.

**Change:** reuse `fetch_results_rows` with `ergast.get_sprint_results(season=season, limit=2000)`. Empty content (no sprint yet) must return `[]`, not raise.

**Check:** same query with `session='Sprint'`; sums are 36 for full sprints.

**Commit:** `feat: store sprint results`

## Step 5: Transactional write and exit codes

**Goal:** one transaction for everything; honest exit codes.

**Change:**
- In `write_to_sqlite`, inside the existing transaction: `DELETE FROM schedule_full WHERE season = ?` and `DELETE FROM race_results WHERE season = ?`, then insert. Set `meta.schema_version = '2'`.
- Wrap in `try/except`: on error `conn.rollback()`, close, re-raise.
- In `__main__`: on exception print to stderr and `sys.exit(1)`.
- Replace, do not upsert: the whole season arrives in one call, so replacing picks up corrections and removed rows.

**Check:**
- Run twice: row counts identical.
- Temporarily raise an error before `commit()`: tables unchanged.
- Failure exit code: `echo $LASTEXITCODE` prints `1`.

**Commit:** `feat: single-transaction write, schema_version 2, exit codes`

## Step 6: Validation gate and tests

**Goal:** bad data never replaces good data.

**Change:**
- New `validation.py` (pure functions; no network, no FastF1 import) implementing V1–V6 from the contract. `run_checks(...)` returns an overall status plus a list of `{id, status, message}`.
- In `main()`, between fetching and writing: run the checks.
  - `fail`: do not write data tables. Insert one `data_health` row in its own small transaction, print the summary, `sys.exit(2)`.
  - `ok` / `warn`: write data and insert the `data_health` row in the same transaction.
- Tests in `tests/test_validation.py` with small hand-made fixtures: ok case; V1 mismatch → warn; V2 shortened-race total 79 → ok; V3 mismatch → fail; V4 missing round → fail; V5 bad abbreviation → fail.
- Add `requirements-dev.txt` with `pytest`.

**Check:** `pytest` passes. End-to-end: temporarily force `run_checks` to return fail; the data tables keep their old row counts and the exit code is `2`.

**Commit:** `feat: validation gate and data_health`

## Step 7 (optional): `qualifying_results`

Only needed for countback level iv and later model work. Use `ergast.get_qualifying_results(season=season, limit=2000)`. Same pattern as Step 3. Skip until Steps 2–6 are merged.

---

## Phase 0 is done when

1. One run on the current season writes all tables and passes the checks.
2. A forced validation failure leaves the data tables unchanged and exits with code 2.
3. A forced error before commit leaves the database unchanged and exits with code 1.
4. `pytest` passes.
5. The existing tables behave exactly as before (compare with the baseline).

Then open a pull request `phase-0-data` → `main` and merge.