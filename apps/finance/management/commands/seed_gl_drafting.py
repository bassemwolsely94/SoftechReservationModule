"""python manage.py seed_gl_drafting - seed the GL posting rules and source maps (idempotent).

Rules/maps whose accounts are missing are skipped and listed; run again after the COA import.
"""
from django.core.management.base import BaseCommand

from apps.finance.gl import drafting, seed


class Command(BaseCommand):
    help = 'Seed GL posting rules and source maps (never overwrites finance edits).'

    def handle(self, *args, **opts):
        res = seed.seed_gl_drafting(user=drafting.system_user())
        for k in ('rules_created', 'rules_existing', 'maps_created', 'maps_existing'):
            self.stdout.write(f'{k}: {len(res[k])}')
        for s in res['skipped']:
            extra = s.get('accounts') or s.get('branch_code') or s.get('errors') or ''
            self.stdout.write(f'  skipped {s["what"]} {s["code"]}: {s["reason"]} {extra}')
