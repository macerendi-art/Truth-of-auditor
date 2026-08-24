"""Pulihkan nominal gateway yang ter-parse dari notasi ilmiah Excel.

Excel/openpyxl kadang menulis 10_000_000 sebagai teks ``1.0E7``.
``parse_decimal`` lama membuang huruf dulu → ``1.0E7`` jadi ``1.07``.
Akibat: panel 10jt ↔ mutasi Rp1, selisih 9.999.999 (BSW 22-08-2026, dll.).

Pemulihan: baca ulang ``raw['total_amount']`` (atau alias Flyer) dengan
``parse_decimal`` yang sudah mendukung ilmiah; perbarui ``amount``,
``money_delta``, dan ``row_hash``.

Bawaan dry-run. ``--terapkan`` menulis. Sasaran terkunci batch → henti
(hapus batch dulu — keputusan pemilik).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction as db_transaction
from django.db.models import Count

from sources.parsers.base import parse_decimal, row_hash
from transactions.models import Transaction

# Kolom nominal yang mungkin di raw Flyer (dan saudara)
_RAW_AMOUNT_KEYS = (
    "total_amount",
    "Transaction Value",
    "Amount",
    "amount",
    "TOTAL_AMOUNT",
)

_SCI_RE = re.compile(r"[0-9][eE][+\-]?[0-9]")


def _raw_nominal(raw: dict | None) -> str | None:
    if not raw:
        return None
    for k in _RAW_AMOUNT_KEYS:
        if k in raw and raw[k] not in (None, ""):
            return str(raw[k])
    # case-insensitive fallback
    lower = {str(k).lower(): v for k, v in raw.items()}
    for k in ("total_amount", "transaction value", "amount"):
        if k in lower and lower[k] not in (None, ""):
            return str(lower[k])
    return None


def _is_sci(s: str) -> bool:
    return bool(_SCI_RE.search(s.replace(" ", "")))


class Command(BaseCommand):
    help = (
        "Pulihkan amount gateway dari raw notasi ilmiah (1.0E7→10jt); "
        "dry-run bawaan."
    )

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        parser.add_argument(
            "--tanggal",
            default=None,
            help="batasi ke satu posted_date (YYYY-MM-DD)",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="laporkan saja (bawaan)")
        mode.add_argument("--terapkan", action="store_true", help="tulis perubahan")

    def handle(self, *args, **opts):
        tanggal = self._parse_tanggal(opts["tanggal"])
        ids = self._kandidat_ids(toko_key=opts["toko"], tanggal=tanggal)
        qs = Transaction.objects.filter(id__in=ids).select_related("toko")
        for kelompok in (
            qs.values("toko__key", "posted_date")
            .annotate(n=Count("id"))
            .order_by("toko__key", "posted_date")
        ):
            self.stdout.write(
                f"sasaran toko={kelompok['toko__key'] or '-'} "
                f"tanggal={kelompok['posted_date'] or 'tanpa-tanggal'} n={kelompok['n']}"
            )

        terkunci = qs.filter(consumed_by_batch__isnull=False).count()
        self.stdout.write(f"kandidat={qs.count()} terkunci_batch={terkunci}")
        if terkunci:
            self.stdout.write(
                self.style.ERROR(
                    "DIHENTIKAN: ada sasaran terkunci batch. Hapus batch terkait dulu, "
                    "lalu jalankan ulang --terapkan."
                )
            )
            return

        siap = []
        for tx in qs.order_by("id").iterator(chunk_size=200):
            raw_s = _raw_nominal(tx.raw)
            if not raw_s or not _is_sci(raw_s):
                continue
            baru = abs(parse_decimal(raw_s))
            lama = abs(tx.amount or Decimal("0"))
            if baru <= 0 or baru == lama:
                continue
            # Hanya naikkan/koreksi bila selisih material (hindari noise)
            if abs(baru - lama) < Decimal("1"):
                continue
            want_jenis = tx.jenis or "depo"
            tx.amount = baru
            tx.money_delta = -baru if want_jenis == "wd" else baru
            # row_hash Flyer: qrflyer|ticket|ref|amt — samakan agar re-upload = dup
            ref = (tx.reference or "").strip()
            ticket = (tx.ticket_no or "").strip()
            tx.row_hash = row_hash("qrflyer", [ticket, ref, baru])
            siap.append(tx)
            if len(siap) <= 15:
                self.stdout.write(
                    f"  id={tx.id} {tx.toko.key if tx.toko_id else '-'} "
                    f"{tx.posted_date} {ticket} {lama} → {baru} (raw={raw_s!r})"
                )

        if opts["terapkan"] and siap:
            with db_transaction.atomic():
                id_list = [tx.id for tx in siap]
                terkunci_baru = (
                    Transaction.objects.select_for_update()
                    .filter(id__in=id_list, consumed_by_batch__isnull=False)
                    .count()
                )
                if terkunci_baru:
                    self.stdout.write(
                        self.style.ERROR(
                            f"DIHENTIKAN: terkunci batch={terkunci_baru} saat tulis; 0 diubah."
                        )
                    )
                    return
                Transaction.objects.bulk_update(
                    siap, ["amount", "money_delta", "row_hash"]
                )
            self.stdout.write(self.style.SUCCESS(f"diperbaiki={len(siap)}"))
        else:
            self.stdout.write(
                f"siap_diperbaiki={len(siap)} (dry-run — pakai --terapkan untuk menulis)"
            )

    def _kandidat_ids(self, toko_key=None, tanggal=None):
        """SQL: gateway yang raw total_amount (dll) memuat notasi ilmiah."""
        sql = """
            SELECT t.id
            FROM transactions_transaction t
            JOIN sources_sourcetype st ON st.id = t.source_type_id
            JOIN sources_toko tk ON tk.id = t.toko_id
            WHERE st.key = 'gateway'
              AND (
                COALESCE(t.raw->>'total_amount','') ~* '[0-9]e[+\-]?[0-9]'
                OR COALESCE(t.raw->>'Transaction Value','') ~* '[0-9]e[+\-]?[0-9]'
                OR COALESCE(t.raw->>'Amount','') ~* '[0-9]e[+\-]?[0-9]'
              )
        """
        params = []
        if toko_key:
            sql += " AND tk.key = %s"
            params.append(toko_key)
        if tanggal is not None:
            sql += " AND t.posted_date = %s"
            params.append(tanggal)
        with connection.cursor() as c:
            c.execute(sql, params)
            return [r[0] for r in c.fetchall()]

    def _parse_tanggal(self, s):
        if not s:
            return None
        try:
            y, m, d = s.split("-")
            return date(int(y), int(m), int(d))
        except Exception as e:
            raise CommandError(f"tanggal tidak valid: {s}") from e
