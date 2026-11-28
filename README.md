# Auto ATTDEF Framework — LKSMLG 2027

Framework otomatisasi Attack-Defense CTF. Python hanya jadi orchestrator,
**Bash tetap bahasa utama exploit**. Sekali jalan, jalan terus — satu round
tiap 180 detik, flag dikirim otomatis ke scoreboard.

## Mode PLAYIT PLUS 2026 — panduan lengkap

Selain mode scoreboard LKSMLG di bawah, framework ini punya **mode
platform** untuk PLAYIT PLUS 2026 (platform ADTickPlatform, API
v2.0.0). Di mode ini kamu **cuma menulis exploit per challenge** —
sisanya diurus framework:

- **Login JWT otomatis** ke `POST /api/v2/authenticate`, token di-cache
  dan di-refresh sekali kalau ditolak (401/403).
- **Target dinamis** dari `GET /api/v2/services` (peta
  challenge → tim → `host:port`), diambil ulang tiap round. Tim sendiri
  (dari `GET /api/v2/session`) otomatis dikecualikan — flag tim sendiri
  tidak pernah diserang maupun di-submit.
- **Tick mengikuti platform**: durasi round diambil dari
  `scheduler.interval_seconds` di `GET /api/v2/game/status`.
- **Submit** ke `POST /api/v2/submit`, batch maksimal 128 flag,
  verdict per flag (`accepted` / `duplicate` / `invalid`) dibaca dari
  `results`. Selama `accepting_submissions` false, flag **ditahan di
  antrean** dan dikirim round berikutnya — tidak hangus.
- **Format flag** otomatis `PLAYITPLUS{...}`.

### Langkah 1 — Ambil kode terbaru

```bash
git clone https://github.com/usernameuser87/attdef-lksmlg2027.git
cd attdef-lksmlg2027
```

Kalau sudah pernah clone, cukup `git pull`. Syaratnya cuma Python
3.8+ — tidak ada yang perlu di-`pip install`, semua stdlib.

### Langkah 2 — Isi kredensial platform di `.env`

```bash
cp .env.example .env
```

Buka `.env` dan isi tiga baris ini dengan akun peserta dari panitia:

```bash
PLAYIT_BASE_URL=https://10.0.2.3   # alamat platform dari panitia
PLAYIT_EMAIL=email-akun-tim-kamu
PLAYIT_PASSWORD=password-akun-tim-kamu
```

| Variabel | Isi |
| --- | --- |
| `PLAYIT_BASE_URL` | Alamat platform. Default di `.env.example` adalah `https://10.0.2.3` — ganti kalau panitia memberi alamat lain. |
| `PLAYIT_EMAIL` | Email akun peserta tim kamu. |
| `PLAYIT_PASSWORD` | Password akun peserta tim kamu. |
| `PLAYIT_VERIFY_TLS` | Opsional. `1` = verifikasi sertifikat TLS platform. Default mati (platform CTF biasanya self-signed). |

Begitu `PLAYIT_EMAIL` + `PLAYIT_PASSWORD` terisi, framework otomatis
masuk mode PLAYIT. Kalau keduanya kosong, framework jalan di mode
LKSMLG lama (target statis + scoreboard) — jadi pastikan langkah ini
tidak terlewat. File `.env` asli tidak ikut ter-commit (sudah di
`.gitignore`).

### Langkah 3 — Konek WireGuard, lalu cek platform

Semua target hanya bisa dijangkau lewat VPN kompetisi:

1. Ambil config WireGuard kamu dari `GET /api/v2/me/wireguard`
   (perlu login dulu), atau pakai file config yang dibagikan panitia.
2. Import config itu ke WireGuard dan aktifkan.
3. Cek platform merespons:

```bash
curl -s https://10.0.2.3/api/v2/game/status
```

(sesuaikan alamatnya dengan `PLAYIT_BASE_URL` kamu). Balasan JSON
berisi `scheduler.interval_seconds` (durasi tick) dan
`match.accepting_submissions` (apakah submit sedang dibuka).

### Langkah 4 — Atur pengecualian proxy (kalau laptopmu memakai proxy)

Koneksi Python framework selalu langsung (tidak lewat proxy), tapi
script Bash kamu mewarisi environment shell. Kalau laptopmu punya
variabel proxy, tambahkan subnet VPN kompetisi ke **kedua** variabel
ini sebelum menjalankan framework:

```bash
export NO_PROXY="$NO_PROXY,10.0.0.0/8"
export no_proxy="$no_proxy,10.0.0.0/8"
```

