"""``purchases`` reader: supplier invoices / returns from the APInvoice mirror, with the invoice VAT
(SOFTECH stktransm.docvalue3, Ruling P32) read from SOFTECH - one SELECT per month that has invoices.

amounts: ``value`` (the whole invoice, positive), ``vat`` (docvalue3, positive when it has the same
sign as the invoice) and ``net`` = value - vat. No SOFTECH header for one invoice -> vat 0 and
attrs.vat_missing (never guessed; returns post their full value, so they are not flagged); a month with invoices but no SOFTECH rows at all is a failed read
and raises (the run goes partial, nothing moves). attrs.vat_value_drift marks a header that disagrees
with the mirror or VAT above the invoice (net goes negative; build_lines flips that line's side).
"""
from contextlib import ExitStack
from decimal import Decimal

from apps.finance.queries import sybase_gl
from apps.finance.recon_models import APInvoice

from . import READERS, SourceDoc
from .sales import code, q, to_date


def _docno(v) -> str:
    """'55', '55.0' and '55.000' are one document number (CONVERT of a numeric may keep decimals)."""
    return code(v).split('.')[0]


def _vat_by_key(invoices, date_from, date_to, fetch) -> dict:
    """(branch, doccode, docnumber, date) -> (VAT signed as its invoice, header docvalue size).
    Months without invoices are never queried; one with invoices but no rows raises."""
    out = {}
    with ExitStack() as stack:
        for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
            if not any(d1 <= inv.docdate <= d2 for inv in invoices):
                continue
            if fetch is None:   # lazy: no SOFTECH connection unless there is something to enrich
                fetch = stack.enter_context(sybase_gl.open_fetch())
            rows = list(fetch(sybase_gl.sql_purchase_vat(d1, d2)))
            if not rows:   # a silent / empty read must never post every invoice without VAT
                raise RuntimeError(f'SOFTECH returned no purchase headers for {d1:%Y-%m}, which has invoices')
            for r in rows:
                key = (code(r['branchcode']), code(r['doccode']), _docno(r['docno']), to_date(r['docdate']))
                docvalue = q(r.get('docvalue'))
                vat = q(r['docvalue3'])
                out[key] = (-vat if docvalue < 0 else vat, abs(docvalue))
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
        value = q(abs(Decimal(inv.doc_value)))
        attrs = {'doccode': doccode, 'docnumber': num, 'docnumber2': inv.docnumber2 or '',
                 'due_date': inv.due_date.isoformat() if inv.due_date else None}
        found = vats.get((branch, doccode, _docno(inv.docnumber), inv.docdate))
        if found is None:
            vat = Decimal('0.00')
            if doccode != '120':   # a return posts its full value (P32), so no VAT is missing from it
                attrs['vat_missing'] = True
        else:
            vat, docvalue = found
            if docvalue != value or vat > value:
                attrs['vat_value_drift'] = True
        yield SourceDoc('purchases', f'ap:{branch}:{doccode}:{num}:{inv.docdate.isoformat()}', inv.docdate, branch,
                        'return' if doccode == '120' else 'invoice', code(inv.party.softech_personcode),
                        {'value': value, 'vat': vat, 'net': value - vat}, attrs)


READERS['purchases'] = read_purchases
