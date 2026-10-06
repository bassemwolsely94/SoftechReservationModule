"""
python manage.py generate_isr --branch 130                 # PG proposal (review in /supply)
python manage.py generate_isr --branches 130,150,160
python manage.py generate_isr --all-operational            # every operational branch (excl. HQ 100)
python manage.py generate_isr --all-operational --auto-approve   # generate + approve + push (gated)
python manage.py generate_isr --branch 130 --max-lines 50

Scheduled / CLI ISR (طلب توريد) generation from the engine gaps. Default = create PG
proposals for human review + approval in /supply. --auto-approve (needs
ISR_AUTO_APPROVE_ENABLED + ISR_WRITER_ENABLED) also writes to SOFTECH with israpp=1.
--once-per-day skips branches that already have a proposal created today.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.branches.models import Branch
from apps.purchasing.models import IsrPush
from apps.purchasing import isr_writer


class Command(BaseCommand):
    help = 'Generate ISR proposals from engine gaps (optionally auto-approve + push, gated)'

    def add_arguments(self, parser):
        parser.add_argument('--branch', action='append', default=None, help='branchcode (repeatable)')
        parser.add_argument('--branches', default=None, help='comma-separated branchcodes')
        parser.add_argument('--all-operational', action='store_true', dest='all_operational',
                            help='every operational branch with its own db_host (excludes HQ 100)')
        parser.add_argument('--auto-approve', action='store_true', dest='auto_approve',
                            help='also approve + push to SOFTECH (needs ISR_AUTO_APPROVE_ENABLED)')
        parser.add_argument('--max-lines', type=int, default=None, dest='max_lines')
        parser.add_argument('--once-per-day', action='store_true', dest='once_per_day',
                            help='skip a branch that already has a proposal created today')

    def _branchcodes(self, o):
        codes = list(o.get('branch') or [])
        if o.get('branches'):
            codes += [c.strip() for c in o['branches'].split(',') if c.strip()]
        if o.get('all_operational'):
            codes += list(Branch.objects.filter(is_active=True, is_operational=True)
                          .exclude(db_host='').exclude(db_host__isnull=True)
                          .exclude(softech_branch_id='100')
                          .values_list('softech_branch_id', flat=True))
        # de-dup, preserve order
        seen, out = set(), []
        for c in codes:
            if c and c not in seen:
                seen.add(c); out.append(c)
        return out

    def handle(self, *a, **o):
        codes = self._branchcodes(o)
        if not codes:
            raise CommandError('Specify --branch / --branches / --all-operational.')

        auto = o['auto_approve']
        if auto and not (isr_writer.auto_approve_enabled() and isr_writer.writer_enabled()):
            raise CommandError('--auto-approve needs ISR_AUTO_APPROVE_ENABLED=True and '
                               'ISR_WRITER_ENABLED=True.')

        today = timezone.localdate()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ generate_isr — {len(codes)} branch(es) — auto_approve={auto} ═══'))
        for bc in codes:
            if o['once_per_day'] and IsrPush.objects.filter(
                    branchcode=bc, created_at__date=today).exclude(
                    status=IsrPush.STATUS_CANCELLED).exists():
                self.stdout.write(f'  ▸ {bc}: skipped (proposal already created today)')
                continue
            try:
                p = isr_writer.auto_generate(bc, max_lines=o.get('max_lines'), auto_approve=auto)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  ▸ {bc}: FAILED — {str(exc)[:120]}'))
                continue
            if p is None:
                self.stdout.write(f'  ▸ {bc}: no gap>0 items — nothing to order')
                continue
            tag = (f'PUSHED isr={p.isrdocnumber}' if p.status == IsrPush.STATUS_PUSHED
                   else f'proposal #{p.id} ({p.status})')
            style = self.style.SUCCESS if p.status == IsrPush.STATUS_PUSHED else self.style.WARNING
            self.stdout.write(style(
                f'  ▸ {bc}: {tag} — {p.line_count} صنف · '
                f'{float(p.docvalue):,.0f} ج'))
