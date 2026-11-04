"""AI-draft counselling sheets for the most-sold items that have none yet (drafts only — a pharmacist
approves each one in /counselling). Usage: python manage.py draft_counselling --top 50 --as <username>"""
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Item
from apps.counselling.ai_draft import draft_for_item
from apps.counselling.services import needs_content_queue
from apps.users.models import StaffProfile


class Command(BaseCommand):
    help = 'AI-draft counselling sheets (drafts only) for the top-N sold items without one'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=20)
        parser.add_argument('--as', dest='username', required=True, help='staff username recorded as creator')

    def handle(self, *args, **opts):
        actor = StaffProfile.objects.filter(user__username=opts['username']).first()
        if actor is None:
            raise CommandError('unknown staff username')
        made = failed = 0
        for row in needs_content_queue(limit=opts['top']):
            try:
                draft_for_item(actor, Item.objects.get(pk=row['item_id']))
                made += 1
            except Exception as exc:   # one bad item must not stop the batch
                failed += 1
                self.stderr.write(f"{row['item_id']} {row['name']}: {exc}")
        self.stdout.write(f'drafts created: {made}, failed: {failed}')
