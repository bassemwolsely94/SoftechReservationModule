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


def _strip_marks(ch):
    return bool(_TASHKEEL.match(ch))


def _split_prefix(core, n):
    """Index in the original word after its first `n` letters (tashkeel skipped)."""
    seen = 0
    for i, ch in enumerate(core):
        if seen == n:
            return i
        if not _strip_marks(ch):
            seen += 1
    return len(core)


def _agreed(term):
    """The agreed word as written in place, without a leading «ال» (the word in the
    text keeps its own prefix)."""
    p = term['preferred'].strip()
    return p[2:] if normalize(p).startswith('ال') and len(normalize(p)) > 4 else p


def occurrences(text, terms):
    """Every avoided word in `text` with its exact place: [{'term', 'avoid', 'start',
    'end', 'match', 'replacement'}] in text order. A word keeps what is attached to it
    («للخزنة» → «للكاشير»); the agreed word itself is never matched. Basis for the
    hints, «طبّق القاموس» and the note fix — one rule everywhere."""
    text = str(text or '')
    toks = []                        # (start, end, normalised core) of each word
    for m in re.finditer(r'\S+', text):
        e = _EDGE.match(m.group(0))
        a = m.start() + len(e.group(1))
        n = normalize(e.group(2))
        toks.append((a, a + len(e.group(2)), n if ' ' not in n else ''))
    out, used = [], set()
    for t in terms:
        pref = bare(t['preferred']).split()
        skip = set()
        for i in range(len(toks)):
            if pref and any(r == pref[0] for _, r in _cores(toks[i][2])) \
                    and [x[2] for x in toks[i + 1:i + len(pref)]] == pref[1:]:
                skip.update(range(i, i + len(pref)))
        for a in t.get('avoid') or []:
            wa = bare(a).split()
            if not wa:
                continue
            for i in range(len(toks) - len(wa) + 1):
                span = range(i, i + len(wa))
                if any(k in skip or k in used for k in span):
                    continue
                hit = next((p for p, r in _cores(toks[i][2]) if r == wa[0]), None)
                if hit is None or [x[2] for x in toks[i + 1:i + len(wa)]] != wa[1:]:
                    continue
                start, end = toks[i][0], toks[i + len(wa) - 1][1]
                cut = start + _split_prefix(text[start:end], len(hit))
                used.update(span)
                out.append({'term': t, 'avoid': a, 'start': start, 'end': end, 'match': text[start:end],
                            'replacement': text[start:cut] + _agreed(t)})
    return sorted(out, key=lambda o: o['start'])


def apply(text, occ):
    """`text` with the given occurrences replaced (from the end, so places stay right)."""
    for o in sorted(occ, key=lambda o: -o['start']):
        text = text[:o['start']] + o['replacement'] + text[o['end']:]
    return text


def find_terms(text, terms):
    """→ [(term, avoid word, count)] for every avoided word found in `text`."""
    counts = {}
    for o in occurrences(text, terms):
        k = (o['term']['id'] if 'id' in o['term'] else id(o['term']), o['avoid'])
        counts.setdefault(k, [o['term'], o['avoid'], 0])[2] += 1
    return [tuple(v) for v in counts.values()]


def fix_note(note, terms):
    """The note with every avoided word replaced by the agreed word; None if none."""
    occ = occurrences(note, terms)
    return apply(note, occ) if occ else None


def strings(v, path=()):
    """(path, Arabic text) for every Arabic text in a help structure — the places
    «طبّق القاموس» may change (path = keys / indexes down to 'ar')."""
    if isinstance(v, dict):
        if isinstance(v.get('ar'), str):
            yield (*path, 'ar'), v['ar']
            return
        for k in v:
            yield from strings(v[k], (*path, k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from strings(x, (*path, i))


def _context(text, start, end, width=50):
    """The sentence around a match, cut to `width` characters each side."""
    stops = '.!?؟\n'
    a = max((text.rfind(c, 0, start) for c in stops), default=-1) + 1
    b = min([x for x in (text.find(c, end) for c in stops) if x != -1] or [len(text)])
    before, after = text[a:start].lstrip(), text[end:b + 1 if b < len(text) else b].rstrip()
    if len(before) > width:
        before = '…' + before[-width:]
    if len(after) > width:
        after = after[:width] + '…'
    return before, after


def scan(data, terms, module):
    """«طبّق القاموس»: every avoided word in a draft, with its place and sentence."""
    terms = [t for t in terms if applies(t, module)]
    items = []
    for path, text in strings(data):
        for o in occurrences(text, terms):
            before, after = _context(text, o['start'], o['end'])
            items.append({'path': list(path), 'start': o['start'], 'end': o['end'], 'match': o['match'],
                          'replacement': o['replacement'], 'avoid': o['avoid'],
                          'preferred': o['term']['preferred'], 'why': o['term'].get('why', ''),
                          'before': before, 'after': after})
    return items


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
