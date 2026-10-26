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


def base_flow(key):
    """A workflow tour as written in the repo ('<module>.<flow key>') — title, summary, steps."""
    modules, _ = registry.load()
    f = registry.flows(modules).get('flow:' + key)
    return None if f is None else {'title': f['title'], 'summary': f.get('summary'), 'steps': f['steps']}


def base_hash(kind, key):
    if kind == HelpTrainingOverride.KIND_FLOW:
        return _hash(base_flow(key))
    return _hash(base_path(key) if kind == HelpTrainingOverride.KIND_PATH else base_quiz(key))


def merge_flow(base, data):
    """A trainer's flow text on top of the repo flow: title / summary replaced when given;
    steps keep the code's targets and order, text matched by position + target."""
    if not data:
        return dict(base)
    out = dict(base)
    for f in ('title', 'summary'):
        if _t_ok(data.get(f)):
            out[f] = data[f]
    out['steps'] = registry._merge_tour(base['steps'], data.get('steps'))
    return out


def flows_effective(modules=None, ov=None):
    """{'flow:<module>.<key>': flow} with trainers' text applied — what users run."""
    if modules is None:
        modules, _ = registry.load()
    ov = overrides(HelpTrainingOverride.KIND_FLOW) if ov is None else ov
    notes = flow_notes()
    out = {}
    for fid, f in registry.flows(modules).items():
        o = ov.get(fid[5:])
        out[fid] = {**f, **merge_flow({'title': f['title'], 'summary': f.get('summary'), 'steps': f['steps']},
                                      o.data if o else None),
                    'change_note': notes.get(fid)}
    return out


FLOW_NOTE_DAYS = 14


def flow_notes(days=FLOW_NOTE_DAYS):
    """'flow:<module>.<key>' → {'ar', 'en'}: the trainer's one-line «what changed» when
    their save is the latest change to that workflow tour and is under `days` old (a
    later save without a note, or a revert, clears it)."""
    from django.utils import timezone
    from .models import HelpRevision
    latest = {}
    for r in (HelpRevision.objects.filter(screen_key__startswith='flow:',
                                          created_at__gte=timezone.now() - timezone.timedelta(days=days))
              .order_by('screen_key', '-created_at', '-id').values('screen_key', 'action', 'public_note')):
        latest.setdefault(r['screen_key'], r)
    return {k: {'ar': r['public_note'], 'en': r['public_note']} for k, r in latest.items()
            if r['action'] == HelpRevision.ACTION_SAVE and r['public_note']}


def flow_brief(fid, f):
    """What the panel / module page need to list and start a workflow tour."""
    return {'id': fid, 'title': f['title'], 'summary': f.get('summary'), 'roles': f.get('roles'),
            'mobile': bool(f.get('mobile')), 'steps': f['steps'], 'change_note': f.get('change_note')}


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


def validate_flow(data, base):
    if not isinstance(data, dict):
        return ['data: يجب أن تكون كائناً']
    errs = []
    if not _t_ok(data.get('title')):
        errs.append('العنوان العربي مطلوب')
    if data.get('summary') not in (None, '') and not isinstance(data.get('summary'), dict):
        errs.append('الملخص: صيغة غير صالحة')
    steps = data.get('steps')
    if not isinstance(steps, list) or len(steps) != len(base['steps']):
        errs.append(f'الخطوات: لازم {len(base["steps"])} خطوة (الخطوات ثابتة — عدّل النص فقط)')
        return errs
    for i, (st, b) in enumerate(zip(steps, base['steps'])):
        if not isinstance(st, dict) or st.get('target') != b['target'] or not _t_ok(st.get('text')):
            errs.append(f'خطوة {i + 1}: النص العربي مطلوب')
    return errs


def clean_flow(data):
    def t(v):
        return {'ar': v['ar'].strip(), 'en': (v.get('en') or '').strip()}
    out = {'title': t(data['title']),
           'steps': [{'target': st['target'], 'text': t(st['text'])} for st in data['steps']]}
    if isinstance(data.get('summary'), dict) and (data['summary'].get('ar') or '').strip():
        out['summary'] = t(data['summary'])
    return out


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
