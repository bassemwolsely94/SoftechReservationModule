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
