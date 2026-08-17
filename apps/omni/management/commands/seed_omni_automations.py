"""
python manage.py seed_omni_automations [--reset]

Seed the starter automation rules from doc 15 §"Automation engine". Idempotent
by name. --reset deletes existing seeded rules first.
"""
from django.core.management.base import BaseCommand

from apps.omni.models import AutomationRule

SEED_RULES = [
    {
        'name': 'تصعيد شكوى فورًا',
        'trigger': 'message_in',
        'conditions': {'text_contains': ['شكوى', 'زعلان', 'غاضب', 'سيء', 'وحش']},
        'actions': [
            {'type': 'set_priority', 'priority': 'urgent'},
            {'type': 'add_tag', 'tag': 'شكوى'},
            {'type': 'notify_role', 'role': 'supervisor', 'text': 'شكوى محتملة'},
        ],
        'order': 10,
    },
    {
        'name': 'أولوية عملاء VIP',
        'trigger': 'message_in',
        'conditions': {'customer_vip': True},
        'actions': [
            {'type': 'set_priority', 'priority': 'high'},
            {'type': 'add_tag', 'tag': 'VIP'},
        ],
        'order': 20,
    },
    {
        'name': 'طلب توصيل',
        'trigger': 'message_in',
        'conditions': {'text_contains': ['توصيل', 'ديليفري', 'دليفري', 'اوصلوا']},
        'actions': [
            {'type': 'add_tag', 'tag': 'توصيل'},
            {'type': 'notify_role', 'role': 'call_center', 'text': 'طلب توصيل جديد'},
        ],
        'order': 30,
    },
    {
        'name': 'متابعة المكالمات الفائتة',
        'trigger': 'call_missed',
        'conditions': {},
        'actions': [
            {'type': 'set_status', 'status': 'pending'},
            {'type': 'add_note', 'text': 'مكالمة فائتة — يلزم معاودة الاتصال'},
            {'type': 'notify_role', 'role': 'call_center', 'text': 'مكالمة فائتة تحتاج معاودة'},
        ],
        'order': 40,
    },
]


class Command(BaseCommand):
    help = 'Seed starter omni automation rules'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true')

    def handle(self, *args, **opts):
        if opts['reset']:
            names = [r['name'] for r in SEED_RULES]
            deleted, _ = AutomationRule.objects.filter(name__in=names).delete()
            self.stdout.write(f'Deleted {deleted} existing seeded rules')

        created = 0
        for spec in SEED_RULES:
            _, was_created = AutomationRule.objects.get_or_create(
                name=spec['name'],
                defaults={
                    'trigger': spec['trigger'],
                    'conditions': spec['conditions'],
                    'actions': spec['actions'],
                    'order': spec['order'],
                    'is_active': True,
                },
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(
            f'Seed done — {created} created, {len(SEED_RULES) - created} already existed'))
