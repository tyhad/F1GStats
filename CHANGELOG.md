# Changelog

Semua perubahan penting pada project ini didokumentasikan di sini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
