"""Notify staff about training changes since the last run (paths gained screens,
quizzes changed) — repo or trainer edits. Runs hourly from the scheduler; safe to
run by hand after a deploy. The first run only records the current state."""
from django.core.management.base import BaseCommand

from apps.help import training


class Command(BaseCommand):
    help = 'Notify staff about training path / quiz changes since the last run.'

    def handle(self, *args, **opts):
        sent = training.announce_changes()
        self.stdout.write(f"paths: {sent['paths']} notified · quizzes: {sent['quizzes']} notified")
