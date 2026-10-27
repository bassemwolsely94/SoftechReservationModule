"""
Repair supplier-invoice lines where the reader put the BATCH number (رقم التشغيلة) into the
supplier item-code field (owner 2026-10-05) — same deterministic rule as ingest
(apps/invoices/ocr.separate_code_and_batch: same value / cut / split) — and clear the
supplier codes that were LEARNED from those batch numbers (VendorItemMapping), keeping the
name→item learning. PG only; SOFTECH is never touched.

    python manage.py fix_invoice_code_batch            # DRY-RUN: what would change
    python manage.py fix_invoice_code_batch --commit   # apply (old values kept in the line notes)
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Move batch numbers out of the supplier-code field on invoice lines; unlearn them as codes.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **opts):
        from apps.invoices.models import InvoiceLine, VendorItemMapping
        from apps.invoices.ocr import FIX_NOTES, _flat, separate_code_and_batch
        commit = opts['commit']
        fixes, batch_values = [], set()
        for ln in InvoiceLine.objects.exclude(vendor_item_code='').order_by('invoice_id', 'order', 'id'):
            code, batch, fix = separate_code_and_batch(ln.vendor_item_code, ln.batch_number)
            if fix:
                fixes.append((ln, code, batch, fix))
                batch_values |= {_flat(ln.vendor_item_code), _flat(batch)}
        maps = [m for m in VendorItemMapping.objects.exclude(vendor_item_code='')
                if _flat(m.vendor_item_code) in batch_values]

        w = self.stdout.write
        w(f'{"APPLY" if commit else "DRY-RUN"}: {len(fixes)} invoice lines · {len(maps)} learned supplier codes')
        for ln, code, batch, fix in fixes:
            w(f'  inv {ln.invoice_id} line {ln.id}: code {ln.vendor_item_code!r} batch {ln.batch_number!r}'
              f' → code {code!r} batch {batch!r} ({fix})')
        for m in maps:
            w(f'  learned code {m.vendor_item_code!r} → item {m.item_id}: code cleared (name mapping kept)')
        if not commit:
            w('nothing written — add --commit to apply')
            return
        with transaction.atomic():
            for ln, code, batch, fix in fixes:
                note = (f'{FIX_NOTES[fix]} — كان: كود «{ln.vendor_item_code}» تشغيلة «{ln.batch_number}»')
                ln.notes = (f'{ln.notes} | {note}' if ln.notes else note)[:300]
                ln.vendor_item_code, ln.batch_number = code, batch
                ln.save(update_fields=['vendor_item_code', 'batch_number', 'notes'])
            for m in maps:
                m.vendor_item_code = ''
                m.save(update_fields=['vendor_item_code', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(f'fixed {len(fixes)} lines, cleared {len(maps)} learned codes'))
