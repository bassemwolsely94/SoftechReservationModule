"""
python manage.py push_isr --branch 150                 # DRY-RUN plan (stockisr lines the branch needs)
python manage.py push_isr --branch 150 --probe         # rollback ISR-probe (real INSERT → rollback, 0 residue)
python manage.py push_isr --branch 150 --commit        # LIVE write (needs ISR_WRITER_ENABLED)
python manage.py push_isr --branch 150 --all           # include overstock (signed), not only gap>0

FEATURE 2 Stage-A driver — generate a SOFTECH ISR (طلب توريد, stockisr) from our
engine for a requesting branch. Dry-run by default; --commit gated by
settings.ISR_WRITER_ENABLED. See apps/purchasing/isr_writer.py.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.purchasing import isr_writer


class Command(BaseCommand):
    help = 'Generate a SOFTECH ISR (stockisr) from engine gaps for a branch (gated dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--branch', required=True, help='requesting softech_branch_id (e.g. 150)')
        parser.add_argument('--probe', action='store_true', help='rollback ISR-probe (0 residue)')
        parser.add_argument('--commit', action='store_true', help='LIVE write (needs ISR_WRITER_ENABLED)')
        parser.add_argument('--all', action='store_true', dest='all_items',
                            help='include overstock/signed lines, not only gap>0')
        parser.add_argument('--limit', type=int, default=25, help='max lines to print')
        parser.add_argument('--max-lines', type=int, default=None, dest='max_lines',
                            help='cap the ISR to N lines (small test ISRs / golden template)')
        parser.add_argument('--probe-n', type=int, default=3, dest='probe_n', help='sample lines for --probe')
        parser.add_argument('--approve', default=None,
                            help='isrdocnumber to APPROVE (stockisrm.israpp=1) — gated by ISR_WRITER_ENABLED')
        parser.add_argument('--probe-approve', default=None, dest='probe_approve',
                            help='isrdocnumber: rehearse the approval (set israpp=1 → restore), 0 residue')

    def handle(self, *a, **o):
        branch = o['branch']

        if o.get('probe_approve'):
            res = isr_writer.probe_approve_isr(branch, o['probe_approve'], confirm=True)
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n═══ ISR approve-probe — branch {branch} ═══'))
            for k, v in res.items():
                self.stdout.write(f'  {k}: {v}')
            return

        if o.get('approve'):
            if not isr_writer.writer_enabled():
                raise CommandError('ISR_WRITER_ENABLED is False — refusing --approve.')
            res = isr_writer.approve_isr(branch, o['approve'])
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n═══ approve ISR {o["approve"]} — branch {branch} ═══'))
            for k, v in res.items():
                self.stdout.write(f'  {k}: {v}')
            self.stdout.write((self.style.SUCCESS if res.get('ok') else self.style.ERROR)(
                f'\n  israpp=1 set: {res.get("ok")}'))
            return

        if o['probe']:
            res = isr_writer.probe_isr_write(branch, sample_n=o['probe_n'], confirm=True)
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n═══ ISR rollback probe — branch {branch} ═══'))
            for k, v in res.items():
                self.stdout.write(f'  {k}: {v}')
            ok = res.get('ok') and 'error' not in res
            self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)(
                f'\n  allocated isrdocnumber={res.get("allocated_isrdocnumber")}  '
                f'verified={res.get("ok")}  (rolled back)'))
            return

        dry_run = not o['commit']
        if o['commit'] and not isr_writer.writer_enabled():
            raise CommandError('ISR_WRITER_ENABLED is False — refusing --commit. '
                               'Validate with --probe first, then enable in settings.')

        plan = isr_writer.push_isr(branch, dry_run=dry_run, positive_only=not o['all_items'],
                                   max_lines=o.get('max_lines'))
        mode = plan.get('mode', 'dry_run').upper()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ push_isr [{mode}] — branch {branch} · run {plan.get("run_id")} · prefix {plan.get("prefix")} ═══'))
        self.stdout.write(f'  lines={plan["line_count"]}'
                          + (f'  isrdocnumber={plan.get("isrdocnumber")}' if plan.get('isrdocnumber') else ''))
        if plan.get('mode') == 'commit':
            rb = plan.get('readback', {})
            self.stdout.write(self.style.SUCCESS(
                f'  wrote_to_softech={plan.get("wrote_to_softech")}  verified={rb.get("verified")}  '
                f'({rb.get("lines_found")}/{rb.get("lines_expected")})'))

        for ln in plan['lines'][:o['limit']]:
            self.stdout.write(
                f'      {ln["itemcode"]:<8} {(ln["item_name"] or "")[:32]:<32} '
                f'order={ln["itemqty"]:>4}  nowqty={ln["nowqty"]:>7}  gap={ln["gap"]:>7}  supp={ln["suppcode"]}')
        if plan['line_count'] > o['limit']:
            self.stdout.write(f'      … {plan["line_count"] - o["limit"]} more')

        if dry_run and plan.get('mode') != 'empty':
            self.stdout.write(self.style.HTTP_INFO(
                '\n  DRY-RUN — nothing written. Use --probe to rehearse, then --commit (gate on) to write.'))
        if plan.get('mode') == 'empty':
            self.stdout.write(self.style.WARNING('  No lines (no gap>0 items for this branch in the latest run).'))
