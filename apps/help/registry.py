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
        'tour':   [{'target': 'reservations-board-new',   # «اعرض لي»: data-tour anchor
                    'label': T(..),           # optional: the button text exactly as on screen
                    'text': T(..),            # what it does (required)
                    'when': T(..),            # optional: when to use it / what happens next
                    'warn': T(..),            # optional ⚠: the costly mistake (required for
                                              # push / approve / discount … anchors, see TOUR_WARN_WORDS)
                    'open_hint': T(..)}],     # optional: how to make the element appear
        'updated': '2026-10-10',              # bump when the text changes → "new" badge
    }]

A module may also have 'journeys' — guided walks through a whole process across screens:

    'journeys': [{'key': 'lifecycle', 'title': T(..), 'summary': T(..),
                  'shell': 'desktop',         # or 'mobile' (/m/…) — a journey never mixes them
                  'roles': ['pharmacist'],    # optional; empty = everyone
                  'steps': [{'screen': 'reservations.new', 'target': '…', 'perm': 'reservations',
                             'label' / 'text' / 'when' / 'warn' / 'open_hint': like tour steps}]}]

T(ar, en) is just {'ar': ar, 'en': en}. Every text must have both languages.
"""
import hashlib
import importlib
import json
import re
from functools import lru_cache

from .content import MODULE_FILES

EDITABLE_FIELDS = ('title', 'summary', 'audience', 'steps', 'tabs', 'tips', 'faq', 'notes', 'tour')

# «اعرض لي» steps: the text parts a trainer may edit (target / screen / perm follow the code)
TOUR_TEXT_KEYS = ('label', 'text', 'when', 'warn', 'open_hint')
TOUR_STEP_KEYS = {'target', *TOUR_TEXT_KEYS}
JOURNEY_STEP_KEYS = TOUR_STEP_KEYS | {'screen', 'perm'}
TOUR_LIMITS = {'label': 40, 'text': 160, 'when': 160, 'warn': 160, 'open_hint': 160}
# a step on a button whose anchor has one of these words must carry a ⚠ warning
TOUR_WARN_WORDS = {'push', 'post', 'approve', 'reject', 'discount', 'send', 'cancel', 'delete',
                   'close', 'settle', 'writeback', 'softech', 'flush'}
# modules whose tours are not rewritten to the rich format yet (limits / ⚠ / full
# coverage not enforced for them); each batch removes the modules it finishes
TOUR_PENDING = {
    'general', 'gamification', 'finance', 'insurance', 'commerce', 'hr', 'admin',
}

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


def _step_text(base, edited):
    """A step with the trainer's text parts on top (only the parts the trainer filled)."""
    if not isinstance(edited, dict):
        return dict(base)
    return {**base, **{k: edited[k] for k in TOUR_TEXT_KEYS if edited.get(k)}}


def _merge_tour(base_tour, edited_tour):
    """Like tabs: the steps and their targets follow the code; trainers edit the text."""
    edited = {t.get('target'): t for t in (edited_tour or []) if isinstance(t, dict)}
    return [_step_text(t, edited.get(t['target'])) for t in base_tour or []]


@lru_cache(maxsize=1)
def journeys():
    """→ {'<module>.<key>': journey} for every module journey, in file order."""
    modules, _ = load()
    out = {}
    for m in modules.values():
        for j in m.get('journeys') or []:
            jid = f"{m['key']}.{j['key']}"
            out[jid] = {**j, 'id': jid, 'module': m['key']}
    return out


def journey_routes(journey, screen):
    """The screen's routes in the journey's shell (desktop or /m/ mobile)."""
    mobile = journey.get('shell') == 'mobile'
    return [r for r in screen['routes'] if r.startswith('/m/') == mobile]


def journey_hash(journey):
    payload = {'title': journey.get('title'), 'summary': journey.get('summary'), 'steps': journey.get('steps')}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def journey_override_key(jid):
    return f'journey:{jid}'


def effective_journey(journey, override=None):
    """The journey as users see it. Trainers edit step text only; an edit applies to a
    step only while the same index still has the same target (code moved → dropped)."""
    j = dict(journey)
    data = getattr(override, 'data', None) or {}
    for f in ('title', 'summary'):
        if data.get(f):
            j[f] = data[f]
    edited = data.get('steps') or []
    steps = []
    for i, st in enumerate(journey['steps']):
        e = edited[i] if i < len(edited) and isinstance(edited[i], dict) else None
        steps.append(_step_text(st, e if e and e.get('target') == st['target'] else None))
    j['steps'] = steps
    return j


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
