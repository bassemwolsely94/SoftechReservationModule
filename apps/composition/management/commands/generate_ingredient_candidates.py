"""
Run the deterministic parser over the SOFTECH mirror and (re)build the
IngredientParseCandidate review queue.

Idempotent: re-running updates each candidate in place (keyed on its raw row)
without disturbing rows a human has already reviewed unless ``--reparse-reviewed``
is passed. Nothing here touches SOFTECH — it reads our mirror and writes our
proposals.

    python manage.py generate_ingredient_candidates
    python manage.py generate_ingredient_candidates --dry-run
    python manage.py generate_ingredient_candidates --limit 200 --low 0.75
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.composition.models import SoftechIngredientRaw, IngredientParseCandidate
from apps.composition.parser import parse


class Command(BaseCommand):
    help = 'Generate/refresh active-ingredient parse candidates from the SOFTECH mirror.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and report, but write nothing.')
        parser.add_argument('--limit', type=int, default=0, help='Cap rows processed (0 = all).')
        parser.add_argument('--low', type=float, default=0.7,
                            help='Confidence below this is flagged needs_review (default 0.7).')
        parser.add_argument('--reparse-reviewed', action='store_true',
                            help='Also overwrite candidates already approved/rejected (default: skip).')

    def handle(self, *args, **opts):
        qs = SoftechIngredientRaw.objects.all().order_by('aicode')
        if opts['limit']:
            qs = qs[:opts['limit']]
        total = qs.count()
        if not total:
            self.stdout.write(self.style.WARNING(
                'Mirror is empty — run `probe_softech_ingredients --mirror` first.'))
            return

        low = opts['low']
        created = updated = skipped = combos = placeholders = flagged = 0

        reviewed_states = {IngredientParseCandidate.STATUS_APPROVED,
                           IngredientParseCandidate.STATUS_REJECTED}

        for raw in qs.iterator():
            res = parse(raw.ainame)
            if res.is_placeholder:
                placeholders += 1
            if res.is_combination:
                combos += 1

            if res.is_placeholder:
                status = IngredientParseCandidate.STATUS_NEEDS_REVIEW
            elif res.confidence < low:
                status = IngredientParseCandidate.STATUS_NEEDS_REVIEW
            else:
                status = IngredientParseCandidate.STATUS_PENDING
            if status == IngredientParseCandidate.STATUS_NEEDS_REVIEW:
                flagged += 1

            if opts['dry_run']:
                continue

            existing = IngredientParseCandidate.objects.filter(raw=raw).first()
            if existing and existing.status in reviewed_states and not opts['reparse_reviewed']:
                skipped += 1
                continue

            defaults = {
                'raw_aicode': raw.aicode,
                'raw_ainame': raw.ainame,
                'parsed_components': [c.to_json() for c in res.components],
                'is_combination': res.is_combination,
                'is_placeholder': res.is_placeholder,
                'proposed_class_code': raw.class_code or '',
                'proposed_class_name': raw.class_name or '',
                'confidence': res.confidence,
                'parser_version': res.parser_version,
            }
            with transaction.atomic():
                obj, was_created = IngredientParseCandidate.objects.get_or_create(
                    raw=raw, defaults={**defaults, 'status': status})
                if not was_created:
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    # keep an already-set non-terminal status fresh; don't clobber review
                    if obj.status not in reviewed_states:
                        obj.status = status
                    obj.save()
            created += was_created
            updated += (not was_created)

        self.stdout.write(self.style.SUCCESS(
            f'Processed {total} raw rows: {created} created, {updated} updated, '
            f'{skipped} skipped(reviewed).'))
        self.stdout.write(
            f'  combinations: {combos} | placeholders: {placeholders} | '
            f'flagged needs_review: {flagged}')
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('  (dry-run — nothing written)'))
