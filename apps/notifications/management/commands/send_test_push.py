"""
Send a test Web Push to a staff member's subscribed devices — used to verify the
push pipeline end-to-end on a real device.

Usage:
    python manage.py send_test_push <username> [--title "..."] [--body "..."]

Prereqs (the command prints diagnostics for each):
  - WEBPUSH_VAPID_* keys configured in the environment.
  - The user enabled browser push on a device (creates a PushSubscription and sets
    StaffProfile.enable_browser_push=True). On iOS this requires an INSTALLED PWA
    (Safari 16.4+); a plain browser tab won't receive Web Push.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.users.models import StaffProfile
from apps.notifications.models import send_web_push


class Command(BaseCommand):
    help = 'Send a test Web Push notification to a user\'s subscribed devices.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--title', default='🔔 إشعار تجريبي')
        parser.add_argument('--body',  default='يعمل الإشعار بنجاح — صيدليات الرزيقي')

    def handle(self, *args, **opts):
        profile = StaffProfile.objects.filter(user__username=opts['username']).first()
        if not profile:
            raise CommandError(f'No staff profile for username {opts["username"]!r}')

        # Diagnostics
        vapid_ok = bool(getattr(settings, 'WEBPUSH_VAPID_PRIVATE_KEY', ''))
        sub_count = profile.push_subscriptions.count()
        self.stdout.write(f'VAPID keys configured : {vapid_ok}')
        self.stdout.write(f'enable_browser_push   : {profile.enable_browser_push}')
        self.stdout.write(f'push subscriptions    : {sub_count}')
        if not vapid_ok:
            self.stderr.write(self.style.ERROR('VAPID keys not set — set WEBPUSH_VAPID_* in the environment.'))
            return
        if not profile.enable_browser_push or sub_count == 0:
            self.stderr.write(self.style.WARNING(
                'User has no active push subscription / push disabled — '
                'open the app on a device and enable "إشعارات المتصفح" first.'))
            return

        sent = send_web_push(profile, opts['title'], opts['body'], url='/m/notifications')
        self.stdout.write(self.style.SUCCESS(f'Pushed to {sent} endpoint(s).'))
