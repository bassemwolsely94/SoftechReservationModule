"""python manage.py build_pic_facts [--since YYYY-MM-DD] [--days N]
Rebuilds PicDayFact for the window (default last 7 days) and PicRollup as of yesterday (Cairo)."""
import time
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.pic_analytics import build


class Command(BaseCommand):
    help = 'Rebuild PIC day facts and per-PIC rollups (our own tables only).'

    def add_arguments(self, parser):
        parser.add_argument('--since', help='YYYY-MM-DD start (backfill)')
        parser.add_argument('--days', type=int, default=7)

    def handle(self, *args, **o):
        yesterday = timezone.localtime().date() - timedelta(days=1)
        start = (datetime.strptime(o['since'], '%Y-%m-%d').date() if o['since']
                 else yesterday - timedelta(days=o['days'] - 1))
        end = max(yesterday, start)
        t = time.time()
        facts = build.build_day_facts(start, end)
        self.stdout.write(f'day facts {start}..{end}: {facts} rows ({time.time() - t:.1f}s)')
        t = time.time()
        rolls = build.build_rollups(yesterday)
        self.stdout.write(f'rollups as of {yesterday}: {rolls} rows ({time.time() - t:.1f}s)')
