# Changelog

Semua perubahan penting pada project ini didokumentasikan di sini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- Tabel `schedule_full`: semua round musim (tidak difilter), termasuk field `has_sprint`, `race_start_utc`, `sprint_start_utc`, dan `status` (`completed` / `scheduled`).
- `build_schedule_full(schedule, season, now_utc)` — membangun baris `schedule_full` dari DataFrame FastF1 schedule tanpa filtering round.
- `fetch_sessions` sekarang menerima DataFrame schedule yang sudah di-fetch alih-alih memanggil `fastf1.get_event_schedule` sendiri; `main()` fetch schedule sekali dan meneruskannya ke keduanya.
- Tabel `race_results`: satu baris per driver per round GP yang sudah selesai, dengan field `season, round, session, driver_abbr, driver_name, team_name, constructor_id, grid, position, position_text, points, status, is_classified`.
- `fetch_results_rows(ergast, season, session)` — mengambil hasil GP (`"Race"`) dari Ergast per round, memetakan kolom API yang sudah dikonfirmasi, dan mengembalikan `list[dict]`.
- Hasil Sprint disimpan di tabel `race_results` dengan `session = 'Sprint'`, memakai `fetch_results_rows(..., "Sprint")` (`ergast.get_sprint_results`). Musim tanpa sprint (belum ada hasil) menghasilkan `[]`, bukan error.
- `main()` mencetak jumlah baris/round sprint dan memberi `[WARN]` bila ada hasil sprint pada round yang `has_sprint = 0` di `schedule_full` (informatif; validasi resmi menyusul di Step 6).
- `tests/test_fetch_results_rows.py`: tes offline (mock `Ergast._get`) untuk mapping Race/Sprint.
- `meta.schema_version = '2'` ditulis setiap run (skema Phase 0). Konsumen mengecek nilai ini saat membuka database.
- `tests/test_write_to_sqlite.py`: tes offline untuk replace per season, run dua kali, rollback saat error, dan `schema_version`.
- `validation.py` (modul murni, tanpa network/FastF1): `run_checks(driver_rows, constructor_rows, race_results_rows, schedule_full_rows)` mengembalikan status keseluruhan (`ok` / `warn` / `fail`) dan daftar `{id, status, message}` untuk V1-V6 sesuai `docs/DATA_CONTRACT.md`.
- Tabel `data_health` (`id, season, checked_at, status, details_json`): satu baris per run.
- Gerbang validasi di `main()` (langkah `[10/11]`): `fail` -> tabel data tidak disentuh, `data_health` dicatat dalam transaksi kecil sendiri, exit code `2`. `ok`/`warn` -> data dan `data_health` ditulis dalam satu transaksi, exit code `0`.
- `write_data_health` dan `write_or_reject` di `fetch_f1_data.py`; `write_to_sqlite` menerima argumen opsional `health`.
- Tes: `tests/test_validation.py` (V1-V6), gerbang dan `data_health` di `tests/test_write_to_sqlite.py`, dan `tests/test_main_gate.py` (end-to-end `main()` dengan fetch di-mock; exit code 2 dan data lama tetap).
- `validation` ditambahkan ke `py-modules` di `pyproject.toml` agar perintah `f1gstats` hasil instalasi bisa meng-import-nya.
- README: dokumentasi tabel `schedule_full`, `race_results`, dan `data_health`.
- Tabel `qualifying_results` (`season, round, driver_abbr, position`, PK `season, round, driver_abbr`): hasil Qualifying reguler per driver per round (Step 7, untuk countback level iv). Diganti per season dalam transaksi yang sama dengan tabel data lain; tidak ikut V1-V6. `schema_version` tetap `2` karena perubahannya hanya penambahan tabel.
- `fetch_qualifying_rows(ergast, season)`: mengambil semua halaman hasil Qualifying (`_iter_result_pages`), `[]` kalau belum ada, error sungguhan tidak ditelan; mencetak `[WARN]` bila jumlah baris terbaca != total dari API.
- `main()`: langkah `[7/12]` mencetak jumlah baris/round qualifying dan `[WARN]` informatif bila ada round dengan hasil Race tapi tanpa hasil Qualifying. `write_to_sqlite` menerima `qualifying_rows` (opsional; `None` = tabel tidak disentuh).
- Tes: `tests/test_fetch_qualifying_rows.py` (mapping, paging 132 baris, driver tanpa Q2/Q3, error tidak ditelan), tes tulis/replace/rollback `qualifying_results` di `tests/test_write_to_sqlite.py`, dan `tests/test_main_gate.py` memeriksa qualifying ikut tertulis / tidak berubah saat validasi gagal.
- README: dokumentasi tabel `qualifying_results`.

