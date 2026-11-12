"""
python manage.py run_whisper_queue [--now] [--max N] [--backfill-days D]

Normally launched by the scheduler inside the nightly window (default 02:00–06:00).
  --now            ignore the window (manual/test run; pause/stop still apply)
  --max N          stop after N transcripts
  --backfill-days  queue answered recorded calls from the last D days first
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Transcribe queued call recordings with local Whisper (CPU).'

    def add_arguments(self, parser):
        parser.add_argument('--now', action='store_true')
        parser.add_argument('--max', type=int, default=None)
        parser.add_argument('--backfill-days', type=int, default=0)

    def handle(self, *args, **opts):
        from apps.callcenter import whisper

        if opts['backfill_days']:
            # Issabel's CDR mirror (sync_pbx_cdr) holds every call, even while the bridge was down
            queued = whisper.enqueue_recent_cdr(hours=opts['backfill_days'] * 24)
            self.stdout.write(f'queued {queued} calls')

        result = whisper.run_queue(ignore_window=opts['now'], max_items=opts['max'])
        self.stdout.write(f"done: {result['processed']} — stopped: {result['stopped']}")