(sesuaikan `10.0.0.0/8` dengan subnet VPN dari config WireGuard).
Versi huruf kecil **wajib** diisi juga: `curl` mendahulukan `no_proxy`
daripada `NO_PROXY`, jadi kalau hanya yang besar yang diisi, `curl` di
dalam exploit bisa tetap mampir ke proxy dan gagal diam-diam —
gejalanya flag tidak pernah ketangkap dan curl keluar dengan kode 52
("empty reply from server").

### Langkah 5 — Buat satu folder per challenge

Di dalam folder `challenges/`, buat satu folder per challenge. Isinya
dua file (template siap salin ada di `challenges/example-playit/`):

```text
challenges/
  nama-challenge/
    config.json
    exploit.sh
```

`config.json`:

```json
{"name": "nama-challenge", "api_id": "1", "port": 8000, "script": "exploit.sh", "enabled": true, "timeout": 15}
```

| Field | Isi |
| --- | --- |
| `api_id` | **Id challenge di platform** (lihat `GET /api/v2/challenges` atau halaman lomba). Field inilah yang mencocokkan folder ini dengan peta target dari platform. |
| `port` | Port cadangan — port asli per tim selalu diambil dari peta `services` platform. |
| `enabled` | `false` untuk menonaktifkan challenge ini tanpa menghapus foldernya. |
| `timeout` | Batas detik per satu kali jalan exploit. |

`exploit.sh` — kontraknya sederhana:

```bash
#!/usr/bin/env bash
# $1 = IP target, $2 = port target (dikirim framework, beda per tim lawan)
# IP dan PORT yang sama juga tersedia sebagai variabel $IP dan $PORT.
curl -s --max-time 5 "http://$1:$2/jalur-flag-kamu"
```

Tulis exploit-mu seperti script Bash biasa, dan pastikan **flag
tercetak ke stdout**. Framework memanggil script ini sekali per tim
lawan per tick, mengekstrak semua pola `PLAYITPLUS{...}` dari
output-nya, lalu mengurus submit. Jangan lupa `chmod +x exploit.sh`.

### Langkah 6 — Jalankan dan baca output-nya

Tes satu round dulu (berhenti sendiri setelah 1 round):

```bash
ATTDEF_MAX_ROUNDS=1 python3 main.py
```

Kalau aman, jalankan penuh dan biarkan terminal terbuka selama lomba:

```bash
python3 main.py
```

Baris-baris penting di output:

```text
Mode: PLAYIT PLUS 2026 platform (https://10.0.2.3)   <- mode benar
Own team id: 101 (excluded from targets)             <- tim sendiri aman
[ONLINE] Tim 102 | banking                           <- target terjangkau
[OFFLINE] Tim 103 | banking | SKIPPED                <- target tidak terjangkau, dilewati
[FLAG] PLAYITPLUS{...}                               <- flag ketangkap dari exploit
[SUBMIT] Accepted | PLAYITPLUS{...}                  <- verdict platform per flag
[ROUND 1] FINISHED ... | flags found: 3 | accepted: 1
```

Berhenti dengan `Ctrl+C`. Flag yang belum terkirim (misalnya submit
sedang ditutup platform) tersimpan di antrean `data/queue.json` dan
dikirim lagi di round berikutnya.

### Kalau framework bermasalah di tengah lomba (fallback manual)

Exploit tetap bisa dijalankan dan di-submit dengan tangan:

```bash
bash challenges/nama-challenge/exploit.sh <IP-target> <PORT-target>

TOKEN=$(curl -s -X POST https://10.0.2.3/api/v2/authenticate \
  -H 'Content-Type: application/json' \
  -d '{"email":"email-akun-tim-kamu","password":"password-akun-tim-kamu"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s -X POST https://10.0.2.3/api/v2/submit \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"flags":["PLAYITPLUS{flag-yang-ketangkap}"]}'
```

Maksimal 128 flag per submit. Jangan submit flag tim sendiri.

### Status pengujian mode ini

- Unit test khusus mode platform: `tests/test_playit.py` (17 checks),
  dan seluruh test lama tetap lolos.
- End-to-end melawan mock platform: auth → services → exploit →
  submit → **Accepted** untuk dua tim dummy.
- End-to-end melawan ADTickPlatform asli (build lokal, match
  dijalankan): auth, peta services, health check, exploit, dan submit
  semua bekerja; flag dummy dibalas `Invalid` — benar, karena platform
  hanya menerima flag HMAC yang diterbitkannya sendiri.

## Langkah-langkah penggunaan

### 1. Siapkan mesin

- Python **3.8+** (cek dengan `python3 --version`). Tidak perlu `pip install`
  apa pun — framework ini hanya pakai stdlib Python.
- `git` untuk clone repo (atau download ZIP dari GitHub).
- Mesin ini harus bisa mencapai jaringan kompetisi (IP target `103.145.226.x`
  dan scoreboard `103.145.226.89:8080`). Kalau mesin kamu pakai proxy,
  framework sudah diatur untuk koneksi langsung — tidak perlu ubah apa pun.