### Changed
- `fetch_results_rows`: error sungguhan saat fetch Sprint (jaringan/HTTP/JSON) tidak lagi ditelan dan dikembalikan sebagai `[]`; error naik ke `__main__`. Hanya respons kosong yang menjadi `[]`.
- Label progres di `main()` jadi `[x/11]` (langkah validasi ditambahkan).
- Label progres di `main()` jadi `[x/12]` (langkah qualifying ditambahkan).
- `write_to_sqlite`: seluruh penulisan data kini satu transaksi eksplisit (`BEGIN` ... `commit`). Error apa pun -> `rollback()`, koneksi ditutup, exception dilempar ulang, sehingga tabel tidak berubah. `__main__` mencetak error ke stderr dan `sys.exit(1)`.
- `schedule_full` dan `race_results` diganti per season (replace, bukan upsert). Pembuatan tabel/migrasi kolom tetap idempotent dan berjalan sebelum transaksi data.
- README: catatan "Re-run" diperbarui; `schema_version` ditambahkan ke deskripsi tabel `meta`.

### Fixed
- `race_results.position` sekarang diisi dari kolom API `position` (urutan akhir) untuk semua baris, termasuk pembalap tidak terklasifikasi (`R`, `D`, dst.). Sebelumnya `NULL` untuk mereka, yang melanggar V5 (`position` tidak boleh null). `is_classified` tetap dari `positionText`. **Perubahan nilai pada data Step 3/4.**
- `fetch_all_race_results`: sekarang mengambil semua halaman hasil (helper `_iter_result_pages`). Sebelumnya hanya 100 baris pertama (~4-5 round) yang dihitung karena Jolpica membatasi respons dan `limit=2000` dipotong diam-diam, sehingga `podiums` dan `dnf_dns` di `driver_standings` dan `constructor_standings` terlalu kecil. Struktur tabel dan kolom tidak berubah; hanya nilainya yang jadi benar.
- `fetch_results_rows`: sekarang mengambil semua halaman hasil (`get_next_result_page`). Jolpica membatasi respons ke 100 baris dan diam-diam memotong `limit=2000`, sehingga sebelumnya hanya ~5 round pertama yang tersimpan. Mencetak `total_results` dan memberi `[WARN]` bila jumlah baris terbaca tidak sama dengan total dari API.

---

## [0.1.0] - 2026-10-05

### Added
- Fetch jadwal sesi (FP1/2/3, Qualifying, Sprint, Race) untuk round Previous / Now / Next relatif terhadap waktu saat ini.
- Fetch WDC (World Drivers' Championship) standing lengkap dengan podium & DNF/DNS count.
- Fetch WCC (World Constructors' Championship) standing lengkap dengan podium & DNF/DNS count.
- Fetch starting grid actual (post-penalty) dari **OpenF1 API**, dengan fallback otomatis ke hasil Qualifying dari **Ergast/Jolpica** bila data OpenF1 belum tersedia.
- Logika `round_relation` (`previous` / `now` / `next`) untuk menentukan round yang relevan terhadap waktu saat script dijalankan.
- Field `grid_source` (`openf1` / `qualifying_fallback`) per baris starting grid, untuk transparansi sumber data.
- Output ke file **SQLite** lokal (`f1gstats.sqlite`) yang kompatibel dengan skema LiveOverlay Studio.
- Tabel `meta` di SQLite untuk menyimpan `season` dan `last_fetched_at`.
- Dukungan argumen CLI: `--season` dan `--output`.
- Skema database otomatis dibuat dan di-migrate (idempotent) setiap kali script dijalankan.