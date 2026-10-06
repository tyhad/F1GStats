# F1GStats

CLI tool yang mengambil data musim **Formula 1** dari beberapa API publik dan menyimpannya ke sebuah file **SQLite** lokal — dirancang untuk dipakai oleh LiveOverlay Studio.

---

## Fitur

| Data | Sumber |
|------|--------|
| Jadwal sesi (FP1/2/3, Quali, Sprint, Race) | FastF1 |
| Nama sirkuit resmi per ronde | Ergast / Jolpica |
| WDC standing (+ podium & DNF/DNS) | Ergast / Jolpica |
| WCC standing (+ podium & DNF/DNS) | Ergast / Jolpica |
| Starting grid actual (post-penalty) | OpenF1 API |
| Starting grid fallback (pre-penalty) | Ergast / Jolpica (Qualifying) |

Script secara otomatis menentukan tiga round yang relevan berdasarkan waktu saat dijalankan:
- **Previous** — round terakhir yang sudah selesai
- **Now** — round yang sedang berlangsung (jika ada)
- **Next** — round terdekat berikutnya

---

## Persyaratan

- Python **≥ 3.10**
- Koneksi internet (untuk fetch dari API)

---

## Instalasi

```bash
# 1. Clone repo
git clone https://github.com/tyhad/F1GStats.git
cd F1GStats

# 2. Buat dan aktifkan virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Cara Pakai

```bash
python fetch_f1_data.py --season 2026 --output ./f1gstats.sqlite
```

### Argumen

| Argumen | Wajib | Default | Keterangan |
|---------|-------|---------|------------|
| `--season` | ✅ | — | Tahun musim F1, contoh: `2026` |
| `--output` | ❌ | `./f1gstats.sqlite` | Path file SQLite output |

### Contoh output terminal

```
[1/7] Fetch season schedule 2026 ...
[2/7] Fetch nama sirkuit resmi per ronde ...
      -> Previous: round 17 | Now: round None | Next: round 18
      -> round yang di-load: [17, 18]
      -> 10 sesi ditemukan (round before/now/after saja)
[3/7] Fetch hasil tiap race musim ini (untuk podium & DNF/DNS) ...
[4/7] Fetch WDC standing ...
      -> 20 driver
[5/7] Fetch WCC standing ...
      -> 10 constructor
[6/7] Fetch starting grid (OpenF1 actual, fallback Qualifying) round terkait ...
  [INFO] Round 17: starting grid dari OpenF1 (actual, post-penalty)
  [WARN] Round 18: starting grid OpenF1 belum tersedia -> fallback ke hasil Qualifying
[7/7] Tulis ke SQLite: ./f1gstats.sqlite

