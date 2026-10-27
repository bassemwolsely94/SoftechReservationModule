"""
Patient-name autocomplete for the motalba screen.

Owner rules (2026-09-30):
  * Names are transcribed EXACTLY as on the ID card — hamza/letters preserved
    (أحمد ≠ احمد).  Suggestions therefore always return the ORIGINAL stored
    spelling; normalization is used ONLY to compare/rank forgivingly.
  * Matching must NOT falsely merge distinct 4-part names that share repeated
    tokens (محمد / أحمد).  We match on the ORDERED token sequence from the start
    (a real autocomplete prefix), not a bag of words — so «أحمد محمد» never
    matches «محمد أحمد», and «محمد» alone doesn't collapse every محمد-name.
  * Suggestions are scoped by the caller (same insurer/جهة across sub-categories).

Pure functions here; the DB query + endpoint live in views.
"""
import re
import unicodedata

_TASHKEEL = re.compile(r'[ً-ْٰـ]')   # harakat + superscript alef + tatweel


def normalize_ar(s: str) -> str:
    """Fold a name for COMPARISON only (never for storage/display).
    Unifies alef/hamza/ya/ta-marbuta forms, strips tashkeel + tatweel, collapses
    whitespace.  The original string is what we still show the user."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', str(s))
    s = _TASHKEEL.sub('', s)
    trans = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
        'ى': 'ي', 'ئ': 'ي',
        'ؤ': 'و',
        'ة': 'ه',
        'ك': 'ك',
    }
    s = ''.join(trans.get(ch, ch) for ch in s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _tokens(s: str) -> list:
    n = normalize_ar(s)
    return n.split(' ') if n else []


def score_match(query: str, candidate: str) -> tuple | None:
    """
    Rank `candidate` (a stored full name) against `query` (what the user typed).

    Returns a sort key tuple (higher = better) or None when it does not match.
    Tiers (most-specific first):
      3  ordered-prefix: every query token equals the candidate token at the same
         position, and the LAST query token may be a prefix of its candidate token
         (live typing).  candidate must have >= as many tokens.  This is the strong,
         false-merge-proof autocomplete match.
      2  ordered-subsequence: the query tokens appear in the candidate in order but
         not from position 0 (e.g. typing a middle/last name fragment).
      1  loose contains: normalized query substring appears in normalized candidate.
    """
    qt = _tokens(query)
    ct = _tokens(candidate)
    if not qt or not ct:
        return None

    # Tier 3 — ordered prefix from the start
    if len(ct) >= len(qt):
        ok = True
        for i, q in enumerate(qt):
            c = ct[i]
            last = (i == len(qt) - 1)
            if c == q or (last and c.startswith(q)):
                continue
            ok = False
            break
        if ok:
            # more of the name already matched (fewer remaining tokens) ranks higher
            return (3, -(len(ct) - len(qt)), -len(candidate))

    # Tier 2 — ordered subsequence (query tokens in order, anywhere)
    j = 0
    for c in ct:
        if j < len(qt):
            q = qt[j]
            last = (j == len(qt) - 1)
            if c == q or (last and c.startswith(q)):
                j += 1
    if j == len(qt):
        return (2, -len(candidate), 0)

    # Tier 1 — loose contains
    if normalize_ar(query) in normalize_ar(candidate):
        return (1, -len(candidate), 0)

    return None


# Non-name tokens that leak into stored patient names (the insurer/company/job
# words) — a completion that only adds one of these is noise, not a real name part.
_JUNK_TOKENS = {
    'كهرباء', 'عامل', 'عاملين', 'موظف', 'موظفين', 'شركه', 'شركة', 'توزيع',
    'قطاع', 'جنوب', 'شمال', 'شرق', 'غرب', 'القاهره', 'القاهرة', 'مجمع',
    'تعاقد', 'تامين', 'صحه', 'صحة', 'طبيه', 'طبية',
}


def _is_junk_extra(extra_tokens: list) -> bool:
    """A completion's ADDED tokens are noise if any is a known entity/job word or a
    bare single letter (e.g. the 'ك' in 'ك(عاملين)')."""
    for t in extra_tokens:
        if t in _JUNK_TOKENS or len(t) <= 1:
            return True
    return False


def suggest_name_improvement(current: str, rows: list) -> dict | None:
    """
    Given a patient's `current` name and historical `rows` ({name, count} from the
    same insurer), propose a SAFE improvement:

      type='complete'  a longer name whose normalized tokens have the current name
                       as an ordered prefix — AND there is exactly ONE such distinct
                       full name in history (ambiguity guard: if several different
                       completions exist we refuse to guess, to avoid mis-identifying
                       the patient).  Returns the most-frequent exact spelling of it
                       (which also fixes spelling).
      type='spelling'  same normalized tokens as current but a different, more common
                       exact spelling (e.g. احمد → أحمد).
      type='ambiguous' several distinct completions exist → no single suggestion;
                       `options` lists them for a human to pick.

    Returns None when the current name already looks best.  `rows` may carry a
    precomputed 'ntokens' (normalized token list) to avoid recomputation.
    """
    ct = _tokens(current)
    if not ct:
        return None
    complete = {}   # normalized-full -> {exact_name: count}
    spelling = {}   # exact_name -> count
    cur_count = 0
    for r in rows:
        name = r.get('name') or ''
        cnt = r.get('count') or 0
        dt = r.get('ntokens')
        if dt is None:
            dt = _tokens(name)
        if name == current:
            cur_count += cnt
            continue
        if not dt:
            continue
        if dt == ct:                                   # same name, different spelling
            spelling[name] = spelling.get(name, 0) + cnt
        elif len(dt) > len(ct) and dt[:len(ct)] == ct:  # ordered-prefix superset
            if _is_junk_extra(dt[len(ct):]):    # added tokens are entity/job noise
                continue
            key = ' '.join(dt)
            complete.setdefault(key, {})
            complete[key][name] = complete[key].get(name, 0) + cnt

    if complete:
        if len(complete) == 1:
            key = next(iter(complete))
            best = max(complete[key].items(), key=lambda kv: kv[1])[0]
            return {'suggestion': best, 'type': 'complete',
                    'count': complete[key][best]}
        # several genuinely different completions → do NOT guess
        opts = sorted({n for d in complete.values() for n in d})
        return {'suggestion': None, 'type': 'ambiguous', 'options': opts[:8]}

    if spelling:
        best, bc = max(spelling.items(), key=lambda kv: kv[1])
        if bc > cur_count:            # only if the variant is genuinely more common
            return {'suggestion': best, 'type': 'spelling', 'count': bc}
    return None


def rank_candidates(query: str, rows: list, limit: int = 15) -> list:
    """
    rows: iterable of dicts {name, count, last_date}.  Returns the best `limit`,
    ranked by (match tier, frequency, recency), each still carrying its EXACT name.
    """
    scored = []
    for row in rows:
        name = row.get('name') or ''
        sc = score_match(query, name)
        if sc is None:
            continue
        # secondary keys: frequency then recency (both higher = better)
        cnt = row.get('count') or 0
        last = row.get('last_date')
        last_ord = last.toordinal() if hasattr(last, 'toordinal') else 0
        scored.append(((sc, cnt, last_ord), row))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in scored[:limit]]
