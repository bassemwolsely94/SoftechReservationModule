"""
apps/help/glossary.py — «قاموس المصطلحات»: the agreed word for each thing and the words
to avoid (HelpGlossaryTerm), kept by trainers in «للمدربين». Used only for gentle hints
(notecheck.py) on «إيه الجديد» notes and on help text being edited, plus a «where is it
used» count over all current help. Every add / change / delete → HelpRevision
'glossary:<id>' (who, when, before/after).
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import notecheck, registry
from .models import HelpGlossaryTerm, HelpRevision
from .views import _can_edit, _overrides, _profile, _staff_name

MAX_AVOID = 10


def terms():
    """All terms as plain dicts (what notecheck works with)."""
    return [_row(t) for t in HelpGlossaryTerm.objects.select_related('updated_by__user')]


def _row(t):
    return {'id': t.id, 'preferred': t.preferred, 'avoid': list(t.avoid or []), 'modules': list(t.modules or []),
            'why': t.why, 'updated_at': t.updated_at, 'updated_by': _staff_name(t.updated_by)}


def _split(v):
    if isinstance(v, str):
        v = v.replace('،', ',').split(',')
    return [' '.join(str(x).split()) for x in (v or []) if str(x).strip()]


def clean(data, modules):
    """→ (clean dict, errors)."""
    if not isinstance(data, dict):
        return None, ['data must be an object']
    errors = []
    preferred = ' '.join(str(data.get('preferred', '') or '').split())
    avoid = list(dict.fromkeys(_split(data.get('avoid'))))
    mods = [m for m in _split(data.get('modules')) if m]
    if not preferred or len(preferred) > 60:
        errors.append('اكتب الكلمة المعتمدة (60 حرف بالكتير)')
    if not avoid:
        errors.append('اكتب كلمة واحدة على الأقل نتجنّبها')
    if len(avoid) > MAX_AVOID or any(len(a) > 40 for a in avoid):
        errors.append(f'بالكتير {MAX_AVOID} كلمات، كل كلمة 40 حرف')
    if preferred and any(notecheck.bare(a) == notecheck.bare(preferred) for a in avoid):
        errors.append('الكلمة المعتمدة مينفعش تكون في «نتجنّب»')
    bad = [m for m in mods if m not in modules]
    if bad:
        errors.append(f'موديول غير معروف: {", ".join(bad)}')
    return {'preferred': preferred, 'avoid': avoid, 'modules': mods,
            'why': ' '.join(str(data.get('why', '') or '').split())[:200]}, errors


def uses(rows=None):
    """term id → {'count': screens, 'screens': first 8 keys} — where the CURRENT help
    (trainers' edits included) still uses a word to avoid."""
    rows = terms() if rows is None else rows
    _, screens = registry.load()
    ov = _overrides()
    texts = {k: (s['module'], '\n'.join(notecheck._texts({f: registry.effective(s, ov.get(k)).get(f)
                                                          for f in registry.EDITABLE_FIELDS})))
             for k, s in screens.items()}
    out = {}
    for t in rows:
        keys = [k for k, (mod, txt) in texts.items() if notecheck.applies(t, mod) and notecheck.find_terms(txt, [t])]
        out[t['id']] = {'count': len(keys), 'screens': keys[:8]}
    return out


def _audit(term_id, action, before, after, profile):
    HelpRevision.objects.create(screen_key=f'glossary:{term_id}', action=action,
                                before=before, after=after, staff=profile)


def _plain(t):
    return {'preferred': t.preferred, 'avoid': t.avoid, 'modules': t.modules, 'why': t.why}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def glossary(request):
    """GET → {'terms', 'can_edit'} (+ 'uses' for trainers). POST (help/edit) adds a term."""
    profile = _profile(request)
    can = _can_edit(profile)
    if request.method == 'GET':
        rows = terms()
        out = {'terms': rows, 'can_edit': can}
        if can:
            u = uses(rows)
            for r in rows:
                r['uses'] = u.get(r['id'])
        return Response(out)
    if not can:
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    modules, _ = registry.load()
    data, errors = clean(request.data, modules)
    if errors:
        return Response({'detail': 'محتوى غير صالح', 'errors': errors}, status=400)
    if any(notecheck.bare(r['preferred']) == notecheck.bare(data['preferred']) for r in terms()):
        return Response({'detail': 'الكلمة دي موجودة في القاموس — عدّلها بدل ما تضيفها تاني'}, status=400)
    t = HelpGlossaryTerm.objects.create(**data, updated_by=profile)
    _audit(t.id, HelpRevision.ACTION_SAVE, None, data, profile)
    return Response(_row(t), status=201)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def glossary_term(request, pk):
    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    t = HelpGlossaryTerm.objects.filter(pk=pk).first()
    if t is None:
        return Response({'detail': 'not found'}, status=404)
    before = _plain(t)
    if request.method == 'DELETE':
        t.delete()
        _audit(pk, HelpRevision.ACTION_REVERT, before, None, profile)
        return Response(status=204)
    modules, _ = registry.load()
    data, errors = clean(request.data, modules)
    if errors:
        return Response({'detail': 'محتوى غير صالح', 'errors': errors}, status=400)
    for f, v in data.items():
        setattr(t, f, v)
    t.updated_by = profile
    t.save()
    _audit(t.id, HelpRevision.ACTION_SAVE, before, data, profile)
    return Response(_row(t))
