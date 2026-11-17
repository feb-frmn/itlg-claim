# ITLG Claim — Docker + Web UI (Multi-Account)

Versi Docker dari bot klaim ITLG Interlink dengan **UI konfigurasi & monitoring berbasis web**,
**multi-akun Interlink**, dan **autentikasi UserGate** (akun pertama yang login menjadi
administrator permanen). Jika UserGate belum dikonfigurasi, aplikasi otomatis berjalan
**tanpa login** (mode lokal).

UI bisa dibuka di desktop maupun mobile (responsive), semua aset lokal (tidak butuh CDN).

---

## Fitur

- **Multi-akun Interlink** — tambah/kelola banyak akun, masing-masing punya token, state, dan log sendiri.
- **Login UserGate** — user pertama yang berhasil login menjadi admin permanen; user UserGate lain ditolak selamanya.
- **Mode tanpa login** — otomatis aktif jika API key UserGate kosong (`AUTH_MODE=auto`), atau bisa dipaksa lewat `AUTH_MODE=none`.
- **Dashboard interaktif** — saldo, countdown mining & group, recovery, rate, referral, grafik riwayat klaim.
- **Kontrol bot** — start/stop/restart per akun atau semua sekaligus, klaim manual (mining/group/recovery).
- **Login OTP & Face** — dari UI, dengan auto-grab OTP via IMAP Gmail.
- **Log real-time** — viewer terminal dengan filter level/akun dan pencarian.
- **Monitoring sistem** — CPU, RAM, disk, uptime.
- **Audit log** — semua tindakan admin tercatat.
- **Keamanan** — secret terenkripsi di database, session httpOnly + CSRF, rate limit login, container non-root.

---

## 1. Persiapan

| Kebutuhan | Keterangan |
|---|---|
| **UserGate API Key** | `ug_...` dari dashboard UserGate (opsional; wajib jika ingin login UserGate) |
| **Akun Interlink** | `loginId` (angka), `passcode` (6 digit), email, Gmail App Password |
| **Docker + Compose** | Docker Engine 20+ dan plugin Compose |
| **Akses internet** | Container harus bisa mencapai `prod.interlinklabs.ai`, `imap.gmail.com:993`, dan UserGate (jika login UserGate aktif) |

Buat file `.env` dari template (opsional, bisa juga export manual):

```bash
cp .env.example .env
```

Isi `.env`:

```env
# ─── Autentikasi ────────────────────────────────────
# auto      = login UserGate jika API key diisi; tanpa login jika kosong (default)
# usergate  = wajib login UserGate
# none      = selalu tanpa login (terbuka)
# Biarkan kosong agar mode bisa diubah dari halaman Pengaturan.
AUTH_MODE=

# ─── UserGate (opsional; wajib untuk mode login) ────
USERGATE_API_KEY=
USERGATE_BASE_URL=https://usergate.sandalgurun.web.id/api/v1

# ─── Keamanan session ───────────────────────────────
SECRET_KEY=ganti-dengan-string-acak-yang-panjang
COOKIE_SECURE=false

# ─── Preferensi ─────────────────────────────────────
TZ=Asia/Jakarta

# ─── Opsional (biarkan kosong untuk default) ────────
ITLG_API_BASE=
ITLG_DATA_DIR=
```

- `AUTH_MODE=auto` (default) memakai UserGate jika API key tersedia. Jika API key kosong, dashboard langsung terbuka tanpa login.
- `AUTH_MODE=usergate` memaksa login UserGate. `AUTH_MODE=none` memaksa tanpa login.
- Jika `AUTH_MODE` diset lewat environment, pilihan mode di halaman Pengaturan dikunci.
- `SECRET_KEY` digunakan untuk mengenkripsi secret di database. Jika kosong, dibuat otomatis di volume.
- `COOKIE_SECURE=true` jika diakses via HTTPS.
- `ITLG_API_BASE` override API Interlink (default `https://prod.interlinklabs.ai/api/v1`).
- `ITLG_DATA_DIR` direktori data di dalam container (default `/app/data`). Jika diubah, pastikan volume Docker juga di-mount ke path tersebut (default volume: `itlg-claim_itlg-data`).

> **Peringatan keamanan:** mode tanpa login membuka dashboard, konfigurasi akun, dan kontrol
> bot kepada siapa pun yang bisa mengakses URL. Gunakan hanya di jaringan tepercaya, di
> belakang reverse proxy yang dilindungi, atau set `AUTH_MODE=usergate` untuk production.

---

## 2. Jalankan

```bash
cd /root/itlg-claim
docker compose up -d --build
```

Cek log:

```bash
docker compose logs -f
```

