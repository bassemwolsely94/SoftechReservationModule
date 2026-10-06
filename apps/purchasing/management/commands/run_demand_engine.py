"""
Management command: run_demand_engine

Modes:
  (default)           Incremental sync (last 10 days) + full recalculation
  --full              Full 365-day SOFTECH backfill + recalculation
  --lookback N        Custom sync window (--lookback 30 fetches last 30 days)
  --sync-only         Only sync SOFTECH → PG, skip metric calculation
  --calc-only         Skip SOFTECH sync, recalculate from existing PG data
  --dry-run           Validate lookups only, write nothing

Usage:
  python manage.py run_demand_engine               # daily incremental run
  python manage.py run_demand_engine --full        # initial backfill
  python manage.py run_demand_engine --lookback 30
  python manage.py run_demand_engine --calc-only   # recalc when SOFTECH is down
  python manage.py run_demand_engine --dry-run

Scheduling (Windows Task Scheduler at 2:00 AM daily):
  "venv\\Scripts\\python.exe" manage.py run_demand_engine >> logs\\demand_engine.log 2>&1
"""
import time
import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger('elrezeiky.purchasing')


class Command(BaseCommand):
    help = 'تشغيل محرك تحليل الطلب — حساب معدلات المبيعات، مخزون الأمان، الفجوات، وتصنيف ABC'

    def add_arguments(self, parser):
        parser.add_argument(
            '--full',
            action='store_true',
            default=False,
            help='تزامن كامل 365 يوم من SOFTECH (للتشغيل الأول أو إعادة البناء الكاملة)',
        )
        parser.add_argument(
            '--lookback',
            type=int,
            default=None,
            metavar='DAYS',
            help='عدد أيام التزامن التراجعي (الافتراضي: 10 للتزامن التدريجي، 365 مع --full)',
        )
        parser.add_argument(
            '--sync-only',
            action='store_true',
            default=False,
            help='تزامن SOFTECH فقط — بدون إعادة حساب المقاييس',
        )
        parser.add_argument(
            '--calc-only',
            action='store_true',
            default=False,
            help='حساب المقاييس من البيانات الموجودة في PG فقط (بدون تزامن SOFTECH)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='اختبار: تحميل البيانات المرجعية فقط، بدون كتابة أي نتائج',
        )

    def handle(self, *args, **options):
        full      = options['full']
        lookback  = options['lookback']
        sync_only = options['sync_only']
        calc_only = options['calc_only']
        dry_run   = options['dry_run']

        # Determine effective lookback
        from apps.purchasing.engine import DEFAULT_INCREMENTAL_DAYS, ROLLING_WINDOW_DAYS
        if lookback is not None:
            effective_lookback = lookback
        elif full:
            effective_lookback = ROLLING_WINDOW_DAYS
        else:
            effective_lookback = DEFAULT_INCREMENTAL_DAYS

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n══════════════════════════════════════════════════\n'
            '   محرك تحليل الطلب والمشتريات الأمثل\n'
            '══════════════════════════════════════════════════'
        ))

        mode_parts = []
        if dry_run:   mode_parts.append('معاينة')
        elif full:    mode_parts.append(f'كامل {effective_lookback} يوم')
        elif calc_only: mode_parts.append('حساب فقط (PG)')
        elif sync_only: mode_parts.append(f'تزامن فقط ({effective_lookback} يوم)')
        else:           mode_parts.append(f'تدريجي ({effective_lookback} يوم)')

        self.stdout.write(f'  الوضع: {" | ".join(mode_parts)}\n')

        t0 = time.monotonic()

        try:
            from apps.purchasing.engine import DemandEngine

            engine = DemandEngine(lookback_days=effective_lookback)

            if dry_run:
                engine._load_lookups()
                self.stdout.write(f'  الفروع:            {len(engine._branch_map)}')
                self.stdout.write(f'  الأصناف في الكتالوج: {len(engine._item_map)}')
                self.stdout.write(f'  صفوف المخزون:      {len(engine._stock_map)}')

                # Count existing PG data
                from apps.purchasing.models import SalesTransactionLine
                pg_count = SalesTransactionLine.objects.count()
                self.stdout.write(f'  حركات في PG:       {pg_count:,}')

                self.stdout.write(self.style.SUCCESS(
                    '\n  ✔ اكتملت المعاينة بنجاح — لم تُكتب أي بيانات.\n'
                ))
                return

            run = engine.run(
                full_backfill=full,
                sync_only=sync_only,
                calc_only=calc_only,
            )

            elapsed = time.monotonic() - t0

            if run.status == 'success':
                self.stdout.write(self.style.SUCCESS(
                    f'\n  ✔ اكتمل التشغيل #{run.pk}\n'
                    f'  SOFTECH:    {"✔ متاح" if run.softech_available else "✗ بيانات PG فقط"}\n'
                    f'  تزامن:      {run.rows_synced:,} صف (آخر {effective_lookback} يوم)\n'
                    f'  حُذف قديم:  {run.rows_purged:,} صف (>365 يوم)\n'
                    f'  الفروع:     {run.branches_processed}\n'
                    f'  الأصناف:    {run.items_processed:,}\n'
                    f'  كُتب:       {run.rows_written:,} صف\n'
                    f'  المدة:      {elapsed:.1f}s\n'
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f'\n  ✗ فشل التشغيل #{run.pk}: {run.error_message}\n'
                ))

        except Exception as exc:
            elapsed = time.monotonic() - t0
            self.stderr.write(self.style.ERROR(
                f'\n  ✗ استثناء غير متوقع بعد {elapsed:.1f}s: {exc}\n'
            ))
            logger.exception('run_demand_engine failed: %s', exc)
            raise SystemExit(1)
