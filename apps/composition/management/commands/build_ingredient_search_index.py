"""
Rebuild the item↔molecule search index (composition.ItemMoleculeIndex).

PG-only and idempotent — reads the itemsai mirror + parse candidates + catalog
items and rebuilds the flat search index that answers "all medicines with
molecule X / at strength Y / in dosage form Z / in class C". Uses the APPROVED
canonical molecule when a candidate is reviewed, otherwise the parser's PROPOSED
molecule (``source`` records which). Never touches SOFTECH.

    python manage.py build_ingredient_search_index
"""
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand

from apps.catalog.models import Item
from apps.composition.models import (
    SoftechItemAI, IngredientParseCandidate, ItemMoleculeIndex,
)


def _dec(v):
    if v is None or v == '':
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


# Molecule fragments that are parser noise, not real ingredients — kept OUT of
# the search index (single letters like vitamin "B"/"E", bare unit tokens like
# "ML"/"MG" that leaked from truncated names). The /composition review layer
# still sees the raw row; this only cleans the search surface.
_UNIT_WORDS = {
    'ML', 'MG', 'MCG', 'UG', 'GM', 'G', 'L', 'IU', 'U', 'UNIT', 'UNITS',
    'CFU', 'MEQ', 'MMOL', 'KG', 'NG', 'MIU', 'M', 'GR', 'MIL',
}


def _is_junk_molecule(mol: str) -> bool:
    return len(mol) < 2 or mol in _UNIT_WORDS


class Command(BaseCommand):
    help = 'Rebuild the item↔molecule search index (Track A).'

    def handle(self, *args, **opts):
        if not SoftechItemAI.objects.exists():
            self.stdout.write(self.style.WARNING(
                'itemsai mirror empty — run `probe_softech_ingredients --mirror` first.'))
            return

        # Preload catalog items: softech_id → (softech_id, id, name, shape, shape_ar)
        items = {}
        for r in Item.objects.values_list(
                'softech_id', 'id', 'name', 'shape_name', 'shape_name_ar'):
            items[str(r[0]).strip()] = r

        # Preload candidates by aicode (skip placeholders / non-drug).
        cands = {}
        qs = (IngredientParseCandidate.objects
              .exclude(is_placeholder=True).exclude(is_non_drug=True)
              .select_related('proposed_class')
              .prefetch_related(
                  'molecule_links__active_ingredient__ingredient_class',
                  'molecule_links__strength'))
        for c in qs:
            cands[c.raw_aicode] = c

        rows, seen = [], set()
        approved_rows = parsed_rows = 0
        for link in SoftechItemAI.objects.filter(is_blocked=False).iterator():
            cand = cands.get(link.aicode)
            if not cand:
                continue
            it = items.get(link.item_softech_id)
            item_id   = it[1] if it else None
            item_name = (it[2] if it else '') or ''
            dosage    = ((it[4] or it[3]) if it else '') or ''

            links = list(cand.molecule_links.all())
            use_approved = cand.status == IngredientParseCandidate.STATUS_APPROVED and links

            molecules = []
            if use_approved:
                for ml in links:
                    ai = ml.active_ingredient
                    molecules.append((
                        ai.name, ai,
                        ml.strength.strength_value if ml.strength else None,
                        ml.strength.strength_unit if ml.strength else '',
                        ai.ingredient_class, ItemMoleculeIndex.SOURCE_APPROVED,
                    ))
            else:
                for comp in (cand.parsed_components or []):
                    m = comp.get('molecule')
                    if not m:
                        continue
                    molecules.append((
                        m.upper(), None,
                        comp.get('strength_value'), comp.get('strength_unit') or '',
                        cand.proposed_class, ItemMoleculeIndex.SOURCE_PARSED,
                    ))

            for mol, ai, sval, sunit, klass, source in molecules:
                mol = (mol or '').strip()
                key = (link.item_softech_id, link.aicode, mol[:200])
                if not mol or _is_junk_molecule(mol) or key in seen:
                    continue
                seen.add(key)
                if source == ItemMoleculeIndex.SOURCE_APPROVED:
                    approved_rows += 1
                else:
                    parsed_rows += 1
                rows.append(ItemMoleculeIndex(
                    item_softech_id=link.item_softech_id, item_id=item_id,
                    item_name=item_name[:255], aicode=link.aicode,
                    molecule=mol[:200], active_ingredient=ai,
                    strength_value=_dec(sval), strength_unit=(sunit or '')[:20],
                    ingredient_class=klass, dosage_form=(dosage or '')[:100],
                    source=source,
                ))

        ItemMoleculeIndex.objects.all().delete()
        ItemMoleculeIndex.objects.bulk_create(rows, batch_size=2000)

        distinct_items = len({r.item_softech_id for r in rows})
        distinct_mols  = len({r.molecule for r in rows})
        self.stdout.write(self.style.SUCCESS(
            f'Index rebuilt: {len(rows)} rows '
            f'({approved_rows} approved, {parsed_rows} parsed) · '
            f'{distinct_items} items · {distinct_mols} distinct molecules.'))
