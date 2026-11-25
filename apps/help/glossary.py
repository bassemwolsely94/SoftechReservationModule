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
NEW_DAYS = 7          # a term added within this many days is «جديد» (badge on the trainers tab)


def _new_since():
    from django.utils import timezone
    return timezone.now() - timezone.timedelta(days=NEW_DAYS)


def new_count():
    """How many terms were added in the last NEW_DAYS days (one count query)."""
    return HelpGlossaryTerm.objects.filter(created_at__gte=_new_since()).count()


def terms():
    """All terms as plain dicts (what notecheck works with)."""
    since = _new_since()
    return [_row(t, since) for t in HelpGlossaryTerm.objects.select_related('updated_by__user')]


def _row(t, since=None):
    since = since or _new_since()
    return {'id': t.id, 'preferred': t.preferred, 'avoid': list(t.avoid or []), 'modules': list(t.modules or []),
            'why': t.why, 'updated_at': t.updated_at, 'updated_by': _staff_name(t.updated_by),
            'is_new': bool(t.created_at and t.created_at >= since)}


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


def _flow_draft(data):
    """The texts of a workflow tour the glossary checks: title, summary, each step's text + more."""
    steps = data.get('steps') if isinstance(data.get('steps'), list) else []
    return {'title': data.get('title'), 'summary': data.get('summary'),
            'steps': [{f: st.get(f) for f in ('text', 'more')} if isinstance(st, dict) else {} for st in steps]}


def _quiz_draft(data):
    """The texts of a quiz the glossary checks: each question, its options and explanation."""
    qs = data.get('questions') if isinstance(data.get('questions'), list) else []
    return {'questions': [{f: q.get(f) for f in ('q', 'options', 'explain')} if isinstance(q, dict) else {}
                          for q in qs]}


def audit_all(rows=None):
    """«طبّق القاموس على الكل»: every avoided word in the CURRENT help (trainers' edits
    included) — each screen, workflow tour and quiz — grouped per item, most first:
    [{'kind', 'key', 'title', 'module', 'count', 'words': [{'avoid', 'preferred', 'n'}],
      'samples': first 3 {path, match, replacement, before, after}}]. Read-only; the
    trainer opens each item and replaces there with «📖 طبّق القاموس»."""
    from . import training
    rows = terms() if rows is None else rows
    if not rows:
        return []
    modules, screens = registry.load()
    ov = _overrides()
    found = []
    for k, sc in screens.items():
        eff = registry.effective(sc, ov.get(k))
        draft = {f: eff.get(f) for f in registry.EDITABLE_FIELDS}
        found.append(('screen', k, eff['title'], sc['module'], notecheck.scan(draft, rows, sc['module'])))
    for fid, f in training.flows_effective(modules).items():
        found.append(('flow', fid[5:], f['title'], f['module'], notecheck.scan(_flow_draft(f), rows, f['module'])))
    for mk, qs in training.quizzes().items():
        if mk not in modules or not qs:
            continue
        t = modules[mk]['title']
        found.append(('quiz', mk, {'ar': f"اختبار {t['ar']}", 'en': f"{t['en']} quiz"}, mk,
                      notecheck.scan(_quiz_draft({'questions': qs}), rows, mk)))
    out = []
    for kind, key, title, module, items in found:
        if not items:
            continue
        words = {}
        for it in items:
            words[(it['avoid'], it['preferred'])] = words.get((it['avoid'], it['preferred']), 0) + 1
        out.append({'kind': kind, 'key': key, 'title': title, 'module': module, 'count': len(items),
                    'words': [{'avoid': a, 'preferred': p, 'n': n}
                              for (a, p), n in sorted(words.items(), key=lambda x: -x[1])],
                    'samples': [{f: it[f] for f in ('path', 'match', 'replacement', 'before', 'after')}
                                for it in items[:3]]})
    out.sort(key=lambda x: (-x['count'], x['kind'], x['key']))
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def scan(request):
    """«طبّق القاموس»: every avoided word in a draft's Arabic text with its place (path,
    start, end), sentence and replacement (notecheck.scan). Read-only: the editor applies
    the ones the trainer accepts to its draft, and nothing changes until they press «حفظ».

      screen help:   POST {screen_key, data: draft}
      workflow tour: POST {kind: 'flow', key: '<module>.<flow>', data: {title, summary, steps}}
      quiz:          POST {kind: 'quiz', key: '<module>', data: {questions}}
    Terms limited to some modules apply by the module the draft belongs to."""
    if not _can_edit(_profile(request)):
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    body = request.data if isinstance(request.data, dict) else {}
    data = body.get('data')
    if not isinstance(data, dict):
        return Response({'detail': 'data must be an object'}, status=400)
    modules, screens = registry.load()
    kind, key = body.get('kind'), str(body.get('key') or '')
    if kind == 'flow':
        from . import training
        if training.base_flow(key) is None:
            return Response({'detail': 'not found'}, status=404)
        return Response({'items': notecheck.scan(_flow_draft(data), terms(), key.split('.')[0])})
    if kind == 'quiz':
        if key not in modules:
            return Response({'detail': 'not found'}, status=404)
        return Response({'items': notecheck.scan(_quiz_draft(data), terms(), key)})
    s = screens.get(str(body.get('screen_key') or ''))
    if s is None:
        return Response({'detail': 'not found'}, status=404)
    draft = {f: data.get(f) for f in registry.EDITABLE_FIELDS if f in data}
    return Response({'items': notecheck.scan(draft, terms(), s['module'])})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit(request):
    """GET (help/edit) → {'items': audit_all(), 'total', 'terms'}: where the whole help
    still uses words the glossary says to avoid. Read-only."""
    if not _can_edit(_profile(request)):
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    rows = terms()
    items = audit_all(rows)
    return Response({'items': items, 'total': sum(i['count'] for i in items), 'terms': len(rows)})
