"""
python manage.py send_followup_reminders
Run this daily via Windows Task Scheduler at start of business (e.g. 9:00 AM).
Sends in-app notifications for reservations with follow_up_date = today.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date

from apps.reservations.models import Reservation
from apps.notifications.models import Notification


class Command(BaseCommand):
    help = 'Send follow-up reminders for reservations due today'

    def handle(self, *args, **options):
        today = date.today()
        due = Reservation.objects.filter(
            follow_up_date=today,
            status__in=['pending', 'available', 'contacted']
        ).select_related('item', 'customer', 'branch', 'assigned_to__user')

        count = 0
        for reservation in due:
            title = f"📅 متابعة مطلوبة — حجز #{reservation.id}"
            message = (
                f"{reservation.item.name} — {reservation.contact_name} "
                f"({reservation.contact_phone}) في {reservation.branch.name_ar or reservation.branch.name}"
            )

            # Notify branch staff
            Notification.send_to_branch(
                branch=reservation.branch,
                notification_type='follow_up_due',
                title=title,
                message=message,
                reservation=reservation,
            )

            # Notify call center
            Notification.send_to_call_center(
                notification_type='follow_up_due',
                title=title,
                message=message,
                reservation=reservation,
            )

            # Notify assigned staff specifically if set
            if reservation.assigned_to:
                Notification.send(
                    recipient=reservation.assigned_to.user,
                    notification_type='follow_up_due',
                    title=title,
                    message=message,
                    reservation=reservation,
                )

            count += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ Sent follow-up reminders for {count} reservations due today ({today})"
        ))
