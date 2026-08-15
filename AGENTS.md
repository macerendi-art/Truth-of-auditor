# AGENTS.md

**Instruksi otoritatif untuk repo ini ada di [`CLAUDE.md`](CLAUDE.md). Baca berkas itu
sampai habis sebelum menyentuh kode apa pun.** Berkas ini sengaja pendek: ia hanya
menunjuk ke sana, ditambah beberapa catatan khusus agen non-Claude.

Alasannya bukan kerapian. `CLAUDE.md` memuat ±200 baris kendala domain yang tiap satunya
lahir dari cacat produksi nyata — konvensi tanda & skala, aturan anchor mesin pencocokan,
penjaga parser, invarian `raw`, catatan performa. Melewatinya berarti mengulangi cacat
yang sudah dibayar mahal.

## Peringatan: salinan basi

Sampai 2026-08-15 ada `AGENTS.md` lama (70 baris, tak ter-track git) yang beredar di
checkout utama. Isinya **salah** dan berbahaya di dua titik:

| Klaim salinan basi | Kenyataan sekarang |
|---|---|
| "`db.sqlite3` is committed" | `db.sqlite3` **gitignored**, memuat data kerja nyata, **jangan pernah** di-commit |
| "**Do not push to origin main**" | Aturan sekarang: **commit per potongan kerja DAN push** ke `origin/main` (fast-forward saja) |

Ia juga mendeskripsikan mesin pencocokan sebagai join ticket sederhana — itu keadaan
sebelum matcher multi-pass dan **aturan anchor**, yang merupakan keputusan domain paling
penting di seluruh basis kode. Kalau menemukan berkas dengan isi seperti itu, buang dan
pakai `CLAUDE.md`.

## Catatan khusus agen non-Claude

- **Bahasa.** UI, komentar kode, pesan commit, dan dokumen memakai **bahasa Indonesia**.
  Pertahankan konvensi itu; jangan "perbaiki" jadi Inggris.
- **Virtualenv** ada di `.venv` — `source .venv/bin/activate` sebelum perintah apa pun.
- **Tes yang me-render template** butuh `staticfiles.json` hasil
  `python manage.py collectstatic --noinput` (gitignored). Worktree/CI baru akan gagal
  dengan `Missing staticfiles manifest entry` sampai perintah itu dijalankan sekali.
- **Deploy tidak otomatis.** `git push` **tidak** men-deploy. Deploy manual, hanya dengan
  konfirmasi eksplisit pemilik — ini aplikasi finansial yang hidup. Lihat bagian
  Deployment di `CLAUDE.md`.
- **Handoff sesi terakhir:** [`docs/handoff-2026-08-15.md`](docs/handoff-2026-08-15.md) —
  keadaan terkini, pekerjaan terbuka yang sudah diprioritaskan, dan jebakan yang diketahui.
