"""
In-app help (apps/help).

Two kinds of tests:
  * content coverage — every staff route in frontend/src/App.jsx has help, every help
    route still exists, every text has Arabic AND English, and every status of a model
    a workflow points at is explained. These fail when a feature ships without help.
  * API — reading for everyone; trainer edits need help/edit and are versioned.
"""
import importlib
import re
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.help import registry
from apps.help.models import HelpEvent, HelpFeedback, HelpOverride, HelpRevision
from apps.tests.factories import make_branch, make_user

APP_JSX = Path(settings.BASE_DIR) / 'frontend' / 'src' / 'App.jsx'

# Public / customer-facing routes: no staff help panel there.
PUBLIC_PREFIXES = ('/login', '/notify', '/track', '/portal')


def _route_tags(src):
    """Yield ('open'|'self'|'close', attrs_text) for every <Route …> in order. Scans
    braces so the '>' inside element={<Page />} doesn't end the tag."""
    i = 0
    while True:
        o = src.find('<Route', i)
        c = src.find('</Route>', i)
        if o == -1 and c == -1:
            return
        if c != -1 and (o == -1 or c < o):
            yield 'close', ''
            i = c + len('</Route>')
            continue
        j, depth = o + len('<Route'), 0
        while j < len(src):
            ch = src[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            elif depth == 0 and src.startswith('/>', j):
                yield 'self', src[o:j]
                i = j + 2
                break
            elif depth == 0 and ch == '>':
                yield 'open', src[o:j]
                i = j + 1
                break
            j += 1
        else:
            return


def app_routes():
    """Full paths of every screen route in App.jsx (redirects and layouts skipped)."""
    src = APP_JSX.read_text(encoding='utf-8')
    stack, out = [], set()

    def full(attrs):
        m = re.search(r'\bpath="([^"]*)"', attrs)
        base = '/'.join(p.strip('/') for p in stack if p.strip('/'))
        if m is None:            # index route
            return '/' + base if base else '/'
        p = m.group(1)
        if p.startswith('/'):
            return p.rstrip('/') or '/'
        return '/' + '/'.join(x for x in (base, p.strip('/')) if x)

    for kind, attrs in _route_tags(src):
        if kind == 'close':
            stack.pop()
            continue
        path = full(attrs)
        if kind == 'open':
            m = re.search(r'\bpath="([^"]*)"', attrs)
            stack.append(path)
            continue
        if '<Navigate' in attrs:
            continue
        out.add(path)
    return {p for p in out if not p.startswith(PUBLIC_PREFIXES)}


def _resolve(dotted):
    """'apps.x.views.Class.ATTR' → the object (longest importable module prefix)."""
    parts = dotted.split('.')
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module('.'.join(parts[:i]))
        except ImportError:
            continue
        for p in parts[i:]:
            obj = getattr(obj, p)
        return obj
    raise ImportError(dotted)


def _walk_t(value, where):
    """Yield (where, T-dict) for every bilingual text."""
    if isinstance(value, dict):
        if set(value) == {'ar', 'en'}:
            yield where, value
            return
        for k, v in value.items():
            yield from _walk_t(v, f'{where}.{k}')
    elif isinstance(value, (list, tuple)):
        for n, v in enumerate(value):
            yield from _walk_t(v, f'{where}[{n}]')


class HelpContentCoverageTests(SimpleTestCase):
    def setUp(self):
        self.modules, self.screens = registry.load()

    def test_route_parser_sees_the_app(self):
        routes = app_routes()
        for p in ('/reservations', '/reservations/:id', '/m/pos', '/procurement/history', '/help'):
            self.assertIn(p, routes)
        self.assertNotIn('/procurement', routes)   # index is a redirect
        self.assertNotIn('/login', routes)

    def test_every_screen_route_has_help(self):
        covered = {r for s in self.screens.values() for r in s['routes']}
        missing = sorted(app_routes() - covered)
        self.assertEqual(missing, [], 'Routes without help — add them to apps/help/content/: '
                                      + ', '.join(missing))

    def test_no_help_for_routes_that_no_longer_exist(self):
        routes = app_routes()
        stale = sorted(f'{s["key"]}: {r}' for s in self.screens.values()
                       for r in s['routes'] if r not in routes)
        self.assertEqual(stale, [], 'Help points at routes that are gone: ' + ', '.join(stale))

    def test_each_route_has_one_screen(self):
        seen = {}
        for s in self.screens.values():
            for r in s['routes']:
                self.assertNotIn(r, seen, f'{r} is in both {seen.get(r)} and {s["key"]}')
                seen[r] = s['key']

    def test_every_text_is_bilingual(self):
        bad = []
        for m in self.modules.values():
            for where, t in _walk_t({k: v for k, v in m.items() if k != 'screens'}, m['key']):
                if not (t['ar'] or '').strip() or not (t['en'] or '').strip():
                    bad.append(where)
        for s in self.screens.values():
            for where, t in _walk_t(s, s['key']):
                if not (t['ar'] or '').strip() or not (t['en'] or '').strip():
                    bad.append(where)
        self.assertEqual(bad, [], 'Texts missing Arabic or English: ' + ', '.join(bad))

    def test_screen_shape(self):
        for key, s in self.screens.items():
            self.assertTrue(key.startswith(s['module'] + '.'), key)
            self.assertTrue(s['module'] in self.modules, key)
            self.assertTrue(s['routes'], key)
            self.assertIn('title', s, key)
            self.assertIn('summary', s, key)
            self.assertRegex(s.get('updated', ''), r'^\d{4}-\d{2}-\d{2}$', key)
            tab_keys = [t['key'] for t in s.get('tabs') or []]
            self.assertEqual(len(tab_keys), len(set(tab_keys)), f'{key}: duplicate tab keys')
            for t in s.get('tabs') or []:
                self.assertIn('title', t, key)
                self.assertIn('body', t, key)
            wf_keys = {w.get('key') for w in self.modules[s['module']].get('workflows') or []}
            for w in s.get('workflows') or []:
                self.assertTrue(w in wf_keys, f'{key}: unknown workflow key {w}')
            for r in s.get('related') or []:
                self.assertTrue(r in self.screens, f'{key}: related screen {r} does not exist')
            for g in [self.modules[s['module']].get('group')]:
                self.assertIn(g, [k for k, _, _ in registry.GROUPS], key)

    def _anchors(self):
        """Every data-tour anchor in frontend/src, plus the side-menu anchors Layout.jsx
        generates: nav-group-<group id> and nav-<path> (navTourId) for every NAV_GROUPS item,
        and mnav-<path> for the mobile tabs. Sets self.nav_paths (the menu's paths)."""
        src = Path(settings.BASE_DIR) / 'frontend' / 'src'
        anchors = set()
        for f in list(src.rglob('*.jsx')) + list(src.rglob('*.js')):
            anchors.update(re.findall(r'data-tour="([a-z0-9-]+)"', f.read_text(encoding='utf-8')))
        layout = (src / 'components' / 'Layout.jsx').read_text(encoding='utf-8')
        nav_block = layout[layout.index('const NAV_GROUPS'):]
        nav_block = nav_block[:nav_block.index('\n]\n')]
        self.nav_paths = set(re.findall(r"\bto:\s*'([^']+)'", nav_block))
        anchors |= {'nav-group-' + g for g in re.findall(r"\bid:\s*'([a-z0-9_-]+)'", nav_block)}
        anchors |= {'nav-' + re.sub(r'-$', '', re.sub(r'[^a-z0-9]+', '-', p.lstrip('/'))) for p in self.nav_paths}
        app_src = APP_JSX.read_text(encoding='utf-8')
        tabs = app_src[app_src.index('MOBILE_TABS'):]
        tabs = tabs[:tabs.index('\n]\n')]
        anchors |= {'mnav-' + re.sub(r'-$', '', re.sub(r'[^a-z0-9]+', '-', re.sub(r'^/m/?', '', p)))
                    for p in re.findall(r"\bto:\s*'(/m/[^']*)'", tabs)}
        return anchors

    def _check_rich_step(self, where, st, allowed):
        """Rich-step rules for modules out of TOUR_PENDING: only known keys, every text
        part bilingual and short, and a ⚠ warning on costly buttons."""
        self.assertLessEqual(set(st), allowed, f'{where}: unknown step keys')
        for k in registry.TOUR_TEXT_KEYS:
            if k in st:
                for lang in ('ar', 'en'):
                    self.assertTrue((st[k].get(lang) or '').strip(), f'{where}.{k}: missing {lang}')
                    self.assertLessEqual(len(st[k][lang]), registry.TOUR_LIMITS[k],
                                         f'{where}.{k}.{lang}: longer than {registry.TOUR_LIMITS[k]}')
        words = set(st['target'].split('-')) & registry.TOUR_WARN_WORDS
        if words:
            self.assertIn('warn', st, f'{where}: anchor says {sorted(words)} — add a ⚠ warn')

    def test_tour_targets_exist_in_the_frontend(self):
        """«اعرض لي» steps highlight [data-tour="…"] elements — each must exist in the code,
        so renaming/removing an anchor fails CI instead of silently breaking a tour.
        Step pages (route / wait) must be real routes, `nav` a real menu path, and a
        screen's `tour_continue` must follow a last step that waits for that screen."""
        anchors = self._anchors()
        routes = app_routes()

        def check(where, steps, allowed):
            bad = []
            self.assertTrue(steps, where)
            for i, st in enumerate(steps):
                w = f'{where}[{i}]'
                self.assertTrue({'target', 'text'} <= set(st) <= allowed, f'{w}: {sorted(set(st) - allowed)}')
                if st['target'] not in anchors:
                    bad.append(f'{w}: {st["target"]}')
                for f in ('route', 'wait'):
                    if st.get(f) and st[f] not in routes:
                        bad.append(f'{w}: {f} {st[f]} is not a route in App.jsx')
                if st.get('nav') and st['nav'] not in self.nav_paths:
                    bad.append(f'{w}: nav {st["nav"]} is not a side-menu item')
            return bad

        missing = []
        for key, s in self.screens.items():
            if s.get('tour'):
                missing += check(f'{key}.tour', s['tour'], registry.TOUR_STEP_KEYS)
            nxt = s.get('tour_continue')
            if nxt:
                self.assertIn(nxt, self.screens, f'{key}: tour_continue')
                self.assertTrue(self.screens[nxt].get('tour'), f'{key}: {nxt} has no tour to continue with')
                self.assertIn(s['tour'][-1].get('wait'), self.screens[nxt]['routes'],
                              f'{key}: last step must wait for a route of {nxt}')
        for m in self.modules.values():
            for f in m.get('flows') or []:
                self.assertTrue(f.get('key') and f.get('title'), m['key'])
                missing += check(f"{m['key']}.flows.{f['key']}", f['steps'], registry.TOUR_STEP_KEYS)
        self.assertEqual(missing, [], 'Broken tour steps')
        no_tour = [k for k, s in self.screens.items() if not s.get('tour')]
        self.assertEqual(no_tour, [], 'Every screen needs a «اعرض لي» tour (add data-tour anchors + tour steps)')

    def test_rich_tours_in_finished_modules(self):
        """Modules out of TOUR_PENDING: every screen has a tour of rich steps."""
        self.assertLessEqual(registry.TOUR_PENDING, set(self.modules), 'TOUR_PENDING has unknown modules')
        for key, s in self.screens.items():
            if s['module'] in registry.TOUR_PENDING:
                continue
            self.assertTrue(s.get('tour'), f'{key}: no «اعرض لي» tour')
            for i, st in enumerate(s['tour']):
                self._check_rich_step(f'{key}.tour[{i}]', st, registry.TOUR_STEP_KEYS)

    def test_journeys_valid(self):
        """Module journeys: real screens and anchors, one shell, valid roles / perms, and a
        hint wherever the user must open a record (no param-free route to go to)."""
        from apps.users.models import MODULE_CHOICES, ROLE_CHOICES
        anchors = self._anchors()
        roles = {r for r, _ in ROLE_CHOICES}
        perms = {m for m, _ in MODULE_CHOICES}
        for jid, j in registry.journeys().items():
            self.assertIn(j.get('shell', 'desktop'), ('desktop', 'mobile'), jid)
            self.assertLessEqual(set(j.get('roles') or []), roles, f'{jid}: unknown role')
            self.assertGreaterEqual(len(j['steps']), 3, f'{jid}: a journey needs at least 3 steps')
            for i, st in enumerate(j['steps']):
                where = f'{jid}.steps[{i}]'
                self.assertIn(st.get('screen'), self.screens, f'{where}: unknown screen')
                self.assertIn(st['target'], anchors, f'{where}: no data-tour anchor')
                routes = registry.journey_routes(j, self.screens[st['screen']])
                self.assertTrue(routes, f'{where}: screen has no {j.get("shell", "desktop")} route')
                if all(':' in r for r in routes):
                    self.assertIn('open_hint', st, f'{where}: record page — add open_hint')
                if 'perm' in st:
                    self.assertIn(st['perm'], perms, f'{where}: unknown RBAC module')
                self._check_rich_step(where, st, registry.JOURNEY_STEP_KEYS)

    def test_finished_modules_have_journeys(self):
        for key, m in self.modules.items():
            if key not in registry.TOUR_PENDING:
                self.assertTrue(m.get('journeys'), f'{key}: no journey (رحلة عمل)')

    def test_every_step_names_its_element(self):
        """Every «اعرض لي» / journey step shows the element's on-screen name in bold
        («label»), so people can find it — and none is left with neither a name nor a
        «متى؟» (batch 7)."""
        missing = [f'{k}.tour[{i}]' for k, s in self.screens.items()
                   for i, st in enumerate(s.get('tour') or []) if 'label' not in st]
        missing += [f'{jid}.steps[{i}]' for jid, j in registry.journeys().items()
                    for i, st in enumerate(j['steps']) if 'label' not in st]
        self.assertEqual(missing, [], 'Steps without a «label» (the element\'s name as on screen)')

    def test_every_module_has_a_brief(self):
        """«🚀 جولة في النظام» shows each module's one-line brief — short and bilingual."""
        for key, m in self.modules.items():
            b = m.get('brief') or {}
            for lang in ('ar', 'en'):
                self.assertTrue((b.get(lang) or '').strip(), f'{key}: brief missing {lang}')
                self.assertLessEqual(len(b[lang]), registry.TOUR_LIMITS['text'], f'{key}: brief.{lang} too long')

    def test_product_tours_valid(self):
        """Every role's product tour (repo paths, both shells) follows the journey rules:
        real screens and anchors, the shell's routes, rich-step limits, ≥3 steps."""
        from apps.help import training
        from apps.help.content import onboarding
        anchors = self._anchors()
        built = 0
        for role in onboarding.ROLE_PATHS:
            for shell in training.PRODUCT_SHELLS:
                j = training.product_tour(role, shell, training.base_path(role))
                if j is None:
                    continue
                built += 1
                jid = j['id']
                self.assertGreaterEqual(len(j['steps']), 3, jid)
                mods = [self.screens[st['screen']]['module'] for st in j['steps'][1:-1]]
                self.assertEqual(len(mods), len(set(mods)), f'{jid}: a module stops twice')
                for i, st in enumerate(j['steps']):
                    where = f'{jid}.steps[{i}]'
                    self.assertIn(st['screen'], self.screens, where)
                    self.assertIn(st['target'], anchors, f'{where}: no data-tour anchor')
                    self.assertTrue(registry.journey_routes(j, self.screens[st['screen']]), f'{where}: no {shell} route')
                    self._check_rich_step(where, st, registry.JOURNEY_STEP_KEYS)
        self.assertGreater(built, len(onboarding.ROLE_PATHS) - 1, 'most roles should have a desktop tour')

    def test_workflow_explains_every_status(self):
        for m in self.modules.values():
            for wf in m.get('workflows') or []:
                keys = [st['key'] for st in wf['states']]
                for st in wf['states']:
                    for n in st.get('next') or []:
                        self.assertIn(n, keys, f'{m["key"]}: {st["key"]} → unknown {n}')
                if wf.get('transitions'):
                    obj = _resolve(wf['transitions'])
                    for st in wf['states']:
                        self.assertEqual(
                            set(st.get('next') or []), set(obj.get(st['key'], set())),
                            f'{m["key"]}: next steps of {st["key"]} differ from {wf["transitions"]}')
                if not wf.get('model'):
                    continue
                model = django_apps.get_model(wf['model'])
                field = model._meta.get_field(wf['field'])
                choices = {str(v) for v, _ in field.flatchoices}
                self.assertEqual(
                    set(keys), choices,
                    f'{m["key"]}: workflow for {wf["model"]}.{wf["field"]} must explain exactly '
                    f'its statuses (missing {sorted(choices - set(keys))}, '
                    f'unknown {sorted(set(keys) - choices)})')


class HelpApiTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.key = 'general.help_center'

    def _client(self, role):
        user, profile, _ = make_user(f'help_{role}', role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c, profile

    def test_index_and_detail_open_to_everyone(self):
        c, _ = self._client('viewer')
        r = c.get('/api/help/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['can_edit'])
        self.assertTrue(any(s['key'] == self.key for s in r.json()['screens']))
        r = c.get(f'/api/help/screens/{self.key}/?tab=browse')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['title']['ar'], 'دليل الاستخدام')
        self.assertNotIn('base', r.json())
        self.assertEqual(HelpEvent.objects.filter(kind='open', screen_key=self.key, tab='browse').count(), 1)

    def test_unknown_screen_404(self):
        c, _ = self._client('viewer')
        self.assertEqual(c.get('/api/help/screens/nope.nope/').status_code, 404)

    def test_viewer_cannot_edit(self):
        c, _ = self._client('pharmacist')
        r = c.put(f'/api/help/screens/{self.key}/', {'data': {'summary': {'ar': 'x', 'en': ''}}}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(HelpOverride.objects.exists())

    def test_granted_role_can_edit(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='supervisor', module='help', action='edit')
        c, _ = self._client('supervisor')
        r = c.put(f'/api/help/screens/{self.key}/',
                  {'data': {'summary': {'ar': 'شرح المدرب', 'en': ''}}, 'note': 'أوضح'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_trainer_edit_versioned_and_revert(self):
        c, _ = self._client('admin')
        tabs = [{'key': 'browse', 'title': {'ar': 'تصفح', 'en': 'Browse'},
                 'body': {'ar': 'نص المدرب للتبويب', 'en': 'Trainer text'}},
                {'key': 'invented', 'title': {'ar': 'ج', 'en': 'n'}, 'body': {'ar': 'ج', 'en': 'n'}}]
        r = c.put(f'/api/help/screens/{self.key}/',
                  {'data': {'summary': {'ar': 'شرح المدرب', 'en': 'Trainer summary'}, 'tabs': tabs},
                   'note': 'تبسيط'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body['summary']['ar'], 'شرح المدرب')
        self.assertFalse(body['override']['base_changed'])
        tab_keys = [t['key'] for t in body['tabs']]
        self.assertNotIn('invented', tab_keys)                 # tabs follow the code
        self.assertEqual(body['tabs'][0]['body']['ar'], 'نص المدرب للتبويب')
        self.assertEqual(len(tab_keys), len(registry.load()[1][self.key]['tabs']))

        rev = HelpRevision.objects.get()
        self.assertEqual(rev.action, 'save')
        self.assertNotEqual(rev.before['summary'], rev.after['summary'])

        # everyone now reads the trainer's text
        v, _ = self._client('viewer')
        self.assertEqual(v.get(f'/api/help/screens/{self.key}/').json()['summary']['ar'], 'شرح المدرب')

        r = c.delete(f'/api/help/screens/{self.key}/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(HelpOverride.objects.exists())
        self.assertEqual(HelpRevision.objects.filter(action='revert').count(), 1)
        self.assertEqual(len(c.get(f'/api/help/screens/{self.key}/revisions/').json()), 2)

    def test_base_changed_flag(self):
        HelpOverride.objects.create(screen_key=self.key, data={}, base_hash='old')
        c, _ = self._client('admin')
        self.assertTrue(c.get(f'/api/help/screens/{self.key}/').json()['override']['base_changed'])

    def test_invalid_edit_rejected(self):
        c, _ = self._client('admin')
        for data in ({'title': {'ar': '', 'en': 'x'}}, {'steps': 'نص'}, {'faq': [{'q': {'ar': 'س', 'en': ''}}]},
                     {'tabs': [{'key': 'browse'}]}, 'not a dict'):
            r = c.put(f'/api/help/screens/{self.key}/', {'data': data}, format='json')
            self.assertEqual(r.status_code, 400, data)
        self.assertFalse(HelpOverride.objects.exists())

    def test_search_arabic_normalized_and_logged(self):
        c, _ = self._client('viewer')
        r = c.get('/api/help/search/?q=الاستخدام')
        self.assertTrue(any(h['key'] == self.key for h in r.json()))
        r = c.get('/api/help/search/?q=دليل الأستخدام')          # hamza variant
        self.assertTrue(any(h['key'] == self.key for h in r.json()))
        c.get('/api/help/search/?q=zzzqqq')
        self.assertEqual(HelpEvent.objects.get(query='zzzqqq').results, 0)

    def test_feedback_and_trainer_views(self):
        v, _ = self._client('viewer')
        r = v.post('/api/help/feedback/', {'screen_key': self.key, 'helpful': False,
                                           'comment': 'مش واضح', 'tab': 'browse'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(v.post('/api/help/feedback/', {'screen_key': 'x.y', 'helpful': True},
                                format='json').status_code, 400)
        self.assertEqual(v.post('/api/help/feedback/', {'screen_key': self.key, 'helpful': 'yes'},
                                format='json').status_code, 400)
        self.assertEqual(v.get('/api/help/feedback/').status_code, 403)
        self.assertEqual(v.get('/api/help/stats/').status_code, 403)

        a, _ = self._client('admin')
        rows = a.get('/api/help/feedback/?open=1').json()
        self.assertEqual(len(rows), 1)
        a.post(f'/api/help/feedback/{rows[0]["id"]}/resolve/', {}, format='json')
        self.assertTrue(HelpFeedback.objects.get().resolved)
        stats = a.get('/api/help/stats/').json()
        self.assertEqual(stats['votes'][0]['down'], 1)
        self.assertEqual(stats['open_comments'], 0)

    def test_anonymous_rejected(self):
        self.assertIn(APIClient().get('/api/help/').status_code, (401, 403))


class OnboardingContentTests(SimpleTestCase):
    """content/onboarding.py must point at real screens/modules and grade sanely."""

    def test_every_role_has_a_path_of_real_screens(self):
        from apps.help.content import onboarding
        from apps.users.models import ROLE_CHOICES
        _, screens = registry.load()
        self.assertEqual(set(onboarding.ROLE_PATHS), {r for r, _ in ROLE_CHOICES})
        for role, keys in onboarding.ROLE_PATHS.items():
            missing = [k for k in keys if k not in screens]
            self.assertFalse(missing, f'{role}: unknown screens {missing}')
            self.assertEqual(len(keys), len(set(keys)), f'{role}: duplicate screens')

    def test_quizzes_valid_and_bilingual(self):
        from apps.help.content import onboarding
        modules, _ = registry.load()
        self.assertFalse(set(onboarding.QUIZZES) - set(modules))
        for mk, qs in onboarding.QUIZZES.items():
            self.assertTrue(qs, mk)
            for i, q in enumerate(qs):
                self.assertGreaterEqual(len(q['options']), 2, f'{mk}[{i}]')
                self.assertTrue(0 <= q['answer'] < len(q['options']), f'{mk}[{i}] answer index')
                for where, t in _walk_t(q, f'{mk}[{i}]'):
                    self.assertTrue(t['ar'].strip() and t['en'].strip(), where)

    def test_every_path_module_has_a_quiz(self):
        from apps.help.content import onboarding
        for role, keys in onboarding.ROLE_PATHS.items():
            mods = {k.split('.')[0] for k in keys}
            self.assertFalse(mods - set(onboarding.QUIZZES), f'{role}: modules without quiz')


class OnboardingApiTests(TestCase):
    def setUp(self):
        self.branch = make_branch()

    def _client(self, role, name=None):
        user, profile, _ = make_user(name or f'ob_{role}', role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c, profile

    def test_path_learn_and_changed(self):
        from apps.help.content import onboarding
        from apps.help.models import HelpLearned
        c, profile = self._client('pharmacist')
        r = c.get('/api/help/onboarding/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([i['key'] for i in body['path']], onboarding.ROLE_PATHS['pharmacist'])
        self.assertEqual(body['progress']['learned'], 0)
        self.assertEqual(body['roles'], ['pharmacist'])
        key = body['path'][0]['key']
        self.assertEqual(c.post('/api/help/onboarding/learned/', {'screen_key': key}, format='json').status_code, 200)
        body = c.get('/api/help/onboarding/').json()
        self.assertEqual(body['path'][0]['state'], 'done')
        self.assertEqual(body['progress']['learned'], 1)
        # the help text changes after it was learned → asks to re-read
        HelpLearned.objects.filter(staff=profile, screen_key=key).update(version='2000-01-01')
        self.assertEqual(c.get('/api/help/onboarding/').json()['path'][0]['state'], 'changed')
        c.post('/api/help/onboarding/learned/', {'screen_key': key, 'done': False}, format='json')
        self.assertFalse(HelpLearned.objects.filter(staff=profile).exists())
        self.assertEqual(c.post('/api/help/onboarding/learned/', {'screen_key': 'x.y'}, format='json').status_code, 400)

    def test_role_preview_only_for_trainers(self):
        c, _ = self._client('pharmacist')
        self.assertEqual(c.get('/api/help/onboarding/?role=admin').json()['role'], 'pharmacist')
        c, _ = self._client('admin')
        self.assertEqual(c.get('/api/help/onboarding/?role=delivery').json()['role'], 'delivery')

    def test_quiz_hides_answers_and_grades_on_server(self):
        from apps.help.content import onboarding
        from apps.help.models import HelpQuizAttempt
        c, _ = self._client('pharmacist')
        r = c.get('/api/help/quizzes/pos/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('answer', str(r.json()))
        self.assertNotIn('explain', str(r.json()))
        qs = onboarding.QUIZZES['pos']
        right = [q['answer'] for q in qs]
        r = c.post('/api/help/quizzes/pos/submit/', {'answers': right}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()['passed'])
        self.assertEqual(r.json()['score'], len(qs))
        wrong = [(q['answer'] + 1) % len(q['options']) for q in qs]
        r = c.post('/api/help/quizzes/pos/submit/', {'answers': wrong}, format='json')
        self.assertFalse(r.json()['passed'])
        self.assertEqual(r.json()['score'], 0)
        self.assertEqual(HelpQuizAttempt.objects.count(), 2)
        # best attempt is what counts
        best = c.get('/api/help/onboarding/').json()
        self.assertTrue(next(q for q in best['quizzes'] if q['module'] == 'pos')['best']['passed'])
        self.assertEqual(c.post('/api/help/quizzes/pos/submit/', {'answers': [0]}, format='json').status_code, 400)
        self.assertEqual(c.get('/api/help/quizzes/nope/').status_code, 404)

    def test_team_view_needs_help_edit(self):
        c, _ = self._client('pharmacist')
        self.assertEqual(c.get('/api/help/onboarding/team/').status_code, 403)
        c, _ = self._client('admin')
        r = c.get('/api/help/onboarding/team/?role=pharmacist')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json())
        self.assertTrue(all(row['role'] == 'pharmacist' for row in r.json()))

    def test_manual_by_role_and_module(self):
        from apps.help.content import onboarding
        c, _ = self._client('pharmacist')
        r = c.get('/api/help/manual/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['role'], 'pharmacist')
        self.assertEqual([s['key'] for s in body['screens']], onboarding.ROLE_PATHS['pharmacist'])
        self.assertEqual(len({m['key'] for m in body['modules']}), len(body['modules']))
        for s in body['screens']:   # role-limited steps only
            for st in s['steps'] + s['tips']:
                if isinstance(st, dict) and 'roles' in st:
                    self.assertIn('pharmacist', st['roles'])
        r = c.get('/api/help/manual/?module=transfers')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(s['module'] == 'transfers' for s in r.json()['screens']))
        self.assertEqual(c.get('/api/help/manual/?module=nope').status_code, 404)
        self.assertEqual(c.get('/api/help/manual/?role=nope').status_code, 404)


class AskTests(TestCase):
    """«اسأل النظام»: grounded in the help text, citations limited to what was sent,
    works without a model (falls back to the articles), rate limited, logged."""

    def setUp(self):
        user, self.profile, _ = make_user('ask_user', role='pharmacist', branch=make_branch())
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

    def test_retrieve_handles_sentences(self):
        modules, screens = registry.load()
        hits = registry.retrieve('ازاي أعمل طلب تحويل لفرع تاني؟', list(screens.values()), modules)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['module'], 'transfers')

    def test_no_model_falls_back_to_articles(self):
        from unittest import mock
        with mock.patch('apps.help.ask.call_llm', return_value=None):
            r = self.c.post('/api/help/ask/', {'question': 'ازاي أعمل حجز جديد؟'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['answer'])
        self.assertFalse(r.json()['ai'])
        self.assertTrue(r.json()['articles'])
        self.assertEqual(HelpEvent.objects.filter(kind='ask').count(), 1)

    def test_answer_only_cites_sent_articles(self):
        from unittest import mock
        captured = {}

        def fake(prompt):
            captured['prompt'] = prompt
            return '```json\n{"answer": "1. اضغط «حجز جديد»", "found": true, "sources": ["reservations.new", "made.up"]}\n```'
        with mock.patch('apps.help.ask.call_llm', side_effect=fake):
            r = self.c.post('/api/help/ask/', {'question': 'ازاي أعمل حجز جديد؟', 'screen_key': 'reservations.board'},
                            format='json')
        body = r.json()
        self.assertTrue(body['ai'] and body['found'])
        self.assertIn('حجز جديد', body['answer'])
        self.assertEqual([s['key'] for s in body['sources']], ['reservations.new'] if '[reservations.new]' in captured['prompt'] else [])
        self.assertIn('ONLY the help articles', captured['prompt'])
        self.assertIn('Never state prices', captured['prompt'])

    def test_rate_limit_and_validation(self):
        from unittest import mock
        from apps.help.views import ASK_PER_HOUR
        self.assertEqual(self.c.post('/api/help/ask/', {'question': 'x'}, format='json').status_code, 400)
        HelpEvent.objects.bulk_create([HelpEvent(kind='ask', staff=self.profile, query='q') for _ in range(ASK_PER_HOUR)])
        with mock.patch('apps.help.ask.call_llm', return_value=None):
            r = self.c.post('/api/help/ask/', {'question': 'ازاي أعمل حجز؟'}, format='json')
        self.assertEqual(r.status_code, 429)


class TrainingEditTests(TestCase):
    """Trainers edit tour text, role paths and quizzes in the app; every change is
    versioned and revertible; learners immediately get the edited version."""

    def setUp(self):
        self.branch = make_branch()

    def _client(self, role, name):
        user, profile, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c

    def test_tour_text_editable_targets_fixed(self):
        c = self._client('admin', 'tr_admin')
        _, screens = registry.load()
        base = screens['reservations.board']['tour']
        edited = [{'target': base[0]['target'], 'text': {'ar': 'نص المدرب', 'en': 'Trainer text'}},
                  {'target': 'made-up', 'text': {'ar': 'x', 'en': 'x'}}]
        r = c.put('/api/help/screens/reservations.board/', {'data': {'tour': edited}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        tour = r.json()['tour']
        self.assertEqual([t['target'] for t in tour], [t['target'] for t in base])
        self.assertEqual(tour[0]['text']['ar'], 'نص المدرب')
        self.assertEqual(tour[1]['text'], base[1]['text'])
        bad = c.put('/api/help/screens/reservations.board/', {'data': {'tour': [{'target': 'x'}]}}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_tour_explanation_editable(self):
        """`more` (the longer explanation under a step's headline): the trainer's when they
        wrote one, else the repo's; a wrong shape is refused."""
        c = self._client('admin', 'tr_more')
        _, screens = registry.load()
        base = screens['reservations.board']['tour']
        edited = [{'target': base[0]['target'], 'text': base[0]['text'],
                   'more': {'ar': 'شرح المدرب الأطول', 'en': 'Trainer explanation'}},
                  {'target': base[1]['target'], 'text': base[1]['text'], 'more': {'ar': '', 'en': ''}}]
        r = c.put('/api/help/screens/reservations.board/', {'data': {'tour': edited}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        tour = r.json()['tour']
        self.assertEqual(tour[0]['more']['ar'], 'شرح المدرب الأطول')
        self.assertEqual(tour[1].get('more'), base[1].get('more'))          # empty → repo text kept
        bad = [{'target': base[0]['target'], 'text': base[0]['text'], 'more': 'نص'}]
        self.assertEqual(c.put('/api/help/screens/reservations.board/', {'data': {'tour': bad}},
                               format='json').status_code, 400)
        # workflow tours too
        url = '/api/help/training/flow/reservations.lifecycle/'
        cur = c.get(url).json()['current']
        cur['steps'][1]['more'] = {'ar': 'شرح أطول للوحة', 'en': 'Longer board text'}
        self.assertEqual(c.put(url, {'data': cur}, format='json').status_code, 200)
        f = next(x for x in c.get('/api/help/modules/reservations/').json()['flows']
                 if x['id'] == 'flow:reservations.lifecycle')
        self.assertEqual(f['steps'][1]['more']['ar'], 'شرح أطول للوحة')

    def test_path_edit_applies_and_reverts(self):
        from apps.help.content import onboarding
        from apps.help.models import HelpRevision
        t = self._client('admin', 'tr_admin2')
        learner = self._client('salesperson', 'tr_sales')
        self.assertEqual(learner.get('/api/help/training/path/salesperson/').status_code, 403)
        new = ['general.help_center', 'pos.order', 'customers.mobile']
        r = t.put('/api/help/training/path/salesperson/', {'data': {'screens': new}, 'note': 'أقصر'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['current'], new)
        self.assertEqual([i['key'] for i in learner.get('/api/help/onboarding/').json()['path']], new)
        self.assertEqual(t.put('/api/help/training/path/salesperson/', {'data': {'screens': ['nope.x']}},
                               format='json').status_code, 400)
        r = t.delete('/api/help/training/path/salesperson/', {'note': 'رجوع'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i['key'] for i in learner.get('/api/help/onboarding/').json()['path']],
                         onboarding.ROLE_PATHS['salesperson'])
        self.assertEqual(HelpRevision.objects.filter(screen_key='path:salesperson').count(), 2)
        self.assertEqual(t.get('/api/help/training/path/nope/').status_code, 404)

    def test_quiz_edit_grades_with_new_answers(self):
        t = self._client('admin', 'tr_admin3')
        learner = self._client('pharmacist', 'tr_ph')
        q = {'q': {'ar': 'سؤال؟', 'en': 'Q?'}, 'options': [{'ar': 'أ', 'en': 'A'}, {'ar': 'ب', 'en': 'B'}],
             'answer': 1, 'explain': {'ar': 'لأن', 'en': 'Because'}}
        r = t.put('/api/help/training/quiz/pos/', {'data': {'questions': [q]}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(t.get('/api/help/training/quiz/pos/').json()['current'][0]['answer'], 1)
        g = learner.get('/api/help/quizzes/pos/').json()
        self.assertEqual(len(g['questions']), 1)
        self.assertNotIn('answer', str(g))
        res = learner.post('/api/help/quizzes/pos/submit/', {'answers': [1]}, format='json').json()
        self.assertTrue(res['passed'])
        bad = dict(q, answer=5)
        self.assertEqual(t.put('/api/help/training/quiz/pos/', {'data': {'questions': [bad]}},
                               format='json').status_code, 400)
        # a trainer can add a quiz to a module that has none in the repo
        from apps.help.content import onboarding
        modules, _ = registry.load()
        free = next(m for m in modules if m not in onboarding.QUIZZES) if set(modules) - set(onboarding.QUIZZES) else None
        if free:
            t.put(f'/api/help/training/quiz/{free}/', {'data': {'questions': [q]}}, format='json')
            self.assertEqual(learner.get(f'/api/help/quizzes/{free}/').status_code, 200)


class TrainingNotifyTests(TestCase):
    """Path additions notify the role; a changed quiz voids old passes (retake) and
    notifies the people who had passed it."""

    def setUp(self):
        self.branch = make_branch()

    def _client(self, role, name):
        user, profile, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c, profile

    def test_path_addition_notifies_role(self):
        from apps.help.content import onboarding
        from apps.notifications.models import Notification
        t, _ = self._client('admin', 'nt_admin')
        _, seller = self._client('salesperson', 'nt_sales')
        _, other = self._client('pharmacist', 'nt_ph')
        new = onboarding.ROLE_PATHS['salesperson'] + ['tasks.list']
        r = t.put('/api/help/training/path/salesperson/', {'data': {'screens': new}}, format='json')
        self.assertEqual(r.json()['notified'], 1)
        self.assertTrue(Notification.objects.filter(recipient=seller, title__contains='مسارك').exists())
        self.assertFalse(Notification.objects.filter(recipient=other, title__contains='مسارك').exists())
        # removing screens is not news
        r = t.put('/api/help/training/path/salesperson/', {'data': {'screens': new[:3]}}, format='json')
        self.assertEqual(r.json()['notified'], 0)

    def test_quiz_change_voids_pass_and_notifies(self):
        from apps.help.content import onboarding
        from apps.notifications.models import Notification
        t, _ = self._client('admin', 'nq_admin')
        c, ph = self._client('pharmacist', 'nq_ph')
        right = [q['answer'] for q in onboarding.QUIZZES['pos']]
        self.assertTrue(c.post('/api/help/quizzes/pos/submit/', {'answers': right}, format='json').json()['passed'])
        best = lambda: next(q for q in c.get('/api/help/onboarding/').json()['quizzes'] if q['module'] == 'pos')['best']
        self.assertTrue(best()['passed'])
        q = {'q': {'ar': 'سؤال جديد؟', 'en': 'New?'}, 'options': [{'ar': 'أ', 'en': 'A'}, {'ar': 'ب', 'en': 'B'}],
             'answer': 0, 'explain': {'ar': 'لأن', 'en': 'Because'}}
        r = t.put('/api/help/training/quiz/pos/', {'data': {'questions': [q]}}, format='json')
        self.assertEqual(r.json()['notified'], 1)
        self.assertTrue(Notification.objects.filter(recipient=ph, title__contains='أعد الاختبار').exists())
        b = best()
        self.assertTrue(b['stale'])
        self.assertFalse(b['passed'])
        prog = c.get('/api/help/onboarding/').json()['progress']
        self.assertEqual(prog['quizzes_passed'], 0)
        # retake on the new version counts again
        c.post('/api/help/quizzes/pos/submit/', {'answers': [0]}, format='json')
        self.assertTrue(best()['passed'])
        self.assertFalse(best()['stale'])
        # reverting to the original changes the quiz again → the first pass counts again, no one to tell
        r = t.delete('/api/help/training/quiz/pos/', {}, format='json')
        self.assertTrue(best()['passed'])


class AnnounceChangesTests(TestCase):
    """The hourly check notifies repo (developer) changes to paths and quizzes once,
    and does not repeat what a trainer's save already announced."""

    def setUp(self):
        self.branch = make_branch()

    def _client(self, role, name):
        user, profile, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c, profile

    def test_repo_path_change_notified_once(self):
        from unittest import mock
        from apps.help import training
        from apps.help.content import onboarding
        from apps.notifications.models import Notification
        _, seller = self._client('salesperson', 'an_sales')
        self.assertEqual(training.announce_changes(), {'paths': 0, 'quizzes': 0})   # first run records
        new_paths = {**onboarding.ROLE_PATHS, 'salesperson': onboarding.ROLE_PATHS['salesperson'] + ['tasks.list']}
        with mock.patch.object(onboarding, 'ROLE_PATHS', new_paths):
            self.assertEqual(training.announce_changes()['paths'], 1)
            self.assertEqual(training.announce_changes()['paths'], 0)
        self.assertEqual(Notification.objects.filter(recipient=seller, title__contains='مسارك').count(), 1)

    def test_repo_quiz_change_notifies_passers(self):
        from unittest import mock
        from apps.help import training
        from apps.help.content import onboarding
        c, ph = self._client('pharmacist', 'an_ph')
        right = [q['answer'] for q in onboarding.QUIZZES['pos']]
        c.post('/api/help/quizzes/pos/submit/', {'answers': right}, format='json')
        training.announce_changes()
        changed = {**onboarding.QUIZZES, 'pos': onboarding.QUIZZES['pos'][:1]}
        with mock.patch.object(onboarding, 'QUIZZES', changed):
            self.assertEqual(training.announce_changes()['quizzes'], 1)
            self.assertEqual(training.announce_changes()['quizzes'], 0)

    def test_trainer_save_not_announced_twice(self):
        from apps.help import training
        from apps.help.content import onboarding
        training.announce_changes()
        t, _ = self._client('admin', 'an_admin')
        self._client('salesperson', 'an_sales2')
        new = onboarding.ROLE_PATHS['salesperson'] + ['tasks.list']
        r = t.put('/api/help/training/path/salesperson/', {'data': {'screens': new}}, format='json')
        self.assertEqual(r.json()['notified'], 1)
        self.assertEqual(training.announce_changes(), {'paths': 0, 'quizzes': 0})


class HelpUsageTests(TestCase):
    def setUp(self):
        branch = make_branch()
        u1, _, _ = make_user('us_admin', role='admin', branch=branch)
        u2, _, _ = make_user('us_ph', role='pharmacist', branch=branch)
        self.admin, self.ph = APIClient(), APIClient()
        self.admin.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u1)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')

    def test_tour_events_and_report(self):
        _, screens = registry.load()
        n = len(registry.tour_flow('reservations.board', screens))   # board + continued detail steps
        self.assertGreater(n, len(screens['reservations.board']['tour']))
        ok = self.ph.post('/api/help/tour-event/', {'screen_key': 'reservations.board', 'reached': n, 'done': True}, format='json')
        self.assertEqual(ok.status_code, 201)
        self.ph.post('/api/help/tour-event/', {'screen_key': 'reservations.board', 'reached': 2, 'done': True}, format='json')
        self.assertEqual(self.ph.post('/api/help/tour-event/', {'screen_key': 'nope.screen'}, format='json').status_code, 400)
        self.ph.get('/api/help/screens/reservations.board/')
        self.assertEqual(self.ph.get('/api/help/usage/').status_code, 403)
        r = self.admin.get('/api/help/usage/?days=7').json()
        row = next(t for t in r['tours'] if t['screen_key'] == 'reservations.board')
        self.assertEqual((row['runs'], row['done'], row['done_pct'], row['common_stop']), (2, 1, 50, 2))
        # the step people did not get past (index 2) maps back to its own screen's text
        self.assertEqual(row['weak_step'], {'screen': 'reservations.board', 'i': 2})
        unopened = {u['screen_key'] for u in r['unopened']}
        self.assertNotIn('reservations.board', unopened)
        self.assertIn('pos.order', unopened)
        pos = next(u for u in r['unopened'] if u['screen_key'] == 'pos.order')
        self.assertIn('pharmacist', pos['on_paths'])
        self.assertTrue(any(t['runs'] == 0 for t in r['tours']))
        self.assertTrue(any(t['flow'] for t in r['tours']))
        # workflow tours report too
        self.assertEqual(self.ph.post('/api/help/tour-event/', {'screen_key': 'flow:general.system', 'reached': 3},
                                      format='json').status_code, 201)
        self.assertEqual(self.ph.post('/api/help/tour-event/', {'screen_key': 'flow:general.nope'},
                                      format='json').status_code, 400)

    def test_screen_payload_carries_flow_and_module_tours(self):
        r = self.ph.get('/api/help/screens/reservations.board/?log=0').json()
        screens_in_flow = {st['screen'] for st in r['tour_flow']}
        self.assertEqual(screens_in_flow, {'reservations.board', 'reservations.detail'})
        detail_steps = [st for st in r['tour_flow'] if st['screen'] == 'reservations.detail']
        self.assertTrue(all(st['route'] == '/reservations/:id' for st in detail_steps))
        self.assertTrue(any(f['id'] == 'flow:reservations.lifecycle' for f in r['module']['flows']))
        m = self.ph.get('/api/help/modules/general/').json()
        self.assertTrue(any(f['id'] == 'flow:general.system' for f in m['flows']))


class TourMergeTests(SimpleTestCase):
    def test_same_target_twice_edited_independently(self):
        base = [{'target': 'a', 'text': {'ar': '1', 'en': '1'}}, {'target': 'a', 'wait': '/x/:id', 'text': {'ar': '2', 'en': '2'}}]
        edited = [{'target': 'a', 'text': {'ar': 'جديد', 'en': 'new'}}, {'target': 'a', 'text': {'ar': '', 'en': ''}}]
        out = registry._merge_tour(base, edited)
        self.assertEqual(out[0]['text']['ar'], 'جديد')
        self.assertEqual(out[1]['text']['ar'], '2')
        self.assertEqual(out[1]['wait'], '/x/:id')
        # a step the code replaced keeps the repo text
        self.assertEqual(registry._merge_tour([{'target': 'b', 'text': {'ar': 'r', 'en': 'r'}}], edited)[0]['text']['ar'], 'r')


class FlowEditTests(TestCase):
    """Trainers edit workflow-tour text (title, summary, step text); steps stay the code's."""

    def setUp(self):
        branch = make_branch()
        u1, _, _ = make_user('fe_admin', role='admin', branch=branch)
        u2, _, _ = make_user('fe_ph', role='pharmacist', branch=branch)
        self.t, self.ph = APIClient(), APIClient()
        self.t.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u1)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')

    def test_edit_apply_validate_revert(self):
        from apps.help.models import HelpRevision
        url = '/api/help/training/flow/reservations.lifecycle/'
        self.assertEqual(self.ph.get(url).status_code, 403)
        cur = self.t.get(url).json()['current']
        cur['title'] = {'ar': 'دورة الحجز (نسخة المدرب)', 'en': 'Reservation (trainer)'}
        cur['steps'][2]['text'] = {'ar': 'نص أوضح للخطوة', 'en': 'Clearer step text'}
        r = self.t.put(url, {'data': cur, 'note': 'أوضح'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        flows = self.ph.get('/api/help/modules/reservations/').json()['flows']
        f = next(x for x in flows if x['id'] == 'flow:reservations.lifecycle')
        self.assertEqual(f['title']['ar'], 'دورة الحجز (نسخة المدرب)')
        self.assertEqual(f['steps'][2]['text']['ar'], 'نص أوضح للخطوة')
        self.assertEqual(f['steps'][2]['wait'], '/reservations/new')     # behaviour kept from the code
        # steps are fixed by the code: wrong count / moved target rejected
        bad = dict(cur, steps=cur['steps'][:-1])
        self.assertEqual(self.t.put(url, {'data': bad}, format='json').status_code, 400)
        bad = dict(cur, steps=[dict(cur['steps'][0], target='other')] + cur['steps'][1:])
        self.assertEqual(self.t.put(url, {'data': bad}, format='json').status_code, 400)
        self.assertEqual(self.t.delete(url, {'note': 'رجوع'}, format='json').status_code, 200)
        f = next(x for x in self.ph.get('/api/help/modules/reservations/').json()['flows']
                 if x['id'] == 'flow:reservations.lifecycle')
        self.assertNotEqual(f['title']['ar'], 'دورة الحجز (نسخة المدرب)')
        self.assertEqual(HelpRevision.objects.filter(screen_key='flow:reservations.lifecycle').count(), 2)
        self.assertEqual(self.t.get('/api/help/training/flow/nope.x/').status_code, 404)

    def test_index_lists_flows_with_mobile_flag(self):
        flows = self.ph.get('/api/help/').json()['flows']
        ids = {f['id']: f for f in flows}
        for fid in ('flow:pos.order', 'flow:demand.lifecycle', 'flow:delivery.lifecycle',
                    'flow:reservations.mobile', 'flow:transfers.mobile', 'flow:demand.mobile'):
            self.assertIn(fid, ids)
        self.assertTrue(ids['flow:reservations.mobile']['mobile'])
        self.assertFalse(ids['flow:reservations.lifecycle']['mobile'])


class FirstDayTests(TestCase):
    """«أول يوم»: cards on the home page until the path is complete or hidden."""

    def setUp(self):
        branch = make_branch()
        user, self.profile, _ = make_user('fd_sales', role='salesperson', branch=branch)
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')

    def test_cards_for_a_new_person(self):
        from apps.help.content import onboarding
        d = self.c.get('/api/help/first-day/').json()
        self.assertTrue(d['show'])
        self.assertEqual(d['role'], 'salesperson')
        self.assertEqual(d['system_tour']['id'], 'flow:general.system')
        self.assertFalse(d['system_tour']['done'])
        self.assertEqual(d['next_screen']['key'], onboarding.ROLE_PATHS['salesperson'][0])
        ids = [f['id'] for f in d['flows']]
        self.assertTrue(ids)
        self.assertTrue(all(not f['mobile'] for f in d['flows']))
        self.assertNotIn('flow:pos.exceptions', ids)          # not a salesperson's tour
        self.assertIsNotNone(d['quiz'])
        m = self.c.get('/api/help/first-day/?mobile=1').json()
        self.assertIsNone(m['system_tour'])                   # the system tour is desktop
        self.assertTrue(all(f['mobile'] for f in m['flows']))

    def test_done_ticks_and_next_screen_move(self):
        from apps.help.content import onboarding
        n = len(registry.flows(registry.load()[0])['flow:general.system']['steps'])
        self.c.post('/api/help/tour-event/', {'screen_key': 'flow:general.system', 'reached': n, 'done': True},
                    format='json')
        first = onboarding.ROLE_PATHS['salesperson'][0]
        self.c.post('/api/help/onboarding/learned/', {'screen_key': first}, format='json')
        d = self.c.get('/api/help/first-day/').json()
        self.assertTrue(d['system_tour']['done'])
        self.assertEqual(d['next_screen']['key'], onboarding.ROLE_PATHS['salesperson'][1])

    def test_hide_and_complete(self):
        from unittest import mock
        self.assertEqual(self.c.post('/api/help/first-day/', {'hidden': True}, format='json').json(), {'hidden': True})
        self.assertFalse(self.c.get('/api/help/first-day/').json()['show'])
        self.c.post('/api/help/first-day/', {'hidden': False}, format='json')
        self.assertTrue(self.c.get('/api/help/first-day/').json()['show'])
        # a finished path hides it by itself
        with mock.patch('apps.help.training.path', return_value=['general.help_center']), \
             mock.patch('apps.help.training.quizzes', return_value={}):
            self.c.post('/api/help/onboarding/learned/', {'screen_key': 'general.help_center'}, format='json')
            d = self.c.get('/api/help/first-day/').json()
        self.assertEqual(d['progress']['percent'], 100)
        self.assertFalse(d['show'])


class TrainingDigestTests(TestCase):
    """Weekly digest: right recipients, branch scope, finished / stuck / failed /
    retake lists, once per week, can be switched off."""

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        from .factories import make_branch2
        self.b1, self.b2 = make_branch(), make_branch2()
        RoleModuleAccess.objects.create(role='supervisor', module='help', action='edit')
        _, self.sup, _ = make_user('dg_sup', role='supervisor', branch=self.b1)
        u, self.ph, _ = make_user('dg_ph', role='pharmacist', branch=self.b1)
        _, self.other, _ = make_user('dg_other', role='pharmacist', branch=self.b2)
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')

    def _age(self, profile, days):
        from django.utils import timezone
        profile.user.date_joined = timezone.now() - timezone.timedelta(days=days)
        profile.user.save(update_fields=['date_joined'])

    def test_recipients_and_scope(self):
        from apps.help import digest
        self.assertIn(self.sup, digest.recipients())
        self.assertNotIn(self.ph, digest.recipients())
        names = {r['id'] for r in digest.summary_for(self.sup)['stuck']} | \
            {r['id'] for r in digest.summary_for(self.sup)['failed']}
        s = digest.summary_for(self.sup)
        self.assertEqual(s['team'], 1)                 # only branch 1, not the supervisor themself
        self.assertNotIn(self.other.id, names)

    def test_stuck_failed_and_text(self):
        from apps.help import digest
        from apps.help.content import onboarding
        self._age(self.ph, 10)
        wrong = [(q['answer'] + 1) % len(q['options']) for q in onboarding.QUIZZES['pos']]
        self.c.post('/api/help/quizzes/pos/submit/', {'answers': wrong}, format='json')
        s = digest.summary_for(self.sup)
        self.assertEqual([r['id'] for r in s['failed']], [self.ph.id])
        self.assertEqual(s['stuck'], [])                # a quiz attempt today = activity
        title, body = digest.render(s)
        self.assertIn('ملخص التدريب', title)
        self.assertIn('رسبوا', body)
        # no activity for 7+ days and joined long ago → stuck
        from apps.help.models import HelpQuizAttempt
        from django.utils import timezone
        HelpQuizAttempt.objects.update(created_at=timezone.now() - timezone.timedelta(days=9))
        self.assertEqual([r['id'] for r in digest.summary_for(self.sup)['stuck']], [self.ph.id])

    def test_new_joiner_not_stuck_and_finished_this_week(self):
        from unittest import mock
        from apps.help import digest
        self.assertEqual(digest.summary_for(self.sup)['stuck'], [])     # joined today
        with mock.patch('apps.help.training.path', return_value=['general.help_center']), \
             mock.patch('apps.help.training.quizzes', return_value={}):
            self.c.post('/api/help/onboarding/learned/', {'screen_key': 'general.help_center'}, format='json')
            s = digest.summary_for(self.sup)
        self.assertEqual([r['id'] for r in s['finished_this_week']], [self.ph.id])
        self.assertEqual(s['complete'], 1)

    def test_sent_once_a_week_and_switch_off(self):
        from apps.config.models import SystemSetting
        from apps.help import digest
        from apps.notifications.models import Notification
        self.assertEqual(len(digest.send_weekly()), 1)
        digest.send_weekly()
        self.assertEqual(Notification.objects.filter(recipient=self.sup, title__contains='ملخص التدريب').count(), 1)
        self.assertEqual(digest.send_weekly(dry_run=True)[0][0], self.sup)
        SystemSetting.objects.update_or_create(key='help_training_digest_enabled',
                                               defaults={'value': 'false', 'value_type': 'boolean'})
        self.assertEqual(digest.send_weekly(), [])

    def test_names_capped(self):
        from apps.help import digest
        rows = [{'name': f'موظف {i}', 'progress': {'percent': 10}} for i in range(8)]
        self.assertIn('و3 غيرهم', digest._names(rows))


class RemindTests(TestCase):
    """«تذكير»: help/edit only, own branches only, 3-day cool-down, recorded, gentle
    notification to the person, re-shows their «ابدأ من هنا» cards."""

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        from .factories import make_branch2
        from django.utils import timezone
        self.b1, self.b2 = make_branch(), make_branch2()
        RoleModuleAccess.objects.create(role='supervisor', module='help', action='edit')
        su, self.sup, _ = make_user('rm_sup', role='supervisor', branch=self.b1)
        _, self.ph, _ = make_user('rm_ph', role='pharmacist', branch=self.b1)
        _, self.other, _ = make_user('rm_other', role='pharmacist', branch=self.b2)
        for p in (self.ph, self.other):
            p.user.date_joined = timezone.now() - timezone.timedelta(days=20)
            p.user.save(update_fields=['date_joined'])
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(su)}')

    def test_team_marks_stuck(self):
        rows = {r['id']: r for r in self.c.get('/api/help/onboarding/team/').json()}
        self.assertTrue(rows[self.ph.id]['stuck'])
        self.assertIsNone(rows[self.ph.id]['last_reminded_at'])

    def test_remind_records_notifies_and_cools_down(self):
        from apps.help.models import HelpPreference, HelpReminder
        from apps.notifications.models import Notification
        HelpPreference.objects.create(staff=self.ph, first_day_hidden_at='2026-01-01T00:00:00Z')
        r = self.c.post('/api/help/onboarding/remind/', {'staff_ids': [self.ph.id]}, format='json').json()
        self.assertEqual(r['sent'], [self.ph.id])
        n = Notification.objects.get(recipient=self.ph, title__contains='تذكير بالتدريب')
        self.assertIn('مساري التدريبي', n.body)
        self.assertEqual(HelpReminder.objects.get(staff=self.ph).sent_by, self.sup)
        self.assertIsNone(HelpPreference.objects.get(staff=self.ph).first_day_hidden_at)
        again = self.c.post('/api/help/onboarding/remind/', {'staff_ids': [self.ph.id]}, format='json').json()
        self.assertEqual(again['sent'], [])
        self.assertEqual(HelpReminder.objects.count(), 1)
        rows = {x['id']: x for x in self.c.get('/api/help/onboarding/team/').json()}
        self.assertIsNotNone(rows[self.ph.id]['last_reminded_at'])

    def test_scope_permission_and_validation(self):
        from apps.help.models import HelpReminder
        r = self.c.post('/api/help/onboarding/remind/', {'staff_ids': [self.other.id]}, format='json').json()
        self.assertEqual(r['sent'], [])                       # another branch
        self.assertEqual(self.c.post('/api/help/onboarding/remind/', {'staff_ids': 'x'}, format='json').status_code, 400)
        u, _, _ = make_user('rm_ph2', role='pharmacist', branch=self.b1)
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.assertEqual(c2.post('/api/help/onboarding/remind/', {'staff_ids': [self.ph.id]}, format='json').status_code, 403)
        self.assertFalse(HelpReminder.objects.exists())

    def test_finished_not_reminded(self):
        from unittest import mock
        with mock.patch('apps.help.training.path', return_value=[]), \
             mock.patch('apps.help.training.quizzes', return_value={}):
            r = self.c.post('/api/help/onboarding/remind/', {'staff_ids': [self.ph.id]}, format='json').json()
        self.assertEqual(r['sent'], [])
        self.assertEqual(r['skipped'][0]['reason'], 'خلّص التدريب')


class WhatsNewTests(TestCase):
    """Home «الجديد»: recent help changes that matter to the person; read on the server."""

    def setUp(self):
        from django.utils import timezone
        u, self.p, _ = make_user('wn_sales', role='salesperson', branch=make_branch())
        u.date_joined = timezone.now() - timezone.timedelta(days=60)
        u.save(update_fields=['date_joined'])
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        today = timezone.localdate()
        self.recent = today.isoformat()
        self.old = (today - timezone.timedelta(days=30)).isoformat()

    def _versions(self, recent_keys):
        _, screens = registry.load()
        return {k: (self.recent if k in recent_keys else self.old) for k in screens}

    def test_relevant_recent_unread_then_read(self):
        from unittest import mock
        from apps.help.content import onboarding
        on_path = onboarding.ROLE_PATHS['salesperson'][1]
        off_path = 'finance.pnl'
        with mock.patch('apps.help.onboarding_views._versions', return_value=self._versions({on_path, off_path})):
            d = self.c.get('/api/help/whats-new/').json()
            self.assertEqual([x['key'] for x in d['items']], [on_path])    # finance is not theirs
            self.assertEqual(d['unread'], 1)
            # opening that screen's help marks it read
            self.c.get(f'/api/help/screens/{on_path}/')
            d = self.c.get('/api/help/whats-new/').json()
            self.assertEqual(d['unread'], 0)
            self.assertTrue(d['items'][0]['read'])
            # a screen whose help they opened becomes relevant too
            self.c.get(f'/api/help/screens/{off_path}/?log=1')
            keys = [x['key'] for x in self.c.get('/api/help/whats-new/').json()['items']]
            self.assertIn(off_path, keys)

    def test_dismiss_all_and_old_changes(self):
        from unittest import mock
        from apps.help.content import onboarding
        keys = set(onboarding.ROLE_PATHS['salesperson'][:3])
        with mock.patch('apps.help.onboarding_views._versions', return_value=self._versions(keys)):
            self.assertEqual(self.c.get('/api/help/whats-new/').json()['unread'], 3)
            self.assertEqual(self.c.post('/api/help/whats-new/').json(), {'unread': 0})
            self.assertEqual(self.c.get('/api/help/whats-new/').json()['unread'], 0)
        with mock.patch('apps.help.onboarding_views._versions', return_value=self._versions(set())):
            self.assertEqual(self.c.get('/api/help/whats-new/').json()['items'], [])

    def test_newcomer_sees_no_flood(self):
        from unittest import mock
        from django.utils import timezone
        from apps.help.content import onboarding
        self.p.user.date_joined = timezone.now()
        self.p.user.save(update_fields=['date_joined'])
        keys = set(onboarding.ROLE_PATHS['salesperson'])
        with mock.patch('apps.help.onboarding_views._versions', return_value=self._versions(keys)):
            self.assertEqual(self.c.get('/api/help/whats-new/').json()['unread'], 0)


class ChangeNoteTests(TestCase):
    """One-line «what changed» note: trainer's public note on the latest save, else the
    repo change_note; shown in the index («الجديد»), the screen and the home card."""

    def setUp(self):
        u, _, _ = make_user('cn_admin', role='admin', branch=make_branch())
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.key = 'reservations.board'
        # start from a screen without a developer note (the trainer's note is what is tested)
        from unittest import mock
        _, screens = registry.load()
        patcher = mock.patch.dict(screens[self.key])
        patcher.start()
        self.addCleanup(patcher.stop)
        screens[self.key].pop('change_note', None)

    def _note(self):
        idx = {s['key']: s for s in self.c.get('/api/help/').json()['screens']}
        return idx[self.key]['change_note']

    def test_trainer_note_shown_then_cleared_by_a_later_plain_save(self):
        self.assertIsNone(self._note())
        r = self.c.put(f'/api/help/screens/{self.key}/',
                       {'data': {'summary': {'ar': 'شرح أوضح', 'en': ''}}, 'note': 'سبب داخلي',
                        'public_note': '  زر   تصدير جديد  '}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['change_note']['ar'], 'زر تصدير جديد')     # whitespace tidied
        self.assertEqual(self._note()['ar'], 'زر تصدير جديد')
        from apps.help.models import HelpRevision
        rev = HelpRevision.objects.get(screen_key=self.key)
        self.assertEqual((rev.note, rev.public_note), ('سبب داخلي', 'زر تصدير جديد'))
        # a later save without a note: the old note no longer describes the current version
        import time; time.sleep(0.01)
        from apps.help.models import HelpOverride
        from django.utils import timezone
        HelpRevision.objects.update(created_at=timezone.now() - timezone.timedelta(minutes=5))
        self.c.put(f'/api/help/screens/{self.key}/', {'data': {'summary': {'ar': 'تاني', 'en': ''}}}, format='json')
        HelpOverride.objects.filter(screen_key=self.key).update(updated_at=timezone.now())
        self.assertIsNone(self._note())

    def test_repo_note(self):
        idx = {s['key']: s for s in self.c.get('/api/help/').json()['screens']}
        self.assertTrue(idx['general.help_center']['change_note']['ar'])
        r = self.c.get('/api/help/screens/general.help_center/?log=0').json()
        self.assertEqual(r['change_note'], idx['general.help_center']['change_note'])

    def test_note_on_home_card(self):
        from unittest import mock
        from django.utils import timezone
        self.c.put(f'/api/help/screens/{self.key}/',
                   {'data': {'summary': {'ar': 'x', 'en': ''}}, 'public_note': 'عمود جديد'}, format='json')
        from apps.users.models import StaffProfile
        p = StaffProfile.objects.get(user__username='cn_admin')
        p.user.date_joined = timezone.now() - timezone.timedelta(days=60)
        p.user.save(update_fields=['date_joined'])
        # only this screen counts as changed (the card shows 20 items at most)
        from apps.help import onboarding_views
        real = onboarding_views._versions()
        only = {k: (v if k == self.key else '2000-01-01') for k, v in real.items()}
        with mock.patch('apps.help.onboarding_views._versions', return_value=only):
            items = {x['key']: x for x in self.c.get('/api/help/whats-new/').json()['items']}
        self.assertEqual(items[self.key]['change_note']['ar'], 'عمود جديد')


class TrainingPublicNoteTests(TestCase):
    """The trainer's one-line «what changed» on path / quiz / workflow-tour saves: added
    to the notification those changes send; shown on the workflow tour's card."""

    def setUp(self):
        self.branch = make_branch()
        self.t, _ = self._client('admin', 'tp_admin')

    def _client(self, role, name):
        user, profile, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c, profile

    def test_path_note_in_notification_and_history(self):
        from apps.help.content import onboarding
        from apps.help.models import HelpRevision
        from apps.notifications.models import Notification
        _, seller = self._client('salesperson', 'tp_sales')
        new = onboarding.ROLE_PATHS['salesperson'] + ['tasks.list']
        r = self.t.put('/api/help/training/path/salesperson/',
                       {'data': {'screens': new}, 'note': 'داخلي', 'public_note': ' ابدأ  بالمهام '}, format='json')
        self.assertEqual(r.json()['notified'], 1)
        n = Notification.objects.get(recipient=seller, title__contains='مسارك')
        self.assertIn('الجديد: ابدأ بالمهام', n.body)
        self.assertNotIn('داخلي', n.body)
        self.assertEqual(r.json()['revisions'][0]['public_note'], 'ابدأ بالمهام')
        self.assertEqual(HelpRevision.objects.get(screen_key='path:salesperson').public_note, 'ابدأ بالمهام')

    def test_quiz_note_in_notification(self):
        from apps.help.content import onboarding
        from apps.notifications.models import Notification
        c, ph = self._client('pharmacist', 'tp_ph')
        right = [q['answer'] for q in onboarding.QUIZZES['pos']]
        c.post('/api/help/quizzes/pos/submit/', {'answers': right}, format='json')
        q = {'q': {'ar': 'سؤال؟', 'en': 'Q?'}, 'options': [{'ar': 'أ', 'en': 'A'}, {'ar': 'ب', 'en': 'B'}],
             'answer': 0, 'explain': {'ar': 'لأن', 'en': 'Because'}}
        self.t.put('/api/help/training/quiz/pos/', {'data': {'questions': [q]}, 'public_note': 'سؤال عن المرتجعات'},
                   format='json')
        n = Notification.objects.get(recipient=ph, title__contains='أعد الاختبار')
        self.assertTrue(n.body.endswith('الجديد: سؤال عن المرتجعات'))

    def test_no_note_keeps_message(self):
        from apps.help import notify
        self.assertEqual(notify._with_note('نص.', ''), 'نص.')

    def test_flow_note_on_cards_until_revert_or_old(self):
        from apps.help.models import HelpRevision
        from django.utils import timezone
        url = '/api/help/training/flow/reservations.lifecycle/'
        fid = 'flow:reservations.lifecycle'
        card = lambda: next(x for x in self.t.get('/api/help/modules/reservations/').json()['flows'] if x['id'] == fid)
        self.assertIsNone(card()['change_note'])
        cur = self.t.get(url).json()['current']
        cur['steps'][0]['text'] = {'ar': 'نص أوضح', 'en': ''}
        self.t.put(url, {'data': cur, 'public_note': 'خطوة أوضح للبداية'}, format='json')
        self.assertEqual(card()['change_note']['ar'], 'خطوة أوضح للبداية')
        # older than two weeks → no longer «new»
        HelpRevision.objects.filter(screen_key=fid).update(created_at=timezone.now() - timezone.timedelta(days=15))
        self.assertIsNone(card()['change_note'])
        HelpRevision.objects.filter(screen_key=fid).update(created_at=timezone.now())
        # a revert clears it (the note described the trainer's version)
        self.t.delete(url, {'public_note': 'ignored'}, format='json')
        self.assertIsNone(card()['change_note'])
        self.assertEqual(HelpRevision.objects.filter(screen_key=fid, action='revert').get().public_note, '')


class NotesLogTests(TestCase):
    """«📝 إيه الجديد» for trainers: last 30 days of one-line notes from screens, paths,
    quizzes and tours together, with each line's state; also in the weekly digest."""

    def setUp(self):
        branch = make_branch()
        u, _, _ = make_user('nl_admin', role='admin', branch=branch)
        u2, _, _ = make_user('nl_ph', role='pharmacist', branch=branch)
        self.t, self.ph = APIClient(), APIClient()
        self.t.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')

    def _trainer_items(self):
        r = self.t.get('/api/help/notes-log/')
        self.assertEqual(r.status_code, 200)
        return [x for x in r.json()['items'] if x['source'] == 'trainer']

    def test_lists_all_kinds_with_state(self):
        from apps.help.content import onboarding
        self.assertEqual(self.ph.get('/api/help/notes-log/').status_code, 403)
        self.t.put('/api/help/screens/reservations.board/',
                   {'data': {'summary': {'ar': 'x', 'en': ''}}, 'public_note': 'عمود جديد'}, format='json')
        self.t.put('/api/help/training/path/salesperson/',
                   {'data': {'screens': onboarding.ROLE_PATHS['salesperson'] + ['tasks.list']},
                    'public_note': 'المهام اتضافت'}, format='json')
        url = '/api/help/training/flow/reservations.lifecycle/'
        cur = self.t.get(url).json()['current']
        self.t.put(url, {'data': cur, 'public_note': 'جولة أوضح'}, format='json')
        items = {x['kind']: x for x in self._trainer_items()}
        self.assertEqual(set(items), {'screen', 'path', 'flow'})
        self.assertEqual((items['screen']['note'], items['screen']['state']), ('عمود جديد', 'shown'))
        self.assertEqual(items['path']['state'], 'sent')
        self.assertIn('البائع', items['path']['title']['ar'])
        self.assertEqual(items['flow']['state'], 'shown')
        self.assertTrue(items['flow']['staff'])
        # a later save without a note → the older line is replaced
        self.t.put(url, {'data': cur}, format='json')
        items = {x['kind']: x for x in self._trainer_items()}
        self.assertEqual(items['flow']['state'], 'replaced')

    def test_older_than_window_left_out(self):
        from apps.help.models import HelpRevision
        from django.utils import timezone
        self.t.put('/api/help/screens/reservations.board/',
                   {'data': {'summary': {'ar': 'x', 'en': ''}}, 'public_note': 'قديم'}, format='json')
        HelpRevision.objects.update(created_at=timezone.now() - timezone.timedelta(days=31))
        self.assertEqual(self._trainer_items(), [])
        r = self.t.get('/api/help/notes-log/?days=40').json()
        self.assertEqual(r['days'], 40)
        self.assertEqual([x['note'] for x in r['items'] if x['source'] == 'trainer'], ['قديم'])

    def test_repo_notes_included(self):
        items = self.t.get('/api/help/notes-log/?days=90').json()['items']
        self.assertTrue(any(x['source'] == 'repo' and x['key'] == 'general.help_center' for x in items))

    def test_digest_line(self):
        from apps.help import digest
        s = {'team': 2, 'complete': 0, 'finished_this_week': [], 'stuck': [], 'failed': [], 'retake': [],
             'notes': [{'title': {'ar': f'شاشة {i}'}, 'note': f'سطر {i}'} for i in range(5)]}
        _, body = digest.render(s)
        self.assertIn('📝 اتحدّث في التدريب (5): شاشة 0: «سطر 0»', body)
        self.assertIn('و2 غيرها', body)
        _, body = digest.render({**s, 'notes': []})
        self.assertNotIn('📝', body)


class NoteCheckTests(TestCase):
    """Gentle hints on the «إيه الجديد» note while typing: big edit with no note, a
    generic note, the same change worded differently elsewhere. Never blocks a save."""

    def setUp(self):
        branch = make_branch()
        u, _, _ = make_user('nc_admin', role='admin', branch=branch)
        u2, _, _ = make_user('nc_ph', role='pharmacist', branch=branch)
        self.t, self.ph = APIClient(), APIClient()
        self.t.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')

    def _check(self, kind, key, note, data):
        r = self.t.post('/api/help/notes-check/', {'kind': kind, 'key': key, 'note': note, 'data': data}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return {h['code']: h for h in r.json()['hints']}

    def test_rules_unit(self):
        from apps.help import notecheck
        self.assertEqual(notecheck.normalize('إضافةُ زرّ'), 'اضافه زر')
        self.assertEqual(notecheck.words('زرار Excel'), {'زر', 'اكسل'})
        self.assertGreaterEqual(notecheck.similarity('زر تصدير اكسل جديد', 'زرار تصدير Excel في القائمة'), 0.6)
        self.assertLess(notecheck.similarity('زر تصدير جديد', 'عمود الفرع المستلم'), 0.6)
        self.assertEqual(notecheck.changed_parts({'a': {'ar': 'x'}, 'b': None}, {'a': {'ar': 'x'}, 'b': {'ar': ''}}), 0)
        self.assertEqual(notecheck.changed_parts([{'ar': 'x'}], [{'ar': 'y'}, {'ar': 'z'}]), 2)

    def test_big_screen_edit_without_note(self):
        self.assertEqual(self.ph.post('/api/help/notes-check/', {'kind': 'screen', 'key': 'reservations.board'},
                                      format='json').status_code, 403)
        key = 'reservations.board'
        cur = self.t.get(f'/api/help/screens/{key}/?log=0').json()
        draft = {'title': cur['title'], 'summary': {'ar': 'جديد 1', 'en': ''}, 'steps': cur['steps']}
        self.assertEqual(self._check('screen', key, '', draft), {})            # one part: fine
        draft['tips'] = [{'ar': 'نصيحة أ', 'en': ''}, {'ar': 'نصيحة ب', 'en': ''}, {'ar': 'نصيحة ج', 'en': ''}]
        draft['tips'] = (cur.get('tips') or []) + draft['tips']
        self.assertIn('big_empty', self._check('screen', key, '', draft))
        self.assertNotIn('big_empty', self._check('screen', key, 'نصايح جديدة للحجز', draft))
        self.assertEqual(self.t.post('/api/help/notes-check/', {'kind': 'screen', 'key': 'nope'},
                                     format='json').status_code, 404)

    def test_path_and_quiz_without_note(self):
        from apps.help.content import onboarding
        base = onboarding.ROLE_PATHS['salesperson']
        self.assertIn('big_empty', self._check('path', 'salesperson', '', {'screens': base + ['tasks.list']}))
        self.assertEqual(self._check('path', 'salesperson', '', {'screens': base[:2]}), {})    # removal: no news
        q = {'q': {'ar': 'سؤال؟', 'en': ''}, 'options': [{'ar': 'أ', 'en': ''}, {'ar': 'ب', 'en': ''}],
             'answer': 0, 'explain': {'ar': 'لأن', 'en': ''}}
        self.assertIn('big_empty', self._check('quiz', 'pos', '', {'questions': [q]}))
        self.assertEqual(self._check('quiz', 'pos', '', {'questions': onboarding.QUIZZES['pos']}), {})

    def test_vague_note(self):
        cur = self.t.get('/api/help/screens/reservations.board/?log=0').json()
        self.assertIn('vague', self._check('screen', 'reservations.board', 'تعديلات بسيطة', {'title': cur['title']}))
        self.assertNotIn('vague', self._check('screen', 'reservations.board', 'زر تصدير جديد', {'title': cur['title']}))

    def test_similar_note_elsewhere_offers_its_wording(self):
        self.t.put('/api/help/screens/reservations.board/',
                   {'data': {'summary': {'ar': 'x', 'en': ''}}, 'public_note': 'زر تصدير اكسل جديد في القائمة'},
                   format='json')
        cur = self.t.get('/api/help/screens/transfers.list/?log=0').json()
        hints = self._check('screen', 'transfers.list', 'زرار تصدير إكسل جديد فوق', {'title': cur['title']})
        self.assertIn('similar', hints)
        self.assertEqual(hints['similar']['suggestion'], 'زر تصدير اكسل جديد في القائمة')
        # the same wording → consistent, nothing to say; own screen's note is skipped
        self.assertNotIn('similar', self._check('screen', 'transfers.list', 'زر تصدير اكسل جديد في القائمة',
                                                {'title': cur['title']}))
        self.assertNotIn('similar', self._check('screen', 'reservations.board', 'زرار تصدير إكسل جديد فوق', {}))
        # unrelated note → no hint
        self.assertNotIn('similar', self._check('screen', 'transfers.list', 'عمود الفرع المستلم', {'title': cur['title']}))
        # sharing only «زر … جديد» is a different change (print, not export)
        self.assertNotIn('similar', self._check('screen', 'transfers.list', 'زر طباعة جديد', {'title': cur['title']}))


class GlossaryTests(TestCase):
    """«قاموس المصطلحات»: trainers keep agreed words + words to avoid (audited); the note
    hints point out avoided words in a note (offering the fixed note) and in help text."""

    def setUp(self):
        branch = make_branch()
        u, _, _ = make_user('gl_admin', role='admin', branch=branch)
        u2, _, _ = make_user('gl_ph', role='pharmacist', branch=branch)
        self.t, self.ph = APIClient(), APIClient()
        self.t.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')

    def _add(self, **data):
        return self.t.post('/api/help/glossary/', data, format='json')

    def test_crud_validation_permissions_and_history(self):
        from apps.help.models import HelpRevision
        self.assertEqual(self.ph.post('/api/help/glossary/', {'preferred': 'x', 'avoid': 'y'}, format='json').status_code, 403)
        r = self._add(preferred='الكاشير', avoid='الخزنة، الخزينة', why='اسم الشاشة')
        self.assertEqual(r.status_code, 201, r.content)
        tid = r.json()['id']
        self.assertEqual(r.json()['avoid'], ['الخزنة', 'الخزينة'])
        self.assertEqual(self._add(preferred='كاشير', avoid='كاش').status_code, 400)          # same word twice
        self.assertEqual(self._add(preferred='حجز', avoid='').status_code, 400)
        self.assertEqual(self._add(preferred='حجز', avoid='الحجز').status_code, 400)          # avoid = preferred
        self.assertEqual(self._add(preferred='حجز', avoid='طلب', modules=['nope']).status_code, 400)
        self.assertEqual(self.ph.put(f'/api/help/glossary/{tid}/', {}, format='json').status_code, 403)
        r = self.t.put(f'/api/help/glossary/{tid}/', {'preferred': 'الكاشير', 'avoid': ['الخزنة']}, format='json')
        self.assertEqual(r.json()['avoid'], ['الخزنة'])
        g = self.ph.get('/api/help/glossary/').json()                # everyone may read; no usage scan
        self.assertFalse(g['can_edit'])
        self.assertNotIn('uses', g['terms'][0])
        self.assertEqual(self.t.delete(f'/api/help/glossary/{tid}/').status_code, 204)
        self.assertEqual(list(HelpRevision.objects.filter(screen_key=f'glossary:{tid}').order_by('id')
                              .values_list('action', flat=True)), ['save', 'save', 'revert'])

    def test_uses_counts_screens_in_scope(self):
        from apps.help import notecheck, registry
        _, screens = registry.load()
        # a word the current help surely uses
        tid = self._add(preferred='بند', avoid=['الشاشة']).json()['id']
        u = next(t for t in self.t.get('/api/help/glossary/').json()['terms'] if t['id'] == tid)['uses']
        self.assertGreater(u['count'], 0)
        self.t.put(f'/api/help/glossary/{tid}/', {'preferred': 'بند', 'avoid': ['الشاشة'], 'modules': ['pos']},
                   format='json')
        u2 = next(t for t in self.t.get('/api/help/glossary/').json()['terms'] if t['id'] == tid)['uses']
        self.assertLess(u2['count'], u['count'])
        self.assertTrue(all(screens[k]['module'] == 'pos' for k in u2['screens']))

    def test_hints_in_note_and_text(self):
        self._add(preferred='الكاشير', avoid=['الخزنة'])
        self._add(preferred='حجز', avoid=['طلب'], modules=['reservations'])
        check = lambda key, note, data: {h['code']: h for h in self.t.post(
            '/api/help/notes-check/', {'kind': 'screen', 'key': key, 'note': note, 'data': data},
            format='json').json()['hints']}
        h = check('reservations.board', 'زر جديد للخزنة', {})
        self.assertEqual(h['term']['suggestion'], 'زر جديد للكاشير')
        h = check('reservations.board', 'طلب جديد', {'tips': [{'ar': 'افتح الطلب من هنا', 'en': ''}]})
        self.assertEqual(h['term']['suggestion'], 'حجز جديد')
        self.assertIn('«طلب»', h['term_text']['text'])
        # «طلب» is only avoided in reservations
        h = check('purchasing.supply', 'طلب جديد', {})
        self.assertNotIn('term', h)
        # the agreed word itself is not flagged
        self.assertNotIn('term', check('reservations.board', 'شاشة الكاشير', {}))

    def test_unit_matching(self):
        from apps.help import notecheck as n
        T = [{'preferred': 'الكاشير', 'avoid': ['الخزنة'], 'modules': []}]
        self.assertEqual([(a, c) for _, a, c in n.find_terms('روح للخزنة، والخزنة مقفولة', T)], [('الخزنة', 2)])
        self.assertEqual(n.find_terms('خزنات', T), [])            # another word, not a prefix form
        self.assertEqual(n.fix_note('اتغيّر «الخزنة».', T), 'اتغيّر «الكاشير».')
        self.assertIsNone(n.fix_note('مفيش حاجة', T))


class GlossaryApplyTests(TestCase):
    """«طبّق القاموس»: the server lists every avoided word in a screen draft with its
    place, sentence and replacement; it changes nothing (the editor applies accepted
    ones to its draft and the normal save records them)."""

    def setUp(self):
        branch = make_branch()
        u, _, _ = make_user('ga_admin', role='admin', branch=branch)
        u2, _, _ = make_user('ga_ph', role='pharmacist', branch=branch)
        self.t, self.ph = APIClient(), APIClient()
        self.t.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u)}')
        self.ph.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(u2)}')
        self.t.post('/api/help/glossary/', {'preferred': 'الكاشير', 'avoid': ['الخزنة']}, format='json')
        self.t.post('/api/help/glossary/', {'preferred': 'حجز', 'avoid': ['طلب', 'أمر بيع'],
                                            'modules': ['reservations']}, format='json')

    def test_unit_places_and_apply(self):
        from apps.help import notecheck as n
        T = [{'preferred': 'الكاشير', 'avoid': ['الخزنة']}, {'preferred': 'حجز', 'avoid': ['طلب', 'أمر بيع']}]
        txt = 'روح للخزنة وادفع. بعدها الطلب يتأكد، وأمر بيع جديد. الكاشير هنا!'
        occ = n.occurrences(txt, T)
        self.assertEqual([(o['match'], o['replacement']) for o in occ],
                         [('للخزنة', 'للكاشير'), ('الطلب', 'الحجز'), ('وأمر بيع', 'وحجز')])
        self.assertTrue(all(txt[o['start']:o['end']] == o['match'] for o in occ))
        self.assertEqual(n.apply(txt, occ), 'روح للكاشير وادفع. بعدها الحجز يتأكد، وحجز جديد. الكاشير هنا!')

    def test_scan_screen_draft(self):
        from apps.help.models import HelpOverride, HelpRevision
        url = '/api/help/glossary/scan/'
        draft = {'title': {'ar': 'لوحة الحجوزات', 'en': ''},
                 'steps': [{'text': {'ar': 'افتح الطلب من الجدول. ثم ادفع في الخزنة', 'en': 'order'}, 'roles': ['x']}],
                 'faq': [{'q': {'ar': 'فين الطلب؟', 'en': ''}, 'a': {'ar': 'في الكاشير', 'en': ''}}]}
        self.assertEqual(self.ph.post(url, {'screen_key': 'reservations.board', 'data': draft}, format='json').status_code, 403)
        r = self.t.post(url, {'screen_key': 'reservations.board', 'data': draft}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        items = r.json()['items']
        self.assertEqual([(i['path'], i['match'], i['replacement']) for i in items], [
            (['steps', 0, 'text', 'ar'], 'الطلب', 'الحجز'),
            (['steps', 0, 'text', 'ar'], 'الخزنة', 'الكاشير'),
            (['faq', 0, 'q', 'ar'], 'الطلب', 'الحجز'),
        ])
        first = items[0]
        self.assertEqual((first['before'], first['after']), ('افتح ', ' من الجدول.'))
        self.assertEqual(items[1]['before'], 'ثم ادفع في ')
        # «طلب» is only avoided in reservations
        r = self.t.post(url, {'screen_key': 'purchasing.supply', 'data': draft}, format='json')
        self.assertEqual([i['match'] for i in r.json()['items']], ['الخزنة'])
        # read-only: nothing saved
        self.assertFalse(HelpOverride.objects.exists())
        self.assertFalse(HelpRevision.objects.exclude(screen_key__startswith='glossary:').exists())
        self.assertEqual(self.t.post(url, {'screen_key': 'nope', 'data': {}}, format='json').status_code, 404)
        self.assertEqual(self.t.post(url, {'screen_key': 'reservations.board', 'data': []}, format='json').status_code, 400)


class JourneyApiTests(TestCase):
    """Journeys are served with the module / screen help (role-filtered), edited by
    trainers like screen help (versioned, revertible), and counted in the usage report."""

    def setUp(self):
        self.branch = make_branch()
        self.jid = next(iter(registry.journeys()))
        self.j = registry.journeys()[self.jid]

    def _client(self, role, name):
        user, profile, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c

    def test_module_and_screen_payload_carry_journeys(self):
        c = self._client('admin', 'jr_admin')
        m = c.get(f'/api/help/modules/{self.j["module"]}/').json()
        row = next(x for x in m['journeys'] if x['id'] == self.jid)
        self.assertEqual(len(row['steps']), len(self.j['steps']))
        for st in row['steps']:
            self.assertIn('routes', st)
            self.assertTrue(st['route'] is None or ':' not in st['route'])
        screen = self.j['steps'][0]['screen']
        sp = c.get(f'/api/help/screens/{screen}/?log=0').json()
        self.assertIn(self.jid, [x['id'] for x in sp['module']['journeys']])

    def test_role_filter(self):
        limited = [(jid, j) for jid, j in registry.journeys().items() if j.get('roles')]
        if not limited:
            self.skipTest('no role-limited journey')
        jid, j = limited[0]
        other = next(r for r in ('viewer', 'delivery', 'purchasing', 'pharmacist') if r not in j['roles'])
        c = self._client(other, 'jr_other')
        ids = [x['id'] for x in c.get(f'/api/help/modules/{j["module"]}/').json()['journeys']]
        self.assertNotIn(jid, ids)

    def test_edit_and_revert(self):
        t = self._client('admin', 'jr_tr')
        learner = self._client('pharmacist', 'jr_ph')
        url = f'/api/help/journeys/{self.jid}/'
        steps = [dict(st) for st in self.j['steps']]
        steps[0] = {**steps[0], 'text': {'ar': 'نص المدرب', 'en': 'Trainer text'}}
        steps[1] = {**steps[1], 'target': 'moved-elsewhere', 'text': {'ar': 'لا يطبق', 'en': 'not applied'}}
        self.assertEqual(learner.put(url, {'data': {'steps': steps}}, format='json').status_code, 403)
        r = t.put(url, {'data': {'steps': steps}, 'note': 'أوضح'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        got = r.json()['steps']
        self.assertEqual(got[0]['text']['ar'], 'نص المدرب')
        self.assertEqual(got[1]['text'], self.j['steps'][1]['text'])          # target mismatch → ignored
        self.assertEqual(got[0]['target'], self.j['steps'][0]['target'])
        self.assertTrue(HelpRevision.objects.filter(screen_key=f'journey:{self.jid}').exists())
        long = [{**steps[0], 'warn': {'ar': 'x' * 200, 'en': 'x'}}]
        self.assertEqual(t.put(url, {'data': {'steps': long}}, format='json').status_code, 400)
        r = t.delete(url, {'note': 'رجوع'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['steps'][0]['text'], self.j['steps'][0]['text'])
        self.assertEqual(t.get('/api/help/journeys/nope.x/').status_code, 404)

    def test_old_tour_override_keeps_new_fields(self):
        """A trainer edit saved before rich steps (text only) keeps the repo's label/when/warn."""
        _, screens = registry.load()
        key, s = next((k, s) for k, s in screens.items() if any('when' in st for st in s.get('tour') or []))
        st = next(x for x in s['tour'] if 'when' in x)
        ov = HelpOverride(screen_key=key, data={'tour': [{'target': st['target'], 'text': {'ar': 'م', 'en': 'm'}}]})
        eff = next(x for x in registry.effective(s, ov)['tour'] if x['target'] == st['target'])
        self.assertEqual(eff['text']['ar'], 'م')
        self.assertEqual(eff['when'], st['when'])

    def test_journey_tour_event_and_usage(self):
        c = self._client('admin', 'jr_ev')
        n = len(self.j['steps'])
        r = c.post('/api/help/tour-event/', {'screen_key': f'journey:{self.jid}', 'reached': 99, 'done': True}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(HelpEvent.objects.get(screen_key=f'journey:{self.jid}').results, n)
        self.assertEqual(c.post('/api/help/tour-event/', {'screen_key': 'journey:nope.x'}, format='json').status_code, 400)
        rows = c.get('/api/help/usage/').json()['tours']
        row = next(x for x in rows if x['screen_key'] == f'journey:{self.jid}')
        self.assertEqual((row['kind'], row['runs'], row['done']), ('journey', 1, 1))


class ProductTourApiTests(TestCase):
    """«🚀 جولة في النظام»: built from the caller's role path, trainers may preview another
    role, tour events are accepted and listed in the usage report."""

    def setUp(self):
        self.branch = make_branch()

    def _client(self, role, name):
        user, _, _ = make_user(name, role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c

    def test_own_role_tour_with_routes(self):
        c = self._client('pharmacist', 'pt_ph')
        r = c.get('/api/help/product-tour/')
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual((j['id'], j['shell']), ('product.pharmacist.desktop', 'desktop'))
        self.assertEqual(j['steps'][0]['screen'], 'general.dashboard')
        self.assertTrue(all('routes' in st and 'screen_title' in st for st in j['steps']))
        self.assertIn('pos', [st['screen'].split('.')[0] for st in j['steps']])
        self.assertEqual(c.get('/api/help/product-tour/?shell=tv').status_code, 400)

    def test_preview_other_role_needs_help_edit(self):
        ph = self._client('pharmacist', 'pt_ph2')
        self.assertEqual(ph.get('/api/help/product-tour/?role=admin').json()['id'], 'product.pharmacist.desktop')
        admin = self._client('admin', 'pt_admin')
        self.assertEqual(admin.get('/api/help/product-tour/?role=purchasing').json()['id'], 'product.purchasing.desktop')

    def test_no_tour_on_a_shell_is_404(self):
        c = self._client('viewer', 'pt_viewer')
        self.assertEqual(c.get('/api/help/product-tour/?shell=mobile').status_code, 404)

    def test_tour_events_and_usage(self):
        c = self._client('pharmacist', 'pt_ph3')
        n = len(c.get('/api/help/product-tour/').json()['steps'])
        key = 'journey:product.pharmacist.desktop'
        self.assertEqual(c.post('/api/help/tour-event/', {'screen_key': key, 'reached': n, 'done': True}, format='json').status_code, 201)
        self.assertEqual(c.post('/api/help/tour-event/', {'screen_key': 'journey:product.nobody.tv'}, format='json').status_code, 400)
        admin = self._client('admin', 'pt_admin2')
        rows = admin.get('/api/help/usage/').json()['tours']
        row = next(x for x in rows if x['screen_key'] == key)
        self.assertEqual((row['kind'], row['runs'], row['done']), ('product', 1, 1))
class TourExplanationTests(SimpleTestCase):
    def setUp(self):
        self.modules, self.screens = registry.load()

    def test_tour_explanations_and_module_tours(self):
        """A longer explanation (`more`, shown under the step) is optional — the rich
        steps already carry label / when / warn — but when present it is real text in
        both languages; and every module has a desktop module tour."""
        short, no_flow = [], []
        for key, s in self.screens.items():
            for i, st in enumerate(s.get('tour') or []):
                m = st.get('more')
                if m is not None and (len((m.get('ar') or '').strip()) < 60 or not (m.get('en') or '').strip()):
                    short.append(f'{key}.tour[{i}]')
        for mk, m in self.modules.items():
            flows = m.get('flows') or []
            if not any(not f.get('mobile') for f in flows):
                no_flow.append(mk)
            for f in flows:
                for i, st in enumerate(f['steps']):
                    mo = st.get('more')
                    if mo is not None and (len((mo.get('ar') or '').strip()) < 60 or not (mo.get('en') or '').strip()):
                        short.append(f'{mk}.flows.{f["key"]}[{i}]')
        self.assertEqual(short, [], 'Tour steps whose longer explanation (`more`) is too short or one-language')
        self.assertEqual(no_flow, [], 'Modules without a desktop module / workflow tour')
