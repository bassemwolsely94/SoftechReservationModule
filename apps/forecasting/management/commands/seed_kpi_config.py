"""
seed_kpi_config  (doc 16, Phase 1)
==================================
Seeds/refreshes the branch-KPI config tables:
  • ChannelBucketMap — every (person_type, channel) from sync.SoftechPersonClassif,
    with validated defaults for person_type '10' (customers). Existing rows are
    NEVER overwritten (owner edits win); only missing rows are inserted, unless
    --reset-defaults is passed.
  • BeautyClassRule — default {50 Cosmetics, 20 Others}.

Usage:
  python manage.py seed_kpi_config
  python manage.py seed_kpi_config --reset-defaults   # re-apply defaults to pt=10 rows
"""
from django.core.management.base import BaseCommand
from django.db import transaction


# Validated defaults for person_type '10' (customers) live in one place:
# apps.forecasting.channels.CHANNEL_DEFAULTS (KPI columns + piece-4 meaning columns).
from apps.forecasting.channels import CHANNEL_DEFAULTS, KPI_FIELDS, MEANING_FIELDS

BEAUTY_DEFAULTS = [('50', 'Cosmetics'), ('20', 'Others')]

# Items removed from معامل الربحية (SOFTECH itemcode → reason). Owner-editable in admin.
PROFIT_EXCLUSION_DEFAULTS = [('2', 'DLV — رسوم التوصيل (حصة مندوبى التوصيل)')]


class Command(BaseCommand):
    help = 'Seed branch-KPI config (ChannelBucketMap + BeautyClassRule)'

    def add_arguments(self, parser):
        parser.add_argument('--reset-defaults', action='store_true',
                            help='Re-apply the validated pt=10 defaults (overwrites those rows)')

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.forecasting.models import ChannelBucketMap, BeautyClassRule
        from apps.sync.models import SoftechPersonClassif

        reset = opts['reset_defaults']
        created = updated = skipped = 0

        for c in SoftechPersonClassif.objects.all():
            pt, ch, label = c.ptcode, c.ptclassifcode, c.ptclassifdescr
            default = CHANNEL_DEFAULTS.get(ch) if pt == '10' else None

            row = ChannelBucketMap.objects.filter(person_type=pt, channel=ch).first()
            if row is None:
                vals = dict(default) if default else {'bucket': 'exclude'}
                ChannelBucketMap.objects.create(
                    person_type=pt, channel=ch, label=label or '', **vals,
                )
                created += 1
            elif reset and default:
                row.label = label or row.label
                fields = KPI_FIELDS + MEANING_FIELDS
                for f in fields:
                    setattr(row, f, default[f])
                row.save(update_fields=['label', *fields])
                updated += 1
            else:
                # keep owner edits; refresh label only if blank
                if not row.label and label:
                    row.label = label
                    row.save(update_fields=['label'])
                skipped += 1

        b_created = 0
        for mt, label in BEAUTY_DEFAULTS:
            _, was = BeautyClassRule.objects.get_or_create(
                medicine_type=mt, defaults={'label': label, 'active': True})
            b_created += int(was)

        # Profit-metric exclusions (معامل الربحية): the DLV delivery-fee item (itemcode 2)
        # — pure-margin fee the delivery staff take a daily cut of; owner removes the bias.
        from apps.forecasting.models import ProfitExclusion
        from apps.catalog.models import Item
        p_created = 0
        for code, note in PROFIT_EXCLUSION_DEFAULTS:
            it = Item.objects.filter(softech_id=code).first()
            if it:
                _, was = ProfitExclusion.objects.get_or_create(
                    item=it, defaults={'note': note, 'active': True})
                p_created += int(was)

        self.stdout.write(self.style.SUCCESS(
            f'ChannelBucketMap: +{created} created, {updated} reset, {skipped} kept. '
            f'BeautyClassRule: +{b_created} created. '
            f'ProfitExclusion: +{p_created} created.'))
