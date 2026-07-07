import re

from django.db import models

from core.models import TimeStampedModel

# Peta token -> label sumber spesifik. Kunci = huruf/angka saja (tanpa spasi),
# dicocokkan per-token utuh dari nama file / provider — BUKAN substring, dan
# TIDAK PERNAH menebak dari teks counterparty.
SPECIFIC_SOURCE_LABELS = {
    "BCA": "BCA",
    "BRI": "BRI",
    "BNI": "BNI",
    "MANDIRI": "MANDIRI",
    "CIMB": "CIMB",
    "PERMATA": "PERMATA",
    "DANAMON": "DANAMON",
    "SEABANK": "SEABANK",
    "JAGO": "JAGO",
    "DANA": "DANA",
    "OVO": "OVO",
    "GOPAY": "GOPAY",
    "LINKAJA": "LINKAJA",
    "SHOPEEPAY": "SHOPEEPAY",
    "QRIS": "QRIS",
    "NXPAY": "NXPAY",
    "QRFLYER": "QR FLYER",
}

_MONEY_KEYS = ("bank", "gateway")


def _normalize_provider(value):
    """'QRFLYER'/'qr flyer' -> 'QR FLYER'; provider tak dikenal tetap dipakai apa adanya."""
    compact = re.sub(r"[^A-Z0-9]+", "", (value or "").upper())
    if not compact:
        return ""
    return SPECIFIC_SOURCE_LABELS.get(compact, (value or "").strip().upper())


def provider_from_filename(name):
    """Ambil token bank/gateway dari nama file upload.

    Contoh nyata: '27_JUNI_2026_WD_BCA_HENDI.pdf' -> 'BCA',
    'MUTASI DP QR FLYER OKE25 27-06.xlsx' -> 'QR FLYER'. Tidak dikenal -> ''.
    """
    tokens = [t for t in re.split(r"[^A-Z0-9]+", (name or "").upper()) if t]
    for i, tok in enumerate(tokens):
        if i + 1 < len(tokens):  # token dua kata, mis. 'QR' + 'FLYER'
            pair = tok + tokens[i + 1]
            if pair in SPECIFIC_SOURCE_LABELS:
                return SPECIFIC_SOURCE_LABELS[pair]
        if tok in SPECIFIC_SOURCE_LABELS:
            return SPECIFIC_SOURCE_LABELS[tok]
    return ""


def specific_source_label(source_key, account=None, upload=None):
    """Label sumber spesifik untuk badge Transaksi.

    Bank/gateway: account.provider > upload.account.provider > upload.provider >
    token dari upload.original_name > fallback 'Bank'/'Gateway'.
    Panel/bracket: tetap label generik ('Panel'/'Bracket').
    """
    key = (source_key or "").lower()
    if key not in _MONEY_KEYS:
        return key.capitalize()
    candidates = []
    if account is not None:
        candidates.append(account.provider)
    if upload is not None:
        if upload.account_id and upload.account is not None:
            candidates.append(upload.account.provider)
        candidates.append(upload.provider)
    for cand in candidates:
        label = _normalize_provider(cand)
        if label:
            return label
    if upload is not None:
        label = provider_from_filename(upload.original_name)
        if label:
            return label
    return key.capitalize()


class Transaction(TimeStampedModel):
    """Baris transaksi kanonik dari SEMUA sumber (uang dinormalisasi ke rupiah)."""

    class Jenis(models.TextChoices):
        DEPO = "depo", "Deposit"
        WD = "wd", "Withdraw"
        BONUS = "bonus", "Bonus"
        ADMIN = "admin", "Biaya Admin"
        MISTAKE = "mistake", "Mistake"
        LAINNYA = "lainnya", "Lainnya"

    upload = models.ForeignKey(
        "sources.Upload", on_delete=models.CASCADE, related_name="transactions"
    )
    source_type = models.ForeignKey("sources.SourceType", on_delete=models.PROTECT)
    account = models.ForeignKey(
        "sources.Account", on_delete=models.SET_NULL, null=True, blank=True
    )
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.PROTECT, null=True, blank=True
    )

    occurred_at = models.DateTimeField(
        null=True, blank=True, help_text="Waktu transaksi asli"
    )
    posted_date = models.DateField(
        null=True, blank=True, help_text="Tanggal 'masuk' (statement/entry)"
    )
    jenis = models.CharField(max_length=10, choices=Jenis.choices, default=Jenis.LAINNYA)

    # Semua nilai uang dinormalisasi ke RUPIAH (Panel sudah dikali amount_scale, mis. x1000)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    money_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    fee = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_after = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )

    # Kunci pencocokan
    ticket_no = models.CharField(max_length=64, blank=True, db_index=True)
    username = models.CharField(max_length=100, blank=True, db_index=True)
    reference = models.CharField(max_length=128, blank=True, db_index=True)
    counterparty = models.CharField(
        max_length=200, blank=True, help_text="nama pengirim/penerima di bank"
    )
    # Kode bank/dompet pemain (sisi kredit) untuk filter: player_bank dari
    # Player Bank / No. Rek Bank Member, bank_title dari Bank Title / Bank.
    # Kosong utk sumber uang (bank/gateway). Tanpa index: query selalu ter-scope run.
    player_bank = models.CharField(max_length=40, blank=True)
    bank_title = models.CharField(max_length=40, blank=True)

    description = models.TextField(blank=True)
    raw = models.JSONField(default=dict, help_text="baris asli (telusur balik)")
    row_hash = models.CharField(
        max_length=64, db_index=True, help_text="guard idempotensi re-import"
    )
    is_duplicate = models.BooleanField(default=False)
    # Setelah batch rekonsiliasi sukses, transaksi yang dipakai "dikonsumsi" (dikunci
    # ke batch itu) agar tidak masuk lagi ke kelengkapan/pencocokan run berikutnya —
    # run selanjutnya butuh upload ulang. SET_NULL: hapus batch → transaksi bebas lagi.
    consumed_by_batch = models.ForeignKey(
        "reconciliation.ReconBatch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consumed_transactions",
        db_index=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "occurred_at"]),
            models.Index(fields=["jenis", "amount"]),
        ]
        constraints = [
            # Idempotensi di DB (guard aplikasi di ingest tetap ada): dua proses
            # ingest bersamaan tak boleh menghasilkan baris kembar. Diverifikasi
            # 2026-07-07: lokal & prod 0 duplikat sebelum constraint ini masuk.
            models.UniqueConstraint(
                fields=["source_type", "toko", "row_hash"],
                name="uniq_tx_source_toko_rowhash",
            ),
            # NULL dianggap distinct oleh constraint di atas — jalur ingest tanpa
            # toko (CLI debug) dijaga constraint kondisional terpisah.
            models.UniqueConstraint(
                fields=["source_type", "row_hash"],
                condition=models.Q(toko__isnull=True),
                name="uniq_tx_source_rowhash_toko_null",
            ),
        ]

    def __str__(self):
        return f"{self.get_jenis_display()} {self.amount}"

    @property
    def source_label(self):
        """Badge sumber spesifik (BCA/BRI/NXPAY/QR FLYER/...) — read-only, tanpa migrasi."""
        return specific_source_label(
            self.source_type.key,
            account=self.account if self.account_id else None,
            upload=self.upload if self.upload_id else None,
        )
