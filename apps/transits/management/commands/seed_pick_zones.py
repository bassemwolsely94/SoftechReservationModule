"""
python manage.py seed_pick_zones

Bootstrap the replenishment pick-zone tables (PickZone / PickZoneRule) from
the built-in defaults — a 1:1 port of the Supply Chain team's Power Query
rules, with the historical pick-path order preserved via sort_key.

Idempotent: does nothing if any PickZone already exists (the zones are managed
from the /pick-zones frontend afterwards). Also ensures the
`replenishment_price_threshold` setting exists (500 EGP) and removes the
legacy `replenishment_pick_zones` JSON setting.
"""
from django.core.management.base import BaseCommand

from apps.transits.export import seed_default_pick_zones


class Command(BaseCommand):
    help = 'Seed default replenishment pick zones + classification rules (idempotent)'

    def handle(self, *args, **options):
        zones, rules = seed_default_pick_zones(stdout=self.stdout)
        if not zones:
            self.stdout.write('PickZone table not empty — nothing seeded (managed from /pick-zones).')
