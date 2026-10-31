"""
Re-normalize stored expiry dates to the owner's SofTech rule (2026-10-31): a month/year
expiry becomes day = month (09.2029 → 2029-09-09), not the 1st of the month.

Lines read before the rule hold e.g. 2028-05-01 for a printed «05.2028». SofTech keeps a
separate stock-expiry bucket per date (stkbalexpiry), so posting 2028-05-01 next to a hand
entry of 2028-05-05 splits the same batch in two. Only lines whose ORIGINAL printed expiry
(kept in raw_text) is month/year-only and whose stored date is still the old 1st-of-month
form are changed — a date someone typed by hand is left alone.

    manage.py renormalize_invoice_expiry                 # dry run, unposted invoices
    manage.py renormalize_invoice_expiry --commit
    manage.py renormalize_invoice_expiry --invoice 224 --commit   # one invoice, any status
"""
import json
import re

from django.core.management.base import BaseCommand

from apps.invoices.models import InvoiceLine
from apps.invoices.ocr import normalize_expiry

_POSTED = ('finalized', 'pushing', 'queued')


def _printed_expiry(line):
    try:
        return str(json.loads(line.raw_text or '{}').get('expiry_date') or '').strip()
    except (ValueError, TypeError, AttributeError):
        return ''


def new_expiry(line):
    """The day = month date for this line, or None when it should stay as it is."""
    raw = _printed_expiry(line)
    if not raw or len(re.findall(r'\d+', raw)) != 2:          # only month/year printings
        return None
    stored = (line.expiry_date or '').strip()
    if not re.fullmatch(r'\d{4}-\d{2}-01', stored):            # not the old 1st-of-month form
        return None
    target = normalize_expiry(raw)
    if not target or target == stored or target[:7] != stored[:7]:
        return None                                            # changed by hand to another month
    return target


class Command(BaseCommand):
    help = 'Re-normalize month/year expiries to day = month (dry run unless --commit).'

    def add_arguments(self, parser):
        parser.add_argument('--invoice', type=int, help='only this invoice (any status)')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, invoice=None, commit=False, **opts):
        qs = InvoiceLine.objects.select_related('invoice')
        qs = qs.filter(invoice_id=invoice) if invoice else qs.exclude(invoice__status__in=_POSTED)
        changed = 0
        for ln in qs.iterator():
            target = new_expiry(ln)
            if not target:
                continue
            changed += 1
            self.stdout.write(f'inv {ln.invoice_id} line {ln.pk}: {ln.expiry_date} → {target} '
                              f'(printed {_printed_expiry(ln)!r})')
            if commit:
                note = f'الصلاحية {ln.expiry_date} ← {target} (اليوم = الشهر)'
                ln.notes = f'{ln.notes}، {note}' if ln.notes else note
                ln.expiry_date = target
                ln.save(update_fields=['expiry_date', 'notes'])
        self.stdout.write(self.style.SUCCESS(
            f'{changed} line(s) {"updated" if commit else "would change (dry run)"}'))
