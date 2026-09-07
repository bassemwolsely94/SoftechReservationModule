"""
apps/demand/management/commands/check_demand_sla.py

Escalate demand-intake SLA breaches (TD-C003).

Runs hourly via APScheduler (apps/sync/tasks.py → _demand_sla_escalation), or
manually / via Windows Task Scheduler:

  python manage.py check_demand_sla

Fires a HIGH-alarm 'demand_sla_breach' notification for any demand record that
is stuck in intake:
  • status 'new'      not assigned within SLA_MINUTES['new']      (default 10m)
  • status 'assigned' not progressed within SLA_MINUTES['assigned'] (default 20m)

Re-escalates at most once per `demand_sla_repeat_minutes` (default 60). Idempotent
and non-fatal — see apps/demand/service.escalate_breached_demand_sla.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Escalate demand-intake SLA breaches (unassigned / stalled records)'

    def handle(self, *args, **options):
        from apps.demand.service import escalate_breached_demand_sla

        escalated = escalate_breached_demand_sla()
        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Demand SLA check done — {escalated} breach escalation(s) sent'
            )
        )
