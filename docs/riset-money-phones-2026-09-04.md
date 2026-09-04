# Riset E3 — harness sidik-jari + dampak `_money_phones` (2026-09-04)

Status: **RISET SELESAI, TIDAK DITERAPKAN** (sesuai gerbang di brief — perubahan
matcher aktual adalah keputusan pemilik, bukan bagian tugas ini).

## Ringkasan

1. **Harness sidik-jari dibangun** di `scripts/harness/` — sebelumnya CLAUDE.md
   menyebutnya berulang kali sebagai prasyarat setiap perubahan matcher, tapi
   belum pernah ada. Diverifikasi: deterministik byte-untuk-byte, bisa
   membandingkan dua revisi per-baris (bukan cuma "berbeda"), murni baca.
2. Kandidat "lewati `_name_score` saat username persis sama" **terbukti
   fingerprint-identik** di semua data yang diuji (data lokal nyata + data
   sintetik yang meniru bentuk insiden 25-08-2026) — aman secara PERILAKU.
3. **Dampak kecepatannya, jujur: nol-terukur pada data lokal, dan KECIL SECARA
   STRUKTURAL pada rezim yang sebenarnya jadi masalah** (QRIS ELITE). Kandidat
   ini TIDAK menyentuh `_phone_match`/`_money_phones`, yang menurut CLAUDE.md
   adalah biaya utama di rezim itu (10,9 dtk dari 14,8 dtk `kandidat`).
   Rekomendasi: aman untuk diterapkan (tidak mengubah hasil), tapi jangan
   diharapkan sebagai perbaikan kecepatan yang berarti untuk anomali
   25-08-2026 — itu perlu perbaikan lain (lihat bagian Rekomendasi).

## Skala & lingkungan (baca ini sebelum mengutip angka mana pun di bawah)

- DB lokal (`db.sqlite3` dev, dipakai bersama agen lain di worktree ini):
  **71.584** baris `Transaction`, hanya **2 toko** berisi data — `k25`
  (31.675 baris) dan `lbs` (39.909 baris), keduanya **panel "nexus" mode
  TICKET** (`Toko.panel == "nexus"`, diverifikasi lewat ORM). **Tidak ada
  satu baris pun** dari toko Vigor/TM Gaming (`g25`/`w25`/`cah`) atau gateway
  QRIS ELITE — yaitu PERSIS rezim yang memicu riset ini. Semua angka "data
  nyata" di bawah karena itu HANYA mewakili rezim Nexus/mode-ticket, BUKAN
  rezim ELITE yang jadi soal utama anomali 25-08-2026.
- Untuk rezim ELITE, dipakai data **SINTETIK** yang dibuat khusus (lihat
  bagian "Bagian 2 — sintetik" di bawah) — dilabeli jelas di setiap output,
  skala jauh lebih kecil dari insiden produksi (4.969.497 pasangan).
- Produksi: 10,34 juta baris (04-09-2026) — TIDAK disentuh, tidak diukur
  langsung sama sekali dalam riset ini (larangan brief).
- DB yang dipakai menjalankan harness = **salinan sekali-pakai** dari
  `db.sqlite3` dev, di-`migrate` ke skema terbaru lalu dibuang setelah sesi
  ini (skema dev saat disalin ternyata belum penuh ter-`migrate` — kolom
  `Toko.panel`/`Toko.kepemilikan` belum ada; migrate pada SALINAN memperbaiki
  ini tanpa menyentuh `db.sqlite3` yang dipakai bersama sesi lain).

## Bagian 1 — Harness sidik-jari

### Kenapa ini penting (kutipan CLAUDE.md)

> Apa pun yang menyempitkan jendela pass 2, mengubah blocking, atau menggeser
> kunci sort **mengubah hasil** dan dilarang kontrak determinisme — setiap
> kandidat perbaikan wajib digerbangi harness sidik-jari `(left_id, right_id,
> bucket, reason_code, score)` atas hari nyata.

Harness ini belum pernah dibangun sebelum sesi ini — dicek `scripts/`,
`reconciliation/`, tidak ada berkas serupa. Sekarang ada, di `scripts/harness/`:

