"""Stores the owner's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx) as version 1 of the Invoicer's code workbook
(doc 36, S3). The file is only read — a copy is kept under TAX_EGS_SHEET_DIR. Refuses when a version already exists
unless --force-new (then it becomes the next version). Audited (`egs_sheet_seed`)."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tax_invoicing import egs_sheet
from apps.tax_invoicing.models import TaxEgsSheetVersion
from apps.tax_invoicing.services import audit


class Command(BaseCommand):
    help = "Store the owner's bulk EGS sheet as the first version of the Invoicer's code workbook (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--force-new', action='store_true',
                            help='store it as the next version even though versions exist')
        parser.add_argument('--note', default='')

    def handle(self, *args, path, force_new=False, note='', **opts):
        src = Path(path)
        if not src.is_file():
            raise CommandError(f'no file at {src}')
        existing = egs_sheet.latest()
        if existing and not force_new:
            raise CommandError(f'version {existing.number} already exists; use --force-new to store this file '
                               'as the next version')
        with open(src, 'rb') as fh:      # read only: the owner's file is never written
            data = fh.read()
        try:
            counts = egs_sheet.read_counts(data)
        except egs_sheet.SheetError as exc:
            raise CommandError(str(exc)) from exc
        with transaction.atomic():      # no version without its audit event
            version = egs_sheet.store(data, source=TaxEgsSheetVersion.SOURCE_SEED,
                                      note=note or f'seed from {src.name}', **counts)
            audit('egs_sheet_seed', entity='egs_sheet', entity_id=version.number, reason=version.note,
                  after={'number': version.number, 'file': src.name, 'sha256': version.sha256, 'size': version.size,
                         'coded_rows': version.coded_rows, 'total_rows': version.total_rows,
                         'coded_items': len(version.coded_itemcodes)})
        self.stdout.write(f'version {version.number}: {version.total_rows} rows, {version.coded_rows} coded rows, '
                          f'{len(version.coded_itemcodes)} coded items')
