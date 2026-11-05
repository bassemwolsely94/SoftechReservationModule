"""
python manage.py run_payment_exception_checks [--days N] [--force]

Runs the payment exception checks (duplicate / delayed / wrong branch) and the anomaly score
over external payments created in the last N days (default 7). Creates PaymentException and
AbuseFlag rows only — never changes a payment, a statement match or SOFTECH. Reruns are
idempotent.

Does nothing while the setting `payments.exception_checks_enabled` is off, unless --force.
"""
from django.core.management.base import BaseCommand

from apps.config.models import SystemSetting

SWITCH_KEY = 'payments.exception_checks_enabled'


def checks_enabled() -> bool:
    return bool(SystemSetting.get(SWITCH_KEY, False))


class Command(BaseCommand):
    help = 'Run the payment exception checks and anomaly score (off unless the setting is on or --force).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7,
                            help='Check payments created in the last N days (default 7).')
        parser.add_argument('--force', action='store_true',
                            help='Run even when payments.exception_checks_enabled is off.')

    def handle(self, *args, days=7, force=False, **options):
        if not force and not checks_enabled():
            self.stdout.write(f'Skipped: {SWITCH_KEY} is off (use --force to run anyway).')
            return
        from apps.payments.audit_service import PaymentAuditService
        out = PaymentAuditService.run_exception_checks(days=max(1, days))
        self.stdout.write(
            f"Checked {out['payments']} payments (last {max(1, days)} days): "
            f"{out['exceptions_created']} new exceptions, {out['anomalies_created']} new anomalies, "
            f"{out['flags_created']} new abuse flags."
        )
