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
