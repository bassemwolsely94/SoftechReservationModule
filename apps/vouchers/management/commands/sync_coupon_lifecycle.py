"""
python manage.py sync_coupon_lifecycle [--full] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--notify]

READ-ONLY: mirrors every SOFTECH movement of the two coupon items (issue to customer 170,
transfers 125/25, redemption 115, customer returns 30, …) into CouponEvent and rebuilds each
serial's lifecycle (who got it, which branch, where/when redeemed) + anomaly flags.
Incremental by default (from 7 days before the latest mirrored movement); --full re-reads
from COUPON_LIFECYCLE_SINCE (2021-01-01). Safe to re-run. Nothing is written to SOFTECH.
--notify (the daily scheduler job) then sends yesterday's misuse digest as an in-app
notification to COUPON_DIGEST_ROLES (coupon_dashboard.daily_digest; nothing new → nothing sent).
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Mirror gift-coupon movements from SOFTECH (read-only) and rebuild lifecycles'

    def add_arguments(self, parser):
        parser.add_argument('--full', action='store_true')
        parser.add_argument('--since', default='')
        parser.add_argument('--until', default='')
        parser.add_argument('--notify', action='store_true',
                            help="send yesterday's misuse digest to COUPON_DIGEST_ROLES")

    def handle(self, *args, **o):
        try:
            since = dt.date.fromisoformat(o['since']) if o['since'] else None
            until = dt.date.fromisoformat(o['until']) if o['until'] else None
        except ValueError:
            raise CommandError('dates must be YYYY-MM-DD')
        from apps.vouchers.coupon_dashboard import locked_sync
        res = locked_sync(since=since, until=until, full=o['full'],
                          progress=lambda a, b, n: self.stdout.write(f'  {a} → {b}: {n} lines'))
        if res is None:
            raise CommandError('another coupon sync is running right now — try again later')
        self.stdout.write(self.style.SUCCESS(
            f'Synced {res["since"]} → {res["until"]}: {res.get("lines", 0)} movement lines '
            f'({res.get("linked", 0)} linked to a serial, {res.get("unknown_serial", 0)} unknown serial, '
            f'{res.get("no_serial", 0)} without serial); {res["serials"]} serial lifecycles rebuilt.'))
        if o['notify']:
            from apps.vouchers import coupon_dashboard as dash
            d = dash.daily_digest()
            sent = dash.notify_digest(d)
            self.stdout.write(f"Digest {d['day']}: {len(d['no_serial'])} lines without serial, "
                              f"{len(d['reused'])} reused serials, {len(d['customers_over'])} customers over "
                              f"— {sent} notification(s) sent.")
        self.stdout.write('Next: python manage.py coupon_report')
