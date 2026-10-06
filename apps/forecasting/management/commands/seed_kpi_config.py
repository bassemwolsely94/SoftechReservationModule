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


# Validated defaults for person_type '10' (customers). 2026-07-29 vs تحقيق مايو 2026.
# channel -> (bucket, subtype, counts_customer, include_in_profit)
PT10_DEFAULTS = {
    '91': ('cash',      '',         True,  True),   # عميل نقدى
    '11': ('cash',      '',         False, True),   # موظفيين شركة الرزيقي
    '12': ('cash',      '',         False, True),   # إيصال إلكترونى بالبطاقة
    '90': ('cash',      'delivery', True,  True),   # عميل Delivery
    '30': ('cash',      'regular',  False, True),   # عميل دائم
    '10': ('credit',    '',         False, False),  # تعاقدات / آجل
    '33': ('credit',    '',         False, False),  # تعاقد - سداد آجل - خصم يدوي
    '17': ('exclude',   '',         False, False),  # تعويضات الشركات — free-pack/patient-support compensations, NOT normal sales
    '31': ('credit',    '',         False, False),  # مقاصات (owner to confirm)
    '15': ('insurance', '',         False, False),  # تأمين صحي
    '16': ('exclude',   '',         False, False),  # تبرعات
    '99': ('exclude',   '',         False, False),  # Vip (owner to map)
}

BEAUTY_DEFAULTS = [('50', 'Cosmetics'), ('20', 'Others')]


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
            default = PT10_DEFAULTS.get(ch) if pt == '10' else None
            bucket, subtype, cust, profit = default or ('exclude', '', False, False)

            row = ChannelBucketMap.objects.filter(person_type=pt, channel=ch).first()
            if row is None:
                ChannelBucketMap.objects.create(
                    person_type=pt, channel=ch, label=label or '',
                    bucket=bucket, subtype=subtype,
                    counts_customer=cust, include_in_profit=profit,
                )
                created += 1
            elif reset and default:
                row.label = label or row.label
                row.bucket, row.subtype = bucket, subtype
                row.counts_customer, row.include_in_profit = cust, profit
                row.save(update_fields=['label', 'bucket', 'subtype',
                                        'counts_customer', 'include_in_profit'])
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

        self.stdout.write(self.style.SUCCESS(
            f'ChannelBucketMap: +{created} created, {updated} reset, {skipped} kept. '
            f'BeautyClassRule: +{b_created} created.'))
