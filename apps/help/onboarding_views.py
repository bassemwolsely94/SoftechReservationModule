"""
apps/help/onboarding_views.py — role onboarding (checklist + module quizzes).

  GET  /api/help/onboarding/                 my path: screens to learn (todo/done/changed),
                                              module quizzes with my best score, progress %
  POST /api/help/onboarding/learned/         {screen_key, done}  «فهمت هذه الشاشة» on/off
  GET  /api/help/onboarding/team/            trainers (help/edit): completion per staff member
  GET  /api/help/quizzes/<module>/           questions; options shuffled, NO answers
  POST /api/help/quizzes/<module>/submit/    {answers: [option id | null]} → graded here

Paths and quizzes come from training.py (the repo's
content/onboarding.py, or a trainer's saved version). Grading is deterministic and done
only on the server; answers + explanations are returned after submitting.
"""
import random

from django.db.models import Max
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.models import ROLE_CHOICES, StaffProfile

from . import registry, training
from .models import HelpLearned, HelpOverride, HelpQuizAttempt, HelpRevision, HelpTrainingOverride
from .views import _can_edit, _profile, _routed_steps, _staff_name, _updated

ROLES = [r for r, _ in ROLE_CHOICES]




def _versions():
    """screen_key → current help date (repo date or the trainer's later save)."""
    _, screens = registry.load()
    ov = {o.screen_key: o for o in HelpOverride.objects.all()}
    return {k: _updated(s, ov.get(k)) for k, s in screens.items()}


def _state(learned_version, current):
    if learned_version is None:
        return 'todo'
    return 'changed' if current and learned_version < current else 'done'


def _progress(keys, learned, versions, mods, best):
    done = sum(1 for k in keys if _state(learned.get(k), versions.get(k)) == 'done')
    passed = sum(1 for m in mods if best.get(m, {}).get('passed'))
    total = len(keys) + len(mods)
    return {
        'learned': done, 'screens': len(keys),
        'quizzes_passed': passed, 'quizzes': len(mods),
        'percent': round(100 * (done + passed) / total) if total else 100,
    }


