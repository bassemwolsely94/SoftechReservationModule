"""
python manage.py pos_checkout_golden --basket <file.json> --user <username> --native <pending docnumber>
        [--plan-only] [--live-pricing] [--confirm-rollback-probe] [--ignore col,col] [--title "..."]
        [--out docs/architecture/39a_POS_SERVER_CHECKOUT_GOLDEN.md] [--keep]

D-18 golden-template comparison (docs/architecture/39_POS_SERVER_CHECKOUT.md §4.1). PREPARED, NOT RUN:
a person runs it on the writer instance, off-peak, one branch, with the owner's written OK for EACH run.

  1. The owner rings a real sale natively on the SOFTECH cashier screen and gives its PENDING docnumber.
  2. This command sends the SAME basket (--basket: the checkout request body) through the new
     POST /api/pos-orders/checkout/ endpoint in DRY RUN, as --user. The switch is turned on for this
     process and this branch only; nothing is pushed. A temporary PostgreSQL order results.
  3. --plan-only stops here and prints the writer's plan (no SOFTECH statement at all).
  4. Otherwise (needs --confirm-rollback-probe AND the SOFTECH_PROBES_ENABLED switch): it reads the
     native pending rows, then runs the writer's own _execute_write for our order inside ONE transaction
     on the branch, reads our rows back inside that transaction, and ALWAYS rolls back — nothing is
     saved, no serial is used up, nothing can be settled (same method as writer.probe_order / pos_probe).
  5. Every column of header / lines / payments / claim / cost-centre rows is compared (golden.py) and a
     section is appended to --out. The temporary PostgreSQL order is deleted unless --keep.
"""
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings

from apps.pos_orders import golden, writer
from apps.pos_orders.models import SoftechSalesOrder

NATIVE_SQL = {
    'stktransm5': 'SELECT * FROM stktransm5 WHERE branchcode=? AND doccode=? AND docnumber=?',
    'stktrans5': 'SELECT * FROM stktrans5 WHERE branchcode=? AND doccode=? AND docnumber=?',
    'branchesales5': 'SELECT * FROM branchesales5 WHERE branchcode=? AND doccode=? AND docnumber=?',
}
COMPANION_SQL = {
    'companiesitems5': 'SELECT * FROM companiesitems5 WHERE branchcode=? AND docnumber=?',
    'branchesalescc5': 'SELECT * FROM branchesalescc5 WHERE branchcode=? AND docnumber=?',
}


def _read(conn, branchcode, doccode, docnumber):
    out = {}
    cur = conn.cursor()
    try:
        for table, sql in NATIVE_SQL.items():
            cur.execute(sql, [branchcode, doccode, int(docnumber)])
            cols = [d[0] for d in cur.description]
            out[table] = [dict(zip(cols, r)) for r in cur.fetchall()]
        for table, sql in COMPANION_SQL.items():
            cur.execute(sql, [branchcode, int(docnumber)])
            cols = [d[0] for d in cur.description]
            out[table] = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return out