Buka UI: **http://IP_SERVER:8000**

Healthcheck: `http://IP_SERVER:8000/api/health`

---

## 3. Setup Pertama

1. Buka UI.
   - Jika `USERGATE_API_KEY` diisi (atau `AUTH_MODE=usergate`), Anda diarahkan ke halaman
     **login UserGate**. Login dengan akun UserGate Anda. **Akun pertama yang berhasil login
     menjadi administrator permanen.** Akun UserGate lain (meski terdaftar) akan ditolak selamanya.
   - Jika API key kosong dan mode `auto`/`none`, Anda langsung masuk tanpa login.
2. Setelah masuk, Anda diarahkan ke **Setup Akun Pertama**:
   - Isi Login ID, passcode, email, Gmail App Password, dan (opsional) foto wajah.
   - Pilih **OTP Email** (kirim kode) atau **Face Login** (unggah selfie).
   - Klik **Mulai Bot**.
3. Bot akan otomatis klaim mining tiap 4 jam, group mining tiap 24 jam, dan recovery tiap siklus.

> **Catatan OTP:** pastikan Gmail App Password benar (16 karakter) dan IMAP Gmail aktif.
> UI akan mencoba membaca OTP otomatis dari inbox; jika gagal, Anda bisa memasukkan kode manual.

---

## 4. Manajemen Akun

Halaman **Akun**:

- **Tambah Akun** — buat akun Interlink baru.
- **Login** — login OTP/face untuk akun tertentu.
- **Edit** — ubah konfigurasi akun (secret lama tidak perlu diisi ulang).
- **Hapus** — hapus akun beserta token, state, dan lognya.
- **Toggle** — aktifkan/nonaktifkan akun.

Semua secret (passcode, Gmail App Password, Telegram token) disimpan **terenkripsi** dan
ditampilkan sebagai `••••••••` di UI.

---

## 5. Struktur Data

Semua data ada di volume Docker `itlg-data` (di dalam container: `/app/data`):

```
/app/data/
├── app.db                 # SQLite: admin, session, akun (secret terenkripsi), audit, settings
├── .secret                # kunci enkripsi (chmod 600)
├── tokens/<id>.json       # token per akun
├── claim_state/<id>.json  # riwayat klaim per akun
├── logs/<id>.log          # log per akun
└── uploads/<id>/          # foto wajah
```

Backup cukup dengan mem-backup volume `itlg-data`:

```bash
docker run --rm -v itlg-claim_itlg-data:/data -v "$PWD":/backup alpine \
  tar czf backup/itlg-data.tar.gz -C /data .
```

---

## 6. HTTPS (Opsional)

UI berjalan HTTP murni. Untuk production, letakkan di belakang reverse proxy dengan HTTPS,
misalnya **Caddy**:

```caddyfile
itlg.domain.and.com {
    reverse_proxy 127.0.0.1:8000
}
```

Lalu set `COOKIE_SECURE=true` di `.env` dan restart container.

---

## 7. Troubleshooting

| Masalah | Solusi |
|---|---|
| Ingin masuk tanpa login | Kosongkan `USERGATE_API_KEY` dengan mode `auto`, atau set `AUTH_MODE=none`, lalu restart container |
| Login UserGate gagal "API key belum dikonfigurasi / tidak dapat dibaca" | Set `USERGATE_API_KEY` di `.env`, atau set `AUTH_MODE=none` sementara lalu isi lewat halaman Pengaturan |
| Mode di Pengaturan tidak bisa diubah | `AUTH_MODE` sedang diset lewat environment. Hapus/kosongkan dari `.env` lalu restart |
| UserGate lain bisa login | Periksa `admin` di database — hanya 1 baris admin, dan login lain memang ditolak |
| OTP tidak masuk | Cek spam, IMAP aktif, App Password 16 karakter; UI bisa input kode manual |
| Face login gagal | Foto min 50KB, wajah jelas, mirip foto registrasi |
| Bot status "Perlu Login" | Token habis/gagal; klik **Login** pada akun di halaman Akun |
| Container tidak bisa klaim | Pastikan container bisa mengakses internet (API Interlink & IMAP) |
| Lupa admin | Set `AUTH_MODE=none` sementara untuk masuk, atau hapus `app.db` di volume dan restart (semua data akun ikut terhapus) |

---

## 8. Pengembangan / CLI

`bot.py` tetap bisa dijalankan standalone seperti sebelumnya (mode single-account):

```bash
python setup.py
python bot.py --login
python bot.py
```

Web engine memakai ulang fungsi-fungsi di `bot.py`; setiap akun punya context file sendiri
(token/state/log) sehingga aman berjalan paralel.
