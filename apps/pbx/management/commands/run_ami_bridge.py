"""
Management command: python manage.py run_ami_bridge

Starts the Asterisk AMI bridge as a long-running async process.
Run this in a separate process (systemd unit or supervisor).
"""
import asyncio
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger('elrezeiky.pbx')


class Command(BaseCommand):
    help = 'Start the Asterisk AMI bridge (long-running async listener)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting AMI bridge…'))
        try:
            from apps.pbx.ami_bridge import run_bridge
            asyncio.run(run_bridge())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('AMI bridge stopped.'))
