"""Laporkan index `transactions_transaction` yang HILANG atau INVALID.

    python manage.py periksa_index     # keluar 0 bila bersih, 1 bila ada temuan

Alasan perintah ini ada: `core/db_ops.TambahIndexAman` sengaja TIDAK pernah
menggagalkan boot — kegagalannya cuma `logger.warning`, dan karena
`apply()` tidak melempar, `MigrationExecutor.apply_migration` tetap memanggil
`record_migration()`. Migrasinya TERCATAT selesai walau index-nya tak pernah
jadi, boot berikutnya melewatinya, dan tak ada satu pun jalur otomatis yang
akan membangunnya ulang. Yang tersisa: halaman lambat, diam-diam, tanpa
keluhan. Perintah ini satu-satunya deteksi yang benar-benar ada — jalankan
setelah deploy yang menyentuh index, dan setiap kali ada `warning` dari
`core.db_ops` di log boot.

Dua bentuk kerusakan yang dicari:

- **hilang**  — index yang tertulis di `Transaction._meta.indexes` tapi tak
  ada di tabelnya. Penyebab lazim: `CREATE INDEX CONCURRENTLY` manual belum
  dijalankan DAN migrasinya gagal (lihat di atas).
- **invalid** — index yang ADA tapi `pg_index.indisvalid = false`: sisa
  `CREATE INDEX CONCURRENTLY` yang gagal/terputus. Planner MENGABAIKANNYA,
  jadi kueri tetap lambat, tetapi namanya memblokir pembuatan ulang — bentuk
  paling menipu dari ketiganya, karena `\\d transactions_transaction` tetap
  menampilkannya seolah baik-baik saja. Yang ini dicari untuk SELURUH index
  tabel, bukan hanya yang terdaftar di model: index unique-constraint pun bisa
  invalid, dan akibatnya sama.

Di luar PostgreSQL (SQLite tes & dev) `pg_index` tak ada dan konsep index
invalid tak berlaku — perintah melapor apa adanya lalu keluar 0, bukan
berpura-pura bersih dan bukan pula galat.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from transactions.models import Transaction

# Semua index tabel + status validitasnya. `indisvalid` = false berarti index
# ada tapi diabaikan planner. `relkind = 'i'` menyaring supaya yang terhitung
# hanya relasi index.
SQL_KATALOG = """
SELECT c.relname, i.indisvalid
  FROM pg_class c
  JOIN pg_index i ON i.indexrelid = c.oid
  JOIN pg_class t ON t.oid = i.indrelid
 WHERE t.relname = %s AND c.relkind = 'i'
"""


def periksa(diharapkan, katalog):
    """Bandingkan daftar index yang WAJIB ada dengan isi katalog DB. MURNI.

    `diharapkan` — iterable nama index (dari `Model._meta.indexes`).
    `katalog`    — {nama index yang benar-benar ada di tabel: indisvalid(bool)}.

    → daftar temuan `{"nama": str, "status": "hilang"|"invalid"}`, terurut
      nama supaya keluarannya bisa dibandingkan antar-jalan. Kosong = bersih.

    Sengaja tanpa DB dan tanpa Django: ambang & aturannya bisa diuji langsung,
    pola yang sama dipakai `web/penjaga.py`. Index yang ada TAPI invalid muncul
    sekali saja (sebagai "invalid", bukan juga "hilang") — ia memang ada.
    """
    temuan = [
        {"nama": nama, "status": "hilang"}
        for nama in diharapkan
        if nama not in katalog
    ]
    temuan += [
        {"nama": nama, "status": "invalid"}
        for nama, valid in katalog.items()
        if not valid
    ]
    return sorted(temuan, key=lambda t: (t["nama"], t["status"]))


def baca_katalog(conn, tabel):
    """{nama index: indisvalid} untuk `tabel` menurut katalog PostgreSQL."""
    with conn.cursor() as cur:
        cur.execute(SQL_KATALOG, [tabel])
        return {nama: bool(valid) for nama, valid in cur.fetchall()}


PEMULIHAN = {
    "hilang": "CREATE INDEX CONCURRENTLY … (lihat runbook DDL; jangan lewat migrate — boot menggantung)",
    "invalid": "DROP INDEX CONCURRENTLY {nama}; lalu bangun ulang",
}


class Command(BaseCommand):
    help = ("Laporkan index transactions_transaction yang hilang atau invalid "
            "(keluar 1 bila ada temuan).")

    def handle(self, *args, **opts):
        tabel = Transaction._meta.db_table
        if connection.vendor != "postgresql":
            self.stdout.write(
                f"Tidak berlaku: basis data ini '{connection.vendor}', bukan "
                "postgresql. `pg_index` tak ada dan index invalid bukan konsep "
                "di sini — tak ada yang bisa diperiksa."
            )
            return

        diharapkan = [i.name for i in Transaction._meta.indexes]
        katalog = baca_katalog(connection, tabel)
        temuan = periksa(diharapkan, katalog)

        self.stdout.write(
            f"{tabel}: {len(katalog)} index di DB, {len(diharapkan)} diwajibkan model."
        )
        if not temuan:
            self.stdout.write(self.style.SUCCESS("Bersih — tak ada index hilang/invalid."))
            return

        for t in temuan:
            self.stdout.write(self.style.ERROR(
                f"  {t['status'].upper():8} {t['nama']}  → "
                + PEMULIHAN[t["status"]].format(nama=t["nama"])
            ))
        raise CommandError(
            f"{len(temuan)} index bermasalah di {tabel}. Halaman akan lambat "
            "(angkanya tetap benar). Perbaiki lewat psql di luar jam sibuk; "
            "`migrate` TIDAK akan memperbaikinya sendiri — migrasinya sudah "
            "tercatat selesai."
        )
