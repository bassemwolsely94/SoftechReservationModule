"""
Management command: python manage.py seed_loyalty

Seeds default LoyaltyTier definitions and a starter RewardCatalog.
Safe to re-run — uses update_or_create on name.

Default tiers:
  Bronze  ≥     0 pts  — multiplier 1.0×
  Silver  ≥  1,000 pts — multiplier 1.25×
  Gold    ≥  5,000 pts — multiplier 1.5×
  VIP     ≥ 15,000 pts — multiplier 2.0×

Default rewards:
  50 ج.م voucher  → 500 pts
  100 ج.م voucher → 900 pts
  200 ج.م voucher → 1,700 pts
  Priority delivery → 300 pts
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.loyalty.models import LoyaltyTier, RewardCatalog


TIERS = [
    dict(name='bronze', name_ar='برونزي', order=0, min_points=0,
         color='#CD7F32', icon='🥉', earn_multiplier=Decimal('1.00'),
         benefits_description='الدرجة الافتراضية — نقطة لكل جنيه على الأصناف المؤهلة'),
    dict(name='silver', name_ar='فضي', order=1, min_points=1000,
         color='#C0C0C0', icon='🥈', earn_multiplier=Decimal('1.25'),
         benefits_description='25% نقاط إضافية — خصم خاص على المنتجات المختارة'),
    dict(name='gold', name_ar='ذهبي', order=2, min_points=5000,
         color='#FFD700', icon='🥇', earn_multiplier=Decimal('1.50'),
         benefits_description='50% نقاط إضافية — أولوية التوصيل — عروض حصرية'),
    dict(name='vip', name_ar='VIP', order=3, min_points=15000,
         color='#9B59B6', icon='👑', earn_multiplier=Decimal('2.00'),
         benefits_description='ضعف النقاط — مدير حساب مخصص — توصيل مجاني دائم'),
]

REWARDS = [
    dict(name='voucher_50', name_ar='قسيمة 50 جنيه', reward_type='voucher',
         points_cost=500, description='استبدل 500 نقطة بقسيمة خصم بقيمة 50 جنيه',
         reward_data={'voucher_value': 50, 'min_order': 100}),
    dict(name='voucher_100', name_ar='قسيمة 100 جنيه', reward_type='voucher',
         points_cost=900, description='استبدل 900 نقطة بقسيمة خصم بقيمة 100 جنيه',
         reward_data={'voucher_value': 100, 'min_order': 200}),
    dict(name='voucher_200', name_ar='قسيمة 200 جنيه', reward_type='voucher',
         points_cost=1700, description='استبدل 1700 نقطة بقسيمة خصم بقيمة 200 جنيه',
         reward_data={'voucher_value': 200, 'min_order': 400}),
    dict(name='priority_delivery', name_ar='توصيل أولوية', reward_type='priority_delivery',
         points_cost=300, description='توصيل في أسرع وقت ممكن لطلبك القادم',
         reward_data={}),
    dict(name='vip_upgrade', name_ar='ترقية VIP لشهر', reward_type='vip_status',
         points_cost=5000, description='استمتع بمزايا VIP لمدة 30 يوماً',
         reward_data={'duration_days': 30}),
]


class Command(BaseCommand):
    help = 'Seed default loyalty tiers and reward catalog'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete and recreate all tiers (WARNING: clears tier FKs)')

    def handle(self, *args, **options):
        if options['reset']:
            LoyaltyTier.objects.all().delete()
            self.stdout.write(self.style.WARNING('All tiers deleted.'))

        # Seed tiers
        tier_map = {}
        for t in TIERS:
            obj, created = LoyaltyTier.objects.update_or_create(
                name=t['name'],
                defaults={k: v for k, v in t.items() if k != 'name'},
            )
            tier_map[t['name']] = obj
            verb = 'Created' if created else 'Updated'
            self.stdout.write(f'  {t["icon"]} {verb}: {t["name_ar"]}')

        self.stdout.write(self.style.SUCCESS(f'\n✅ {len(TIERS)} tiers seeded'))

        # Seed rewards
        created_rewards = 0
        for r in REWARDS:
            _, created = RewardCatalog.objects.update_or_create(
                name=r['name'],
                defaults={k: v for k, v in r.items() if k != 'name'},
            )
            if created:
                created_rewards += 1

        self.stdout.write(self.style.SUCCESS(f'✅ {len(REWARDS)} rewards seeded ({created_rewards} new)'))
        self.stdout.write('\nRun python manage.py seed_loyalty again at any time to refresh defaults.')
