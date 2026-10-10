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
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.models import ROLE_CHOICES, StaffProfile

from . import registry, training
from .models import HelpLearned, HelpOverride, HelpQuizAttempt, HelpRevision, HelpTrainingOverride
from .views import _can_edit, _profile, _staff_name, _updated

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


def _best(staff_ids):
    """{staff_id: {module: {score, total, passed, at}}} — best attempt per module."""
    out = {}
    for a in HelpQuizAttempt.objects.filter(staff_id__in=staff_ids).order_by('created_at'):
        cur = out.setdefault(a.staff_id, {}).get(a.module_key)
        mine = {'score': a.score, 'total': a.total, 'passed': a.passed, 'at': a.created_at}
        if cur is None or (a.passed, a.score) >= (cur['passed'], cur['score']):
            out[a.staff_id][a.module_key] = mine
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
    best = _best([profile.id]).get(profile.id, {})
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
    best = _best([profile.id]).get(profile.id, {}).get(module_key)
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
                                   passed=passed, answers=clean)
    return Response({'score': score, 'total': total, 'percent': percent, 'passed': passed,
                     'pass_percent': training.PASS_PERCENT, 'results': results},
                    status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team(request):
    """Trainers / supervisors: everyone's onboarding completion. Branch-bound trainers
    see only the branches they can access."""
    profile = _profile(request)
    if not _can_edit(profile):
        return Response({'detail': 'forbidden'}, status=403)
    staff = StaffProfile.objects.filter(is_active=True, user__is_active=True).select_related('user', 'branch')
    allowed = profile.accessible_branch_ids
    if allowed is not None:
        staff = staff.filter(branch_id__in=allowed)
    if request.query_params.get('role'):
        staff = staff.filter(role=request.query_params['role'])
    if request.query_params.get('branch'):
        staff = staff.filter(branch_id=request.query_params['branch'])
    staff = list(staff.order_by('role', 'user__first_name')[:500])
    ids = [p.id for p in staff]
    versions = _versions()
    learned = {}
    for sid, key, ver in HelpLearned.objects.filter(staff_id__in=ids).values_list('staff_id', 'screen_key', 'version'):
        learned.setdefault(sid, {})[key] = ver
    last = dict(HelpLearned.objects.filter(staff_id__in=ids).values('staff_id')
                .annotate(t=Max('created_at')).values_list('staff_id', 't'))
    best = _best(ids)
    path_ov = training.overrides('path')
    qz = training.quizzes()
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
            'failed_quizzes': [m for m, v in mine.items() if not v['passed']],
            'last_activity': max(at) if at else None,
        })
    return Response(rows)


# ── trainers: edit paths / quizzes (help/edit) ────────────────────────────────

def _training_payload(kind, key, override):
    base = training.base_path(key) if kind == 'path' else training.base_quiz(key)
    if override is None:
        current = base
    else:
        current = override.data.get('screens' if kind == 'path' else 'questions', [])
    revs = HelpRevision.objects.filter(screen_key=f'{kind}:{key}').select_related('staff__user')[:20]
    return {
        'kind': kind, 'key': key, 'current': current, 'base': base,
        'override': None if override is None else {
            'updated_at': override.updated_at, 'updated_by': _staff_name(override.updated_by),
            'base_changed': override.base_hash != training.base_hash(kind, key),
        },
        'revisions': [{'id': r.id, 'action': r.action, 'note': r.note, 'created_at': r.created_at,
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
            or kind not in ('path', 'quiz'):
        return Response({'detail': 'not found'}, status=404)
    override = HelpTrainingOverride.objects.filter(kind=kind, key=key).select_related('updated_by__user').first()
    if request.method == 'GET':
        return Response(_training_payload(kind, key, override))

    field = 'screens' if kind == 'path' else 'questions'
    before = {field: override.data.get(field) if override else
              (training.base_path(key) if kind == 'path' else training.base_quiz(key))}
    note = str((request.data or {}).get('note', ''))[:300] if isinstance(request.data, dict) else ''
    if request.method == 'DELETE':
        if override is None:
            return Response({'detail': 'لا يوجد تعديل للرجوع عنه'}, status=400)
        override.delete()
        base = training.base_path(key) if kind == 'path' else training.base_quiz(key)
        HelpRevision.objects.create(screen_key=f'{kind}:{key}', action=HelpRevision.ACTION_REVERT,
                                    before=before, after={field: base}, note=note, staff=profile)
        return Response(_training_payload(kind, key, None))

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
    HelpRevision.objects.create(screen_key=f'{kind}:{key}', action=HelpRevision.ACTION_SAVE,
                                before=before, after=clean, note=note, staff=profile)
    return Response(_training_payload(kind, key, override))