### 2. Clone repo

```bash
git clone https://github.com/usernameuser87/attdef-lksmlg2027.git
cd attdef-lksmlg2027
```

### 3. Isi token tim (wajib)

```bash
cp .env.example .env
```

Buka `.env` dan isi token tim kamu:

```bash
ATTDEF_TEAM_TOKEN=token-tim-kamu
```

Token ini dipakai sebagai header `X-Team-Token` di setiap pengiriman flag.
**Tanpa token, flag TIDAK dikirim** — mereka hanya masuk antrean
(`data/queue.json`) dan menunggu sampai token diisi. Token tidak pernah
ditulis ke log dan file `.env` tidak akan ter-commit (sudah ada di
`.gitignore`).

### 4. (Opsional) Tambah challenge sendiri

Kalau kamu punya exploit Bash untuk service lain, buat folder baru di
`challenges/` — lihat bagian "Tambah challenge baru" di bawah. Kalau belum
ada, lewati langkah ini: tiga contoh challenge sudah disertakan
(`calculator`, `web-flag`, `notes-app`).

### 5. Jalankan

```bash
python3 main.py
```

Biarkan terminal ini terbuka selama kompetisi. Framework jalan terus
sampai kamu menghentikannya dengan `Ctrl+C`.

### 6. Baca output di terminal

Setiap round tampilannya seperti ini:

```
[ROUND 1] START
[ONLINE] SMKN 5 Malang | Calculator
[OFFLINE] SMKN 8 Malang | Calculator | SKIPPED
[EXEC] Calculator | SMKN 5 Malang
[FLAG] LKS{ABC123...}
[SUBMIT] Accepted | LKS{ABC123...} | +75.90 pts
[ROUND 1] FINISHED in 12.4s | flags found: 1 | accepted: 1
[NEXT ROUND] 180-second schedule | Round 2 at 18:03:00 (in 168s)
```

Artinya:

| Baris | Arti |
| --- | --- |
| `[ROUND n] START` | Round dimulai (tepat di tick 180 detik) |
| `[ONLINE] ...` | Target + challenge bisa dijangkau, exploit dijalankan |
| `[OFFLINE] ... \| SKIPPED` | Target/challenge mati, dilewati round ini |
| `[EXEC] ...` | Script Bash dijalankan untuk pasangan itu |
| `[FLAG] ...` | Flag ditemukan di stdout exploit |
| `[SUBMIT] Accepted \| ... \| +75.90 pts` | Scoreboard menerima flag + poinnya |
| `[SUBMIT] Invalid \| ...` | Scoreboard menolak flag (salah/kedaluwarsa) |
| `[QUEUE] n flag(s) waiting for retry` | Ada flag yang gagal dikirim, dicoba lagi round berikut |
| `[ROUND n] FINISHED ...` | Ringkasan round: berapa flag ketemu & diterima |
| `[NEXT ROUND] ...` | Kapan round berikutnya mulai |

### 7. Cek log & status kapan saja

- `logs/round-001-*.log` — detail lengkap tiap round (stderr, exit code,
  timeout, error). Satu file per round.
- `logs/submissions.log` — riwayat setiap percobaan kirim flag beserta
  verdict-nya (`accepted` / `invalid` / `too_old` / `duplicate` /
  `error`) dan poin yang didapat.
- `data/submitted.json` — flag yang sudah punya verdict final (tidak akan
  dikirim ulang).
- `data/queue.json` — flag yang gagal dikirim dan menunggu retry.

### 8. Berhenti

Tekan `Ctrl+C` di terminal framework. Untuk jalan lagi, tinggal
`python3 main.py` — flag yang sudah diterima tidak dikirim ulang, dan
antrean yang tertunda langsung dicoba lagi di round pertama.

## Kalau ada masalah (troubleshooting)

| Gejala | Penyebab & solusi |
| --- | --- |
| `[WARN] ATTDEF_TEAM_TOKEN is empty` saat start | `.env` belum diisi. Isi token, lalu restart framework. Flag yang sudah masuk antrean akan dikirim di round pertama setelah token ada. |
| Semua target `[OFFLINE]` | Mesin tidak bisa mencapai jaringan kompetisi. Cek koneksi (ping salah satu IP target). Framework tetap jalan dan mencoba lagi tiap round. |
| `[SUBMIT] Unknown` terus-menerus | Respons scoreboard tidak dikenali — laporkan ke pembuat framework (ini bug parser, bukan salah kamu). Flag tetap aman di antrean. |
| `[QUEUE] n flag(s) waiting for retry` tidak berkurang | Scoreboard sedang error/timeout. Framework akan retry otomatis tiap round — flag tidak hilang. |
| Round melebihi 180 detik | Normal kalau exploit lambat. Framework tidak pernah menjalankan dua round bersamaan; slot yang terlewat dilewati dan round berikutnya tetap di grid tick. |
| `python3 main.py` langsung crash | Cek `config.json` challenge yang baru kamu tambah (JSON tidak valid, `port` bukan angka, atau `script` tidak ada). Framework memberi `[WARN]` dan melewati challenge yang rusak — kalau tetap crash, jalankan `python3 tests/test_units.py` untuk cek. |

