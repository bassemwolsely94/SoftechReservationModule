"""
python manage.py sync_insurance_cache

Sync SOFTECH motalba + companiesitems into the local PostgreSQL cache.
Run from the SERVER (where the Sybase connection is reachable).

  python manage.py sync_insurance_cache                       # both, normal incremental
  python manage.py sync_insurance_cache --motalba             # motalba only
  python manage.py sync_insurance_cache --companies           # companiesitems only

Historical back-fill (e.g. a prior year) — read-only, idempotent upsert:

  python manage.py sync_insurance_cache --year 2025           # 2025-01-01 .. 2025-12-31
  python manage.py sync_insurance_cache --from 2025-01-01 --to 2025-12-31
  python manage.py sync_insurance_cache --from 2025-06-01     # from a date up to today

The back-fill lets the "إضافة يدوية" lookup resolve old receipts' branch/parent
codes from the local cache instead of a slow live full-table scan.
"""
import datetime as _dt

from django.core.management.base import BaseCommand, CommandError


def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        raise CommandError(f'تاريخ غير صالح: {s!r} — استخدم الصيغة YYYY-MM-DD')


class Command(BaseCommand):
    help = ('Sync motalba + companiesitems caches from SOFTECH '
            '(default: incremental; --year/--from/--to for a historical back-fill)')

    def add_arguments(self, parser):
        parser.add_argument('--motalba',   action='store_true', help='Sync motalba only')
        parser.add_argument('--companies', action='store_true', help='Sync companiesitems only')
        parser.add_argument('--year',  type=int, help='Back-fill a whole calendar year, e.g. 2025')
        parser.add_argument('--from',  dest='from_date', help='Back-fill start date YYYY-MM-DD')
        parser.add_argument('--to',    dest='to_date',   help='Back-fill end date YYYY-MM-DD (inclusive)')

    def handle(self, *args, **opts):
        from apps.insurance.sync import (
            sync_motalba, sync_companiesitems, sync_insurance_cache,
        )

        # Resolve an optional explicit window
        from_date = to_date = None
        if opts.get('year'):
            y = opts['year']
            from_date = _dt.date(y, 1, 1)
            to_date   = _dt.date(y, 12, 31)
        if opts.get('from_date'):
            from_date = _parse_date(opts['from_date'])
        if opts.get('to_date'):
            to_date = _parse_date(opts['to_date'])

        if to_date and from_date and to_date < from_date:
            raise CommandError('--to يجب أن يكون بعد --from')

        if from_date:
            self.stdout.write(self.style.WARNING(
                f'Back-fill window: {from_date} .. {to_date or "today"} '
                '(read-only, idempotent upsert)'
            ))

        if opts['motalba']:
            stats = sync_motalba(from_date=from_date, to_date=to_date)
            self.stdout.write(self.style.SUCCESS(f'motalba: {stats}'))
        elif opts['companies']:
            stats = sync_companiesitems(from_date=from_date, to_date=to_date)
            self.stdout.write(self.style.SUCCESS(f'companiesitems: {stats}'))
        else:
            result = sync_insurance_cache(from_date=from_date, to_date=to_date)
            if result.get('status') == 'ok':
                self.stdout.write(self.style.SUCCESS(f'Sync complete: {result}'))
            else:
                self.stdout.write(self.style.ERROR(f'Sync failed: {result}'))
