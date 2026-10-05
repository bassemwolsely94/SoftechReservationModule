"""
python manage.py export_coupon_batch BATCH_ID [--out DIR]

Writes, for one coupon batch:
  coupon_batch_<id>_print.xlsx     — 4-up collated print sheet (Excel `Printing Sheet` layout)
  coupon_batch_<id>_dataload.tsv   — rows for the WorkBench DataLoad grid, both items, in the
                                     exact column layout of Dataload_for_Coupon_Serial_Number.dld
                                     (interim, until the SOFTECH push is approved)
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.vouchers import coupons
from apps.vouchers.models import CouponBatch


class Command(BaseCommand):
    help = 'Export a coupon batch: print sheet (.xlsx) + DataLoad grid (.tsv)'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        parser.add_argument('--out', default='.')

    def handle(self, *args, **opts):
        try:
            batch = CouponBatch.objects.get(pk=opts['batch_id'])
        except CouponBatch.DoesNotExist:
            raise CommandError(f'batch {opts["batch_id"]} not found')
        os.makedirs(opts['out'], exist_ok=True)
        xlsx = os.path.join(opts['out'], f'coupon_batch_{batch.pk}_print.xlsx')
        coupons.print_workbook(batch).save(xlsx)
        tsv = os.path.join(opts['out'], f'coupon_batch_{batch.pk}_dataload.tsv')
        with open(tsv, 'w', encoding='utf-8', newline='') as f:
            for row in coupons.dataload_rows(batch):
                f.write('\t'.join(row) + '\r\n')
        self.stdout.write(self.style.SUCCESS(f'Wrote {xlsx}\nWrote {tsv}'))
