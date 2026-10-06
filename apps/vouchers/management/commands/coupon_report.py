"""
python manage.py coupon_report                     # overview: stages, anomalies, branches
python manage.py coupon_report --serial 27101-ZWU704   # one coupon's full timeline
python manage.py coupon_report --anomaly redeemed_twice [--limit 50]   # list flagged serials

Reads only our archive (run sync_coupon_lifecycle first).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.vouchers import coupon_lifecycle, coupons
from apps.vouchers.models import CouponSerial


class Command(BaseCommand):
    help = 'Gift-coupon lifecycle report'

    def add_arguments(self, parser):
        parser.add_argument('--serial', default='')
        parser.add_argument('--anomaly', default='', choices=[''] + list(coupon_lifecycle.ANOMALY_LABELS))
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **o):
        if o['serial']:
            return self._serial(o['serial'])
        if o['anomaly']:
            return self._anomaly(o['anomaly'], o['limit'])
        r = coupon_lifecycle.report()
        self.stdout.write('── Coupons by stage ──')
        labels = dict(CouponSerial.STAGE_CHOICES)
        for stage, n in sorted(r['stages'].items(), key=lambda x: -x[1]):
            name = labels.get(stage, stage) if stage else 'لم يُدخل في SOFTECH (مولّد / إكسل فقط)'
            self.stdout.write(f'  {name}: {n}')
        self.stdout.write('── Anomalies (serials) ──')
        if not r['anomalies']:
            self.stdout.write('  none')
        for code, n in sorted(r['anomalies'].items(), key=lambda x: -x[1]):
            self.stdout.write(f'  {code}: {n}  — {coupon_lifecycle.ANOMALY_LABELS.get(code, "")}')
        self.stdout.write('── Redemptions WITHOUT a valid serial, by branch (lines, qty) ──')
        for bc, n, qty in r['redeemed_without_valid_serial_by_branch'] or [('—', 0, 0)]:
            self.stdout.write(f'  branch {bc}: {n} lines, qty {qty:g}')
        self.stdout.write('── Redeemed coupons by branch ──')
        for bc, n in r['redeemed_by_branch']:
            self.stdout.write(f'  branch {bc}: {n}')

    def _serial(self, raw):
        parsed = coupons.parse_serial(raw)
        if not parsed:
            raise CommandError(f'not a coupon serial: {raw}')
        c = CouponSerial.objects.filter(serial=parsed[2]).first()
        if not c:
            raise CommandError(f'serial {parsed[2]} is not in the archive')
        self.stdout.write(f'{c.serial}  stage={c.get_stage_display()}  anomalies={c.anomalies or "none"}')
        self.stdout.write(f'  stocked: points doc {c.points_docnumber} ({c.points_docdate}), '
                          f'served doc {c.served_docnumber} ({c.served_docdate}), expiry key {c.points_expiry}')
        if c.conflict_note:
            self.stdout.write(f'  archive note: {c.conflict_note}')
        for e in c.events.order_by('docdate', 'docnumber'):
            who = f' customer {e.customer_pic}' if e.customer_pic else ''
            party = f' → {e.party_code}' if e.kind.startswith('transfer') and e.party_code else ''
            self.stdout.write(f'  {e.docdate}  {e.get_kind_display():<32} {e.leg:<6} '
                              f'{e.branchcode}/{e.doccode}/{e.docnumber}{party}{who}')

    def _anomaly(self, code, limit):
        qs = CouponSerial.objects.filter(anomalies__contains=[code]).order_by('number')
        self.stdout.write(f'{qs.count()} serial(s) flagged {code} — {coupon_lifecycle.ANOMALY_LABELS[code]}')
        for c in qs[:limit]:
            self.stdout.write(f'  {c.serial}: issued {c.issued_at or "—"} to {c.issued_pic or "—"} | '
                              f'sent {c.sent_branch or "—"} | redeemed x{c.redeem_count} at '
                              f'{c.redeemed_branch or "—"} {c.redeemed_at or ""} by {c.redeemed_pic or "—"}')