| Berkas | Peran |
|---|---|
| `inti.py` | Fungsi bersama: boot Django ke SALINAN sqlite, jalankan satu matcher relasi lewat `matcher.sides()`+`matcher.match()` (bypass `run_batch` — lihat "Batasan sengaja" di bawah), kanonikalisasi & serialisasi sidik jari, baca/tulis berkas. |
| `sidik_jari.py` | CLI: hasilkan satu berkas sidik-jari dari satu (DB, toko, rentang tanggal, daftar relasi), opsional `--patch modul:fungsi` untuk menguji kandidat lewat monkeypatch in-memory. |
| `bandingkan.py` | CLI: diff dua berkas sidik-jari, laporan **per baris** (hilang/baru/berubah), exit code 0 hanya bila identik — bisa dipakai sbg gerbang otomatis. |
| `patch_lewati_name_score.py` | Kandidat spesifik Bagian 2 (lihat di bawah), dipakai lewat mekanisme `--patch`. |
| `ukur_kandidat.py` | CLI: gabungan sidik-jari + waktu-tempuh baseline vs kandidat pada data NYATA (satu DB, satu proses, biar bisa dibandingkan adil). |
| `sintetik_elite.py` | CLI: reproduksi SINTETIK rezim ELITE (tanpa DB sama sekali), karena data lokal tak mewakilinya. |

### Kontrak yang dipenuhi (per baris brief)

- **Deterministik**: dua jalan atas data SAMA → berkas identik byte-untuk-byte.
  **Dibuktikan**, bukan diasumsikan:
  ```
  $ python scripts/harness/sidik_jari.py --db ... --toko lbs ... --out run1.txt
  $ python scripts/harness/sidik_jari.py --db ... --toko lbs ... --out run2.txt
  $ cmp run1.txt run2.txt && echo "IDENTIK byte-untuk-byte"
  IDENTIK byte-untuk-byte
  ```
  (lbs, rentang 2026-06-01..2026-06-28, 3 relasi, 35.385 baris — `cmp` lolos).
- **Bisa membandingkan dua revisi, per baris, bukan cuma "berbeda"**:
  `bandingkan.py` mengelompokkan tiap ketidaksamaan ke `hilang`/`baru`/`berubah`,
  dengan detail baris. **Diverifikasi kedua arah**: (a) kandidat Bagian 2 yang
  BENAR-BENAR setara → `identik=16000 hilang=0 baru=0 berubah=0`; (b) kandidat
  SABOTASE sengaja (`_identity` dipaksa selalu `100.0`, untuk membuktikan
  alatnya benar-benar mendeteksi, bukan selalu bilang "aman") →
  `identik=15105 hilang=0 baru=0 berubah=895`, tiap baris berubah tercetak
  dengan bucket/reason/score lama vs baru, exit code 1. Skrip sabotase itu
  file sekali-pakai, sudah dihapus — bukan bagian deliverable. `bandingkan()`
  juga menjaga diri sendiri: `assert` bahwa jumlah kunci unik == jumlah baris
  di tiap berkas, supaya kunci yang (secara teori) bertabrakan gagal KERAS
  alih-alih diam-diam menimpa satu baris dan membuat diff KURANG melapor.
- **Tidak mengubah data**: harness memanggil `matcher.sides()` + `matcher.match()`
  LANGSUNG, bukan `reconciliation.engine.run_batch` — tidak ada `ReconBatch`/
  `MatchRun`/`MatchResult` yang PERNAH `.save()`/`bulk_create()`. Dijalankan di
  atas salinan sqlite sekali-pakai (dibuang setelah sesi), meski sifatnya
  sendiri sudah baca-saja.
- **Terdokumentasi**: docstring di kepala tiap berkas berisi cara pakai
  lengkap (lihat kutipan di atas + isi berkas).

### Batasan sengaja (baca sebelum memakai harness ini utk hal lain)

- **Bypass `run_batch`, bukan mengganti kontraknya.** Harness memanggil
  `matcher.sides()`+`matcher.match()` langsung, TIDAK mereplikasi orkestrasi
  batch harian (`carried`/`retro`/`consumed_by_batch`/gerbang `completeness`).
  Ini sengaja: pertanyaan yang dijawab kontrak determinisme CLAUDE.md adalah
  "apakah keputusan PASANGAN matcher berubah", bukan "apakah status batch
  berubah" — dan `sides()` sendiri sudah menyaring `_active()` (baris yang
  sudah `consumed_by_batch` tidak ikut), jadi harness otomatis hanya melihat
  populasi yang REALISTIS diproses ulang.
