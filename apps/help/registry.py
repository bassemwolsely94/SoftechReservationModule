"""
apps/help/registry.py — loads the help content shipped in apps/help/content/ and
merges trainer edits (HelpOverride) on top of it.

Content format (one file per module, see content/reservations.py for a full example):

    MODULE = {
        'key': 'reservations', 'group': 'operations', 'icon': '📋',
        'title': T('الحجوزات', 'Reservations'),
        'summary': T('…', '…'),
        'workflows': [{                      # optional — the record's life cycle
            'key': 'order',                  # needed only when a screen picks workflows
            'title': T('…', '…'),
            'model': 'reservations.Reservation', 'field': 'status',   # optional; when
                # given, a test checks every status of the model is explained here
            'transitions': 'apps.reservations.views.ReservationViewSet._VALID_TRANSITIONS',
                # optional; dotted path to the server's {state: {next states}} — a test
                # checks each state's 'next' matches it exactly
            'intro': T('…', '…'),
            'states': [{'key': 'pending', 'label': T(..), 'desc': T(..), 'next': ['…']}],
        }],
    }
    SCREENS = [{
        'key': 'reservations.board',          # unique, '<module>.<screen>'
        'routes': ['/reservations'],          # react-router patterns this help covers
        'title': T(..), 'summary': T(..),     # required
        'audience': T(..),                    # who uses it
        'steps':  [T(..) | {'text': T(..), 'roles': [...]}],   # how to use it
        'tabs':   [{'key': 'items', 'title': T(..), 'body': T(..)}],  # key = what the page
                                              # passes to useHelpTab() / ?tab=
        'tips':   [T(..)],                    # common mistakes, good to know
        'faq':    [{'q': T(..), 'a': T(..)}],
        'related': ['demand.list'],           # other screen keys
        'workflows': ['order'],               # optional — show only these module workflows
                                              # (default: all of the module's)
        'updated': '2026-10-10',              # bump when the text changes → "new" badge
    }]

T(ar, en) is just {'ar': ar, 'en': en}. Every text must have both languages.
"""
import hashlib
import importlib
import json
import re
from functools import lru_cache

from .content import MODULE_FILES

EDITABLE_FIELDS = ('title', 'summary', 'audience', 'steps', 'tabs', 'tips', 'faq', 'notes', 'tour')

GROUPS = [
    ('home',       'الرئيسية',      'Home'),
    ('operations', 'العمليات',      'Operations'),
    ('callcenter', 'مركز الاتصال',  'Call center'),
    ('customers',  'العملاء',       'Customers'),
    ('inventory',  'المخزون',       'Inventory'),
    ('purchasing', 'المشتريات',     'Purchasing'),
    ('analytics',  'التحليلات',     'Analytics'),
    ('finance',    'المالية',       'Finance'),
    ('hr',         'الموارد البشرية', 'HR'),
    ('admin',      'الإدارة والنظام', 'Administration'),
]


@lru_cache(maxsize=1)
def load():
    """→ (modules: dict key→module, screens: dict key→screen), in file order."""
    modules, screens = {}, {}
    for name in MODULE_FILES:
        mod = importlib.import_module(f'apps.help.content.{name}')
        m = dict(mod.MODULE)
        m['screens'] = []
        modules[m['key']] = m
        for s in mod.SCREENS:
            s = dict(s)
            s.setdefault('module', m['key'])
            screens[s['key']] = s
            m['screens'].append(s['key'])
    return modules, screens


def base_hash(screen):
    # 'tour' only counts when the screen has one, so adding the field did not flag
    # every existing trainer edit as "base changed"
    payload = {f: screen.get(f) for f in EDITABLE_FIELDS if f != 'tour' or screen.get('tour')}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _merge_tabs(base_tabs, edited_tabs):
    """Tabs follow the code: keep the repo's tab list/order, take the trainer's text
    for tabs that still exist (a tab removed from the code disappears)."""
    edited = {t.get('key'): t for t in (edited_tabs or []) if isinstance(t, dict)}
    out = []
    for t in base_tabs or []:
        e = edited.get(t['key'])
        out.append({**t, **({'title': e['title']} if e and e.get('title') else {}),
                    **({'body': e['body']} if e and e.get('body') else {})})
    return out


def _merge_tour(base_tour, edited_tour):
    """Like tabs: the steps and their targets follow the code; trainers edit the text
    (`text` = the one-line headline, `more` = the longer explanation under it).
    Matched by position AND target (a tour may point at the same element twice, e.g.
    "this is the list" then "open a row"); a step the code moved or replaced keeps the
    repo text."""
    edited = [t for t in (edited_tour or []) if isinstance(t, dict)]
    out = []
    for i, t in enumerate(base_tour or []):
        e = edited[i] if i < len(edited) else None
        ok = e and e.get('target') == t['target'] and (e.get('text') or {}).get('ar', '').strip()
        step = {**t, **({'text': e['text']} if ok else {})}
        # the longer explanation («more»): the trainer's when they wrote one
        if ok and isinstance(e.get('more'), dict) and (e['more'].get('ar') or '').strip():
            step['more'] = e['more']
        out.append(step)
    return out


def effective(screen, override=None):
    """The screen as users see it: repo text, with the trainer's edit on top."""
    s = dict(screen)
    if override is not None:
        for f in EDITABLE_FIELDS:
            if f not in override.data:
                continue
            if f == 'tabs':
                s['tabs'] = _merge_tabs(screen.get('tabs'), override.data.get('tabs'))
            elif f == 'tour':
                s['tour'] = _merge_tour(screen.get('tour'), override.data.get('tour'))
            else:
                s[f] = override.data[f]
    return s