## Scheduler (180 detik, dari START tiap round)

- Interval dihitung dari **waktu MULAI tiap round**, memakai
  `time.monotonic()` (kebal perubahan jam sistem/NTP).
- Contoh: Round 1 mulai 18:00:00, selesai 18:02:20, Round 2 mulai
  tepat 18:03:00.
- Kalau satu round lebih lama dari 180 detik: **tidak ada dua round
  yang berjalan bersamaan**. Slot yang terlewat **dilewati**, round
  berikutnya jalan di slot grid berikutnya — framework tidak pernah
  bergeser (drift) dari tick scoreboard.

```
[ROUND 1] START
...
[ROUND 1] FINISHED in 140.2s | flags found: 3 | accepted: 3
[NEXT ROUND] 180-second schedule | Round 2 at 18:03:00 (in 40s)
```

## Target (hanya yang masuk scope kompetisi)

Sembilan sekolah di `config.py` (`DEFAULT_TARGETS`):

| Tim | IP |
| --- | --- |
| SMKN 5 Malang | 103.145.226.96 |
| SMKS Islam Batu | 103.145.226.94 |
| SMKN 11 Malang | 103.145.226.90 |
| SMKN 8 Malang | 103.145.226.93 |
| SMKN 12 Malang | 103.145.226.82 |
| SMKS PGRI 3 Malang | 103.185.52.42 |
| SMKN 9 Malang | 103.145.226.92 |
| SMK Telkom Malang | 103.185.52.146 |
| SMKN 2 Malang | 103.145.226.98 |

Framework **hanya** menyentuh target dan service di atas. Jangan tambah
target lain.

## Tambah challenge baru

Cukup buat folder baru di `challenges/` — tidak perlu ubah code lain:

```
challenges/nama-challenge/
├── config.json
└── exploit.sh
```

`config.json`:

```json
{
  "name": "Calculator",
  "port": 8081,
  "protocol": "http",
  "health_path": "/health",
  "timeout": 30,
  "script": "exploit.sh",
  "enabled": true
}
```

| Field | Arti |
| --- | --- |
| `name` | Nama challenge (tampil di log) |
| `port` | Port challenge ini (tiap challenge beda) |
| `protocol` | `http`, `https`, atau `tcp` |
| `health_path` | Path health-check (HTTP saja, `""` = `/`) |
| `timeout` | Timeout per proses exploit (detik) |
| `script` | Nama file Bash di folder yang sama |
| `enabled` | `false` = challenge dilewati |

## Kontrak script Bash

Framework menjalankan:

```bash
bash exploit.sh <IP> <PORT>     # $1 = IP target, $2 = port
```

IP dan port tersedia dengan DUA cara — pakai yang mana saja:

- sebagai argumen: `IP="$1"; PORT="$2"`
- sebagai environment variable: `$IP` dan `$PORT` (sudah di-export
  framework ke proses exploit, sejak perbaikan bug 16)

Dua-duanya membawa nilai yang sama. Contoh lama yang pakai `$1`/`$2`
tetap jalan tanpa diubah.

- Tulis exploit seperti biasa (`curl`, `grep`, `sed`, `awk`, dll).
  Source-nya **tidak diubah** dan tidak dipindah ke Python.
- stdout dan stderr ditangkap **terpisah**. Flag dibaca dari stdout.
- **Exit code nonzero bukan berarti tidak ada flag** — flag tetap
  diparsing dari stdout walaupun script exit 1 atau timeout.
- Timeout per proses dari `config.json` — proses yang timeout
  dimatikan, tapi output yang sudah keluar tetap diparsing.
- Satu proses gagal tidak menghentikan yang lain, dan output antar
  proses tidak tercampur.

Contoh `exploit.sh`:

```bash
#!/bin/bash
IP="$1"; PORT="$2"
curl -s --max-time 10 "http://$IP:$PORT/calc?expr=1%2B1%3Bcat%20secret.txt"
```

## Flag parser

Mendukung `LKS{...}` dan `LKSMLG2027{...}`, diekstrak dari stdout Bash.
Sebelum regex, output dibersihkan dari:

