"""
python manage.py post_usage_notice

P-57: the one-time staff notice that screen usage is recorded. Posts a pinned internal
announcement (read receipts via the existing announcements module) to every role.
Idempotent — a second run does nothing. Run once at go-live, before staff use the system.
"""
from django.core.management.base import BaseCommand

TITLE = 'تسجيل استخدام الشاشات'
BODY = ('السيستم بيسجّل الشاشات اللي كل موظف بيفتحها (اسم الشاشة بس — من غير بيانات العملاء '
        'أو اللي اتكتب فيها) علشان نعرف إيه المفيد وإيه محتاج تحسين. ممكن يُستخدم في تقييم الأداء '
        'مع نتائج الشغل نفسها، ومش لوحده أبداً. البيانات بتتحفظ ١٢ شهر بس.\n\n'
        'Screen usage is recorded (screen names only — no customer data or what you type) to improve '
        'the system. It may be used in performance evaluation together with work outcomes, never on '
        'its own. Kept for 12 months.')


class Command(BaseCommand):
    help = 'Post the one-time P-57 screen-usage notice (idempotent).'

    def handle(self, *args, **options):
        from apps.notifications.models import Announcement
        if Announcement.objects.filter(title=TITLE).exists():
            self.stdout.write('notice already posted — nothing to do')
            return
        Announcement.objects.create(title=TITLE, body=BODY, priority=Announcement.PRIORITY_HIGH, is_pinned=True)
        self.stdout.write(self.style.SUCCESS('screen-usage notice posted'))
