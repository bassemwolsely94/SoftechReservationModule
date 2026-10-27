"""
Seed / refresh the pharmacological class taxonomy (chronic.IngredientClass)
from apps.composition.taxonomy.CLASSES.

Maps SOFTECH's 23 classes by ``softech_code`` and adds the extended families.
Idempotent (keyed on ``key``); never overwrites an owner's edited display names
unless ``--reset-names`` is passed. Reconciles against SoftechIngredientClassRaw
and reports any code/name drift.

    python manage.py seed_ingredient_classes
    python manage.py seed_ingredient_classes --reset-names
"""
from django.core.management.base import BaseCommand

from apps.chronic.models import IngredientClass
from apps.composition.models import SoftechIngredientClassRaw
from apps.composition.taxonomy import CLASSES


class Command(BaseCommand):
    help = 'Seed the IngredientClass taxonomy (SOFTECH 23 + extended families).'

    def add_arguments(self, parser):
        parser.add_argument('--reset-names', action='store_true',
                            help='Overwrite English/Arabic names from the seed (default: keep owner edits).')

    def handle(self, *args, **opts):
        created = updated = 0
        for key, en, ar, softech_code in CLASSES:
            defaults = {
                'softech_code': softech_code or '',
            }
            obj, was_created = IngredientClass.objects.get_or_create(
                key=key,
                defaults={'name': en, 'name_ar': ar, **defaults},
            )
            if was_created:
                created += 1
                continue
            # existing — refresh softech_code + (optionally) names
            changed = False
            if obj.softech_code != (softech_code or ''):
                obj.softech_code = softech_code or ''
                changed = True
            if opts['reset_names']:
                if obj.name != en or obj.name_ar != ar:
                    obj.name, obj.name_ar = en, ar
                    changed = True
            if not obj.key:
                obj.key = key
                changed = True
            if changed:
                obj.save()
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'IngredientClass: {created} created, {updated} updated, '
            f'{IngredientClass.objects.count()} total.'))

        # Reconcile against the real SOFTECH class rows.
        raw = {r.softech_code: r.name for r in SoftechIngredientClassRaw.objects.all()}
        if raw:
            self.stdout.write('\nReconciliation vs SOFTECH basic_data(600):')
            seeded_codes = {c[3]: c[1] for c in CLASSES if c[3]}
            for code, sname in sorted(raw.items(), key=lambda x: (len(x[0]), x[0])):
                mine = seeded_codes.get(code)
                mark = 'ok ' if mine else 'MISSING in seed'
                self.stdout.write(f'  [{code:>2}] {sname:32} → {mark}')
            for code in seeded_codes:
                if code not in raw:
                    self.stdout.write(self.style.WARNING(
                        f'  seed code {code} not present in SOFTECH mirror'))
        else:
            self.stdout.write(self.style.WARNING(
                '\n(SOFTECH class mirror empty — run probe_softech_ingredients --mirror to reconcile.)'))
