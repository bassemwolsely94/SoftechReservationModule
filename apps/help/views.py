"""
apps/help/views.py — mounted at /api/help/

Reading help is open to every logged-in staff member. Editing (trainers) needs the
RBAC grant help/edit (admins always); every save/revert is written to HelpRevision.
"""
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import registry
from .models import HelpEvent, HelpFeedback, HelpOverride, HelpRevision


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_edit(profile):
    return bool(profile and profile.can_do('help', 'edit'))


def _overrides():
    return {o.screen_key: o for o in HelpOverride.objects.select_related('updated_by__user')}


def _updated(screen, override):
    """Date the text last changed (repo date, or the trainer's save if newer)."""
    d = screen.get('updated') or ''
    if override is not None:
        od = override.updated_at.date().isoformat()
        d = max(d, od)
    return d


def _log(kind, request, screen_key='', tab='', query='', results=None):
    p = _profile(request)
    HelpEvent.objects.create(
        kind=kind, screen_key=screen_key[:80], tab=(tab or '')[:60], query=(query or '')[:200], results=results,
        staff=p, role=getattr(p, 'role', '') or '', branch_id=getattr(p, 'branch_id', None),
    )


def _brief(s, modules):
    m = modules.get(s['module'], {})
    return {'key': s['key'], 'module': s['module'], 'title': s['title'],
            'summary': s['summary'], 'module_title': m.get('title'), 'icon': m.get('icon', '')}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def index(request):
    """Everything the panel needs to find the help for the current page + the help
    center: modules (grouped), screens (key, routes, title, updated, tab keys)."""
    modules, screens = registry.load()
    ov = _overrides()
    return Response({
        'groups': [{'key': k, 'title': {'ar': ar, 'en': en}} for k, ar, en in registry.GROUPS],
        'modules': [{
            'key': m['key'], 'group': m.get('group', 'admin'), 'icon': m.get('icon', ''),
            'title': m['title'], 'summary': m['summary'], 'screens': m['screens'],
            'has_workflow': bool(m.get('workflows')),
        } for m in modules.values()],
        'screens': [{
            'key': s['key'], 'module': s['module'], 'routes': s['routes'],
            'title': registry.effective(s, ov.get(s['key']))['title'],
            'tabs': [t['key'] for t in s.get('tabs') or []],
            'updated': _updated(s, ov.get(s['key'])),
        } for s in screens.values()],
        'can_edit': _can_edit(_profile(request)),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def module_detail(request, key):
    modules, screens = registry.load()
    m = modules.get(key)
    if m is None:
        return Response({'detail': 'not found'}, status=404)
    ov = _overrides()
    return Response({
        **{k: v for k, v in m.items() if k != 'screens'},
        'screens': [_brief(registry.effective(screens[k], ov.get(k)), modules) for k in m['screens']],
    })


def _screen_payload(request, key, s, modules, screens, override):
    eff = registry.effective(s, override)
    m = modules.get(s['module'], {})
    can_edit = _can_edit(_profile(request))
    payload = {
        **eff,
        'module': {'key': m.get('key'), 'title': m.get('title'), 'icon': m.get('icon', ''),
                   'summary': m.get('summary'), 'workflows': m.get('workflows') or []},
        'siblings': [_brief(registry.effective(screens[k], None), modules)
                     for k in m.get('screens', []) if k != key],
        'related': [_brief(screens[k], modules) for k in s.get('related', []) if k in screens],
        'updated': _updated(s, override),
        'can_edit': can_edit,
        'override': None,
    }
    if override is not None:
        payload['override'] = {
            'updated_at': override.updated_at,
            'updated_by': getattr(getattr(override.updated_by, 'user', None), 'get_full_name', lambda: '')()
                          or getattr(getattr(override.updated_by, 'user', None), 'username', ''),
            'base_changed': override.base_hash != registry.base_hash(s),
        }
    if can_edit:
        payload['base'] = {f: s.get(f) for f in registry.EDITABLE_FIELDS}
    return payload


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def screen_detail(request, key):
    modules, screens = registry.load()
    s = screens.get(key)
    if s is None:
        return Response({'detail': 'not found'}, status=404)
    override = HelpOverride.objects.filter(screen_key=key).select_related('updated_by__user').first()

    if request.method == 'GET':
        if request.query_params.get('log') != '0':
            _log(HelpEvent.KIND_OPEN, request, key, request.query_params.get('tab', ''))
        return Response(_screen_payload(request, key, s, modules, screens, override))

    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'ليس لديك صلاحية تعديل الشرح'}, status=403)
    before = {f: registry.effective(s, override).get(f) for f in registry.EDITABLE_FIELDS}

    if request.method == 'DELETE':
        if override is None:
            return Response({'detail': 'لا يوجد تعديل للرجوع عنه'}, status=400)
        override.delete()
        HelpRevision.objects.create(
            screen_key=key, action=HelpRevision.ACTION_REVERT, before=before,
            after={f: s.get(f) for f in registry.EDITABLE_FIELDS},
            note=(request.data or {}).get('note', '')[:300] if isinstance(request.data, dict) else '',
            staff=profile)
        return Response(_screen_payload(request, key, s, modules, screens, None))

    data = request.data.get('data')
    errors = _validate_edit(data)
    if errors:
        return Response({'detail': 'محتوى غير صالح', 'errors': errors}, status=400)
    clean = {f: data[f] for f in registry.EDITABLE_FIELDS if f in data}
    if override is None:
        override = HelpOverride(screen_key=key)
    override.data = clean
    override.base_hash = registry.base_hash(s)
    override.updated_by = profile
    override.save()
    HelpRevision.objects.create(
        screen_key=key, action=HelpRevision.ACTION_SAVE, before=before,
        after={f: registry.effective(s, override).get(f) for f in registry.EDITABLE_FIELDS},
        note=str(request.data.get('note', ''))[:300], staff=profile)
    return Response(_screen_payload(request, key, s, modules, screens, override))