- **Konsekuensi nyata yang terlihat saat memakainya**: untuk toko `k25` lokal,
  dari 7.933 baris panel hanya **239** yang `consumed_by_batch IS NULL`
  (7.694 sudah terkonsumsi Batch #4) — jadi sidik jari `k25` hanya mewakili
  239 baris, bukan seluruh riwayatnya. Ini BUKAN bug harness; itu perilaku
  matcher yang benar (baris yang sudah final tidak diproses ulang). Toko `lbs`
  kebetulan 100% masih aktif (16.000/16.000) — dipakai sbg sampel utama Bagian
  2 karena volumenya lebih besar.
- **Urutan OUTPUT vs urutan KOMPUTASI.** Baris di berkas sidik-jari diurutkan
  kanonik (`relation, left_id, right_id`) demi diff yang stabil — ini TIDAK
  menyentuh urutan `sides()` atau kunci sort di dalam `match()` sama sekali
  (harness hanya membaca hasil `match()` yang SUDAH final sebelum
  diurutkan-ulang untuk ditampilkan). Kontrak determinisme CLAUDE.md soal
  `order_by("id")` dan pemecah seri `-left.id/-right.id` di dalam
  `reconciliation/engine.py` tidak disentuh atau dipengaruhi harness ini
  dengan cara apa pun — harness ini sendiri tidak mengubah `reconciliation/`.
- Kunci baris di `bandingkan.py` adalah `(relation, "L", left_id)` atau
  `(relation, "R", right_id)` bila `left_id` NULL — BUKAN pasangan
  `(left_id, right_id)` penuh. Sengaja: itu satu-satunya cara menangkap kasus
  "kredit yang sama kini kawin dengan uang yang berbeda" sebagai **berubah**,
  bukan tersamar jadi satu baris hilang + satu baris baru yang kebetulan tak
  pernah disandingkan pembaca manusia.

## Bagian 2 — dampak kandidat "lewati `_name_score` saat username sama"

### Kandidat yang diuji

Dari `_MoneyMatcher._identity` (`reconciliation/engine.py`):

```python
if p.username and b.username:
    s = 100.0 if p.username.lower() == b.username.lower() else 40.0
    if p.counterparty and b.counterparty:
        s = max(s, _name_score(p.counterparty, b.counterparty))   # <- dibuang max() saat s==100
    return s
```

`max(100.0, x)` untuk `x` di rentang `[0, 100]` (rentang `_name_score`) SELALU
`100.0` — jadi memanggil `_name_score` saat `s` sudah `100.0` murni biaya
tanpa efek pada hasil akhir. Patch (`scripts/harness/patch_lewati_name_score.py`)
menambah satu guard `s < 100.0` sebelum baris itu. **Tidak menyentuh
`_phone_match`/`_money_phones` sama sekali** (blok itu tetap dijalankan penuh,
identik, sebelum baris yang di-guard).

### Hasil pada DATA NYATA lokal (rezim Nexus/mode-ticket — BUKAN rezim ELITE)

Diukur `scripts/harness/ukur_kandidat.py`, 7 ulangan per sel, median wall-time
`matcher.match()` per panggilan (proses sama, DB sama, hanya `_identity`
di-monkeypatch di antara dua pengukuran):

| toko | relasi | n baris hasil | fingerprint identik | speedup median (baseline/patch) |
|---|---|---:|---|---:|
| k25 | panel_bank | 239 | **True** | 0,94× (dlm noise) |
| k25 | panel_bracket | 239 | True | 1,00× (matcher lain, tak tersentuh patch — kontrol negatif) |
| k25 | bracket_bank | 18 | True | 0,99× |
| lbs | panel_bank | 16.000 | **True** | 1,02× (dlm noise) |
| lbs | panel_bracket | 16.000 | True | 1,00× (kontrol negatif) |
| lbs | bracket_bank | 3.385 | True | 1,00× |

`panel_bracket` disertakan sengaja sebagai **kontrol negatif**: matcher itu
tidak pernah memanggil `_MoneyMatcher._identity` sama sekali, jadi speedup-nya
HARUS ≈1,0× kalau alat ukurnya jujur — dan memang begitu.

(Relasi keempat, `fr_bank` — default `--relations` yang tidak muncul di tabel
ini karena `FR_BANK_ENABLED=False` di produksi — sudah diverifikasi TERPISAH
bisa berjalan lewat harness ini: lbs, 8.069 baris, dua jalan `sidik_jari.py`
byte-untuk-byte identik. Disebut di sini supaya default `--relations` di
`sidik_jari.py` tidak diam-diam berisi kombinasi yang tak pernah dicoba.)

**Kesimpulan jujur**: pada rezim Nexus/mode-ticket, dampak kecepatannya **tidak
terukur di atas noise** (rentang 0,94×–1,02× pada 7 ulangan). Ini masuk akal:
mode ticket menyelesaikan mayoritas baris di pass 0/0b (join ticket/reference
EXACT) SEBELUM pernah sampai ke `_identity` pass 1 — populasi yang benar-benar
mengevaluasi `_identity` kecil, jadi ruang penghematan juga kecil.

### Hasil pada data SINTETIK yang meniru rezim ELITE

DB lokal tidak punya rezim ELITE sama sekali (lihat "Skala & lingkungan"), jadi
dibangun `scripts/harness/sintetik_elite.py`: N baris panel (tanpa
ticket/reference, seperti panel DP QRIS ELITE COR yang sebenarnya) × N baris
gateway (raw berisi `ID`/`VENDOR ID` 9-digit — persis mekanisme yang dipanen
`_money_phones` sbg "nomor HP" palsu), satu bucket nominal+tanggal yang sama
sehingga SELURUH N×N pasangan dievaluasi di pass 1 (meniru struktur insiden
25-08-2026: 8.502 baris panel × bucket nominal → 4.969.497 pasangan — TAK
mungkin direplikasi persis di laptop, jadi diuji pada skala jauh lebih kecil).
Hanya diagonal `i==j` (username persis sama) yang jadi pasangan "benar":

| n (baris tiap sisi) | pasangan dievaluasi | fraksi diagonal | fingerprint identik | speedup median |
|---:|---:|---:|---|---:|
| 60 | 3.600 | 1,67% | True | 1,05× |
| 300 | 90.000 | 0,33% | True | 0,99× (dlm noise) |

**Pola yang konsisten dan bisa dijelaskan**: manfaat patch skala dgn fraksi
"diagonal" (pasangan yang username-nya persis sama) terhadap TOTAL pasangan
dievaluasi — pada insiden nyata (8.502 panel vs pool gateway per bucket),
fraksi itu jauh lebih kecil lagi daripada 0,33% di atas (populasi jauh lebih
besar per bucket nominal), jadi manfaatnya **secara struktural kecil**, bukan
sekadar "belum sempat terukur". `_phone_match`/`_money_phones` — yang menurut
profil CLAUDE.md adalah 10,9 dtk dari 14,8 dtk `kandidat` — SAMA SEKALI tidak
disentuh patch ini, dan tetap dijalankan identik pada kedua varian.

**Sintetik ini bahkan MURAH HATI ke patch, dan tetap tak menang.** Data sintetik
mengisi `counterparty` di SEMUA baris panel & gateway (supaya `_name_score`
punya sesuatu utk dikerjakan bila TIDAK di-skip). CLAUDE.md sendiri mencatat
insiden produksi 25-08-2026 hanya menghasilkan **231 rb panggilan
`_name_score`** dari **4.969.497 pasangan** (≈4,6%) — artinya pada MAYORITAS
pasangan produksi sungguhan, `counterparty` kemungkinan KOSONG di salah satu
sisi (kondisi `if p.counterparty and b.counterparty` di `_identity` gagal
duluan, `_name_score` tak pernah dipanggil SAMA SEKALI — dgn ATAU tanpa
patch). Populasi yang benar-benar bisa diselamatkan patch ini di produksi
kemungkinan LEBIH KECIL lagi daripada fraksi diagonal 0,33%–1,67% di atas,
bukan lebih besar. Sintetik di sini karena itu adalah skenario yang
MENGUNTUNGKAN patch dibanding kondisi produksi sungguhan, dan hasilnya
tetap masuk noise — argumen tambahan bahwa kesimpulan "manfaat kecil" bukan
artefak desain sintetik yang tak adil.

### Rekomendasi

1. **Aman diterapkan** (fingerprint identik di semua data diuji, argumen
   matematis `max(100,x)≡100` untuk `x∈[0,100]` berlaku universal) — tapi
   **jangan diklaim sebagai perbaikan anomali 25-08-2026**. Dampaknya nyata
   tapi kecil dan pada sumbu yang BEDA dari bottleneck yang dilaporkan
   (`_phone_match`, bukan `_name_score`).
2. **Perbaikan yang benar-benar menyasar anomali itu ada di DATA, bukan
   kode** — persis seperti sudah dicatat CLAUDE.md: panel bisa mengekspor DP
   QRIS ELITE dengan `Transaction ID`, atau ELITE menuliskan tiket panel di
   kolom `TICKET` untuk Vigor/TM Gaming (sudah dilakukannya untuk brand
   Nexus) → pass 0/0b hidup lagi, `_phone_match` tak pernah dipanggil massal.
   Riset ini TIDAK menemukan alasan untuk mengubah kesimpulan itu.
3. Bila suatu saat ATURAN pemangkasan `_phone_match`/`_money_phones` mau
   dikalibrasi (mis. menyaring kunci `raw` mana yang boleh dipanen sbg
   "nomor HP") — CLAUDE.md sudah menegaskan itu MENGUBAH HASIL dan perlu
   kalibrasi terpisah dengan data ELITE **sungguhan** (bukan sintetik seperti
   di sini): sintetik ini cukup untuk membuktikan METODOLOGI harness bekerja
   pada bentuk data itu, TIDAK cukup untuk mengkalibrasi ambang mana pun
   (mis. panjang digit minimum, exclude-list nama kolom `raw`) karena
   distribusi ID/VENDOR-ID sungguhan (tabrakan dgn nomor HP asli, dsb) tak
   direplikasi.

### Yang masih perlu dikalibrasi sebelum ADA keputusan penerapan

- Data ELITE **produksi sungguhan** (bukan sintetik) melalui harness ini,
  untuk toko Vigor/TM Gaming — riset ini tidak mengaksesnya (larangan brief).
- Volume nyata pass-1 per hari per toko pada rezim ELITE saat ini (setelah
  9 hari berjalan sejak 25-08-2026) — apakah pola 93,5% cocok / 22-29 dtk
  masih berlaku atau sudah membaik/berubah.
- Bila kandidat lain (mis. indeks HP + memo, yang CLAUDE.md sudah menolak
  dengan angka regresi 0,78× pada hari UNO/Nexus) ingin diuji ulang — harness
  ini SUDAH siap dipakai: `sidik_jari.py --patch modul:fungsi` + `bandingkan.py`
  memberi bukti fingerprint sebelum satu baris `reconciliation/engine.py`
  pun perlu disentuh untuk mengujinya.

## Cara mereproduksi angka di atas

```bash
# 1) Salin DB dev, migrate salinannya (aman -- SALINAN, bukan db.sqlite3 asli)
cp db.sqlite3 /tmp/salinan.sqlite3
DATABASE_URL=sqlite:////tmp/salinan.sqlite3 \
    /Users/macads/Truth-of-auditor/.venv/bin/python manage.py migrate

# 2) Determinisme (dua kali jalan sama persis)
/Users/macads/Truth-of-auditor/.venv/bin/python scripts/harness/sidik_jari.py \
    --db /tmp/salinan.sqlite3 --toko lbs --dari 2026-06-01 --sampai 2026-06-28 \
    --relations panel_bank --out /tmp/fp1.txt
/Users/macads/Truth-of-auditor/.venv/bin/python scripts/harness/sidik_jari.py \
    --db /tmp/salinan.sqlite3 --toko lbs --dari 2026-06-01 --sampai 2026-06-28 \
    --relations panel_bank --out /tmp/fp2.txt
cmp /tmp/fp1.txt /tmp/fp2.txt && echo IDENTIK

# 3) Kandidat Bagian 2 -- fingerprint + waktu, data nyata
/Users/macads/Truth-of-auditor/.venv/bin/python scripts/harness/ukur_kandidat.py \
    --db /tmp/salinan.sqlite3 --toko lbs --dari 2026-06-01 --sampai 2026-06-28 \
    --relations panel_bank,panel_bracket,bracket_bank --ulang 7

# 4) Kandidat Bagian 2 -- rezim ELITE sintetik (tanpa DB)
/Users/macads/Truth-of-auditor/.venv/bin/python scripts/harness/sintetik_elite.py \
    --n 300 --ulang 5
```
