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

### Changed
- `fetch_results_rows`: error sungguhan saat fetch Sprint (jaringan/HTTP/JSON) tidak lagi ditelan dan dikembalikan sebagai `[]`; error naik ke `__main__`. Hanya respons kosong yang menjadi `[]`.
- Label progres di `main()` jadi `[x/10]`.

### Fixed
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