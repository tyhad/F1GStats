# AGENTS.md

## What this is
F1GStats: Python fetcher for F1 data. It pulls from Ergast/Jolpica (via FastF1) and OpenF1,
validates the data, and writes `f1gstats.sqlite`. Two consumers read that file:
- LiveOverlay Studio (existing tables; must not break)
- To the Flag (new tables from Phase 0; separate repo, read-only)

## Commands (Windows / PowerShell)
- Setup: `py -m venv venv`, then `venv\Scripts\activate`, then `pip install -r requirements.txt -r requirements-dev.txt`
- Run: `py fetch_f1_data.py --season 2026 --output ./f1gstats.sqlite`
- Test: `pytest`

## Read first
1. `docs/DATA_CONTRACT.md`: tables, domain rules, validation, exit codes. Source of truth.
2. `docs/PHASE_0.md`: the task list. Work through it in order.

If code and documents disagree, follow the documents and ask the owner.

## Layout
- `fetch_f1_data.py`: fetching and writing (existing)
- `validation.py`: pure checks, no network and no FastF1 import (new in Phase 0)
- `tests/`: pytest; fixtures only, never the network
- `docs/`: contract and task list
- `pyproject.toml`: packaging; every new module must be added to `py-modules`
- `CHANGELOG.md`, `README.md`: keep in sync with behavior changes

## Hard rules
- Do not rename, drop, or change existing tables and columns. LiveOverlay depends on them. Only add.
- Validate before writing. Write all tables in ONE SQLite transaction; roll back on any error.
- On validation failure, do not touch the data tables. Record `data_health` and exit with code 2.
- Exit codes: 0 ok or warn, 1 unexpected error, 2 validation failed.
- Never hardcode round count, driver count, or sprint weekends. Derive them from the schedule.
- Tests must not call the network.
- No secrets in the repo. Do not commit `.sqlite`, `.env`, `.venv`, or `.fastf1_cache`.
- Print a column list or sample row before mapping API fields; do not assume column names.

## How to work
- Branch `phase-0-data`. One commit per step in `docs/PHASE_0.md`, with a clear message.
- After each step: run the fetcher, run the check described in the step, then commit.
- Update `CHANGELOG.md` for every user-visible change (new tables, exit codes) and fix README notes that become stale (for example the "Re-run" note).
- Write tests for validation before the validation code.
- Run `pytest` before saying "done". If a rule is ambiguous, ask the owner.