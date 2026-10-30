"""
apps/help/training.py — the training paths and quizzes people actually get:
the repo version (content/onboarding.py) unless a trainer saved their own
(HelpTrainingOverride). Every reader of paths/quizzes goes through here.
"""
import hashlib
import json

from . import registry
from .content import onboarding
from .models import HelpTrainingOverride

PASS_PERCENT = onboarding.PASS_PERCENT


def _hash(v):
    return hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def overrides(kind):
    return {o.key: o for o in HelpTrainingOverride.objects.filter(kind=kind).select_related('updated_by__user')}


def base_path(role):
    return list(onboarding.ROLE_PATHS.get(role, []))


def base_quiz(module):
    return list(onboarding.QUIZZES.get(module, []))


def base_hash(kind, key):
    return _hash(base_path(key) if kind == HelpTrainingOverride.KIND_PATH else base_quiz(key))


def path(role, ov=None):
    """Ordered screen keys for a role (unknown role → viewer). Screens removed from the
    code since the trainer's save are dropped."""
    ov = overrides(HelpTrainingOverride.KIND_PATH) if ov is None else ov
    if role not in onboarding.ROLE_PATHS:
        role = 'viewer'
    o = ov.get(role)
    if o is None:
        return base_path(role)
    _, screens = registry.load()
    return [k for k in o.data.get('screens', []) if k in screens]


def quizzes(ov=None):
    """module key → questions (repo quizzes, trainer versions on top; a trainer may
    add a quiz for a module that has none; an empty saved quiz removes it)."""
    ov = overrides(HelpTrainingOverride.KIND_QUIZ) if ov is None else ov
    out = {k: list(v) for k, v in onboarding.QUIZZES.items()}
    for k, o in ov.items():
        qs = o.data.get('questions') or []
        if qs:
            out[k] = qs
        else:
            out.pop(k, None)
    return out


def quiz_version(questions):
    """Short, stable fingerprint of a quiz's questions."""
    return _hash(questions or [])[:12]


def quiz(module):
    return quizzes().get(module)


def path_modules(keys, qz):
    """Modules of a path, in first-seen order, that have a quiz."""
    out = []
    for k in keys:
        m = k.split('.', 1)[0]
        if m in qz and m not in out:
            out.append(m)
    return out


PRODUCT_SHELLS = ('desktop', 'mobile')
_HELP_BUTTON = {'desktop': 'general-help-center-open-help', 'mobile': 'general-help-center-open-help-mobile'}


def _short(title):
    """A module title short enough for a step label: cut at «(» / «—» / «&» when long."""
    for sep in (' (', ' — ', ' & '):
        if len(title) > 36 and sep in title:
            title = title.split(sep, 1)[0]
    return title[:38]


def _screens_ar(n):
    return {1: 'شاشة واحدة', 2: 'شاشتين'}.get(n) or (f'{n} شاشات' if n <= 10 else f'{n} شاشة')


def product_tour(role, shell='desktop', keys=None):
    """«🚀 جولة في النظام»: a journey built from the role's training path (trainer edits
    included) — a welcome, then one stop per module in path order (its first screen on this
    shell that has a tour and a route without parameters; highlights that screen's first
    tour step and shows the module's one-line `brief`), then where help is. None when no
    module of the path has such a screen on this shell. Same shape as registry journeys."""
    modules, screens = registry.load()
    keys = path(role) if keys is None else keys
    mobile = shell == 'mobile'
    stops, seen = [], set()
    for k in keys:
        s = screens.get(k)
        if not s or s['module'] in ('general', *seen) or not s.get('tour'):
            continue
        if not any(r.startswith('/m/') == mobile and ':' not in r for r in s['routes']):
            continue
        m = modules[s['module']]
        seen.add(s['module'])
        n = sum(1 for x in keys if x.split('.', 1)[0] == s['module'])
        stops.append({
            'screen': k, 'target': s['tour'][0]['target'],
            'label': {lang: f"{m.get('icon', '')} {_short(m['title'][lang])}".strip() for lang in ('ar', 'en')},
            'text': m['brief'],
            'when': {'ar': f'في مسارك التدريبي {_screens_ar(n)} من الموديول ده — هتتعلمها بالترتيب.',
                     'en': f"Your training path has {n} screen{'s' if n > 1 else ''} here — you will learn them in order."},
        })
    if not stops:
        return None
    pt = onboarding.PRODUCT_TOUR
    help_target = _HELP_BUTTON[shell]
    if mobile:
        welcome = {'screen': stops[0]['screen'], 'target': help_target, **pt['welcome']}
    else:
        welcome = {'screen': 'general.dashboard', 'target': 'general-dashboard-greeting', **pt['welcome']}
    finish = {'screen': stops[-1]['screen'], 'target': help_target, **pt['finish']}
    return {
        'id': f'product.{role}.{shell}', 'key': f'{role}.{shell}', 'module': 'general', 'shell': shell,
        'title': pt['title'], 'summary': pt['summary'], 'product': True,
        'steps': [welcome, *stops, finish],
    }


