"""
management command: tag_chronic_items

Scans the Item catalog and creates/updates ChronicMedication records
based on phcode (ATC code) prefixes.

Usage:
    python manage.py tag_chronic_items
    python manage.py tag_chronic_items --reset   # clears all tags first
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Tag catalog items as chronic medications based on phcode/ATC prefixes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete all existing ChronicMedication tags before re-tagging'
        )

    def handle(self, *args, **options):
        from apps.catalog.models import ChronicMedication
        from apps.catalog.chronic import tag_chronic_items

        if options['reset']:
            deleted, _ = ChronicMedication.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Deleted {deleted} existing tags'))

        created = tag_chronic_items()
        total = ChronicMedication.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f'Done — {created} new chronic tags created. Total in DB: {total}'
            )
        )
