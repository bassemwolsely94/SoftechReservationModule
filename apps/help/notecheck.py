"""
apps/help/notecheck.py — gentle hints on the one-line «إيه الجديد للمستخدمين؟» note while
a trainer types it (screen help, path, quiz, workflow tour). Deterministic word rules,
no model; never blocks a save — the editor shows the hints under the field.

  big_empty  — a big edit (BIG_EDIT+ parts changed), or path screens added / a quiz
               changed (people get a notification), with no note
  vague      — the note is only generic words («تعديلات بسيطة», «تحديث»)
  similar    — another recent note (Dice ≥ SIMILAR, 2+ shared non-generic words) (last 30 days, other screen / path / quiz / tour)
               describes the same change in different words → offer its wording
"""
import re

BIG_EDIT = 3
SIMILAR = 0.6            # word overlap (Dice) from which two notes look like one change

_TASHKEEL = re.compile(r'[ً-ٰٟـ]')
_PUNCT = re.compile(r'[^\w\s]', re.UNICODE)
STOP = {'في', 'من', 'علي', 'عن', 'الي', 'مع', 'او', 'ثم', 'كل', 'ده', 'دي', 'دا', 'اللي', 'بقي', 'بقت',
        'لما', 'عشان', 'علشان', 'ان', 'انه', 'لو', 'هو', 'هي', 'the', 'a', 'an', 'to', 'of', 'in', 'on',
        'for', 'and', 'or', 'is', 'now'}
GENERIC = {'تعديل', 'تعديلات', 'تحديث', 'تحديثات', 'تحسين', 'تحسينات', 'تغيير', 'تغييرات', 'جديد', 'جديده',
           'شرح', 'بسيط', 'بسيطه', 'عام', 'عامه', 'اضافه', 'اضافات', 'اصلاح', 'اصلاحات', 'صغير', 'صغيره',
           'تظبيط', 'مراجعه', 'نص', 'كلام', 'حاجات', 'update', 'updates', 'updated', 'change', 'changes',
           'fix', 'fixes', 'minor', 'improvement', 'improvements', 'new', 'text', 'edit', 'edits'}


# spoken / English variants of the same word → one form
SAME = {'زرار': 'زر', 'زراير': 'زر', 'button': 'زر', 'excel': 'اكسل', 'اكسيل': 'اكسل', 'عواميد': 'عمود',
        'اعمده': 'عمود', 'column': 'عمود', 'تبويبه': 'تبويب', 'tab': 'تبويب', 'خطوات': 'خطوه', 'step': 'خطوه',
        'شاشات': 'شاشه', 'screen': 'شاشه', 'اسئله': 'سؤال', 'question': 'سؤال', 'فلاتر': 'فلتر', 'filter': 'فلتر',
        'تقارير': 'تقرير', 'report': 'تقرير', 'export': 'تصدير', 'print': 'طباعه'}


def normalize(text):
    t = _TASHKEEL.sub('', str(text or '').lower())
    t = re.sub('[أإآ]', 'ا', t).replace('ى', 'ي').replace('ة', 'ه')
    return ' '.join(_PUNCT.sub(' ', t).split())


def words(text):
    out = set()
    for w in normalize(text).split():
        if w.startswith('ال') and len(w) > 4:
            w = w[2:]
        elif w.startswith('وال') and len(w) > 5:
            w = w[3:]
        w = SAME.get(w, w)
        if len(w) > 1 and w not in STOP:
            out.add(w)
    return out


def similarity(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return 2 * len(wa & wb) / (len(wa) + len(wb))


def _texts(v):
    """Every non-empty Arabic text inside a help structure, in order (T dicts, lists,
    dicts); an empty field and a missing one count the same."""
    if isinstance(v, dict):
        if 'ar' in v and isinstance(v.get('ar'), str):
            return [v['ar'].strip()] if v['ar'].strip() else []
        return [t for k in sorted(v) for t in _texts(v[k])]
    if isinstance(v, (list, tuple)):
        return [t for x in v for t in _texts(x)]
    if isinstance(v, (int, str)) and not isinstance(v, bool) and str(v).strip():
        return [str(v).strip()]
    return []


def changed_parts(before, after):
    """How many texts differ between two versions (position by position + added/removed)."""
    a, b = _texts(before), _texts(after)
    return sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))


def check(kind, note, before, after, recent, self_key=None):
    """→ list of {'code', 'text', 'suggestion'?}. `recent` = onboarding_views.recent_notes()
    rows; `self_key` = '<kind>:<key>' of what is being edited (its own notes are skipped)."""
    note = ' '.join(str(note or '').split())
    hints = []
    if not note:
        if kind == 'path':
            added = [k for k in (after or []) if k not in set(before or [])]
            if added:
                hints.append({'code': 'big_empty', 'text':
                              f'بتضيف {len(added)} شاشة للمسار والناس هيوصلهم إشعار — سطر «إيه الجديد» '
                              'هيتضاف للإشعار ويقولهم يبدأوا بإيه.'})
        elif kind == 'quiz':
            if after and changed_parts(before, after):
                hints.append({'code': 'big_empty', 'text':
                              'الاختبار اتغيّر — اللي نجحوا فيه هيوصلهم إشعار يعيدوه. سطر قصير يقولهم إيه '
                              'الجديد (مثلاً «سؤالين عن المرتجعات») بيساعدهم.'})
        else:
            n = changed_parts(before, after)
            if n >= BIG_EDIT:
                hints.append({'code': 'big_empty', 'text':
                              f'تعديل كبير ({n} أجزاء اتغيّرت) من غير سطر «إيه الجديد» — الناس مش هتعرف تدوّر '
                              'على إيه. اكتب سطر قصير؟'})
        return hints

    w = words(note)
    if w and w <= GENERIC:
        hints.append({'code': 'vague', 'text':
                      f'«{note}» عام شوية — اكتب إيه اللي اتغيّر بالظبط (اسم الزر، الخطوة، أو العمود).'})
    seen = set()
    best = []
    for r in recent:
        other = r.get('note') or ''
        rkey = r['key'] if r['kind'] == 'screen' else f"{r['kind']}:{r['key']}"
        if rkey == self_key or normalize(other) == normalize(note) or normalize(other) in seen:
            continue
        s = similarity(note, other)
        if s >= SIMILAR and len((words(note) & words(other)) - GENERIC) >= 2:
            seen.add(normalize(other))
            best.append((s, r))
    for s, r in sorted(best, key=lambda x: -x[0])[:2]:
        hints.append({'code': 'similar', 'suggestion': r['note'], 'text':
                      f"نفس التعديل اتوصف على «{r['title']['ar']}» كده: «{r['note']}» — تستخدم نفس الصياغة؟"})
    return hints
