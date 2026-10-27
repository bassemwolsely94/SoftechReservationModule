"""
seed_near_expiry_incentive  (A5.3)
==================================
Stand up a ready-to-use "near-expiry sell-through" staff incentive using the
EXISTING incentives engine (IncentiveRule.expiry_within_days is already wired) —
no new engine code. Rewards staff for selling units whose batch expires within N
days, motivating sell-through WITHOUT changing any price.

Created INACTIVE by default: the program pays real money, so enabling it is a
deliberate owner action. Review it at /incentives, then activate (or pass
--activate). Idempotent — re-running won't duplicate.

Usage:
  python manage.py seed_near_expiry_incentive
  python manage.py seed_near_expiry_incentive --days 90 --percent 2.5 --activate
"""
import datetime as _dt
from decimal import Decimal
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed a near-expiry sell-through staff incentive (A5.3), inactive by default.'

    DEFAULT_NAME = 'حافز تصريف قرب انتهاء الصلاحية'

    def add_arguments(self, parser):
        parser.add_argument('--name', default=self.DEFAULT_NAME,
                            help='Program name (idempotency key).')
        parser.add_argument('--days', type=int, default=90,
                            help='Reward sales of units expiring within N days (default 90).')
        parser.add_argument('--percent', type=float, default=2.0,
                            help='Incentive as %% of net sale value (default 2.0).')
        parser.add_argument('--activate', action='store_true',
                            help='Create the program ACTIVE (default: inactive — pays money, review first).')

    def handle(self, *args, **opts):
        from apps.incentives.models import IncentiveProgram, IncentiveRule

        name = opts['name']
        today = _dt.date.today()

        program, created = IncentiveProgram.objects.get_or_create(
            name=name,
            defaults=dict(
                description=('حافز لتحفيز فريق البيع على تصريف الأصناف قرب انتهاء صلاحيتها '
                             'قبل تلفها — يُطبَّق على الوحدات التي تنتهي صلاحيتها خلال الفترة المحددة.'),
                start_date=today,
                end_date=today.replace(year=today.year + 1),
                calculation_period='monthly',
                is_active=bool(opts['activate']),
            ),
        )
        if not created:
            self.stdout.write(self.style.WARNING(
                f'Program "{name}" already exists (id={program.pk}, active={program.is_active}). '
                f'Left as-is.'))

        rule, rcreated = IncentiveRule.objects.get_or_create(
            program=program,
            rule_name='قرب انتهاء الصلاحية',
            defaults=dict(
                incentive_type='percent',
                incentive_value=Decimal(str(opts['percent'])),
                expiry_within_days=opts['days'],
                is_imported_filter='any',
            ),
        )

        state = 'ACTIVE' if program.is_active else 'INACTIVE (review at /incentives then activate)'
        self.stdout.write(self.style.SUCCESS(
            f'Near-expiry incentive ready — program id={program.pk} [{state}], '
            f'rule id={rule.pk} ({opts["percent"]}% on units expiring ≤{opts["days"]}d). '
            f'program_created={created} rule_created={rcreated}'
        ))
        if program.is_active:
            self.stdout.write(self.style.WARNING(
                '⚠️ Program is ACTIVE and will accrue incentive payouts on qualifying sales.'))