- HTML tags (`<div>LKS{ABC}</div>` -> `LKS{ABC}`)
- ANSI escape codes (output berwarna)
- Progress meter curl
- Whitespace berlebih

Flag yang sama hanya dihitung sekali (dedupe).

## Submission API

```
PUT http://103.145.226.89:8080/flags
X-Team-Token: <dari .env>
Content-Type: application/json
Body: ["LKS{FLAG1}", "LKSMLG2027{FLAG2}"]
```

- Token **hanya** dari `.env` (`ATTDEF_TEAM_TOKEN`), tidak pernah
  di-hardcode dan tidak pernah ditulis ke log.
- String kosong dan duplikat tidak pernah dikirim.
- HTTP 200 **tidak** dianggap "semua diterima" — respons dibaca
  per flag: Accepted / Invalid / Too old / Duplicate / Error.
  Format respons scoreboard yang sebenarnya (sudah diverifikasi live):
  `[{"flag": "...", "msg": "[...] Flag accepted! Earned 75.90 flag points!"}]`
  — verdict dibaca dari teks `msg`, dan poin yang didapat ditampilkan di
  console (`[SUBMIT] Accepted | LKS{...} | +75.90 pts`) dan di
  `logs/submissions.log`.
- Koneksi ke scoreboard **langsung, tanpa proxy** — mesin dengan proxy
  terkonfigurasi pun tetap bisa submit (lihat `core/net.py`).
- Flag yang sudah punya verdict final (accepted/invalid/too_old/
  duplicate) dicatat di `data/submitted.json` dan tidak dikirim lagi.
- Kalau submission gagal (server error, timeout, tidak ada jaringan),
  flag masuk antrean aman di `data/queue.json` dan dicoba lagi di
  round berikutnya — **flag tidak pernah hilang**.
- Semua percobaan submission dicatat di `logs/submissions.log`.

## Output terminal

```
[ROUND 1] START
[ONLINE] SMKN 5 Malang | Calculator
[OFFLINE] SMKN 8 Malang | Calculator | SKIPPED
[EXEC] Calculator | SMKN 5 Malang
[FLAG] LKS{...}
[SUBMIT] Accepted | LKS{...} | +75.90 pts
[ROUND 1] FINISHED in 12.4s | flags found: 1 | accepted: 1
[NEXT ROUND] 180-second schedule | Round 2 at 18:03:00 (in 168s)
```

HTML response lengkap tidak pernah dicetak. Detail (stderr, exit code,
timeout) hanya masuk file log round.

## File & log

```
main.py                  # entry point: python3 main.py
config.py                # target, tick, API, path (baca .env + env var)
requirements.txt         # tidak ada dependensi eksternal (stdlib saja)
.env.example             # contoh .env
core/
  loader.py              # baca challenges/*/config.json
  scanner.py             # health-check (HTTP/TCP, paralel, timeout)
  runner.py              # jalankan bash script.sh IP PORT
  parser.py              # ekstrak LKS{...} / LKSMLG2027{...}
  submitter.py           # PUT /flags + dedupe + antrean aman
  scheduler.py           # tick 180s dari START, monotonic, skip overrun
  logger.py              # console ringkas + log per round
  net.py                 # koneksi HTTP langsung, tanpa proxy
challenges/              # contoh: calculator, web-flag, notes-app
logs/
  round-001-*.log        # satu file per round, detail lengkap
  submissions.log        # riwayat submission per flag
data/
  submitted.json         # flag yang sudah punya verdict final
  queue.json             # flag yang gagal dikirim, menunggu retry
tests/                   # mock server + test suite (lihat bawah)
```

## Tes (sudah dijalankan, semua PASS)

Satu soal tes lengkap disertakan: mock service rentan + mock scoreboard
di localhost, jadi tidak menyentuh infrastruktur kompetisi.

```bash
python3 tests/test_units.py       # parser + scheduler + submitter + net + runner + loader + scanner + logger + config (80 checks)
python3 tests/test_framework.py   # end-to-end (29 checks)
python3 tests/test_playit.py      # mode platform PLAYIT: parser respons + chunking 128 + antrean + peta services (17 checks)
```

Yang diverifikasi `test_framework.py`:

- **Phase 1 — tick normal (5 detik), 3 round:** interval antar round
  tepat 5.00 detik; flag ditemukan dan dikirim tepat sekali (tidak ada
  duplikat, tidak ada yang hilang); kedua format flag (`LKS{...}` dan
  `LKSMLG2027{...}`) diterima; target offline dilewati; exploit yang
  exit 1 tetap menghasilkan flag; log per round tersimpan.
- **Antrean submission:** request submit pertama sengaja dibuat gagal
  (HTTP 500) — flag masuk antrean dan berhasil dikirim di round
  berikutnya.
