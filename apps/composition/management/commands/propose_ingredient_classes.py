"""
Propose a pharmacological class for each parse candidate using the deterministic
INN-stem classifier. Writes a PROPOSAL (proposed_class + rule + confidence) for a
pharmacist to approve — never a final assignment.

For combinations, every component molecule is classified (stored back into
parsed_components as ``class_key``); the candidate's headline proposed_class is
the highest-confidence component.

    python manage.py propose_ingredient_classes
    python manage.py propose_ingredient_classes --dry-run
    python manage.py propose_ingredient_classes --only-unclassified
"""
from collections import Counter

from django.core.management.base import BaseCommand

from apps.chronic.models import IngredientClass
from apps.composition.models import IngredientParseCandidate
from apps.composition.classify import classify, CLASSIFIER_VERSION


class Command(BaseCommand):
    help = 'Propose ingredient classes (INN-stem classifier) for review.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--only-unclassified', action='store_true',
                            help='Only fill candidates that have no proposed_class yet.')
        parser.add_argument('--reparse-reviewed', action='store_true',
                            help='Also touch approved/rejected candidates (default: skip).')

    def handle(self, *args, **opts):
        class_by_key = {c.key: c for c in IngredientClass.objects.all() if c.key}
        if not class_by_key:
            self.stdout.write(self.style.ERROR(
                'No IngredientClass rows — run `seed_ingredient_classes` first.'))
            return

        reviewed = {IngredientParseCandidate.STATUS_APPROVED,
                    IngredientParseCandidate.STATUS_REJECTED}

        qs = IngredientParseCandidate.objects.filter(is_placeholder=False)
        if opts['only_unclassified']:
            qs = qs.filter(proposed_class__isnull=True)

        total = matched = updated = 0
        dist = Counter()
        item_covered = 0
        for cand in qs.select_related('raw').iterator():
            total += 1
            if cand.status in reviewed and not opts['reparse_reviewed']:
                continue

            components = cand.parsed_components or []
            best = (None, '', 0.0)   # (class_key, rule, conf)
            for comp in components:
                key, rule, conf = classify(comp.get('molecule', ''))
                comp['class_key'] = key or ''
                if conf > best[2]:
                    best = (key, rule, conf)

            key, rule, conf = best
            if key and key in class_by_key:
                matched += 1
                dist[key] += 1
                if cand.raw and cand.raw.item_count:
                    item_covered += cand.raw.item_count
                if not opts['dry_run']:
                    cand.proposed_class = class_by_key[key]
                    cand.class_rule = f'{rule} [{CLASSIFIER_VERSION}]'
                    cand.class_confidence = conf
                    cand.parsed_components = components
                    cand.save(update_fields=[
                        'proposed_class', 'class_rule', 'class_confidence',
                        'parsed_components', 'updated_at'])
                    updated += 1
            elif not opts['dry_run']:
                # keep per-component class annotations even when unmatched
                cand.parsed_components = components
                cand.save(update_fields=['parsed_components', 'updated_at'])

        pct = (100.0 * matched / total) if total else 0.0
        self.stdout.write(self.style.SUCCESS(
            f'Classified {matched}/{total} candidates ({pct:.1f}%) '
            f'covering {item_covered} item links. '
            f'{"(dry-run)" if opts["dry_run"] else f"{updated} written."}'))
        self.stdout.write('\nTop proposed classes:')
        for key, n in dist.most_common(25):
            self.stdout.write(f'  {n:>5}  {class_by_key[key].name}')
        self.stdout.write(f'\nUnclassified candidates: {total - matched} '
                          '(need manual class or new stem rule).')
