# Auto ATTDEF Framework — LKSMLG 2027

Framework otomatisasi Attack-Defense CTF. Python hanya jadi orchestrator,
**Bash tetap bahasa utama exploit**. Sekali jalan, jalan terus:

```bash
python3 main.py
```

## Cara jalan

```bash
# 1. Salin .env dan isi token tim (wajib)
cp .env.example .env
# edit .env -> ATTDEF_TEAM_TOKEN=...

# 2. Jalankan (tidak perlu install apa-apa, stdlib Python saja)
python3 main.py
```

Berhenti dengan `Ctrl+C`. Framework tidak perlu dijalankan ulang tiap tick.

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
[SUBMIT] Accepted | LKS{...}
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
python3 tests/test_units.py       # parser + scheduler (31 checks)
python3 tests/test_framework.py   # end-to-end (29 checks)
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

Hasil terakhir: **31/31 unit tests PASS, 29/29 end-to-end PASS.**

## Catatan

- Python 3.8+ saja, tanpa `pip install` apa pun.
- Jangan jalankan framework ini ke target di luar scope kompetisi.
- Token tim ada di `.env` — jangan commit file itu (sudah ada di
  `.gitignore`).
