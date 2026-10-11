"""
apps/help/notecheck.py — gentle hints on the one-line «إيه الجديد للمستخدمين؟» note while
a trainer types it (screen help, path, quiz, workflow tour). Deterministic word rules,
no model; never blocks a save — the editor shows the hints under the field.

  big_empty  — a big edit (BIG_EDIT+ parts changed), or path screens added / a quiz
               changed (people get a notification), with no note
  vague      — the note is only generic words («تعديلات بسيطة», «تحديث»)
  term       — the note uses a word the glossary («قاموس المصطلحات») says to avoid → offers
               the note with the agreed word
  term_text  — the help text being edited uses words to avoid (count per word)
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


# ── glossary («قاموس المصطلحات») ──────────────────────────────────────────────

PREFIXES = ('وبال', 'وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و', 'ب', 'ل', 'ف')
_EDGE = re.compile(r'^(\W*)(.*?)(\W*)$', re.UNICODE | re.DOTALL)


def bare(term):
    """Normalised term without a leading «ال» (so «الخزنة» also finds «للخزنة», «والخزنة»)."""
    t = normalize(term)
    return t[2:] if t.startswith('ال') and len(t) > 4 else t


def _cores(token):
    """(prefix, rest) readings of one normalised word: as is, and without each prefix."""
    out = [('', token)]
    for p in PREFIXES:
        if token.startswith(p) and len(token) - len(p) >= 2:
            out.append((p, token[len(p):]))
    return out


def applies(term, module):
    """A term limited to some modules applies only there; unscoped terms everywhere."""
    mods = term.get('modules') or []
    return not mods or (module is not None and module in mods)


def find_terms(text, terms):
    """→ [(term, avoid word, count)] for every avoided word found in `text`. The
    agreed word itself is never counted (its words are blanked out first)."""
    toks = normalize(text).split()
    out = []
    for t in terms:
        pref = bare(t['preferred']).split()
        skip = set()
        for i in range(len(toks)):
            if pref and any(r == pref[0] for _, r in _cores(toks[i])) and toks[i + 1:i + len(pref)] == pref[1:]:
                skip.update(range(i, i + len(pref)))
        for a in t.get('avoid') or []:
            words_a = bare(a).split()
            if not words_a:
                continue
            n = sum(1 for i in range(len(toks))
                    if i not in skip and any(r == words_a[0] for _, r in _cores(toks[i]))
                    and toks[i + 1:i + len(words_a)] == words_a[1:])
            if n:
                out.append((t, a, n))
    return out


def fix_note(note, terms):
    """The note with single-word avoided terms replaced by the agreed word, keeping
    the attached «ال» / «و» / «ب» …; None when nothing could be replaced."""
    changed = False
    parts = []
    for tok in note.split(' '):
        m = _EDGE.match(tok)
        lead, core, tail = m.group(1), m.group(2), m.group(3)
        n = normalize(core)
        new = None
        for t in terms:
            pref_bare = t['preferred'].strip()
            if normalize(pref_bare).startswith('ال') and len(normalize(pref_bare)) > 4:
                pref_bare = pref_bare[2:]
            for a in t.get('avoid') or []:
                if len(bare(a).split()) != 1 or ' ' in n:
                    continue
                hit = next((p for p, r in _cores(n) if r == bare(a)), None)
                if hit is not None:
                    new = hit + pref_bare
                    break
            if new:
                break
        if new:
            changed = True
            parts.append(lead + new + tail)
        else:
            parts.append(tok)
    return ' '.join(parts) if changed else None


def term_hints(note, after, kind, terms, module):
    terms = [t for t in terms if applies(t, module)]
    if not terms:
        return []
    hints = []
    if note:
        found = find_terms(note, terms)
        if found:
            said = '، '.join(f"«{t['preferred']}» مش «{a}»" for t, a, _ in found[:3])
            fixed = fix_note(note, [t for t, _, _ in found])
            hints.append({'code': 'term', 'text': f'القاموس: {said}.', **({'suggestion': fixed} if fixed else {})})
    if kind in ('screen', 'flow', 'quiz') and after:
        found = sorted(find_terms('\n'.join(_texts(after)), terms), key=lambda x: -x[2])
        if found:
            said = '، '.join(f"«{a}» ×{n} ← «{t['preferred']}»" for t, a, n in found[:4])
            hints.append({'code': 'term_text', 'text':
                          f'في نص الشرح كلمات القاموس بيقول نتجنّبها: {said}. غيّرها لو المعنى واحد.'})
    return hints


def check(kind, note, before, after, recent, self_key=None, terms=(), module=None):
    """→ list of {'code', 'text', 'suggestion'?}. `recent` = onboarding_views.recent_notes()
    rows; `self_key` = '<kind>:<key>' of what is being edited (its own notes are skipped);
    `terms` = glossary rows (glossary.terms()), `module` = where the edit lives."""
    note = ' '.join(str(note or '').split())
    hints = term_hints(note, after, kind, list(terms), module)
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