def validate_path(data):
    _, screens = registry.load()
    keys = data.get('screens') if isinstance(data, dict) else None
    if not isinstance(keys, list) or not keys:
        return ['screens: قائمة الشاشات مطلوبة']
    errs = [f'شاشة غير موجودة: {k}' for k in keys if k not in screens]
    if len(keys) != len(set(keys)):
        errs.append('شاشة مكررة في المسار')
    return errs


def _t_ok(v):
    return isinstance(v, dict) and isinstance(v.get('ar'), str) and v['ar'].strip() \
        and isinstance(v.get('en', ''), str) and not set(v) - {'ar', 'en'}


def validate_quiz(data):
    qs = data.get('questions') if isinstance(data, dict) else None
    if not isinstance(qs, list):
        return ['questions: يجب أن تكون قائمة']
    errs = []
    for i, q in enumerate(qs):
        n = i + 1
        if not isinstance(q, dict) or not _t_ok(q.get('q')):
            errs.append(f'سؤال {n}: نص السؤال مطلوب')
            continue
        opts = q.get('options')
        if not isinstance(opts, list) or len(opts) < 2 or not all(_t_ok(o) for o in opts):
            errs.append(f'سؤال {n}: اختياران على الأقل، وكل اختيار له نص عربي')
            continue
        a = q.get('answer')
        if not isinstance(a, int) or isinstance(a, bool) or not 0 <= a < len(opts):
            errs.append(f'سؤال {n}: حدد الإجابة الصحيحة')
        if not _t_ok(q.get('explain')):
            errs.append(f'سؤال {n}: التوضيح مطلوب')
    return errs


def clean_path(data):
    return {'screens': list(data['screens'])}


def clean_quiz(data):
    def t(v):
        return {'ar': v['ar'].strip(), 'en': (v.get('en') or '').strip()}
    return {'questions': [{'q': t(q['q']), 'options': [t(o) for o in q['options']],
                           'answer': q['answer'], 'explain': t(q['explain'])} for q in data['questions']]}


# ── announcing changes (repo or trainer) ──────────────────────────────────────

def record_snapshot(kind, key):
    """Remember the current path / quiz version as already announced."""
    from .models import HelpTrainingSnapshot
    if kind == 'path':
        data = path(key)
    else:
        data = quiz_version(quizzes().get(key) or [])
    HelpTrainingSnapshot.objects.update_or_create(kind=kind, key=key, defaults={'data': data})


def announce_changes():
    """Notify what changed since the last snapshot — screens added to a role's path,
    quizzes whose questions changed — then store the new snapshot. The first run only
    records (nothing to compare with). → {'paths': n_notified, 'quizzes': n_notified}."""
    from apps.users.models import ROLE_CHOICES
    from . import notify
    from .models import HelpTrainingSnapshot
    snaps = {(s.kind, s.key): s.data for s in HelpTrainingSnapshot.objects.all()}
    sent = {'paths': 0, 'quizzes': 0}
    path_ov = overrides(HelpTrainingOverride.KIND_PATH)
    for role, _ in ROLE_CHOICES:
        cur = path(role, path_ov)
        old = snaps.get(('path', role))
        if old is not None and cur != old:
            sent['paths'] += notify.path_changed(role, old, cur, 'auto-' + _hash(cur)[:10])
        if old != cur:
            HelpTrainingSnapshot.objects.update_or_create(kind='path', key=role, defaults={'data': cur})
    qz = quizzes()
    for module in set(qz) | {k for (kind, k) in snaps if kind == 'quiz'}:
        cur = quiz_version(qz.get(module) or [])
        old = snaps.get(('quiz', module))
        if old is not None and cur != old and qz.get(module):
            sent['quizzes'] += notify.quiz_changed(module, old, cur, 'auto-' + cur)
        if old != cur:
            HelpTrainingSnapshot.objects.update_or_create(kind='quiz', key=module, defaults={'data': cur})
    return sent