=== FETCH SELESAI ===
Season         : 2026
Sessions       : 10
Driver standing: 20
Constructor    : 10
Starting grid  : 40
Output file    : ./f1gstats.sqlite
```

---

## Skema SQLite

### `meta`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `key` | TEXT | Nama kunci (`season`, `last_fetched_at`, `schema_version`) |
| `value` | TEXT | Nilai |

### `sessions`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `id` | INTEGER | Primary key |
| `round` | INTEGER | Nomor ronde |
| `race_name` | TEXT | Nama Grand Prix |
| `session_type` | TEXT | `FP1`, `FP2`, `FP3`, `Qualifying`, `Sprint`, `Sprint Qualifying`, `Race` |
| `start_time_utc` | TEXT | Waktu mulai sesi (ISO 8601, UTC) |
| `circuit_name` | TEXT | Nama sirkuit resmi |
| `country_flag` | TEXT | Emoji flag negara |
| `round_relation` | TEXT | `previous`, `now`, atau `next` |

### `driver_standings`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `id` | INTEGER | Primary key |
| `position` | INTEGER | Posisi klasemen |
| `driver_name` | TEXT | Nama lengkap driver |
| `driver_abbr` | TEXT | Kode 3 huruf (contoh: `VER`, `HAM`) |
| `team_name` | TEXT | Nama tim terkini |
| `points` | REAL | Total poin |
| `wins` | INTEGER | Jumlah kemenangan musim ini |
| `podiums` | INTEGER | Jumlah podium musim ini |
| `dnf_dns` | INTEGER | Jumlah DNF/DNS musim ini |

### `constructor_standings`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `id` | INTEGER | Primary key |
| `position` | INTEGER | Posisi klasemen |
| `team_name` | TEXT | Nama tim |
| `points` | REAL | Total poin |
| `wins` | INTEGER | Jumlah kemenangan musim ini |
| `podiums` | INTEGER | Jumlah podium musim ini |
| `dnf_dns` | INTEGER | Jumlah DNF/DNS musim ini |

### `starting_grid`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `id` | INTEGER | Primary key |
| `round` | INTEGER | Nomor ronde |
| `round_relation` | TEXT | `previous`, `now`, atau `next` |
| `position` | INTEGER | Posisi grid |
| `driver_name` | TEXT | Nama lengkap driver |
| `driver_abbr` | TEXT | Kode 3 huruf |
| `team_name` | TEXT | Nama tim |
| `grid_source` | TEXT | `openf1` (actual, post-penalty) atau `qualifying_fallback` (pre-penalty) |

### `schedule_full`
Semua round musim (tidak difilter previous/now/next). Diganti per `season` setiap run.

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `season` | INTEGER | Tahun musim (PK bersama `round`) |
| `round` | INTEGER | Nomor ronde |
| `race_name` | TEXT | Nama Grand Prix |
| `has_sprint` | INTEGER | `1` kalau weekend punya sesi Sprint, else `0` |
| `race_start_utc` | TEXT | Waktu mulai Race (ISO 8601, UTC) |
| `sprint_start_utc` | TEXT | Waktu mulai Sprint (ISO 8601, UTC), `NULL` kalau tidak ada |
| `status` | TEXT | `completed` (Race mulai + 3 jam sudah lewat) atau `scheduled` |

### `race_results`
Satu baris per driver per sesi per round yang sudah selesai. Diganti per `season` setiap run.

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `season` | INTEGER | Tahun musim (PK: `season`, `round`, `session`, `driver_abbr`) |
| `round` | INTEGER | Nomor ronde |
| `session` | TEXT | `Race` (Grand Prix) atau `Sprint` |
| `driver_abbr` | TEXT | Kode 3 huruf |
| `driver_name` | TEXT | Nama lengkap driver |
| `team_name` | TEXT | Nama tim (dibersihkan, sama dengan tabel standings) |
| `constructor_id` | TEXT | ID konstruktor Ergast (mis. `mercedes`) |
| `grid` | INTEGER | Posisi start dari Ergast |
| `position` | INTEGER | Urutan akhir dari API; terisi juga untuk pembalap yang tidak terklasifikasi |
| `position_text` | TEXT | Angka posisi, atau kode huruf (`R`, `D`, `W`, `N`, `E`, `F`) |
| `points` | REAL | Poin yang diperoleh di sesi ini |
| `status` | TEXT | Status resmi (mis. `Finished`, `+1 Lap`, `Retired`) |
| `is_classified` | INTEGER | `1` kalau `position_text` berupa angka (finis resmi), else `0` |

Untuk hitungan "finis resmi" (countback, podium), pakai `is_classified = 1`, bukan `position` saja.

### `qualifying_results`
Hasil Qualifying reguler (bukan Sprint Qualifying), satu baris per driver per round yang sudah selesai. Diganti per `season` setiap run. Dipakai untuk countback level iv.

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `season` | INTEGER | Tahun musim (PK: `season`, `round`, `driver_abbr`) |
| `round` | INTEGER | Nomor ronde |
| `driver_abbr` | TEXT | Kode 3 huruf |
| `position` | INTEGER | Posisi hasil Qualifying resmi |

Tabel ini tidak ikut validasi V1-V6. Baca `meta.schema_version` (`2`) seperti biasa; database lama yang dibuat sebelum Step 7 tidak punya tabel ini sampai fetch dijalankan lagi.

### `data_health`
Satu baris per run: hasil validasi V1-V6 (lihat `docs/DATA_CONTRACT.md`, bagian 5).

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| `id` | INTEGER | Primary key |
| `season` | INTEGER | Tahun musim |
| `checked_at` | TEXT | Waktu pengecekan (ISO 8601, UTC) |
| `status` | TEXT | `ok`, `warn`, atau `fail` |
| `details_json` | TEXT | JSON: list `{id, status, message}` untuk V1-V6 |

Baris dengan `status = 'fail'` berarti run itu **tidak menulis** tabel data; data yang ada di tabel lain berasal dari run sebelumnya.

---

## Sumber Data

| Sumber | URL |
|--------|-----|
| FastF1 | https://docs.fastf1.dev |
| Ergast / Jolpica | https://jolpi.ca |
| OpenF1 | https://openf1.org |

---

## Cache FastF1

Script secara otomatis membuat direktori `.fastf1_cache/` di folder project untuk menyimpan cache session FastF1. Direktori ini di-ignore oleh Git (lihat `.gitignore`) karena ukurannya bisa sangat besar.

---

## Catatan

- **`round_relation`**: Script hanya menyimpan data untuk 2–3 round (previous, now, next). Data round lain tidak disimpan ke SQLite.
- **`grid_source`**: Field ini menunjukkan apakah starting grid untuk suatu round berasal dari OpenF1 (actual, sudah termasuk grid penalty) atau dari hasil Qualifying via Ergast (fallback, belum termasuk grid penalty). Cek field ini untuk mengetahui akurasi data grid tiap round.
- **Re-run**: Setiap kali script dijalankan, semua tabel data ditulis ulang dalam **satu transaksi SQLite**. `sessions`, `driver_standings`, `constructor_standings`, dan `starting_grid` dikosongkan lalu diisi ulang. `schedule_full` dan `race_results` **diganti per season** (`DELETE ... WHERE season = ?` lalu insert, bukan upsert), sehingga data season lain tidak tersentuh dan koreksi pasca-race ikut masuk. `meta` di-update (`season`, `last_fetched_at`, `schema_version`).
- **Gagal = database tidak berubah**: kalau terjadi error saat menulis, transaksi di-rollback dan semua tabel tetap seperti sebelumnya. Proses keluar dengan exit code `1` (cek `echo %ERRORLEVEL%` di cmd atau `echo $LASTEXITCODE` di PowerShell).
- **Validasi sebelum menulis**: data dicek (V1-V6, lihat `docs/DATA_CONTRACT.md`) sebelum transaksi dibuka. Hasilnya dicatat di tabel `data_health`. Status `fail` (mis. hasil race belum terbit sementara jadwal sudah `completed`) berarti tabel data **tidak disentuh** dan proses keluar dengan exit code `2`; jalankan ulang nanti. Status `ok`/`warn` menulis data (exit code `0`).
- **Exit code**: `0` = ok atau warn (data ditulis), `1` = error tak terduga (tidak ada yang ditulis), `2` = validasi gagal (data tidak ditulis, `data_health` dicatat).