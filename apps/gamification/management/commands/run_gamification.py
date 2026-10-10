"""
python manage.py run_gamification               # score today (no day close)
python manage.py run_gamification --days 1      # score yesterday + today, close yesterday
python manage.py run_gamification --days 30     # backfill the last 30 days of activity
python manage.py run_gamification --seed [--reset-defaults]

Reads existing records only (sales mirror, reservations, transfers, demand, tasks …);
never writes to SOFTECH. Safe to re-run: every point carries a unique source key.
"""
from django.core.management.base import BaseCommand

from apps.gamification import engine
from apps.gamification.defaults import ensure_defaults


class Command(BaseCommand):
    help = 'Gamification: award points for recorded work, close days, refresh levels/badges'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=0)
        parser.add_argument('--no-finalize', action='store_true')
        parser.add_argument('--seed', action='store_true', help='only seed rules/levels/badges')
        parser.add_argument('--reset-defaults', action='store_true',
                            help='with --seed: overwrite admin edits with the defaults')

    def handle(self, *args, **opts):
        if opts['seed']:
            n = ensure_defaults(reset=opts['reset_defaults'])
            self.stdout.write(self.style.SUCCESS(f'seeded ({n} new rows)'))
            return
        days = max(0, opts['days'])
        r = engine.run(days=days, finalize=days > 0 and not opts['no_finalize'])
        self.stdout.write(self.style.SUCCESS(
            f"awarded={r['awarded']} players={r['players']} promotions={r['promotions']}"))