def _is_t(v, required=True):
    if not isinstance(v, dict) or set(v) - {'ar', 'en'}:
        return False
    if not all(isinstance(v.get(l, ''), str) for l in ('ar', 'en')):
        return False
    return bool((v.get('ar') or '').strip()) if required else True


def _validate_edit(data):
    """Trainers edit the same structure the repo uses; reject anything else so a bad
    save can never break the panel for everyone."""
    if not isinstance(data, dict):
        return ['data must be an object']
    errors = []
    for f in ('title', 'summary'):
        if f in data and not _is_t(data[f]):
            errors.append(f'{f}: النص العربي مطلوب')
    for f in ('audience', 'notes'):
        if f in data and data[f] is not None and not _is_t(data[f], required=False):
            errors.append(f'{f}: صيغة غير صالحة')
    for f in ('steps', 'tips'):
        if f in data:
            items = data[f]
            if not isinstance(items, list):
                errors.append(f'{f}: يجب أن تكون قائمة')
                continue
            for i, it in enumerate(items):
                text = it.get('text') if isinstance(it, dict) and 'text' in it else it
                if not _is_t(text):
                    errors.append(f'{f}[{i}]: النص العربي مطلوب')
    if 'tabs' in data:
        if not isinstance(data['tabs'], list):
            errors.append('tabs: يجب أن تكون قائمة')
        else:
            for i, t in enumerate(data['tabs']):
                if not isinstance(t, dict) or not isinstance(t.get('key'), str) \
                        or not _is_t(t.get('title')) or not _is_t(t.get('body')):
                    errors.append(f'tabs[{i}]: العنوان والشرح مطلوبان')
    if 'faq' in data:
        if not isinstance(data['faq'], list):
            errors.append('faq: يجب أن تكون قائمة')
        else:
            for i, qa in enumerate(data['faq']):
                if not isinstance(qa, dict) or not _is_t(qa.get('q')) or not _is_t(qa.get('a')):
                    errors.append(f'faq[{i}]: السؤال والإجابة مطلوبان')
    return errors


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def screen_revisions(request, key):
    if not _can_edit(_profile(request)):
        return Response({'detail': 'forbidden'}, status=403)
    rows = HelpRevision.objects.filter(screen_key=key).select_related('staff__user')[:50]
    return Response([{
        'id': r.id, 'action': r.action, 'note': r.note, 'created_at': r.created_at,
        'staff': (r.staff.user.get_full_name() or r.staff.user.username) if r.staff_id else '',
        'before': r.before, 'after': r.after,
    } for r in rows])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search(request):
    q = (request.query_params.get('q') or '').strip()[:200]
    if not q:
        return Response([])
    modules, screens = registry.load()
    ov = _overrides()
    eff = [registry.effective(s, ov.get(k)) for k, s in screens.items()]
    hits = registry.search(q, eff, modules)
    if request.query_params.get('log') != '0':
        _log(HelpEvent.KIND_SEARCH, request, query=q, results=len(hits))
    return Response([{**_brief(s, modules), 'routes': s['routes']} for s in hits])


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def feedback(request):
    profile = _profile(request)
    if request.method == 'POST':
        _, screens = registry.load()
        key = str(request.data.get('screen_key', ''))
        if key not in screens:
            return Response({'detail': 'unknown screen'}, status=400)
        helpful = request.data.get('helpful')
        if not isinstance(helpful, bool):
            return Response({'detail': 'helpful must be true/false'}, status=400)
        fb = HelpFeedback.objects.create(
            screen_key=key, tab=str(request.data.get('tab', ''))[:60], helpful=helpful,
            comment=str(request.data.get('comment', ''))[:500],
            lang='en' if request.data.get('lang') == 'en' else 'ar',
            staff=profile, role=getattr(profile, 'role', '') or '')
        return Response({'id': fb.id}, status=status.HTTP_201_CREATED)

    # GET — trainers' review list
    if not _can_edit(profile):
        return Response({'detail': 'forbidden'}, status=403)
    qs = HelpFeedback.objects.select_related('staff__user')
    if request.query_params.get('open') == '1':
        qs = qs.filter(resolved=False).exclude(comment='')
    return Response([{
        'id': f.id, 'screen_key': f.screen_key, 'tab': f.tab, 'helpful': f.helpful,
        'comment': f.comment, 'lang': f.lang, 'role': f.role, 'resolved': f.resolved,
        'created_at': f.created_at,
        'staff': (f.staff.user.get_full_name() or f.staff.user.username) if f.staff_id else '',
    } for f in qs[:200]])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def feedback_resolve(request, pk):
    if not _can_edit(_profile(request)):
        return Response({'detail': 'forbidden'}, status=403)
    n = HelpFeedback.objects.filter(pk=pk).update(resolved=bool(request.data.get('resolved', True)))
    return Response({'updated': n})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stats(request):
    """Trainers' dashboard: which screens people open help on most, how helpful it
    is, and what they search for without finding."""
    if not _can_edit(_profile(request)):
        return Response({'detail': 'forbidden'}, status=403)
    try:
        days = max(1, min(int(request.query_params.get('days', 30)), 365))
    except ValueError:
        days = 30
    since = timezone.now() - timezone.timedelta(days=days)
    opens = (HelpEvent.objects.filter(kind=HelpEvent.KIND_OPEN, created_at__gte=since)
             .values('screen_key').annotate(n=Count('id')).order_by('-n')[:30])
    by_role = (HelpEvent.objects.filter(kind=HelpEvent.KIND_OPEN, created_at__gte=since)
               .values('role').annotate(n=Count('id')).order_by('-n'))
    votes = (HelpFeedback.objects.filter(created_at__gte=since).values('screen_key')
             .annotate(up=Count('id', filter=Q(helpful=True)), down=Count('id', filter=Q(helpful=False)))
             .order_by('-down')[:30])
    searches = (HelpEvent.objects.filter(kind=HelpEvent.KIND_SEARCH, created_at__gte=since)
                .values('query').annotate(n=Count('id'), misses=Count('id', filter=Q(results=0)))
                .order_by('-n')[:30])
    _, screens = registry.load()
    title = {k: s['title'] for k, s in screens.items()}
    return Response({
        'days': days,
        'opens': [{**o, 'title': title.get(o['screen_key'])} for o in opens],
        'by_role': list(by_role),
        'votes': [{**v, 'title': title.get(v['screen_key'])} for v in votes],
        'searches': list(searches),
        'overrides': HelpOverride.objects.count(),
        'open_comments': HelpFeedback.objects.filter(resolved=False).exclude(comment='').count(),
    })
