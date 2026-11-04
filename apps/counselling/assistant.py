"""
Staff drug assistant — one read that gathers what the counter needs about an item, in a fixed
order: safety first, then identity, molecules, verified alternatives, unverified suggestions and
the pharmacist-approved guidance. No business logic of its own: it composes catalog.safety,
composition.alternatives and the counselling sheets. Read-only; never touches SOFTECH.
"""
from apps.catalog.safety import item_safety_flags
from apps.composition.alternatives import alternatives_for, unverified_alternatives_for
from apps.composition.models import ItemMoleculeIndex

from .permissions import can
from .selectors import approved_content, content_enabled, sheet_for


def _guidance(item, profile):
    approved = approved_content(item)
    editor = can(profile, 'edit')
    if approved:
        out = {'status': 'approved', 'content': approved, 'can_edit': editor}
    else:
        out = {'status': 'none', 'content': None, 'can_edit': editor}
    sheet = sheet_for(item) if content_enabled() else None
    # Unapproved text never reaches counter staff (an AI or hand draft could be read aloud to a
    # customer). Editors see the pending draft, clearly marked.
    if editor and sheet is not None and sheet.status in ('draft', 'pending_review'):
        out['draft'] = {**sheet.snapshot(), 'status': sheet.status, 'source': sheet.source,
                        'content_id': sheet.pk}
        if not approved:
            out['status'] = 'draft'
    if sheet is not None:
        out['content_id'] = sheet.pk if editor else None
    return out


def assistant_payload(item, *, branch_id, profile) -> dict:
    flags = item_safety_flags(item)
    molecules = [{'molecule': r.molecule,
                  'strength': (f'{r.strength_value.normalize():f} {r.strength_unit}'.strip()
                               if r.strength_value is not None else ''),
                  'dosage_form': r.dosage_form,
                  'verified': r.source == ItemMoleculeIndex.SOURCE_APPROVED}
                 for r in ItemMoleculeIndex.objects.filter(item_id=item.pk).order_by('molecule')]
    return {
        'item_id': item.pk,
        'safety': flags,
        'blocked': any(f['severity'] == 'block' for f in flags),
        'identity': {
            'name': item.name, 'name_ar': getattr(item, 'name_ar', '') or '',
            'softech_id': item.softech_id,
            'form': item.shape_name_ar or item.shape_name or '',
            'indication': item.effect_name_ar or item.effect_name or '',
            'medicine_type': getattr(item, 'medicine_type', '') or '',
            'requires_fridge': bool(getattr(item, 'requires_fridge', False)),
            'pack_price': float(item.pack_price) if item.pack_price is not None else None,
        },
        'molecules': molecules,
        'molecules_verified': bool(molecules) and all(m['verified'] for m in molecules),
        'alternatives': alternatives_for(item.pk, branch_id=branch_id),
        'suggestions': unverified_alternatives_for(item.pk, branch_id=branch_id)['items'],
        'guidance': _guidance(item, profile),
    }
