"""Rincian Rekening — breakdown sisi UANG (bank/gateway) per rekening operator.

Kembaran Breakdown Bracket untuk mutasi bank nyata. Baris per rekening
(`source_label_full`, mis. "BCA a/n HENDI"): Deposit / Withdraw / Biaya Admin /
Net / Trx / Saldo Awal / Saldo Akhir / Selisih Kontrol. Saldo memakai
`balance_after` (saldo berjalan statement) via metode rantai-saldo yang sama
dengan breakdown FR (`_saldo_batas`) — kebal acak urutan. Sumber tanpa saldo
(gateway QRIS, BCA PDF) → saldo & selisih "—".
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum

from sources.models import Account, SourceType, Upload
from transactions.models import Transaction
from web.breakdown import _saldo_batas

NOL = Decimal("0")
MONEY_KEYS = ("bank", "gateway")


def _label_kombinasi(kombinasi):
    """(source_type_id, account_id, upload_id) → label `source_label_full`.

    Label rekening adalah FUNGSI MURNI dari ketiga kunci itu (lihat
    `Transaction.source_label_full`): `source_type` memilih jalur bank/gateway
    vs generik, `account.provider` MENANG atas provider upload, dan upload
    menyumbang provider + nama file + `owner_name`. Kalau kuncinya kurang —
    misalnya hanya `upload_id` — dua baris dengan rekening berbeda dari satu
    file akan lebur jadi SATU baris rekening, dan mutasi/saldonya tercatat di
    rekening yang salah.

    Dihitung SEKALI per kombinasi (ratusan), bukan per baris (ratusan ribu):
    referensinya (SourceType/Account/Upload) di-fetch bulk lalu logika labelnya
    DIPAKAI ULANG lewat instance `Transaction` tak-tersimpan — bukan disalin ke
    sini, supaya tak bisa menyimpang dari badge di halaman Transaksi. Hasilnya
    HIDUP HANYA SELAMA PANGGILAN INI (jangan pernah global: aplikasi keuangan,
    label harus ikut data terbaru tiap request).
    """
    st_ids = {st for st, _a, _u in kombinasi}
    acc_ids = {a for _st, a, _u in kombinasi if a is not None}
    up_ids = {u for _st, _a, u in kombinasi if u is not None}
    st_map = SourceType.objects.in_bulk(st_ids)
    acc_map = Account.objects.in_bulk(acc_ids)
    up_map = {
        u.id: u
        for u in Upload.objects.filter(id__in=up_ids).select_related("account")
    }
    labels = {}
    for st_id, acc_id, up_id in kombinasi:
        t = Transaction(source_type=st_map[st_id])
        if acc_id is not None:
            t.account = acc_map[acc_id]
        if up_id is not None:
            t.upload = up_map[up_id]
        labels[(st_id, acc_id, up_id)] = t.source_label_full
    return labels, st_map


def rekening_breakdown(toko, dari, sampai=None):
    """Agregasi sisi uang `toko` untuk `occurred_at ∈ [dari, sampai]` → dict view.

    Rentang [dari, sampai] (default `sampai=dari` = perilaku 1-hari lama, dipakai
    juga oleh sheet export per-batch). Saldo memakai `balance_after`: karena baris
    diurut `(occurred_at, id)` — `occurred_at` datetime penuh, jadi rantai saldo
    benar lintas hari — `_saldo_batas` atas baris in-range menghasilkan saldo_awal
    = saldo sebelum baris pertama rentang (carry-in dari hari sebelumnya, otomatis)
    dan saldo_akhir = penutup baris terakhir. Rekening tanpa baris in-range tak
    tampil (sama seperti mode 1-hari).

    Bentuknya DUA query, bukan materialisasi ORM per baris (dulu: rentang sebulan
    = 267 rb objek `Transaction` + relasinya ≈ 800 rb `Model.__init__`, 20+ detik
    murni membangun objek Python yang lalu cuma dijumlah):
    (1) GROUP BY (source_type, account, upload) di SQL untuk deposit/withdraw/
        admin/mutasi/trx/count — grup = kombinasi label, ratusan bukan ratusan ribu;
    (2) fetch `values_list` HANYA baris ber-`balance_after` (bank; gateway QRIS
        tak bersaldo dan memang tak pernah menyumbang rantai) untuk `_saldo_batas`.
    `_saldo_batas` sendiri mengabaikan baris tanpa saldo — di loop multiset maupun
    fallback first/last (`t[3] is not None`) — jadi menyaringnya di SQL identik
    dengan menyertakannya lalu dilewati di Python.

    {"accounts": [per rekening], "total": agregat, "count": jumlah baris,
     "dari": date, "sampai": date}
    """
    if sampai is None:
        sampai = dari
    if dari > sampai:
        dari, sampai = sampai, dari
    # Rentang datetime setengah-terbuka, BUKAN `occurred_at__date__range` yang
    # lebih enak dibaca: `__date__` membungkus kolomnya (`CAST(occurred_at AS DATE)`
    # di Postgres) sehingga index btree atas `occurred_at` — `(source_type,
    # occurred_at)` yang ada di `transactions.Transaction.Meta.indexes` — TIDAK
    # bisa dipakai dan setiap muat halaman /rekening/ jadi scan lebar (1,88 dtk
    # di toko besar, prod). Dengan sisi kiri kolom telanjang, index terpakai.
    # Setara persis: `USE_TZ = False` dan seluruh waktu di app ini naif WIB, jadi
    # `CAST(occurred_at AS DATE) BETWEEN dari AND sampai` == `dari 00:00:00 <=
    # occurred_at < (sampai+1) 00:00:00`; baris `occurred_at` NULL sama-sama gugur.
    # Batasnya dikunci `test_batas_tengah_malam_ikut_terhitung` — jangan "dirapikan".
    #
    # Ujung kalender ditangani TERPISAH: `date.max` (9999-12-31) + 1 hari melempar
    # `OverflowError` — di Python, SEBELUM query dibentuk — jadi yang muncul bukan
    # tabel kosong melainkan HTTP 500 untuk seluruh halaman. Tanggal itu bisa
    # dicapai lewat UI biasa: `<input type="date">` di rekening.html tak punya
    # atribut `max` dan spinner tahun bawaan browser sampai 9999, sementara
    # `web/views.py::_parse_date` (`date.fromisoformat`) menerimanya sebagai
    # tanggal sah. Pembatasan di template bukan penjaga; penjaganya di sini.
    # Di ujung itu batas EKSKLUSIF `sampai+1 00:00:00` diganti batas INKLUSIF
    # `datetime.max` — semantiknya sama persis ("sampai akhir hari terakhir yang
    # bisa diwakili") tanpa aritmetika yang bisa meluap, dan untuk tanggal waras
    # mana pun cabang ini tak pernah diambil sehingga tak satu angka pun berubah.
    if sampai >= date.max:
        batas_atas = {"occurred_at__lte": datetime.max}
    else:
        batas_atas = {
            "occurred_at__lt": datetime.combine(sampai + timedelta(days=1), time.min)
        }
    # SATU filter dasar untuk kedua query — batas tanggalnya tak boleh menyimpang.
    dasar = Transaction.objects.filter(
        toko=toko, source_type__key__in=MONEY_KEYS,
        occurred_at__gte=datetime.combine(dari, time.min),
        **batas_atas,
    )

    # (1) Agregat per kombinasi label, dihitung di SQL. `.order_by()` WAJIB:
    # ordering apa pun yang bocor akan ikut masuk GROUP BY (Django menambahkan
    # kolom sort ke grouping) → satu grup per baris → kembali memindahkan ratusan
    # ribu baris ke Python, tanpa satu tes pun gagal karena angkanya tetap benar.
    bukan_admin = ~Q(jenis="admin")
    agregat = (
        dasar.values("source_type_id", "account_id", "upload_id")
        .order_by()
        .annotate(
            n=Count("id"),
            # Semantik lama per baris: `admin` menang atas arah (baris admin
            # berdelta positif tetap admin, bukan deposit); baris non-admin
            # berdelta 0 hanya menyumbang mutasi & count, tidak deposit/withdraw/trx.
            #
            # `mutasi`/`admin` MENGECUALIKAN baris berdelta 0 — bukan demi angka
            # (nol tak menambah apa-apa) tapi demi SKALA Decimal-nya: loop lama
            # memakai `t.money_delta or NOL`, jadi baris 0.00 tersalin sebagai
            # Decimal('0') skala-0 dan grup yang SEMUA barisnya nol menghasilkan
            # '0', bukan '0.00'. Sum tanpa filter mengembalikan '0.00' untuk grup
            # itu — nilainya sama, str()-nya beda, render template bergeser.
            # Dengan filter, grup all-nol → NULL → NOL ('0'), persis loop lama.
            mutasi=Sum("money_delta", filter=~Q(money_delta=0)),
            admin=Sum("money_delta", filter=Q(jenis="admin") & ~Q(money_delta=0)),
            deposit=Sum("money_delta", filter=bukan_admin & Q(money_delta__gt=0)),
            withdraw=Sum("money_delta", filter=bukan_admin & Q(money_delta__lt=0)),
            trx=Count(
                "id",
                filter=bukan_admin & (Q(money_delta__gt=0) | Q(money_delta__lt=0)),
            ),
        )
    )
    agregat = list(agregat)

    labels, st_map = _label_kombinasi(
        [(r["source_type_id"], r["account_id"], r["upload_id"]) for r in agregat]
    )

    # Dua kombinasi berbeda bisa menghasilkan label yang SAMA (mis. dua upload
    # harian rekening yang sama dalam satu rentang) — di layar itu satu baris
    # rekening, jadi agregatnya dilebur per label, persis perilaku lama.
    per = {}  # label → dict kolom
    count = 0
    for r in agregat:
        count += r["n"]
        label = labels[(r["source_type_id"], r["account_id"], r["upload_id"])]
        slot = per.setdefault(label, {
            "deposit": NOL, "withdraw": NOL, "admin": NOL, "mutasi": NOL,
            "trx": 0, "is_gateway": False, "items": [],
        })
        if st_map[r["source_type_id"]].key == "gateway":
            slot["is_gateway"] = True
        # `is None`, BUKAN `or`: Sum SQL yang delta-nya saling meniadakan
        # mengembalikan Decimal('0.00') — falsy, dan `or NOL` menggantinya jadi
        # Decimal('0') yang nilainya sama tapi str()-nya beda ('0' vs '0.00'),
        # menggeser render template. Terbukti di data nyata (k25 Juli 2026).
        for k in ("deposit", "withdraw", "admin", "mutasi"):
            v = r[k]
            slot[k] += NOL if v is None else v
        slot["trx"] += r["trx"]

    # (2) Baris rantai saldo: hanya yang ber-`balance_after`, tuple ringan (bukan
    # objek ORM), urut global (occurred_at, id) — appended per label dalam urutan
    # stream, jadi kombinasi yang melebur ke satu label tetap ter-interleave benar
    # dan first/last fallback `_saldo_batas` melihat urutan yang sama dgn dulu.
    rantai = (
        dasar.filter(balance_after__isnull=False)
        .order_by("occurred_at", "id")
        .values_list(
            "source_type_id", "account_id", "upload_id",
            "occurred_at", "id", "money_delta", "balance_after",
        )
    )
    # TANPA `.iterator()`: server-side cursor Postgres memakai rencana yang
    # dioptimalkan untuk sebagian awal hasil (cursor_tuple_fraction) dan terukur
    # ~2× lebih lambat di sini; barisnya sudah tersaring ber-saldo (bank saja,
    # ±14% dari baris rentang) jadi materialisasi list tuple ringan aman.
    for st_id, acc_id, up_id, jam, pk, delta, bal in rantai:
        # bentuk tuple sama dgn breakdown FR agar _saldo_batas bisa dipakai ulang:
        # (jam, id, delta, balance, slug) — slug tak dipakai _saldo_batas.
        per[labels[(st_id, acc_id, up_id)]]["items"].append(
            (jam, pk, delta or NOL, bal, None)
        )

    accounts = []
    for label, slot in per.items():
        withdraw = abs(slot["withdraw"])
        saldo_awal, saldo_akhir = _saldo_batas(slot["items"])
        selisih = None
        if saldo_awal is not None and saldo_akhir is not None:
            selisih = saldo_akhir - (saldo_awal + slot["mutasi"])
        accounts.append({
            "label": label, "is_gateway": slot["is_gateway"],
            "deposit": slot["deposit"], "withdraw": withdraw, "admin": slot["admin"],
            "net": slot["deposit"] - withdraw, "trx": slot["trx"],
            "mutasi": slot["mutasi"],
            "saldo_awal": saldo_awal, "saldo_akhir": saldo_akhir, "selisih": selisih,
        })

    accounts.sort(key=lambda a: (a["is_gateway"], a["label"]))

    total = {
        "deposit": NOL, "withdraw": NOL, "admin": NOL, "net": NOL, "trx": 0,
        "mutasi": NOL, "saldo_awal": None, "saldo_akhir": None, "selisih": None,
    }
    for a in accounts:
        for k in ("deposit", "withdraw", "admin", "net", "trx", "mutasi"):
            total[k] += a[k]
        for k in ("saldo_awal", "saldo_akhir", "selisih"):
            if a[k] is not None:
                total[k] = (total[k] or NOL) + a[k]
    return {
        "accounts": accounts, "total": total, "count": count,
        "dari": dari, "sampai": sampai,
    }
