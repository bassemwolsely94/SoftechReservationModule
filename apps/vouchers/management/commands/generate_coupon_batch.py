"""
python manage.py generate_coupon_batch [--size 200] [--start-number N] [--start-date YYYY-MM-DD]
                                       [--no-softech-check] [--out DIR]

Generates the next batch of gift-coupon serials into the archive (status `generated`),
replacing the Excel `Serial Generator` + `Coupon Expiry Dates` sheets:
  * serial numbers continue after the highest one ever issued;
  * random codes never repeat an earlier code;
  * one expiry date per serial, shared by both legs, never used before and not present in
    SOFTECH stkbalexpiry for either coupon item (read live, SELECT only), so serials
    can never merge into one stock row.
Writes the print sheet (.xlsx) and the DataLoad grid (.tsv) for the batch to --out.
Nothing is written to SOFTECH.
"""
import datetime as dt

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.vouchers import coupons


class Command(BaseCommand):
    help = 'Generate the next gift-coupon serial batch (archive only — no SOFTECH write)'

    def add_arguments(self, parser):
        parser.add_argument('--size', type=int, default=0, help='default COUPON_BATCH_SIZE (200)')
        parser.add_argument('--start-number', type=int, default=0)
        parser.add_argument('--start-date', default='', help='first expiry date (YYYY-MM-DD)')
        parser.add_argument('--no-softech-check', action='store_true',
                            help='skip reading SOFTECH stkbalexpiry (NOT recommended)')
        parser.add_argument('--out', default='', help='folder for the print sheet + DataLoad file')

    def handle(self, *args, **opts):
        blocked = set()
        if not opts['no_softech_check']:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
            try:
                blocked = coupons.read_blocked_expiries(conn)
            finally:
                conn.close()
            self.stdout.write(f'SOFTECH stkbalexpiry dates on coupon items: {len(blocked)}')
        start_date = None
        if opts['start_date']:
            try:
                start_date = dt.date.fromisoformat(opts['start_date'])
            except ValueError:
                raise CommandError('--start-date must be YYYY-MM-DD')
        try:
            batch = coupons.generate_batch(size=opts['size'] or None,
                                           start_number=opts['start_number'] or None,
                                           start_date=start_date, blocked_dates=blocked)
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(
            f'Batch #{batch.pk}: {batch.size} serials {batch.serial_from}–{batch.serial_to}, '
            f'expiry {batch.expiry_from} → {batch.expiry_to}'))
        if opts['out']:
            call_command('export_coupon_batch', batch.pk, out=opts['out'], stdout=self.stdout)
