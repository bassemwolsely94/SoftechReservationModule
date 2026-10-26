"""
Management command: run_engine_job — the dashboard's engine buttons, in their own process.

Started by apps/purchasing/background.launch() for a DemandCalculationRun the view already
created (status='running'); not meant to be run by hand (use run_demand_engine for that).

  --mode quick     «▶ تشغيل»          incremental sync + recalculation
  --mode full      «🔄 مزامنة كاملة»  catalog refresh + 365-day backfill + recalculation
  --mode catchup   «⟳ تعويض المبيعات» chunked sales backfill + recalculation
  --run <id>       the run to drive
  --params <json>  per-run EngineConfig overrides (quick / full)
"""
import json
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')


class Command(BaseCommand):
    help = 'تشغيل محرك الطلب من أزرار لوحة المشتريات في عملية مستقلة'

    def add_arguments(self, parser):
        parser.add_argument('--mode', required=True, choices=['quick', 'full', 'catchup'])
        parser.add_argument('--run', type=int, required=True)
        parser.add_argument('--params', default='')

    def handle(self, *args, **opts):
        from apps.purchasing.models import DemandCalculationRun
        run = DemandCalculationRun.objects.filter(pk=opts['run']).first()
        if run is None:
            raise CommandError(f'run {opts["run"]} not found')
        if run.status != 'running':
            logger.warning('[engine-job] run %s is %s — nothing to do', run.pk, run.status)
            return
        params = json.loads(opts['params']) if opts['params'] else {}
        mode = opts['mode']
        logger.info('[engine-job] %s run %s started', mode, run.pk)
        try:
            from apps.purchasing.engine import DemandEngine
            if mode == 'catchup':
                from apps.purchasing.catchup import run_catchup
                run_catchup(run_id=run.pk)
            elif mode == 'full':
                # Full sync refreshes the CATALOG first (new items + price / itemtrans /
                # امر التوريد / tax) so the engine reads the freshest Item rows.
                try:
                    from apps.sync.tasks import run_items_sync
                    run_items_sync()
                except Exception:
                    logger.exception('[engine-job] catalog refresh failed (continuing to sales sync)')
                DemandEngine(param_overrides=params).run(full_backfill=True, existing_run=run)
            else:
                DemandEngine(param_overrides=params).run(full_backfill=False, existing_run=run)
        except Exception as exc:
            logger.exception('[engine-job] %s run %s failed: %s', mode, run.pk, exc)
            run.refresh_from_db()
            if run.status == 'running':
                run.status = 'failed'
                run.error_message = str(exc)[:500]
                run.finished_at = timezone.now()
                run.save(update_fields=['status', 'error_message', 'finished_at'])
            raise SystemExit(1)
        logger.info('[engine-job] %s run %s finished', mode, run.pk)
