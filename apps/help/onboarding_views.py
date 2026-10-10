"""
apps/help/onboarding_views.py — role onboarding (checklist + module quizzes).

  GET  /api/help/onboarding/                 my path: screens to learn (todo/done/changed),
                                              module quizzes with my best score, progress %
  POST /api/help/onboarding/learned/         {screen_key, done}  «فهمت هذه الشاشة» on/off
  GET  /api/help/onboarding/team/            trainers (help/edit): completion per staff member
  GET  /api/help/quizzes/<module>/           questions; options shuffled, NO answers
  POST /api/help/quizzes/<module>/submit/    {answers: [option id | null]} → graded here

The path comes from content/onboarding.ROLE_PATHS. Grading is deterministic and done
only on the server; answers + explanations are returned after submitting.
"""
import random

from django.db.models import Max
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.models import ROLE_CHOICES, StaffProfile

from . import registry
from .content import onboarding
from .models import HelpLearned, HelpOverride, HelpQuizAttempt
from .views import _can_edit, _profile, _staff_name, _updated

ROLES = [r for r, _ in ROLE_CHOICES]


def path_modules(keys):
    """Modules of a path, in first-seen order, that have a quiz."""
    out = []
    for k in keys:
        m = k.split('.', 1)[0]
        if m in onboarding.QUIZZES and m not in out:
            out.append(m)
    return out


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
    if asked and asked != role and _can_edit(profile) and asked in onboarding.ROLE_PATHS:
        role = asked
    keys = onboarding.ROLE_PATHS.get(role, onboarding.ROLE_PATHS['viewer'])
    modules, screens = registry.load()
    ov = {o.screen_key: o for o in HelpOverride.objects.filter(screen_key__in=keys)}
    versions = _versions()
    learned = dict(HelpLearned.objects.filter(staff=profile).values_list('screen_key', 'version'))
    mods = path_modules(keys)
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
        'pass_percent': onboarding.PASS_PERCENT,
        'path': items,
        'quizzes': [{
            'module': mk, 'title': modules.get(mk, {}).get('title'), 'icon': modules.get(mk, {}).get('icon', ''),
            'questions': len(onboarding.QUIZZES[mk]), 'best': best.get(mk),
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
    qs = onboarding.QUIZZES.get(module_key)
    if qs is None or profile is None:
        return Response({'detail': 'not found'}, status=404)
    modules, _ = registry.load()
    best = _best([profile.id]).get(profile.id, {}).get(module_key)
    return Response({
        'module': module_key, 'title': modules.get(module_key, {}).get('title'),
        'pass_percent': onboarding.PASS_PERCENT, 'best': best,
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
    qs = onboarding.QUIZZES.get(module_key)
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
    passed = percent >= onboarding.PASS_PERCENT
    HelpQuizAttempt.objects.create(staff=profile, module_key=module_key, score=score, total=total,
                                   passed=passed, answers=clean)
    return Response({'score': score, 'total': total, 'percent': percent, 'passed': passed,
                     'pass_percent': onboarding.PASS_PERCENT, 'results': results},
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
    rows = []
    for p in staff:
        keys = onboarding.ROLE_PATHS.get(p.role, onboarding.ROLE_PATHS['viewer'])
        mods = path_modules(keys)
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
