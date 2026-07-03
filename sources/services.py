"""Service ingest: parse file -> simpan Transaction kanonik (idempoten via row_hash)."""
from pathlib import Path

from django.db import transaction as db_tx

from transactions.models import Transaction

from .models import SourceType, Upload
from .parsers.banks import BCACSVParser, BRIParser, MandiriParser
from .parsers.bca_pdf import BCAPDFParser
from .parsers.bracket import BracketParser
from .parsers.gateways import NXPayParser, QRFlyerParser
from .parsers.panel import PanelParser

# parser_key -> kelas parser (parser.source_key menentukan SourceType-nya)
PARSERS = {
    "bracket": BracketParser,
    "panel": PanelParser,
    "bri": BRIParser,
    "bca_csv": BCACSVParser,
    "bca_pdf": BCAPDFParser,
    "mandiri": MandiriParser,
    "nxpay": NXPayParser,
    "qrflyer": QRFlyerParser,
}


def ingest(parser_key, file_path, recon_date=None, account=None, flow="", user=None, toko=None, provider=""):
    """Parse `file_path` dengan parser `parser_key`, simpan sebagai Transaction.

    Mengembalikan (upload, created, duplicate).
    """
    if parser_key not in PARSERS:
        raise ValueError(f"Parser '{parser_key}' tidak dikenal. Pilihan: {', '.join(PARSERS)}")

    parser = PARSERS[parser_key]()
    rows = parser.parse(file_path, flow=flow)
    st = SourceType.objects.get(key=parser.source_key)

    with db_tx.atomic():
        up = Upload.objects.create(
            source_type=st,
            account=account,
            toko=toko,
            provider=provider,
            flow=flow or "",
            recon_date=recon_date,
            original_name=Path(file_path).name,
            status=Upload.PARSED,
            uploaded_by=user,
        )
        existing = set(
            Transaction.objects.filter(source_type=st, toko=toko).values_list("row_hash", flat=True)
        )
        objs, seen, dup = [], set(), 0
        for row in rows:
            rh = row["row_hash"]
            if rh in existing or rh in seen:
                dup += 1
                continue
            seen.add(rh)
            objs.append(
                Transaction(
                    upload=up,
                    source_type=st,
                    account=account,
                    toko=toko,
                    occurred_at=row["occurred_at"],
                    posted_date=row["posted_date"],
                    jenis=row["jenis"],
                    amount=row["amount"],
                    credit_delta=row["credit_delta"],
                    money_delta=row["money_delta"],
                    fee=row["fee"],
                    bonus=row["bonus"],
                    balance_after=row["balance_after"],
                    ticket_no=row["ticket_no"],
                    username=row["username"],
                    reference=row["reference"],
                    counterparty=row["counterparty"],
                    description=row["description"],
                    raw=row["raw"],
                    row_hash=rh,
                )
            )
        Transaction.objects.bulk_create(objs, batch_size=1000)
        up.rows_parsed = len(objs)
        up.rows_duplicate = dup
        up.save(update_fields=["rows_parsed", "rows_duplicate"])

    return up, len(objs), dup
