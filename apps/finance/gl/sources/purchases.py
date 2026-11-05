"""``purchases`` reader: supplier invoices / returns from the APInvoice mirror, with the invoice VAT
(SOFTECH stktransm.docvalue3, Ruling P32) read from SOFTECH - one SELECT per month that has invoices.

amounts: ``value`` (the whole invoice, positive), ``vat`` (docvalue3, positive when it has the same
sign as the invoice) and ``net`` = value - vat. No SOFTECH header -> vat 0 and attrs.vat_missing
(never guessed).
"""
from contextlib import ExitStack
from decimal import ROUND_HALF_UP, Decimal

from apps.finance.queries import sybase_gl
from apps.finance.recon_models import APInvoice

from . import READERS, SourceDoc
from .sales import code, to_date

CENT = Decimal('0.01')


def _q(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _vat_by_key(invoices, date_from, date_to, fetch) -> dict:
    """(branch, doccode, docnumber, date) -> VAT signed as its invoice; months without invoices
    are never queried."""
    out = {}
    with ExitStack() as stack:
        for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
            if not any(d1 <= inv.docdate <= d2 for inv in invoices):
                continue
            if fetch is None:   # lazy: no SOFTECH connection unless there is something to enrich
                fetch = stack.enter_context(sybase_gl.open_fetch())
            for r in fetch(sybase_gl.sql_purchase_vat(d1, d2)):
                key = (code(r['branchcode']), code(r['doccode']), code(r['docno']), to_date(r['docdate']))
                vat = _q(r['docvalue3'])
                if Decimal(str(r.get('docvalue') or 0)) < 0:
                    vat = -vat
                out[key] = vat
    return out


def read_purchases(date_from, date_to, fetch=None):
    invoices = list(APInvoice.objects.filter(doccode__in=['10', '120'], party_type='supplier',
                                             docdate__gte=date_from, docdate__lte=date_to)
                    .select_related('party').order_by('docdate', 'branchcode', 'doccode', 'docnumber'))
    if not invoices:
        return
    vats = _vat_by_key(invoices, date_from, date_to, fetch)
    for inv in invoices:
        branch, doccode, num = code(inv.branchcode), code(inv.doccode), code(inv.docnumber)
        value = _q(abs(Decimal(inv.doc_value)))
        attrs = {'doccode': doccode, 'docnumber': num, 'docnumber2': inv.docnumber2 or '',
                 'due_date': inv.due_date.isoformat() if inv.due_date else None}
        vat = vats.get((branch, doccode, num, inv.docdate))
        if vat is None:
            vat = Decimal('0.00')
            attrs['vat_missing'] = True
        yield SourceDoc('purchases', f'ap:{branch}:{doccode}:{num}:{inv.docdate.isoformat()}', inv.docdate, branch,
                        'return' if doccode == '120' else 'invoice', code(inv.party.softech_personcode),
                        {'value': value, 'vat': vat, 'net': value - vat}, attrs)


READERS['purchases'] = read_purchases
