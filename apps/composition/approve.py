"""
Reconciliation approval engine — realises reviewed parse candidates into the
canonical taxonomy (chronic.ActiveIngredient / IngredientStrength) in OUR
Postgres. No SOFTECH writes; this is the reviewed source of truth that Track B
will later replay into SOFTECH.

Dedup is automatic: molecules are keyed by normalized name, so approving the
dozens of "AMLODIPINE …" rows all resolve to ONE ActiveIngredient.

All actions are auditable (reviewer + timestamp) and idempotent (re-approving
rebuilds the molecule links cleanly).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.chronic.models import ActiveIngredient, IngredientStrength, IngredientClass
from .classify import classify
from .models import IngredientParseCandidate, CandidateMolecule


def _norm_molecule(name: str) -> str:
    return re.sub(r'\s+', ' ', (name or '').upper()).strip()


def _fmt_strength(value, unit: str) -> str:
    if value is None:
        return ''
    v = f'{value:g}' if isinstance(value, (int, float)) else str(value)
    return f'{v}{unit}'.strip()


def _class_for(molecule: str, cand: IngredientParseCandidate, override: IngredientClass | None):
    """Class for a molecule: explicit override (primary), else classifier, else the
    candidate's existing proposed_class."""
    if override is not None:
        return override
    key, _, _ = classify(molecule)
    if key:
        return IngredientClass.objects.filter(key=key).first() or cand.proposed_class
    return cand.proposed_class


def _get_or_create_molecule(name: str, class_obj, user):
    ai, created = ActiveIngredient.objects.get_or_create(
        name=name,
        defaults={'source': 'parsed', 'is_verified': True,
                  'verified_by': user, 'verified_at': timezone.now()},
    )
    changed = False
    if class_obj and not ai.ingredient_class_id:
        ai.ingredient_class = class_obj
        changed = True
    if not ai.is_verified:
        ai.is_verified, ai.verified_by, ai.verified_at = True, user, timezone.now()
        changed = True
    if changed:
        ai.save()
    return ai


def _get_or_create_strength(ai: ActiveIngredient, value, unit: str):
    if value is None and not unit:
        return None
    dval = None
    if value is not None:
        try:
            dval = Decimal(str(value))
        except (InvalidOperation, ValueError):
            dval = None
    st, _ = IngredientStrength.objects.get_or_create(
        active_ingredient=ai, strength_value=dval, strength_unit=(unit or ''),
        defaults={'display_name': f'{ai.name} {_fmt_strength(value, unit)}'.strip(),
                  'source': 'parsed'},
    )
    return st


@transaction.atomic
def approve_candidate(cand: IngredientParseCandidate, user, class_override=None):
    """Realise a candidate into canonical molecule(s) + strength tier(s)."""
    if cand.is_placeholder:
        raise ValidationError('لا يمكن اعتماد قيمة عامة/فارغة — استخدم رفض أو "غير دوائي".')
    # Only realise components the reviewer kept (include != False) — junk
    # fragments (CALORIES, CARBS…) are dropped per-component before approval.
    components = [c for c in (cand.parsed_components or [])
                 if c.get('molecule') and c.get('include', True)]
    if not components:
        raise ValidationError('لا توجد مادة فعّالة مُختارة في هذا السطر.')

    cand.molecule_links.all().delete()   # idempotent rebuild
    primary_ai = None
    for i, comp in enumerate(components):
        mol = _norm_molecule(comp['molecule'])
        class_obj = _class_for(mol, cand, class_override if i == 0 else None)
        ai = _get_or_create_molecule(mol, class_obj, user)
        st = _get_or_create_strength(ai, comp.get('strength_value'), comp.get('strength_unit') or '')
        if i == 0 and comp.get('salt') and not ai.salt_form:
            ai.salt_form = comp['salt'][:60]
            ai.save(update_fields=['salt_form'])
        CandidateMolecule.objects.create(
            candidate=cand, active_ingredient=ai, strength=st,
            salt_form=comp.get('salt', '')[:60], is_primary=(i == 0),
        )
        if i == 0:
            primary_ai = ai

    cand.canonical_ingredient = primary_ai
    cand.is_non_drug = False
    cand.status = IngredientParseCandidate.STATUS_APPROVED
    cand.reviewed_by = user
    cand.reviewed_at = timezone.now()
    cand.save(update_fields=['canonical_ingredient', 'is_non_drug', 'status',
                             'reviewed_by', 'reviewed_at', 'updated_at'])
    return cand


@transaction.atomic
def mark_non_drug(cand: IngredientParseCandidate, class_key: str, user):
    """Mark a row as a non-drug product (cosmetic / medical supply / formula).
    No molecule is created; the chosen non-drug class is recorded."""
    NON_DRUG = {'cosmetics', 'medical_supplies', 'infant_formula'}
    if class_key not in NON_DRUG:
        raise ValidationError(f'تصنيف غير دوائي غير صالح: {class_key}')
    klass = IngredientClass.objects.filter(key=class_key).first()
    if not klass:
        raise ValidationError('التصنيف غير موجود — شغّل seed_ingredient_classes.')
    cand.molecule_links.all().delete()
    cand.canonical_ingredient = None
    cand.proposed_class = klass
    cand.is_non_drug = True
    cand.status = IngredientParseCandidate.STATUS_APPROVED
    cand.reviewed_by = user
    cand.reviewed_at = timezone.now()
    cand.save(update_fields=['canonical_ingredient', 'proposed_class', 'is_non_drug',
                             'status', 'reviewed_by', 'reviewed_at', 'updated_at'])
    return cand


@transaction.atomic
def reject_candidate(cand: IngredientParseCandidate, user, notes=''):
    cand.molecule_links.all().delete()
    cand.canonical_ingredient = None
    cand.status = IngredientParseCandidate.STATUS_REJECTED
    cand.reviewed_by = user
    cand.reviewed_at = timezone.now()
    if notes:
        cand.review_notes = notes[:2000]
    cand.save(update_fields=['canonical_ingredient', 'status', 'reviewed_by',
                             'reviewed_at', 'review_notes', 'updated_at'])
    return cand


def set_class(cand: IngredientParseCandidate, class_id, user):
    """Manually override the proposed class (does not change approval status)."""
    klass = IngredientClass.objects.filter(pk=class_id).first()
    if not klass:
        raise ValidationError('التصنيف غير موجود.')
    cand.proposed_class = klass
    cand.class_rule = f'manual:{getattr(user, "id", "?")}'
    cand.class_confidence = 1.0
    cand.save(update_fields=['proposed_class', 'class_rule', 'class_confidence', 'updated_at'])
    # propagate to the canonical molecule if already approved
    if cand.canonical_ingredient_id and not cand.canonical_ingredient.ingredient_class_id:
        cand.canonical_ingredient.ingredient_class = klass
        cand.canonical_ingredient.save(update_fields=['ingredient_class'])
    return cand
