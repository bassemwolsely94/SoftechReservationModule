"""
python manage.py sync_insurance_cache

Sync SOFTECH motalba + companiesitems into the local PostgreSQL cache.
Run from the SERVER (where the Sybase connection is reachable).

  python manage.py sync_insurance_cache              # both tables
  python manage.py sync_insurance_cache --motalba    # motalba only
  python manage.py sync_insurance_cache --companies  # companiesitems only
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sync motalba + companiesitems caches from SOFTECH (last 90 days, incremental)'

    def add_arguments(self, parser):
        parser.add_argument('--motalba',   action='store_true', help='Sync motalba only')
        parser.add_argument('--companies', action='store_true', help='Sync companiesitems only')

    def handle(self, *args, **opts):
        from apps.insurance.sync import (
            sync_motalba, sync_companiesitems, sync_insurance_cache,
        )

        if opts['motalba']:
            stats = sync_motalba()
            self.stdout.write(self.style.SUCCESS(f'motalba: {stats}'))
        elif opts['companies']:
            stats = sync_companiesitems()
            self.stdout.write(self.style.SUCCESS(f'companiesitems: {stats}'))
        else:
            result = sync_insurance_cache()
            if result.get('status') == 'ok':
                self.stdout.write(self.style.SUCCESS(f'Sync complete: {result}'))
            else:
                self.stdout.write(self.style.ERROR(f'Sync failed: {result}'))