# ── search ────────────────────────────────────────────────────────────────────

_AR_DIACRITICS = re.compile(r'[ً-ْـ]')


def normalize(text):
    t = _AR_DIACRITICS.sub('', str(text or '').lower())
    t = re.sub('[أإآٱ]', 'ا', t)
    t = t.replace('ة', 'ه').replace('ى', 'ي').replace('ؤ', 'و').replace('ئ', 'ي')
    return re.sub(r'\s+', ' ', t).strip()


def _texts(value):
    """Every string inside a content value (T dicts, lists, nested dicts)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _texts(v)


def search(query, screens, modules, limit=25):
    q = normalize(query)
    words = [w for w in q.split(' ') if len(w) > 1]
    if not words:
        return []
    results = []
    for s in screens:
        title = normalize(' '.join(_texts(s.get('title'))))
        summary = normalize(' '.join(_texts(s.get('summary'))))
        body = normalize(' '.join(_texts([s.get(f) for f in
                                          ('audience', 'steps', 'tabs', 'tips', 'faq', 'notes')])))
        mod = modules.get(s['module'], {})
        mtitle = normalize(' '.join(_texts(mod.get('title'))))
        score = 0
        for w in words:
            if w in title:
                score += 10
            elif w in mtitle:
                score += 6
            elif w in summary:
                score += 4
            elif w in body:
                score += 1
            else:
                score -= 3     # every word should appear somewhere
        if q in title:
            score += 15
        if score > 0:
            results.append((score, s))
    results.sort(key=lambda r: -r[0])
    return [s for _, s in results[:limit]]


# ── retrieval for «اسأل النظام» ───────────────────────────────────────────────
# A question is a sentence, not keywords: words that are not in an article must not
# sink it (unlike search()), and common words / prefixes are ignored.

_STOP = set(normalize(w) for w in (
    'ازاي إزاي كيف ايه إيه ماذا ما هو هي هل في من على عن الى إلى لو اعمل أعمل عايز عاوز ممكن '
    'يعني اللي التي الذي ده دي دا هذا هذه انا أنا احنا إحنا لما ليه لماذا امتى متى فين أين '
    'وانا مع او أو ثم بعد قبل كل بس لسه the a an is are how do does i to of in on for what why when where can my me'
).split())


def _stem(w):
    for p in ('وال', 'بال', 'لل', 'فال', 'كال', 'ال'):
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    if w[:1] in ('و', 'ب', 'ف') and len(w) >= 5:
        return w[1:]
    return w


def retrieve(question, screens, modules, limit=5, prefer=None):
    """Best-matching help articles for a free-text question (most relevant first).
    `prefer` = the screen the user is on; it gets a boost so "this screen" questions work."""
    words = [_stem(w) for w in normalize(question).split(' ') if len(w) > 1 and w not in _STOP]
    words = [w for w in words if len(w) > 1]
    scored = []
    for s in screens:
        title = normalize(' '.join(_texts(s.get('title'))))
        summary = normalize(' '.join(_texts(s.get('summary'))))
        body = normalize(' '.join(_texts([s.get(f) for f in
                                          ('audience', 'steps', 'tabs', 'tips', 'faq', 'notes')])))
        mtitle = normalize(' '.join(_texts(modules.get(s['module'], {}).get('title'))))
        score = 0
        for w in words:
            score += 6 if w in title else 4 if w in mtitle else 3 if w in summary else 1 if w in body else 0
        if prefer and s['key'] == prefer:
            score += 4
        if score >= 3:
            scored.append((score, s))
    scored.sort(key=lambda r: -r[0])
    return [s for _, s in scored[:limit]]


# ── «اعرض لي» flows ───────────────────────────────────────────────────────────
# A tour step: {target, text, route?, wait?, nav?}
#   route — the page the step lives on (router pattern); the runner navigates there when it
#           has no :params. Screen-tour steps without it live on the page the tour started on.
#   wait  — the step waits for the user to open that page (e.g. click a row → '/x/:id'),
#           then continues on it.
#   nav   — open the side-menu group of this path first (to point at its menu item).
# A screen may set `tour_continue: '<screen key>'`: after its own steps (the last one should
# `wait` for that screen), the other screen's tour follows — list → detail as one flow.

def tour_flow(key, screens, overrides=None):
    """The full tour run from a screen: its own (effective) steps, then the continued
    screen's steps. Each step carries `screen` and `i` (its index in that screen's own
    tour) so usage can point a trainer at the exact text to fix."""
    ov = overrides or {}
    s = screens[key]
    out = [{**st, 'screen': key, 'i': i} for i, st in enumerate(effective(s, ov.get(key)).get('tour') or [])]
    nxt = s.get('tour_continue')
    if out and nxt in screens:
        n = screens[nxt]
        route = n['routes'][0]
        out += [{**st, 'route': st.get('route') or route, 'screen': nxt, 'i': i}
                for i, st in enumerate(effective(n, ov.get(nxt)).get('tour') or [])]
    return out


def flows(modules):
    """{'flow:<module>.<key>': flow} for every module workflow tour."""
    return {f"flow:{m['key']}.{f['key']}": {**f, 'module': m['key']}
            for m in modules.values() for f in m.get('flows') or []}
