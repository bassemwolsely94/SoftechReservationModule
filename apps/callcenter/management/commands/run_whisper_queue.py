"""
python manage.py run_whisper_queue [--now] [--max N] [--backfill-days D]

Normally launched by the scheduler inside the nightly window (default 02:00–06:00).
  --now            ignore the window (manual/test run; pause/stop still apply)
  --max N          stop after N transcripts
  --backfill-days  queue answered recorded calls from the last D days first
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Transcribe queued call recordings with local Whisper (CPU).'

    def add_arguments(self, parser):
        parser.add_argument('--now', action='store_true')
        parser.add_argument('--max', type=int, default=None)
        parser.add_argument('--backfill-days', type=int, default=0)

    def handle(self, *args, **opts):
        from apps.callcenter import whisper
        from apps.callcenter.models import CallLog

        if opts['backfill_days']:
            since = timezone.now() - timedelta(days=opts['backfill_days'])
            queued = sum(whisper.enqueue(c) for c in
                         CallLog.objects.filter(called_at__gte=since).select_related('pbx_session'))
            self.stdout.write(f'queued {queued} calls')

        result = whisper.run_queue(ignore_window=opts['now'], max_items=opts['max'])
        self.stdout.write(f"done: {result['processed']} — stopped: {result['stopped']}")
