"""Fill source_sha256 on old uploads so the same-file notice recognises them.
Dry run by default; prints counts only. Invoices that belong to a batch (rendered pages) are skipped."""
from django.core.management.base import BaseCommand

from apps.invoices.models import InvoiceBatch, SupplierInvoice
from core.upload_safety import sha256_of


class Command(BaseCommand):
    help = 'Backfill empty source_sha256 on invoices and bundles (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **opts):
        jobs = (
            ('invoices', SupplierInvoice.objects.filter(source_sha256='', batch__isnull=True)
             .exclude(source_image='').exclude(source_image__isnull=True), 'source_image', SupplierInvoice),
            ('batches', InvoiceBatch.objects.filter(source_sha256='')
             .exclude(source_file='').exclude(source_file__isnull=True), 'source_file', InvoiceBatch),
        )
        for name, qs, field, model in jobs:
            fillable = missing = 0
            for obj in qs.iterator():
                f = getattr(obj, field)
                try:
                    f.open('rb')
                    try:
                        sha = sha256_of(f)
                    finally:
                        f.close()
                except (OSError, ValueError):
                    missing += 1
                    continue
                fillable += 1
                if apply:
                    model.objects.filter(pk=obj.pk).update(source_sha256=sha)
            self.stdout.write(f'{name}: {"filled" if apply else "would fill"} {fillable}, file missing {missing}')
        if not apply:
            self.stdout.write('dry run — add --apply to write')
