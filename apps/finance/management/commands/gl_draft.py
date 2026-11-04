"""python manage.py gl_draft --from YYYY-MM-DD --to YYYY-MM-DD [--source TYPE ...] [--dry-run] [--allow-mass-vanish]

Runs the GL drafting engine over a date range: SOFTECH source documents (SELECT only) → draft ledger
entries. ``--allow-mass-vanish`` bypasses the guard that refuses to vanish > 20 % (and > 10) of a
type's documents in one run (Ruling P10). ``--dry-run`` runs everything inside one transaction and rolls it back, printing the counts.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.finance.gl import drafting


def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CommandError(f'bad date: {value} (YYYY-MM-DD)')


class Command(BaseCommand):
    help = 'Draft GL entries from SOFTECH source documents for a date range.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', required=True)
        parser.add_argument('--to', dest='date_to', required=True)
        parser.add_argument('--source', dest='sources', action='append', default=[],
                            choices=list(drafting.SOURCE_ORDER))
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--allow-mass-vanish', action='store_true')

    def handle(self, *args, **opts):
        d1, d2 = _day(opts['date_from']), _day(opts['date_to'])
        if d2 < d1:
            raise CommandError('--to is before --from')
        sources = opts['sources'] or None
        if opts['dry_run']:
            with transaction.atomic():
                run = self._run(d1, d2, sources, 'gl_draft --dry-run', opts['allow_mass_vanish'])
                transaction.set_rollback(True)
            self.stdout.write('DRY RUN — rolled back, nothing saved')
        else:
            run = self._run(d1, d2, sources, 'gl_draft', opts['allow_mass_vanish'])
        self.stdout.write(f'status: {run.status}')
        for k, v in run.counts.items():
            self.stdout.write(f'  {k}: {v}')
        for k, v in (run.detail or {}).items():
            if v:
                self.stdout.write(f'  {k}: {v}')

    def _run(self, d1, d2, sources, who, allow_mass_vanish):
        try:
            run = drafting.start_run(triggered_by=who, date_from=d1, date_to=d2, source_types=sources or [])
        except drafting.DraftBusy:
            raise CommandError('another drafting run is running (يعمل بالفعل)')
        return drafting.draft_range(d1, d2, source_types=sources, run=run,
                                    allow_mass_vanish=allow_mass_vanish)
