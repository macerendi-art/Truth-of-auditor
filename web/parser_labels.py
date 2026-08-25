"""Label tampilan jenis parser di Impor data (UI only — value POST tetap key).

Prefix internal ``cor_*`` diganti di label sesuai panel toko:
- ``panel=vigor`` → ``Vgr_*``
- ``panel=tm_gaming`` → ``Tmg_*``
- ``panel=nexus`` → ``Vgr_*``  (bukan nx_ — permintaan owner)
- panel kosong / tak dikenal → tetap ``cor_*``

Value ``<option>`` dan commit ingest **tidak** berubah — hanya teks yang
terlihat + pencarian combobox Jenis terdeteksi.
"""
from __future__ import annotations

from sources.models import Toko
from sources.services import PARSERS

# panel toko → pengganti awalan "cor" (casing label: Vgr / Tmg)
_PANEL_PREFIX = {
    Toko.PANEL_VIGOR: "Vgr",
    Toko.PANEL_TMG: "Tmg",
    Toko.PANEL_NEXUS: "Vgr",
}


def label_parser(parser_key: str, panel: str = "") -> str:
    """Teks opsi dropdown untuk satu parser_key.

    Hanya mengganti awalan literal ``cor_`` (bukan substring di tengah nama).
    """
    key = (parser_key or "").strip()
    if not key.startswith("cor_"):
        return key
    ganti = _PANEL_PREFIX.get((panel or "").strip().lower())
    if not ganti:
        return key
    return f"{ganti}_{key[4:]}"


def parser_options(panel: str = ""):
    """Daftar ``{\"key\", \"label\"}`` terurut key — siap template Impor."""
    return [
        {"key": k, "label": label_parser(k, panel)}
        for k in sorted(PARSERS.keys())
    ]
