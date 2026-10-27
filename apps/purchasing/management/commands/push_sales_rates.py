"""
python manage.py push_sales_rates                       # DRY-RUN plan, all eligible branches
python manage.py push_sales_rates --branch 130          # restrict to one branch
python manage.py push_sales_rates --item 87602          # restrict to one item (debug)
python manage.py push_sales_rates --commit              # LIVE write (needs SALES_RATE_WRITER_ENABLED)
python manage.py push_sales_rates --probe-branch 130 --probe-item 87602   # rollback write-probe

FEATURE 1 driver — pushes engine monthly_avg → SOFTECH stkbal.monthlyqty
(معدل الإستهلاك). READ-ONLY dry-run by default; --commit is gated behind
settings.SALES_RATE_WRITER_ENABLED. See apps/purchasing/rate_writer.py.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.purchasing import rate_writer


class Command(BaseCommand):
    help = 'Push engine sales-rate (monthly_avg) into SOFTECH stkbal.monthlyqty (gated dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--branch', action='append', default=None,
                            help='softech_branch_id to restrict to (repeatable)')
        parser.add_argument('--item', action='append', default=None,
                            help='softech itemcode to restrict to (repeatable; debug)')
        parser.add_argument('--commit', action='store_true',
                            help='LIVE write to SOFTECH (requires SALES_RATE_WRITER_ENABLED=True)')
        parser.add_argument('--target', default='both', choices=['both', 'node', 'hq'],
                            help='both (branch server + server 100, default) | node | hq')
        parser.add_argument('--limit', type=int, default=25, help='max changes to print per branch')
        parser.add_argument('--save', action='store_true',
                            help='persist a SalesRatePush audit record (proposed on dry-run, executed on --commit)')
        parser.add_argument('--probe-branch', dest='probe_branch', default=None)
        parser.add_argument('--probe-item', dest='probe_item', default=None)

    def handle(self, *a, **o):
        if o.get('probe_branch') or o.get('probe_item'):
            if not (o.get('probe_branch') and o.get('probe_item')):
                raise CommandError('--probe-branch AND --probe-item are both required for a probe.')
            res = rate_writer.probe_write(o['probe_branch'], o['probe_item'], confirm=True)
            self.stdout.write(self.style.MIGRATE_HEADING('\n═══ rate_writer rollback write-probe ═══'))
            for k, v in res.items():
                self.stdout.write(f'  {k}: {v}')
            ok = res.get('restored') and 'error' not in res
            self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)(
                f'\n  landed={res.get("write_landed")}  restored={res.get("restored")}'))
            return

        dry_run = not o['commit']
        if o['commit'] and not rate_writer.writer_enabled():
            raise CommandError('SALES_RATE_WRITER_ENABLED is False — refusing --commit. '
                               'Set it True in settings only after reviewing a dry-run.')

        plan = rate_writer.push(branch_filter=o.get('branch'), item_filter=o.get('item'),
                                dry_run=dry_run, persist=(o['save'] or o['commit']),
                                target=o['target'])

        t = plan['totals']
        mode = plan.get('mode', 'dry_run').upper()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ push_sales_rates [{mode}] — run {plan["run_id"]} ({plan["calc_date"]}) '
            f'— target={plan.get("target")} ═══'))
        self.stdout.write(
            f'  branches={t["branches"]}  eligible={t["eligible"]}  '
            f'skipped={t["skipped"]}  unreachable={t["unreachable"]}\n')

        for b in plan['branches']:
            head = f'  ▸ {b["branchcode"]} {b["name"]} (store {b["store"]})'
            if not b['reachable']:
                self.stdout.write(self.style.ERROR(head + f'  UNREACHABLE: {b.get("error", "")}'))
                continue
            wrote = (f'  written={b.get("written", 0)} verified={b.get("verified", 0)} '
                     f'not_confirmed={b.get("reverted", 0)}' if not dry_run else '')
            self.stdout.write(self.style.WARNING(
                head + f'  eligible={b["eligible_count"]} skipped={b["skipped_count"]}' + wrote))
            if b.get('error'):
                self.stdout.write(self.style.WARNING(
                    f'      connection dropped {b.get("connection_drops", 1)}x, resumed: {b["error"][:300]}'))
                if b.get('reverted'):
                    self.stdout.write(self.style.WARNING(
                        '      some items are still not confirmed — run the same command again; '
                        'it only writes what is not correct yet.'))
            shown = [c for c in b['changes'] if c['eligible']][:o['limit']]
            for c in shown:
                v = f' verified={c["verified"]}' if 'verified' in c else ''
                hq = f'  server100 {c["old_hq"]}' if c.get('old_hq') is not None else ''
                self.stdout.write(
                    f'      {c["itemcode"]:<8} {(c["item_name"] or "")[:34]:<34} '
                    f'{str(c["old"]):>8} → {str(c["new"]):>8}  (Δ{c["delta"]}){hq}{v}')

        if plan.get('push_id'):
            self.stdout.write(self.style.SUCCESS(f'\n  saved SalesRatePush #{plan["push_id"]}'))
        if dry_run:
            self.stdout.write(self.style.HTTP_INFO(
                '\n  DRY-RUN only — nothing written. Add --commit (with the gate on) to apply.'))