def _best(staff_ids, qz):
    """{staff_id: {module: {score, total, passed, stale, at}}} — best attempt per module
    on the CURRENT version of its quiz. A pass on an older version (the quiz changed
    since) is reported as stale and does not count: it has to be retaken."""
    current = {m: training.quiz_version(q) for m, q in qz.items()}
    out, stale = {}, {}
    for a in HelpQuizAttempt.objects.filter(staff_id__in=staff_ids).order_by('created_at'):
        mine = {'score': a.score, 'total': a.total, 'passed': a.passed, 'stale': False, 'at': a.created_at}
        if a.version != current.get(a.module_key):
            if a.passed:
                stale.setdefault(a.staff_id, {})[a.module_key] = {**mine, 'passed': False, 'stale': True}
            continue
        cur = out.setdefault(a.staff_id, {}).get(a.module_key)
        if cur is None or (a.passed, a.score) >= (cur['passed'], cur['score']):
            out[a.staff_id][a.module_key] = mine
    for sid, mods in stale.items():
        for m, v in mods.items():
            out.setdefault(sid, {}).setdefault(m, v)
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_path(request):
    profile = _profile(request)
    if profile is None:
        return Response({'detail': 'no staff profile'}, status=400)
    role = profile.role
    # trainers may preview another role's path (read-only; progress stays their own)
    asked = request.query_params.get('role')
    if asked and asked != role and _can_edit(profile) and asked in ROLES:
        role = asked
    keys = training.path(role)
    qz = training.quizzes()
    modules, screens = registry.load()
    ov = {o.screen_key: o for o in HelpOverride.objects.filter(screen_key__in=keys)}
    versions = _versions()
    learned = dict(HelpLearned.objects.filter(staff=profile).values_list('screen_key', 'version'))
    mods = training.path_modules(keys, qz)
    best = _best([profile.id], qz).get(profile.id, {})
    items = []
    for k in keys:
        s = registry.effective(screens[k], ov.get(k))
        m = modules.get(s['module'], {})
        items.append({
            'key': k, 'module': s['module'], 'module_title': m.get('title'), 'icon': m.get('icon', ''),
            'title': s['title'], 'summary': s['summary'], 'routes': s['routes'],
            'updated': versions.get(k), 'state': _state(learned.get(k), versions.get(k)),
        })
    return Response({
        'role': role,
        'roles': ROLES if _can_edit(profile) else [profile.role],
        'pass_percent': training.PASS_PERCENT,
        'path': items,
        'quizzes': [{
            'module': mk, 'title': modules.get(mk, {}).get('title'), 'icon': modules.get(mk, {}).get('icon', ''),
            'questions': len(qz[mk]), 'best': best.get(mk),
        } for mk in mods],
        'progress': _progress(keys, learned, versions, mods, best),
        # every screen I ticked (also outside my path), so the «فهمت» button knows its state
        'learned': {k: _state(v, versions.get(k)) for k, v in learned.items()},
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_tour(request):
    """«🗺️ جولة في موديولات دورك» for the caller's role (?shell=desktop|mobile); trainers may
    preview another role (?role=). 404 when the role's path has nothing on that shell."""
    profile = _profile(request)
    if profile is None:
        return Response({'detail': 'no staff profile'}, status=400)
    shell = request.query_params.get('shell', 'desktop')
    if shell not in training.PRODUCT_SHELLS:
        return Response({'detail': 'unknown shell'}, status=400)
    role = profile.role
    asked = request.query_params.get('role')
    if asked and asked != role and _can_edit(profile) and asked in ROLES:
        role = asked
    j = training.product_tour(role, shell)
    if j is None:
        return Response({'detail': 'no tour for this role'}, status=404)
    _, screens = registry.load()
    return Response({**j, 'steps': _routed_steps(j, j['steps'], screens)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_learned(request):
    profile = _profile(request)
    if profile is None:
        return Response({'detail': 'no staff profile'}, status=400)
    key = str(request.data.get('screen_key', ''))
    _, screens = registry.load()
    if key not in screens:
        return Response({'detail': 'unknown screen'}, status=400)
    if request.data.get('done', True) is False:
        HelpLearned.objects.filter(staff=profile, screen_key=key).delete()
        return Response({'screen_key': key, 'state': 'todo'})
    version = _versions().get(key, '')
    HelpLearned.objects.update_or_create(staff=profile, screen_key=key, defaults={'version': version})
    return Response({'screen_key': key, 'state': 'done', 'version': version})


def _shuffled(staff_id, module_key, qi, n):
    """Stable per person + question, so a reload shows the same order."""
    order = list(range(n))
    random.Random(f'{staff_id}:{module_key}:{qi}').shuffle(order)
    return order


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quiz(request, module_key):
    profile = _profile(request)
    qs = training.quiz(module_key)
    if qs is None or profile is None:
        return Response({'detail': 'not found'}, status=404)
    modules, _ = registry.load()
    best = _best([profile.id], training.quizzes()).get(profile.id, {}).get(module_key)
    return Response({
        'module': module_key, 'title': modules.get(module_key, {}).get('title'),
        'pass_percent': training.PASS_PERCENT, 'best': best,
        'questions': [{
            'q': q['q'],
            'options': [{'id': i, 'text': q['options'][i]}
                        for i in _shuffled(profile.id, module_key, qi, len(q['options']))],
        } for qi, q in enumerate(qs)],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quiz_submit(request, module_key):
    profile = _profile(request)
    qs = training.quiz(module_key)
    if qs is None or profile is None:
        return Response({'detail': 'not found'}, status=404)
    answers = request.data.get('answers')
    if not isinstance(answers, list) or len(answers) != len(qs):
        return Response({'detail': f'answers must be a list of {len(qs)}'}, status=400)
    clean, results = [], []
    for q, a in zip(qs, answers):
        a = a if isinstance(a, int) and not isinstance(a, bool) and 0 <= a < len(q['options']) else None
        clean.append(a)
        results.append({'chosen': a, 'answer': q['answer'], 'correct': a == q['answer'], 'explain': q['explain']})
    score = sum(r['correct'] for r in results)
    total = len(qs)
    percent = round(100 * score / total)
    passed = percent >= training.PASS_PERCENT
    HelpQuizAttempt.objects.create(staff=profile, module_key=module_key, score=score, total=total,
                                   passed=passed, answers=clean, version=training.quiz_version(qs))
    return Response({'score': score, 'total': total, 'percent': percent, 'passed': passed,
                     'pass_percent': training.PASS_PERCENT, 'results': results},
                    status=status.HTTP_201_CREATED)


STUCK_DAYS = 7          # no training activity for this long (and path not done) = stuck
REMIND_COOLDOWN_DAYS = 3


def is_stuck(row, now=None):
    """Shared by the trainers' team view, «تذكير» and the weekly digest."""
    now = now or timezone.now()
    before = now - timezone.timedelta(days=STUCK_DAYS)
    return row['progress']['percent'] < 100 and (row['last_activity'] or row['joined']) < before


def team_rows(staff_qs, limit=500):
    """Training progress per person (shared by the trainers' team view and the
    weekly digest): progress, failed quizzes, quizzes to retake, last activity."""
    staff = list(staff_qs.select_related('user', 'branch').order_by('role', 'user__first_name')[:limit])
    ids = [p.id for p in staff]
    versions = _versions()
    learned = {}
    for sid, key, ver in HelpLearned.objects.filter(staff_id__in=ids).values_list('staff_id', 'screen_key', 'version'):
        learned.setdefault(sid, {})[key] = ver
    last = dict(HelpLearned.objects.filter(staff_id__in=ids).values('staff_id')
                .annotate(t=Max('created_at')).values_list('staff_id', 't'))
    path_ov = training.overrides('path')
    qz = training.quizzes()
    best = _best(ids, qz)
    rows = []
    for p in staff:
        keys = training.path(p.role, path_ov)
        mods = training.path_modules(keys, qz)
        mine = best.get(p.id, {})
        at = [v['at'] for v in mine.values()] + ([last[p.id]] if p.id in last else [])
        rows.append({
            'id': p.id, 'name': _staff_name(p), 'role': p.role,
            'branch': p.branch_name,
            'progress': _progress(keys, learned.get(p.id, {}), versions, mods, mine),
            'failed_quizzes': [m for m, v in mine.items() if not v['passed'] and not v['stale']],
            'retake_quizzes': [m for m, v in mine.items() if v['stale']],
            'last_activity': max(at) if at else None,
            'joined': p.user.date_joined,
        })
    from .models import HelpReminder
    reminded = dict(HelpReminder.objects.filter(staff_id__in=ids).values('staff_id')
                    .annotate(t=Max('created_at')).values_list('staff_id', 't'))
    now = timezone.now()
    for r in rows:
        r['stuck'] = is_stuck(r, now)
        r['last_reminded_at'] = reminded.get(r['id'])
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team(request):
    """Trainers / supervisors: everyone's onboarding completion. Branch-bound trainers
    see only the branches they can access."""
    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'forbidden'}, status=403)
    staff = StaffProfile.objects.filter(is_active=True, user__is_active=True)
    allowed = profile.accessible_branch_ids
    if allowed is not None:
        staff = staff.filter(branch_id__in=allowed)
    if request.query_params.get('role'):
        staff = staff.filter(role=request.query_params['role'])
    if request.query_params.get('branch'):
        staff = staff.filter(branch_id=request.query_params['branch'])
    return Response(team_rows(staff))


# ── trainers: edit paths / quizzes (help/edit) ────────────────────────────────

def _training_payload(kind, key, override):
    if kind == 'flow':
        base = training.base_flow(key)
        current = training.merge_flow(base, override.data if override else None)
    elif kind == 'path':
        base = training.base_path(key)
        current = base if override is None else override.data.get('screens', [])
    else:
        base = training.base_quiz(key)
        current = base if override is None else override.data.get('questions', [])
    revs = HelpRevision.objects.filter(screen_key=f'{kind}:{key}').select_related('staff__user')[:20]
    return {
        'kind': kind, 'key': key, 'current': current, 'base': base,
        'override': None if override is None else {
            'updated_at': override.updated_at, 'updated_by': _staff_name(override.updated_by),
            'base_changed': override.base_hash != training.base_hash(kind, key),
        },
        'revisions': [{'id': r.id, 'action': r.action, 'note': r.note, 'public_note': r.public_note,
                       'created_at': r.created_at,
                       'staff': _staff_name(r.staff)} for r in revs],
    }


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def training_edit(request, kind, key):
    """GET the path/quiz as trainers edit it (quiz answers included), PUT {data, note}
    to save a trainer version, DELETE {note} to go back to the repo version."""
    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'ليس لديك صلاحية تعديل التدريب'}, status=403)
    modules, _ = registry.load()
    if (kind == 'path' and key not in ROLES) or (kind == 'quiz' and key not in modules) \
            or (kind == 'flow' and training.base_flow(key) is None) or kind not in ('path', 'quiz', 'flow'):
        return Response({'detail': 'not found'}, status=404)
    override = HelpTrainingOverride.objects.filter(kind=kind, key=key).select_related('updated_by__user').first()
    if request.method == 'GET':
        return Response(_training_payload(kind, key, override))

    body = request.data if isinstance(request.data, dict) else {}
    note = str(body.get('note', '') or '')[:300]
    # one line for the people affected (notification / workflow-tour card); saves only
    public = ' '.join(str(body.get('public_note', '') or '').split())[:120] if request.method == 'PUT' else ''
    if kind == 'flow':
        return _flow_edit(request, key, override, profile, note, public)
    field = 'screens' if kind == 'path' else 'questions'
    before = {field: override.data.get(field) if override else
              (training.base_path(key) if kind == 'path' else training.base_quiz(key))}
    if request.method == 'DELETE':
        if override is None:
            return Response({'detail': 'لا يوجد تعديل للرجوع عنه'}, status=400)
        override.delete()
        base = training.base_path(key) if kind == 'path' else training.base_quiz(key)
        rev = HelpRevision.objects.create(screen_key=f'{kind}:{key}', action=HelpRevision.ACTION_REVERT,
                                          before=before, after={field: base}, note=note, staff=profile)
        return Response({**_training_payload(kind, key, None),
                         'notified': _announce(kind, key, before[field], base, rev.id)})

    data = request.data.get('data')
    errors = training.validate_path(data) if kind == 'path' else training.validate_quiz(data)
    if errors:
        return Response({'detail': 'محتوى غير صالح', 'errors': errors}, status=400)
    clean = training.clean_path(data) if kind == 'path' else training.clean_quiz(data)
    if override is None:
        override = HelpTrainingOverride(kind=kind, key=key)
    override.data = clean
    override.base_hash = training.base_hash(kind, key)
    override.updated_by = profile
    override.save()
    rev = HelpRevision.objects.create(screen_key=f'{kind}:{key}', action=HelpRevision.ACTION_SAVE,
                                      before=before, after=clean, note=note, public_note=public, staff=profile)
    return Response({**_training_payload(kind, key, override),
                     'notified': _announce(kind, key, before[field], clean[field], rev.id, public)})


def _announce(kind, key, before, after, revision_id, note=''):
    """Tell the people affected (see notify.py), then record the new state as
    announced so the hourly check does not tell them again. → number notified."""
    from . import notify
    if kind == 'path':
        n = notify.path_changed(key, before or [], after or [], revision_id, note)
    elif not after:          # quiz removed — nothing to retake
        n = 0
    else:
        n = notify.quiz_changed(key, training.quiz_version(before or []),
                                training.quiz_version(after), revision_id, note)
    training.record_snapshot(kind, key)
    return n


def _flow_edit(request, key, override, profile, note, public=''):
    """Workflow-tour text: title, summary, each step's text (steps fixed by the code).
    Same history as screen help (HelpRevision 'flow:<module>.<key>'); no notification —
    the one-line `public` note shows on the tour's card instead (training.flow_notes)."""
    base = training.base_flow(key)
    before = training.merge_flow(base, override.data if override else None)
    if request.method == 'DELETE':
        if override is None:
            return Response({'detail': 'لا يوجد تعديل للرجوع عنه'}, status=400)
        override.delete()
        HelpRevision.objects.create(screen_key=f'flow:{key}', action=HelpRevision.ACTION_REVERT,
                                    before=before, after=base, note=note, staff=profile)
        return Response(_training_payload('flow', key, None))
    data = request.data.get('data')
    errors = training.validate_flow(data, base)
    if errors:
        return Response({'detail': 'محتوى غير صالح', 'errors': errors}, status=400)
    clean = training.clean_flow(data)
    if override is None:
        override = HelpTrainingOverride(kind='flow', key=key)
    override.data = clean
    override.base_hash = training.base_hash('flow', key)
    override.updated_by = profile
    override.save()
    HelpRevision.objects.create(screen_key=f'flow:{key}', action=HelpRevision.ACTION_SAVE,
                                before=before, after=training.merge_flow(base, clean), note=note,
                                public_note=public, staff=profile)
    return Response(_training_payload('flow', key, override))


# ── «أول يوم» — first-day cards on the home page ─────────────────────────────

def _done_tours(profile):
    """Tour ids (screen keys / flow ids) this person finished at least once."""
    from .models import HelpEvent
    return set(HelpEvent.objects.filter(kind=HelpEvent.KIND_TOUR, staff=profile, query='done')
               .values_list('screen_key', flat=True).distinct())


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def first_day(request):
    """GET  → the cards: system tour, my role's module tour, my training path (+ the next screen), my role's
              workflow tours, the next quiz; `show` = path not finished and not hidden.
       POST {hidden: bool} → hide / show the cards (stored per person)."""
    from .models import HelpPreference
    profile = _profile(request)
    if profile is None:
        return Response({'detail': 'no staff profile'}, status=400)
    pref, _ = HelpPreference.objects.get_or_create(staff=profile)
    if request.method == 'POST':
        pref.first_day_hidden_at = timezone.now() if request.data.get('hidden', True) else None
        pref.save(update_fields=['first_day_hidden_at', 'updated_at'])
        return Response({'hidden': bool(pref.first_day_hidden_at)})

    mobile = request.query_params.get('mobile') == '1'
    role = profile.role
    keys = training.path(role)
    qz = training.quizzes()
    modules, screens = registry.load()
    versions = _versions()
    learned = dict(HelpLearned.objects.filter(staff=profile).values_list('screen_key', 'version'))
    mods = training.path_modules(keys, qz)
    best = _best([profile.id], qz).get(profile.id, {})
    progress = _progress(keys, learned, versions, mods, best)
    done = _done_tours(profile)
    nxt = next((k for k in keys if _state(learned.get(k), versions.get(k)) != 'done'), None)
    flows = training.flows_effective(modules)
    system = flows.get('flow:general.system')
    mine = [training.flow_brief(fid, f) for fid, f in flows.items()
            if fid != 'flow:general.system' and bool(f.get('mobile')) == mobile
            and (not f.get('roles') or role in f['roles'])]
    quiz = next((m for m in mods if not best.get(m, {}).get('passed')), None)
    # «🗺️ جولة في موديولات دورك» — one stop per module of this role's path (training.product_tour)
    pt = training.product_tour(role, 'mobile' if mobile else 'desktop', keys)

    def screen_card(k):
        s = screens[k]
        return {'key': k, 'title': s['title'], 'summary': s['summary'], 'routes': s['routes'],
                'module_title': modules[s['module']]['title'], 'icon': modules[s['module']].get('icon', ''),
                'has_tour': bool(s.get('tour'))}

    return Response({
        'show': progress['percent'] < 100 and pref.first_day_hidden_at is None,
        'hidden': pref.first_day_hidden_at is not None,
        'role': role,
        'progress': progress,
        'system_tour': (None if mobile or not system else
                        {**training.flow_brief('flow:general.system', system),
                         'done': 'flow:general.system' in done}),
        'module_tour': None if not pt else {'id': pt['id'], 'title': pt['title'], 'summary': pt['summary'],
                                            'stops': len(pt['steps']) - 2,
                                            'done': f"journey:{pt['id']}" in done},
        'next_screen': screen_card(nxt) if nxt else None,
        'flows': [{**f, 'done': f['id'] in done} for f in mine[:4]],
        'quiz': None if not quiz else {'module': quiz, 'title': modules[quiz]['title'],
                                       'icon': modules[quiz].get('icon', ''), 'questions': len(qz[quiz])},
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remind(request):
    """POST {staff_ids: [..]} — a supervisor's gentle «تذكير» to people stuck on their
    training path. help/edit only; only people in the branches the supervisor can see;
    one reminder per person every REMIND_COOLDOWN_DAYS days; each one recorded
    (HelpReminder) and delivered through apps.notifications. Re-shows the person's
    «ابدأ من هنا» cards if they had hidden them."""
    from .models import HelpPreference, HelpReminder
    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'ليس لديك صلاحية إرسال تذكير'}, status=403)
    ids = request.data.get('staff_ids')
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids) or len(ids) > 200:
        return Response({'detail': 'staff_ids: قائمة أرقام مطلوبة'}, status=400)
    staff = StaffProfile.objects.filter(pk__in=ids, is_active=True, user__is_active=True)
    allowed = profile.accessible_branch_ids
    if allowed is not None:
        staff = staff.filter(branch_id__in=allowed)
    rows = {r['id']: r for r in team_rows(staff, limit=200)}
    since = timezone.now() - timezone.timedelta(days=REMIND_COOLDOWN_DAYS)
    recent = set(HelpReminder.objects.filter(staff_id__in=rows, created_at__gte=since)
                 .values_list('staff_id', flat=True))
    sender = _staff_name(profile)
    result = {'sent': [], 'skipped': []}
    for sid in ids:
        r = rows.get(sid)
        if r is None:
            result['skipped'].append({'id': sid, 'reason': 'خارج فروعك أو غير نشط'})
            continue
        if r['progress']['percent'] >= 100:
            result['skipped'].append({'id': sid, 'reason': 'خلّص التدريب'})
            continue
        if sid in recent:
            result['skipped'].append({'id': sid, 'reason': f'اتبعتله تذكير في آخر {REMIND_COOLDOWN_DAYS} أيام'})
            continue
        p = r['progress']
        left = []
        if p['screens'] - p['learned']:
            left.append(f"{p['screens'] - p['learned']} شاشة")
        if p['quizzes'] - p['quizzes_passed']:
            left.append(f"{p['quizzes'] - p['quizzes_passed']} اختبار")
        body = (f'👋 {sender} بيفكّرك تكمّل مسارك التدريبي — وصلت {p["percent"]}%'
                + (f'، وفاضلك {" و".join(left)}' if left else '') + '. '
                'ابدأ من «الرئيسية» ← «ابدأ من هنا»، أو «دليل الاستخدام» ← «مساري التدريبي». '
                'كل خطوة قصيرة، وتقدر تكمّل وقت ما يناسبك.')
        target = StaffProfile.objects.get(pk=sid)
        try:
            from apps.notifications.models import Notification
            Notification.send_to_user(target, 'system', '🎓 تذكير بالتدريب', body,
                                      dedup_key=f'help_remind_{sid}_{timezone.localdate().isoformat()}',
                                      bypass_role_gate=True)
        except Exception as exc:
            result['skipped'].append({'id': sid, 'reason': f'تعذّر الإرسال: {exc}'})
            continue
        HelpReminder.objects.create(staff=target, sent_by=profile, percent=p['percent'])
        HelpPreference.objects.filter(staff=target).update(first_day_hidden_at=None)
        result['sent'].append(sid)
    return Response(result)


# ── «الجديد في الشرح» — home card ────────────────────────────────────────────

WHATS_NEW_DAYS = 7


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def whats_new(request):
    """GET  → screens whose help (text or tour) changed in the last WHATS_NEW_DAYS days
              that matter to this person — on their role's training path, or whose help
              they opened in the last 90 days — each with `read` (opened the help after the
              change, or dismissed). `unread` = how many are not read.
       POST → «تمام، شفتها»: everything changed until now counts as read."""
    from .models import HelpEvent, HelpPreference
    profile = _profile(request)
    if profile is None:
        return Response({'detail': 'no staff profile'}, status=400)
    pref, _ = HelpPreference.objects.get_or_create(staff=profile)
    now = timezone.now()
    if request.method == 'POST':
        pref.whats_new_seen_at = now
        pref.save(update_fields=['whats_new_seen_at', 'updated_at'])
        return Response({'unread': 0})

    modules, screens = registry.load()
    versions = _versions()
    from .views import change_notes
    notes = change_notes(screens, {o.screen_key: o for o in HelpOverride.objects.all()})
    since = (timezone.localdate() - timezone.timedelta(days=WHATS_NEW_DAYS)).isoformat()
    # only changes after the person joined — for a newcomer everything is "new", and the
    # «ابدأ من هنا» cards already cover that (also avoids a flood at go-live)
    joined = timezone.localtime(profile.user.date_joined).date().isoformat()
    opened = {}
    for key, at in (HelpEvent.objects.filter(kind=HelpEvent.KIND_OPEN, staff=profile,
                                             created_at__gte=now - timezone.timedelta(days=90))
                    .values_list('screen_key', 'created_at')):
        opened[key] = max(opened.get(key, at), at)
    mine = set(training.path(profile.role)) | set(opened)
    seen_day = timezone.localtime(pref.whats_new_seen_at).date().isoformat() if pref.whats_new_seen_at else ''
    items = []
    for k in mine:
        v = versions.get(k) or ''
        if k not in screens or v < since or v <= joined:
            continue
        read_day = timezone.localtime(opened[k]).date().isoformat() if k in opened else ''
        s = screens[k]
        m = modules[s['module']]
        items.append({
            'key': k, 'title': s['title'], 'module_title': m['title'], 'icon': m.get('icon', ''),
            'routes': s['routes'], 'updated': v, 'has_tour': bool(s.get('tour')),
            'change_note': notes.get(k),
            'read': bool((read_day and read_day >= v) or (seen_day and seen_day >= v)),
        })
    items.sort(key=lambda x: (x['read'], -int(x['updated'].replace('-', ''))))   # unread first, newest first
    return Response({'days': WHATS_NEW_DAYS, 'items': items[:20],
                     'unread': sum(1 for x in items if not x['read'])})


# ── «إيه الجديد» log — every one-line note of the last N days, for trainers ──

NOTES_LOG_DAYS = 30
ROLE_AR = {'pharmacist': 'الصيدلي', 'salesperson': 'البائع', 'call_center': 'الكول سنتر',
           'purchasing': 'المشتريات', 'delivery': 'الطيار / التوصيل', 'supervisor': 'المشرف',
           'quality_manager': 'مدير الجودة', 'viewer': 'مشاهد', 'admin': 'مدير النظام'}


def recent_notes(days=NOTES_LOG_DAYS, now=None):
    """→ newest first: the «what changed» one-liners of the last `days` days — trainers'
    saves of screen help, paths, quizzes and workflow tours (HelpRevision.public_note) and
    the developers' repo `change_note` on screens updated in that window. Each row:
      kind   screen | path | quiz | flow       source  trainer | repo
      state  shown     — people still see it («الجديد» / home card / tour card)
             sent      — went out inside the path / quiz notification
             replaced  — a later change replaced it (or a flow note older than 14 days)"""
    from .views import change_notes
    now = now or timezone.now()
    since = now - timezone.timedelta(days=days)
    modules, screens = registry.load()
    flows = training.flows_effective(modules)
    current = change_notes(screens, {o.screen_key: o for o in HelpOverride.objects.all()})
    flow_now = training.flow_notes()
    latest = {}
    for sk, rid in (HelpRevision.objects.filter(created_at__gte=since)
                    .order_by('screen_key', '-created_at', '-id').values_list('screen_key', 'id')):
        latest.setdefault(sk, rid)

    def title(kind, key):
        if kind == 'path':
            return {'ar': f'مسار {ROLE_AR.get(key, key)}', 'en': f'{key} path'}
        if kind == 'quiz':
            t = modules.get(key, {}).get('title') or {'ar': key, 'en': key}
            return {'ar': f'اختبار {t["ar"]}', 'en': f'{t["en"]} quiz'}
        if kind == 'flow':
            return (flows.get(f'flow:{key}') or {}).get('title') or {'ar': key, 'en': key}
        return (screens.get(key) or {}).get('title') or {'ar': key, 'en': key}

    rows = []
    for r in (HelpRevision.objects.filter(action=HelpRevision.ACTION_SAVE, created_at__gte=since)
              .exclude(public_note='').select_related('staff__user').order_by('-created_at', '-id')[:300]):
        kind, _, key = r.screen_key.partition(':')
        if kind not in ('path', 'quiz', 'flow'):
            kind, key = 'screen', r.screen_key
        if kind == 'screen' and key not in screens or kind == 'flow' and f'flow:{key}' not in flows:
            continue
        if kind in ('path', 'quiz'):
            state = 'sent'
        elif latest.get(r.screen_key) != r.id:
            state = 'replaced'
        elif kind == 'flow':
            state = 'shown' if r.screen_key in flow_now else 'replaced'
        else:
            state = 'shown' if (current.get(key) or {}).get('ar') == r.public_note else 'replaced'
        rows.append({'kind': kind, 'key': key, 'title': title(kind, key), 'note': r.public_note,
                     'source': 'trainer', 'staff': _staff_name(r.staff), 'at': r.created_at.isoformat(),
                     'state': state})
    since_day = timezone.localtime(since).date().isoformat()
    for k, s in screens.items():
        cn = s.get('change_note')
        if cn and (s.get('updated') or '') >= since_day:
            rows.append({'kind': 'screen', 'key': k, 'title': s['title'], 'note': cn['ar'], 'note_en': cn.get('en'),
                         'source': 'repo', 'staff': None, 'at': s['updated'],
                         'state': 'shown' if current.get(k) == cn else 'replaced'})
    rows.sort(key=lambda x: x['at'], reverse=True)
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notes_log(request):
    """Trainers (help/edit): GET ?days=30 (1–90) → {'days', 'items': recent_notes()}."""
    if not _can_edit(_profile(request)):
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    try:
        days = min(max(int(request.query_params.get('days', NOTES_LOG_DAYS)), 1), 90)
    except ValueError:
        days = NOTES_LOG_DAYS
    return Response({'days': days, 'items': recent_notes(days)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notes_check(request):
    """Trainers: POST {kind: screen|path|quiz|flow, key, note, data} → {'hints': [...]}
    (notecheck.py) for the note being typed against the draft being edited. Read-only."""
    from . import notecheck
    from .views import _overrides
    if not _can_edit(_profile(request)):
        return Response({'detail': 'ليس لديك صلاحية'}, status=403)
    body = request.data if isinstance(request.data, dict) else {}
    kind, key, data = body.get('kind'), str(body.get('key') or ''), body.get('data')
    modules, screens = registry.load()
    if kind == 'screen' and key in screens:
        current = registry.effective(screens[key], _overrides().get(key))
        before = {f: current.get(f) for f in registry.EDITABLE_FIELDS}
        after = {**before, **{f: v for f, v in (data or {}).items() if f in registry.EDITABLE_FIELDS}} \
            if isinstance(data, dict) else before
        self_key = key
    elif kind == 'path' and key in ROLES:
        before, after = training.path(key), (data or {}).get('screens') if isinstance(data, dict) else None
        self_key = f'path:{key}'
    elif kind == 'quiz' and key in modules:
        before, after = training.quizzes().get(key, []), (data or {}).get('questions') if isinstance(data, dict) else None
        self_key = f'quiz:{key}'
    elif kind == 'flow' and training.base_flow(key) is not None:
        o = HelpTrainingOverride.objects.filter(kind='flow', key=key).first()
        before = training.merge_flow(training.base_flow(key), o.data if o else None)
        after = data if isinstance(data, dict) else before
        self_key = f'flow:{key}'
    else:
        return Response({'detail': 'not found'}, status=404)
    from .glossary import terms
    module = (screens[key]['module'] if kind == 'screen' else key if kind == 'quiz'
              else key.split('.')[0] if kind == 'flow' else None)
    hints = notecheck.check(kind, body.get('note', ''), before, after, recent_notes(), self_key,
                            terms=terms(), module=module)
    return Response({'hints': hints})
