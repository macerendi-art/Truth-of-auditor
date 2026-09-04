"""Kandidat "gratis dan pasti setara" dari CLAUDE.md, bagian
"Anomali matcher 25-08-2026":

    > Yang gratis dan pasti setara: lewati `_name_score` saat username persis
    > sama (`max(100, s) ≡ 100`).

`_MoneyMatcher._identity` (reconciliation/engine.py) saat ini:

    if p.username and b.username:
        s = 100.0 if p.username.lower() == b.username.lower() else 40.0
        if p.counterparty and b.counterparty:
            s = max(s, _name_score(p.counterparty, b.counterparty))
        return s

Saat username PERSIS SAMA, `s` sudah 100.0 SEBELUM baris `_name_score`
dipanggil -- dan `_name_score` mengembalikan skor di rentang [0, 100], jadi
`max(100.0, apa pun_di_rentang_itu)` SELALU 100.0. Baris itu memanggil
rapidfuzz lalu MEMBUANG hasilnya lewat `max()`. Patch ini menambah SATU guard
(`s < 100.0`) sebelum baris itu -- provably equivalent, bukan tebakan: untuk
SEMUA nilai kemungkinan `_name_score` di [0, 100], hasil akhir `s` tak pernah
berubah. Dibuktikan EMPIRIS (bukan cuma argumen) oleh `sidik_jari.py --patch`
+ `bandingkan.py`: lihat docs/riset-money-phones-2026-09-04.md.

DIPAKAI LEWAT MONKEYPATCH IN-MEMORY, BUKAN MENULIS reconciliation/engine.py:
tiap skrip di paket harness ini adalah PROSES YANG KELUAR setelah selesai, dan
`terapkan()` hanya mengubah atribut kelas pada objek modul `engine` yang
diimpor proses ITU -- efeknya lenyap begitu proses berakhir, tak pernah bocor
ke `reconciliation/engine.py` di disk atau ke proses lain.

CATATAN JUJUR (lihat docs/riset-money-phones-2026-09-04.md untuk detail):
patch ini TIDAK menyentuh `_phone_match`/`_money_phones` -- pemeriksaan nomor
HP/VA yang menurut profil produksi 25-08-2026 justru BIAYA UTAMA pada rezim
QRIS ELITE (Vigor/TM Gaming). Manfaat patch ini terbatas pada baris yang (a)
username-nya persis sama DAN (b) kedua sisi punya `counterparty` terisi --
bukan perbaikan untuk pola lambat yang didiagnosis di CLAUDE.md.
"""


def terapkan(engine):
    """Monkeypatch `engine._MoneyMatcher._identity` di tempat. Mengembalikan
    fungsi ASLI (unwrapped) supaya pemanggil bisa memulihkannya bila perlu,
    meski dalam pemakaian normal (skrip sekali-proses) itu tak dibutuhkan."""
    # `_identity` diakses lewat KELAS: deskriptor `staticmethod` sudah
    # mengembalikan fungsi polos (bukan bound/unbound method), jadi TANPA
    # `.__func__` -- beda dari method biasa.
    asli = engine._MoneyMatcher._identity

    def _identity_patched(p, b):
        pp = getattr(p, "_phone", None)
        if pp is None:
            pp = p._phone = engine._panel_phone(p)
        phones = getattr(b, "_phones", None)
        if phones is None:
            phones = b._phones = engine._money_phones(b)
        if engine._phone_match(pp, phones):
            return 100.0
        if p.username and b.username:
            s = 100.0 if p.username.lower() == b.username.lower() else 40.0
            # --- satu-satunya beda dari _identity asli: guard 's < 100.0' ---
            # max(100.0, x) selalu 100.0 utk x di [0,100] (rentang _name_score),
            # jadi memanggilnya saat s sudah 100.0 murni biaya tanpa efek hasil.
            if s < 100.0 and p.counterparty and b.counterparty:
                s = max(s, engine._name_score(p.counterparty, b.counterparty))
            return s
        return engine._name_score(p.counterparty, b.counterparty)

    engine._MoneyMatcher._identity = staticmethod(_identity_patched)
    return asli


def pulihkan(engine, asli):
    """Kebalikan `terapkan()` -- jarang dibutuhkan (proses biasanya keluar
    setelah selesai), disediakan untuk skrip yang menguji baseline & kandidat
    dalam satu proses yang sama (mis. `ukur_kandidat.py`)."""
    engine._MoneyMatcher._identity = staticmethod(asli)