class Command(BaseCommand):
    help = 'D-18: diff a new-checkout sale against a native SOFTECH sale (rollback probe; never commits)'

    def add_arguments(self, parser):
        parser.add_argument('--basket', required=True, help='JSON file: the checkout request body')
        parser.add_argument('--user', required=True, help='username the checkout runs as (the seller)')
        parser.add_argument('--native', type=int, help='PENDING docnumber of the native sale')
        parser.add_argument('--plan-only', action='store_true', dest='plan_only',
                            help='build the order and print the plan; no SOFTECH statement')
        parser.add_argument('--live-pricing', action='store_true', dest='live_pricing',
                            help='price from the branch (SELECT only), as the cashier screen does')
        parser.add_argument('--confirm-rollback-probe', action='store_true', dest='confirm',
                            help='run the real statements on the branch inside a transaction that is rolled back')
        parser.add_argument('--ignore', default='', help='extra columns reported as expected (comma list)')
        parser.add_argument('--title', default='', help='report section title (basket name)')
        parser.add_argument('--out', default='docs/architecture/39a_POS_SERVER_CHECKOUT_GOLDEN.md')
        parser.add_argument('--keep', action='store_true', help='keep the temporary PostgreSQL order')

    def handle(self, *args, **o):
        if not o['plan_only']:
            if not o['confirm']:
                raise CommandError('Real statements on SOFTECH (rolled back): pass --confirm-rollback-probe, '
                                   'or use --plan-only.')
            if not o['native']:
                raise CommandError('--native <pending docnumber> is required for the comparison.')
            from core.softech_switches import command_require_probes
            command_require_probes('pos_orders.pos_checkout_golden')
        order = self._checkout(o)
        try:
            if o['plan_only']:
                self.stdout.write(json.dumps(writer.build_payload(order), ensure_ascii=False, indent=2,
                                             default=str))
                return
            self._probe_and_diff(order, o)
        finally:
            if not o['keep']:
                order.delete()
                self.stdout.write('  (temporary PostgreSQL order deleted)')

    # ── 2. the basket through the NEW endpoint, dry run ───────────────────────────────────────────
    def _checkout(self, o):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.branches.models import Branch
        from apps.pos_orders import checkout

        body = json.loads(Path(o['basket']).read_text(encoding='utf-8'))
        body['client_token'] = str(uuid.uuid4())
        ck = body.setdefault('checkout', {})
        ck['mode'] = 'dry_run'
        ck.pop('confirm', None)
        branch = Branch.objects.filter(pk=body.get('branch')).first()
        if branch is None:
            raise CommandError('basket.branch: unknown branch id')
        user = get_user_model().objects.filter(username=o['user']).first()
        if user is None:
            raise CommandError(f'unknown user {o["user"]}')
        req = APIRequestFactory().post('/api/pos-orders/checkout/', body, format='json')
        force_authenticate(req, user=user)
        over = {'POS_SERVER_CHECKOUT': True, 'POS_SERVER_CHECKOUT_BRANCHES': [branch.softech_branch_id]}
        if o['live_pricing']:
            over['POS_LIVE_PRICING'] = True
        with override_settings(**over):
            resp = checkout.checkout(req)
        if resp.status_code != 200 or not resp.data.get('order_id'):
            raise CommandError(f'checkout refused ({resp.status_code}): {json.dumps(resp.data, ensure_ascii=False, default=str)}')
        order = SoftechSalesOrder.objects.get(pk=resp.data['order_id'])
        self.stdout.write(self.style.SUCCESS(
            f'new-endpoint order #{order.pk} (dry run): due {resp.data["totals"]["due"]} '
            f'tenders {resp.data["tenders"]}'))
        return order

    # ── 4–5. native rows, probe rows (rolled back), diff ──────────────────────────────────────────
    def _probe_and_diff(self, order, o):
        from config.sybase import get_branch_connection

        br = order.branch
        if not br or not br.effective_db_host:
            raise CommandError('order branch has no db_host')
        bc, dc = order.softech_branchcode, order.softech_doccode
        seller = order.seller_usercode or getattr(settings, 'POS_DEFAULT_SELLER_USERCODE', '') or '1'

        conn = get_branch_connection(br.effective_db_host, br.effective_db_port, br.db_name or 'SOFTECHDB9')
        try:
            native = _read(conn, bc, dc, o['native'])
        finally:
            conn.close()
        if not native['stktransm5']:
            raise CommandError(f'no pending native sale {o["native"]} on branch {bc} (settled already?)')

        self.stdout.write(self.style.WARNING(
            f'\nROLLBACK PROBE on branch {bc}: real statements inside one transaction, then ROLLBACK…'))
        probe, allocated, err = {}, None, None
        conn = get_branch_connection(br.effective_db_host, br.effective_db_port, br.db_name or 'SOFTECHDB9',
                                     charset=writer._write_charset())
        try:
            conn.begin()
            w = writer._execute_write(conn, order, seller)     # identical to the commit path
            allocated = w['docnumber']
            probe = _read(conn, bc, dc, allocated)
        except Exception as exc:
            err = str(exc)
        finally:
            try:
                conn.rollback()                                # ALWAYS — nothing persists
                self.stdout.write('  rolled back')
            finally:
                conn.close()
        if err:
            raise CommandError(f'probe failed (rolled back): {err}')

        diff = golden.diff_tables(native, probe, also_ignore=[c.strip() for c in o['ignore'].split(',')
                                                              if c.strip()])
        title = o['title'] or f'branch {bc} · native {o["native"]}'
        md = golden.report_markdown(title, diff, notes=[
            f'Native pending docnumber {o["native"]}; probe serial {allocated} (rolled back).',
            f'New endpoint order #{order.pk}, channel {order.channel}, due '
            f'{order.doc_value - order.change_discount}.',
            f'Live pricing: {"yes" if o["live_pricing"] else "no (catalog prices)"}.',
        ])
        out = Path(o['out'])
        if not out.exists():
            out.write_text('# 39a · POS server checkout — golden-template comparison\n\n'
                           'Each section: one basket rung natively and through POST checkout/ (dry run), '
                           'probe rolled back. Method: doc 39 §4.1.\n\n', encoding='utf-8')
        with out.open('a', encoding='utf-8') as f:
            f.write('\n' + md)
        self.stdout.write(md)
        self.stdout.write(self.style.SUCCESS(f'appended to {out}') if not (diff['fails'] or diff['row_count'])
                          else self.style.ERROR(f'DIFFERENCES — appended to {out}'))