- **Phase 2 — overrun:** satu challenge sengaja dibuat tidur 8 detik
  (lebih lama dari tick 5 detik) — round 2 dilewati, round 3 mulai
  tepat di grid (10.00 detik setelah round 1), tidak ada round yang
  tumpang tindih, dan flag dari challenge lambat itu tetap terkirim.

Hasil terakhir: **80/80 unit tests PASS, 29/29 end-to-end PASS.**

## Bug yang ditemukan & diperbaiki (2026-11-24)

Bug hunt setelah tes submit manual melawan scoreboard asli:

1. **Parser submit tidak membaca format asli scoreboard (kritis).**
   Scoreboard mengembalikan `[{"flag": ..., "msg": "..."}]` — tidak ada
   field `status`. Parser lama hanya membaca `status`, jadi semua flag
   kembali `Unknown` dan terjebak di antrean selamanya, tidak pernah
   tercatat diterima/ditolak. Sekarang verdict dibaca dari teks `msg`
   (`Flag accepted!` / `Flag is invalid or too old.`) dan poin
   (`Earned 75.90 flag points!`) diekstrak dan ditampilkan.
2. **Koneksi lewat proxy (kritis).** `urllib` mengikuti env var
   `http_proxy`/`https_proxy`, jadi di mesin yang proxy-nya terkonfigurasi
   semua health check dan submission gagal (dialihkan ke proxy). Sekarang
   semua koneksi HTTP memakai opener tanpa proxy (`core/net.py`).
3. **Path challenge relatif membuat semua exploit gagal (kritis).**
   Kalau `ATTDEF_CHALLENGES_DIR` diisi path relatif, runner menjalankan
   script dengan `cwd` = folder challenge, sehingga path script tidak
   ketemu (`No such file or directory`, exit 127) dan tidak ada flag
   yang ditemukan sama sekali. Sekarang semua path di-resolve ke absolut
   (`config.py` + `core/loader.py`).
4. **Timeout exploit di Python 3.8–3.10.** `TimeoutExpired` di versi itu
   tidak punya atribut `.stdout` (hanya `.output`) — handler timeout
   akan crash dan flag yang sudah tercetak hilang. Sekarang dibaca
   dengan fallback yang aman di semua versi.
5. **Satu `config.json` rusak mematikan seluruh framework.** Nilai
   `timeout` yang tidak valid (mis. `"abc"` atau `null`) membuat
   `load_challenges()` crash saat startup. Sekarang fallback ke default
   dengan peringatan.
6. **`load_challenges()` dipanggil dua kali** di `main.py` (peringatan
   tercetak ganda). Sekarang sekali saja.
7. **Nilai env yang buruk membuat crash saat startup.** `ATTDEF_TICK=0`
   atau worker `0` membuat `Scheduler`/`ThreadPoolExecutor` melempar
   `ValueError` tanpa penanganan. Sekarang dikembalikan ke default.

## Bug hunt putaran 2 (2026-11-24 malam, belum di-push)

8. **Satu entri antrean yang rusak menghapus SELURUH antrean (kritis).**
   `Submitter._load()` membangun `queue` dengan list comprehension —
   satu entri dengan `"attempts": "abc"` membuat `int()` melempar
   `ValueError`, `except` mereset `self.queue = []`, dan semua flag
   yang menunggu retry hilang (flag rotate, jadi tidak kembali).
   Sekarang tiap entri dibaca dengan toleransi per-item: entri rusak
   dilewati / `attempts` jatuh ke 0, flag yang bagus tetap selamat.
   Bonus dari perbaikan yang sama: `submitted.json` yang isinya bukan
   dict (mis. list) dulu membuat `data.get()` melempar `AttributeError`
   yang tidak tertangkap — framework crash saat startup. Sekarang
   hanya string flag yang valid yang dipakai.
9. **Challenge https dengan sertifikat self-signed selalu OFFLINE.**
   Health check memakai verifikasi TLS default, jadi service https
   dengan cert self-signed (sangat umum di CTF) gagal verifikasi dan
   exploit-nya tidak pernah jalan — diam-diam, tanpa error. Sekarang
   kalau verifikasi gagal karena sertifikat, health check diulang
   tanpa verifikasi (`core/net.py: direct_opener_unverified()`).
   Health check tidak mengirim kredensial, jadi ini tidak membocorkan
   apa pun; exploit Bash-nya sendiri tetap pakai aturan curl masing-masing.
10. **Log spam saat scoreboard lama mati.** Peringatan "exceeded retries"
    dicetak setiap round untuk setiap flag yang mengantre (sekali flag
    melewati batas). Sekarang hanya dicetak sekali, saat batas itu
    pertama kali terlampaui.
