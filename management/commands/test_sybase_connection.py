"""
python manage.py test_sybase_connection
Tests connectivity to SOFTECH Sybase ASE 12.5 and prints server time.
"""
from django.core.management.base import BaseCommand
from config.sybase import test_connection


class Command(BaseCommand):
    help = 'Test read-only connection to SOFTECH Sybase ASE 12.5'

    def handle(self, *args, **options):
        self.stdout.write("Testing Sybase connection...")
        success, message = test_connection()
        if success:
            self.stdout.write(self.style.SUCCESS(f"✅ {message}"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Connection failed: {message}"))
