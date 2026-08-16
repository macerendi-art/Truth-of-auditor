"""Penurunan arah transaksi dari nama berkas."""
import os
import re


def detect_flow(path):
    """Ambil token ``dp``/``wd`` terakhir dari nama berkas.

    Nama ekspor sering memuat lebih dari satu penanda arah. Token terakhir
    adalah penanda paling spesifik yang diketik operator. Token harus berdiri
    sendiri: ``WDPANEL`` dan ``DPNXPAY`` bukan penanda arah.
    """
    nama = os.path.basename(os.fspath(path)).casefold()
    token_arah = [
        token for token in re.split(r"[^a-z0-9]+", nama)
        if token in {"dp", "wd"}
    ]
    return token_arah[-1] if token_arah else ""