11. **`health_path` tanpa slash depan membuat pair salah OFFLINE.**
    `config.json` dengan `"health_path": "health"` membangun URL
    `http://IP:PORThealth` — `InvalidURL` yang tidak tertangkap
    `check_one`, sehingga service yang sebenarnya hidup ditandai
    offline dan exploit-nya tidak pernah jalan. Sekarang loader
    menormalkan path (tambah `/` kalau belum ada) dan scanner
    menganggap segala error URL sebagai offline, bukan crash.
12. **`submitted.json` yang isinya string menghancurkan state.**
    `"accepted": "LKS{ABC}"` (bukan list) membuat set comprehension
    mengiterasi string itu per karakter — `accepted` jadi
    `{'L', 'K', 'S', ...}` dan flag aslinya tidak pernah tercatat
    diterima, jadi dikirim ulang selamanya. Sekarang hanya nilai list
    yang dipakai; yang lain diabaikan.
13. **`ATTDEF_LOGS_DIR=""` / `ATTDEF_DATA_DIR=""` menyebar file state.**
    `Path("")` sama dengan `Path(".")`, jadi file log dan `submitted.json`
    / `queue.json` tertulis ke direktori kerja, bukan ke `logs/` /
    `data/`. Sekarang string kosong dianggap "tidak diset" dan fallback
    ke default.
14. **Parser memakan flag di baris yang diawali persentase.**
    Regex pembersih progress meter cocok dengan SEMUA baris yang diawali
    angka+`%`, jadi output exploit seperti `50% done LKS{...}`
    kehilangan flag-nya. Sekarang regex mensyaratkan kolom waktu curl
    (`--:--:--`), jadi hanya baris meter asli yang dibersih.
15. **`open_round()` di luar `try` di `run_round()`.** Kalau file log
    tidak bisa dibuat (disk penuh, izin), framework crash padahal
    docstring menjanjikan fungsi ini tidak pernah raise. Sekarang
    pembuatan file log ada di dalam `try`.

16. **Exploit yang pakai `$IP`/`$PORT` langsung selalu "malformed"
    (2026-11-25).** Runner hanya melempar IP/port sebagai argumen
    `$1`/`$2` — bukan sebagai env var. Script yang menulis
    `curl "http://$IP:$PORT/..."` tanpa `IP="$1"; PORT="$2"` dulu
    mendapat nilai kosong, jadi curl gagal dengan
    `curl: (3) URL rejected: No host part in the URL` (exit 3).
    Kalau script pakai `set -u`, gagalnya bahkan lebih awal:
    `IP: unbound variable`. Sekarang runner juga mengekspor
    `IP` dan `PORT` sebagai environment variable ke proses exploit,
    jadi kedua gaya (`$1`/`$2` maupun `$IP`/`$PORT`) jalan. Tes
    regresi di `tests/test_units.py` (`[runner: $IP/$PORT env vars]`,
    2 checks) — total unit jadi 65/65.

Tes baru untuk putaran 2 ada di `tests/test_units.py` (submitter state
loading + https self-signed + health_path + corrupt submitted.json +
empty env dirs + parser persentase, 15 checks) — total unit jadi 63/63
sebelum bug 16, 65/65 sesudahnya.

## Bug hunt putaran 3 (2026-11-25)

17. **`ATTDEF_TICK=nan` / `inf` membuat framework crash setelah round 1.**
    `float()` menerima `"nan"` dan `"inf"`, dan cek lama (`<= 0`) tidak
    menangkap keduanya: `nan` lolos ke scheduler lalu `math.ceil(nan)`
    melempar `ValueError` di `advance_after_round`, sementara `inf`
    lolos ke `main()` lalu `timedelta(seconds=inf)` melempar
    `OverflowError` di baris `[NEXT ROUND]`. Keduanya crash di luar
    `try` round, jadi framework mati. Sekarang `config.py` memakai
    helper `_positive_float()` (finite dan > 0, kalau tidak kembali ke
    default 180), dan `Scheduler`/`next_round_index` menolak tick
    non-finite dengan `ValueError` yang jelas di konstruksi (fail fast),
    bukan crash misterius setelah round 1.
18. **Timeout negatif / nol / non-finite gagal diam-diam.** Nilai env
    `ATTDEF_SUBMIT_TIMEOUT=-5` membuat `urlopen` melempar `ValueError`,
    `0` membuat socket non-blocking (semua submit gagal), dan
    `timeout=-5` di `config.json` satu challenge membuat exploit-nya
    mati instan (`TimeoutExpired` seketika) setiap round; `timeout=nan`
    lebih parah — `subprocess.run` melempar `ValueError` yang tidak
    ditangkap `run_one`, jadi SATU challenge rusak meracuni SEMUA round.
    Sekarang semua timeout (env maupun per-challenge) difilter
    `_positive_float()` / cek `math.isfinite` di loader: nilai buruk
    jatuh ke default dengan peringatan.
