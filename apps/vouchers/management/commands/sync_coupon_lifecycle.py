"""
python manage.py sync_coupon_lifecycle [--full] [--since YYYY-MM-DD] [--until YYYY-MM-DD]

READ-ONLY: mirrors every SOFTECH movement of the two coupon items (issue to customer 170,
transfers 125/25, redemption 115, customer returns 30, …) into CouponEvent and rebuilds each
serial's lifecycle (who got it, which branch, where/when redeemed) + anomaly flags.
Incremental by default (from 7 days before the latest mirrored movement); --full re-reads
from COUPON_LIFECYCLE_SINCE (2021-01-01). Safe to re-run. Nothing is written to SOFTECH.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.vouchers import coupon_lifecycle


class Command(BaseCommand):
    help = 'Mirror gift-coupon movements from SOFTECH (read-only) and rebuild lifecycles'

    def add_arguments(self, parser):
        parser.add_argument('--full', action='store_true')
        parser.add_argument('--since', default='')
        parser.add_argument('--until', default='')

    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection
        try:
            since = dt.date.fromisoformat(o['since']) if o['since'] else None
            until = dt.date.fromisoformat(o['until']) if o['until'] else None
        except ValueError:
            raise CommandError('dates must be YYYY-MM-DD')
        conn = get_sybase_connection()
        try:
            res = coupon_lifecycle.sync(
                conn, since=since, until=until, full=o['full'],
                progress=lambda a, b, n: self.stdout.write(f'  {a} → {b}: {n} lines'))
        finally:
            conn.close()
        self.stdout.write(self.style.SUCCESS(
            f'Synced {res["since"]} → {res["until"]}: {res.get("lines", 0)} movement lines '
            f'({res.get("linked", 0)} linked to a serial, {res.get("unknown_serial", 0)} unknown serial, '
            f'{res.get("no_serial", 0)} without serial); {res["serials"]} serial lifecycles rebuilt.'))
        self.stdout.write('Next: python manage.py coupon_report')
