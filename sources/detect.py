"""Auto-deteksi jenis sumber file dari tanda-tangan header/isi.

detect_source(path, filename) -> [{"parser_key", "confidence"}] terurut menurun.
parser_key mengacu ke kunci sources.services.PARSERS.
"""
import os

import openpyxl


def _ext(filename):
    return os.path.splitext(filename)[1].lower()


def _xlsx_tokens(path, max_rows=3):
    toks = set()
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if i > max_rows:
                break
            for c in row:
                if c is not None:
                    toks.add(str(c).strip().lower())
        wb.close()
    except Exception:
        pass
    return toks


def _csv_text(path, n=6):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return "\n".join(line.strip().lower() for _, line in zip(range(n), f))
    except Exception:
        return ""


def _has(toks, needle):
    return any(needle in t for t in toks)


def detect_source(path, filename=""):
    filename = filename or os.path.basename(path)
    ext = _ext(filename)
    fn = filename.lower()
    scored = {}

    def add(key, conf):
        scored[key] = max(scored.get(key, 0.0), conf)

    if ext in (".xlsx", ".xls"):
        t = _xlsx_tokens(path)
        if _has(t, "ticket number") and _has(t, "user name") and (_has(t, "deposit amount") or _has(t, "withdrawal amount")):
            add("panel", 0.95)
        if _has(t, "ticket number") and (_has(t, "admin fee") or _has(t, "account title")) and not _has(t, "deposit amount"):
            add("nxpay", 0.90)
        if _has(t, "kategori") and (_has(t, "credit awal") or _has(t, "credit akhir")):
            add("bracket", 0.95)
        if _has(t, "client reference") and (_has(t, "settlement time") or _has(t, "txn id")):
            add("qrflyer", 0.90)
        if _has(t, "qris") or _has(t, "qr flyer") or "qrflyer" in fn or "qris" in fn or "qr flyer" in fn:
            add("qrflyer", 0.85)
        if _has(t, "e-statement") or _has(t, "rekening koran") or "mandiri" in fn:
            add("mandiri", 0.80)
    elif ext == ".csv":
        c = _csv_text(path)
        if "mutasi_debet" in c or "mutasi_kredit" in c or "tgl_tran" in c:
            add("bri", 0.95)
        if ("cabang" in c and "keterangan" in c and "saldo" in c) or "bca" in fn:
            add("bca_csv", 0.85)
    elif ext == ".pdf":
        add("bca_pdf", 0.75)

    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    return [{"parser_key": k, "confidence": c} for k, c in ranked]