19. **Log dir yang tidak bisa dipakai mematikan round (dan startup).**
    `Logger()` crash (`FileExistsError`) kalau `ATTDEF_LOGS_DIR` adalah
    file yang sudah ada, dan `open_round()` melempar `FileNotFoundError`
    kalau folder log terhapus setelah startup — round langsung gagal
    sebelum exploit jalan, padahal logging bukan pekerjaannya. Sekarang
    `Logger` toleran: mkdir gagal → lanjut console-only dengan
    peringatan; `open_round` membuat ulang folder yang hilang, dan kalau
    tetap tidak bisa menulis, round tetap jalan (detail log jadi no-op)
    dengan satu peringatan saja.
20. **`SUBMIT_URL` yang salah ketik menghilangkan flag.** `Request()`
    dibuat DI LUAR `try` di `_send()`, jadi URL tanpa skema (`notaurl`),
    URL kosong, atau host berisi spasi melempar `ValueError` /
    `InvalidURL` keluar dari `submit()` — round gagal DAN flag tidak
    pernah masuk antrean, jadi flag yang sudah rotate hilang selamanya.
    Sekarang konstruksi `Request` ada di dalam `try`, dan `except`
    juga menangkap `http.client.HTTPException` (`InvalidURL` BUKAN
    subclass `ValueError`, jadi tanpa ini tetap lolos). URL rusak kini
    sekadar transport error: flag tetap antre dan di-retry.
21. **State file yang tidak bisa ditulis mematikan round.** `_save()`
    melempar `OSError` (mis. `submitted.json` tertimpa folder) keluar
    dari `submit()` → round gagal, padahal state in-memory sudah benar.
    Sekarang `_save()` toleran: gagal tulis dicatat lewat log submission
    (yang juga toleran) dan round lanjut; paling buruk, restart nanti
    mengulang submit yang dijawab scoreboard `DUPLICATE`.

Tes baru untuk putaran 3 ada di `tests/test_units.py` (config env
non-finite, scheduler tick non-finite, loader timeout negatif/nol/
non-finite, logger dir rusak, submitter URL rusak, submitter state
rusak — 9 checks) — total unit jadi 73/73.

## Bug hunt putaran 4 (2026-11-25)

22. **`"enabled": "false"` di `config.json` malah MENGAKTIFKAN challenge.**
    `bool("false")` itu `True` di Python, jadi siapa pun yang menulis
    `"enabled": "false"` (atau `"0"`, `"no"`) mendapat kebalikan dari
    yang diminta — challenge yang diniatkan mati malah jalan dan
    mengirim flag. Sekarang loader memakai `_as_bool()`: string
    `"true"/"1"/"yes"/"on"` dan `"false"/"0"/"no"/"off"` diparse
    case-insensitive, bool dan angka tetap seperti biasa.
23. **`.env` dengan `export KEY=value` diam-diam tidak berfungsi.**
    Loader lama menyimpan variabel dengan nama harfiah
    `"export ATTDEF_TEAM_TOKEN"`, jadi token tetap kosong dan semua
    flag cuma masuk antrean (hanya ada `[WARN]` sekali di startup).
    Sekarang awalan `export ` / `export<TAB>` dihapus dulu sebelum
    key dipakai.
24. **`.env` yang tidak bisa dibaca membuat framework crash saat import.**
    Kalau `.env` ternyata sebuah folder, `read_text()` melempar
    `IsADirectoryError`; kalau isinya bukan UTF-8 valid, melempar
    `UnicodeDecodeError` — keduanya terjadi di `import config`,
    sebelum `try/except` apa pun ada, jadi framework tidak bisa start
    sama sekali. Sekarang `_load_dotenv()` menangkap `OSError` /
    `ValueError`, memberi peringatan, dan lanjut dengan default.
25. **`script` yang isinya folder lolos loader.** `exists()` bernilai
    `True` untuk folder, jadi `exploit.sh` yang ternyata direktori
    dimuat sebagai challenge lalu gagal tiap round dengan exit 126
    (`bash: ... is a directory`), nol flag, tanpa peringatan yang
    jelas. Sekarang loader memakai `is_file()`.

Tes baru untuk putaran 4 ada di `tests/test_units.py` (loader enabled
string, loader script harus file, config .env export + .env rusak —
7 checks) — total unit jadi 80/80.

## Catatan

- Python 3.8+ saja, tanpa `pip install` apa pun.
- Jangan jalankan framework ini ke target di luar scope kompetisi.
- Token tim ada di `.env` — jangan commit file itu (sudah ada di
  `.gitignore`).
