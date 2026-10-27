"""
python manage.py populate_phcodes

Pre-loads the Chronic Classifier module by converting existing
catalog.ChronicMedication entries (tagged by tag_chronic_items) into
ActiveIngredient + ItemIngredientMap records that the new module can use.

Safe to re-run — idempotent.

NOTE: The command is named populate_phcodes for historical reasons but
      stktransm.phcode is the customer personcode (e.g. 04HD1006), NOT a drug
      code. This command works from catalog.ChronicMedication, not from phcodes.
"""
from django.core.management.base import BaseCommand
from apps.chronic.classifier import preload_from_chronic_medication


class Command(BaseCommand):
    help = 'Pre-classify chronic items using existing ChronicMedication catalog tags'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without saving',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        from apps.catalog.models import ChronicMedication
        from apps.chronic.models import ItemIngredientMap

        total_chronic = ChronicMedication.objects.filter(is_active=True).count()
        already       = ItemIngredientMap.objects.values('item_id').distinct().count()

        self.stdout.write(
            f'Chronic items in catalog: {total_chronic}\n'
            f'Already mapped in classifier: {already}\n'
        )

        if dry_run:
            todo = (
                ChronicMedication.objects
                .filter(is_active=True)
                .exclude(item__ingredient_maps__isnull=False)
                .count()
            )
            self.stdout.write(
                self.style.WARNING(f'[DRY RUN] Would process {todo} unmapped chronic items.')
            )
            return

        self.stdout.write('Importing from ChronicMedication catalog...')
        result = preload_from_chronic_medication()

        self.stdout.write(
            self.style.SUCCESS(
                f'  {result["ingredients_created"]} ActiveIngredients created.\n'
                f'  {result["maps_created"]} ItemIngredientMap records created.\n'
                f'  {result["already_mapped"]} items were already mapped.\n'
                f'Done.'
            )
        )
