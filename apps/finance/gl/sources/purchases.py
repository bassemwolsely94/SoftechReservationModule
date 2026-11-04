"""``purchases`` reader: supplier invoices / returns from the APInvoice mirror (Postgres only)."""
from decimal import ROUND_HALF_UP, Decimal

from apps.finance.recon_models import APInvoice

from . import READERS, SourceDoc
from .sales import code


def read_purchases(date_from, date_to, fetch=None):
    qs = (APInvoice.objects.filter(doccode__in=['10', '120'], party_type='supplier',
                                   docdate__gte=date_from, docdate__lte=date_to)
          .select_related('party').order_by('docdate', 'branchcode', 'doccode', 'docnumber'))
    for inv in qs:
        branch, doccode, num = code(inv.branchcode), code(inv.doccode), code(inv.docnumber)
        value = abs(Decimal(inv.doc_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        yield SourceDoc('purchases', f'ap:{branch}:{doccode}:{num}:{inv.docdate.isoformat()}', inv.docdate, branch,
                        'return' if doccode == '120' else 'invoice', code(inv.party.softech_personcode),
                        {'value': value},
                        {'doccode': doccode, 'docnumber': num, 'docnumber2': inv.docnumber2 or '',
                         'due_date': inv.due_date.isoformat() if inv.due_date else None})


READERS['purchases'] = read_purchases
