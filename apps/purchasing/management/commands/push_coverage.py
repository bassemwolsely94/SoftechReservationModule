"""
python manage.py push_coverage --months 1.5                       # DRY-RUN plan, all branches, both servers
python manage.py push_coverage --months 2 --branch 130            # restrict to one branch
python manage.py push_coverage --months 1.5 --target node         # branch servers only
python manage.py push_coverage --months 1.5 --target hq           # server 100 (192.168.1.8) only
python manage.py push_coverage --months 1.5 --item 87602          # restrict to one item (debug)
python manage.py push_coverage --months 1.5 --commit              # LIVE (needs COVERAGE_WRITER_ENABLED)
python manage.py push_coverage --probe-branch 130 --probe-item 87602 --target hq   # rollback write-probe

BATCH 2b driver — writes the max-stock coverage window → SOFTECH stkbal.maxnowqtymonths,
and (when settings.COVERAGE_WRITE_MAXQTY is on) maxnowqty = that server's rate × coverage,
since SOFTECH does not recompute maxnowqty itself. READ-ONLY dry-run by default; --commit
is gated behind settings.COVERAGE_WRITER_ENABLED. Default target = both servers.
Branch 100's own rows are never written. See apps/purchasing/coverage_writer.py.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.purchasing import coverage_writer as cw


class Command(BaseCommand):
    help = 'Push coverage months → SOFTECH stkbal.maxnowqtymonths (gated dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=float, default=None,
                            help='coverage window (months) to write on every targeted item')
        parser.add_argument('--branch', action='append', default=None,
                            help='softech_branch_id to restrict to (repeatable)')
        parser.add_argument('--item', action='append', default=None,
                            help='softech itemcode to restrict to (repeatable; debug)')
        parser.add_argument('--commit', action='store_true',
                            help='LIVE write to SOFTECH (requires COVERAGE_WRITER_ENABLED=True)')
        parser.add_argument('--target', default='both', choices=['both', 'node', 'hq'],
                            help='both (branch server + server 100, default) | node | hq')
        parser.add_argument('--limit', type=int, default=25, help='max changes to print per branch')
        parser.add_argument('--probe-branch', dest='probe_branch', default=None)
        parser.add_argument('--probe-item', dest='probe_item', default=None)
        parser.add_argument('--reset-non-stock', dest='reset_non_stock', action='store_true',
                            help='reset coverage+max to 0 on coupons/gifts/price≤0/non-stockable '
                                 'items WE wrote earlier (preview unless --commit)')

    def handle(self, *a, **o):
        if o.get('reset_non_stock'):
            return self._reset_non_stock(o)
        if o.get('probe_branch') or o.get('probe_item'):
            if not (o.get('probe_branch') and o.get('probe_item')):
                raise CommandError('--probe-branch AND --probe-item are both required for a probe.')
            if o['target'] == 'both':
                raise CommandError('A probe checks ONE server — pass --target node or --target hq.')
            res = cw.probe_coverage_write(o['probe_branch'], o['probe_item'],
                                          confirm=True, target=o['target'])
            self.stdout.write(self.style.MIGRATE_HEADING('\n═══ coverage_writer rollback write-probe ═══'))
            for k, v in res.items():
                self.stdout.write(f'  {k}: {v}')
            return

        if not o.get('months'):
            raise CommandError('--months is required (the coverage window to write).')

        commit = o.get('commit', False)
        gated = not cw.coverage_writer_enabled()
        if commit and gated:
            raise CommandError('COVERAGE_WRITER_ENABLED is off — refusing --commit. Review the dry-run first.')

        plan = cw.push_coverage(coverage_months=o['months'], branch_filter=o.get('branch'),
                                item_filter=o.get('item'), dry_run=not commit, target=o['target'])

        t = plan['totals']
        both = plan.get('target') == 'both'
        mode = plan.get('mode', 'dry_run')
        head = 'LIVE COMMIT' if mode == 'commit' else 'DRY-RUN (no SOFTECH write)'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ coverage push — {head} — cov={plan["coverage_months"]} months '
            f'— target={plan.get("target")} ═══'))
        self.stdout.write(f'  branches: {t["branches"]}  to write: {t["eligible"]}  '
                          f'already correct: {t["skipped"]}  unreachable: {t["unreachable"]}')
        self.stdout.write(f'  writes maxnowqty too: {plan.get("write_maxqty")}')
        for b in plan['branches']:
            if not b['reachable']:
                self.stdout.write(self.style.WARNING(
                    f'  · branch {b["branchcode"]}: UNREACHABLE ({b.get("error")})'))
                continue
            tail = ''
            if mode == 'commit':
                tail = (f'  → written {b.get("written",0)} verified {b.get("verified",0)} '
                        f'not confirmed {b.get("not_confirmed",0)}')
            self.stdout.write(self.style.HTTP_INFO(
                f'  · branch {b["branchcode"]}/{b["store"]}: {b["eligible_count"]} to write{tail}'))
            if b.get('error'):
                self.stdout.write(self.style.WARNING(
                    f'      connection dropped {b.get("connection_drops", 1)}x, resumed: {b["error"][:300]}'))
                if b.get('not_confirmed'):
                    self.stdout.write(self.style.WARNING(
                        '      some items are still not confirmed — run the same command again; '
                        'it only writes what is not correct yet.'))
            if both:
                self.stdout.write('      item     name                        '
                                  '[branch server: months rate max→new]  [server 100: months rate max→new]')
            for c in b['changes'][:o['limit']]:
                line = (f'      {c["itemcode"]:<8} {(c["item_name"] or "")[:26]:<26} '
                        f'[{c["old_months"]}→{c["new_months"]}  rate {c["cur_rate"]}  '
                        f'max {c["old_maxqty"]}→{c["implied_maxqty"]}]')
                if both:
                    line += (f'  [{c.get("old_months_hq")}→{c["new_months"]}  rate {c.get("cur_rate_hq")}  '
                             f'max {c.get("old_maxqty_hq")}→{c.get("implied_maxqty_hq")}]')
                self.stdout.write(line)
        if gated and mode != 'commit':
            self.stdout.write(self.style.WARNING(
                '\n  COVERAGE_WRITER_ENABLED = OFF → this was a preview only.'))

    def _reset_non_stock(self, o):
        from apps.catalog.models import Item
        if o['commit'] and not cw.coverage_writer_enabled():
            raise CommandError('COVERAGE_WRITER_ENABLED is off — refusing --commit.')
        res = cw.reset_non_stock(branch_filter=o.get('branch'), target=o['target'],
                                 dry_run=not o['commit'])
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ reset coverage on non-stock items — {res["mode"].upper()} — target={res["target"]} ═══'))
        codes = set()
        for r in res['branches']:
            head = f'  · branch {r["branchcode"]} [{r["surface"]}]'
            if not r['reachable']:
                self.stdout.write(self.style.WARNING(f'{head}: UNREACHABLE ({r.get("error")})'))
                continue
            line = f'{head}: {r["candidates"]} to reset'
            if res['mode'] == 'commit':
                line += f'  → verified {r["verified"]}  not confirmed {r["not_confirmed"]}'
            self.stdout.write(line)
            if r.get('error'):
                self.stdout.write(self.style.WARNING(f'      connection dropped, resumed: {r["error"][:250]}'))
            codes.update(r['codes'])
        if codes:
            self.stdout.write('  items:')
            for i in Item.objects.filter(softech_id__in=codes).order_by('name'):
                self.stdout.write(f'    {i.softech_id:<8} {i.name[:40]:<40} price {i.pack_price}  '
                                  f'type {i.medicine_type}  stockable {i.is_stockable}')
