"""
Role review Task 4 (owner decision 4): the server's branch rule on the five create flows.

supervisor / quality_manager / accountant / purchasing are all-branch roles (and carry the
all-branches flag here). For each flow, a create for a branch that is NOT their home branch is
accepted (201) when the role holds the module's create grant from the live seed matrix, and is
refused by the matrix (403) when it does not — the picker is moot for a form they cannot submit.
A branch-bound pharmacist is refused on a foreign branch (the control). Nothing here widens a rule.
"""
from unittest import mock

from django.test import TestCase

from apps.demand.models import DemandRecord
from apps.qa.models import QAChecklistTemplate
from apps.reservations.models import Reservation
from apps.shortage.models import ShortageList
from apps.transfers.models import TransferRequest
from apps.users.management.commands.seed_permissions import PERMISSIONS
from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from .factories import make_branch, make_branch2, make_item, make_user

ROLES = ('supervisor', 'quality_manager', 'accountant', 'purchasing')
# flow -> (module that gates the POST, actions any of which opens it)
GATE = {
    'reservation': ('reservations', ('create', 'edit', 'approve', 'finalize')),
    'demand':      ('demand', ('create', 'edit', 'approve', 'finalize')),
    'transfer':    ('transfers', ('create', 'edit', 'approve', 'finalize')),
    'shortage':    ('shortage', ('create', 'edit', 'approve')),
    'qa':          ('hr', ('create', 'edit', 'approve', 'finalize', 'export')),
}
QA_ROLES = ('supervisor', 'quality_manager')       # registry qa_inspections


def seed_matrix(role):
    for module, actions in PERMISSIONS.get(role, {}).items():
        for a in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module=module, action=a,
                                                   defaults={'is_allowed': True})
    module_access.clear_cache()


class BranchPickerServerRuleTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        self.home = make_branch()
        self.other = make_branch2()
        self.third = make_branch('فرع ثالث', 'B03')
        self.item = make_item(softech_id='RB001')
        p = mock.patch('apps.demand.service.lookup_customer_in_erp', return_value=None)
        p.start()
        self.addCleanup(p.stop)
        self.tpl = QAChecklistTemplate.objects.create(name='t', items=[{'key': 'a', 'label': 'a'}])

    def tearDown(self):
        module_access.clear_cache()

    def _post(self, flow, client, branch):
        b = branch.id
        if flow == 'reservation':
            return client.post('/api/reservations/', {
                'item': self.item.id, 'branch': b, 'quantity_requested': 1,
                'contact_phone': '01012345678', 'contact_name': 'x'}, format='json')
        if flow == 'demand':
            return client.post('/api/demand/', {
                'phone': '01012345678', 'branch': b, 'source': 'walk_in',
                'items': [{'item_name_free': 'x'}]}, format='json')
        if flow == 'transfer':
            sup = self.third if b != self.third.id else self.other
            return client.post('/api/transfers/', {'requesting_branch': b, 'supplying_branch': sup.id},
                               format='json')
        if flow == 'shortage':
            return client.post('/api/shortage/lists/', {'branch': b, 'title': 'x'}, format='json')
        return client.post('/api/qa/inspections/', {'template': self.tpl.id, 'branch': b}, format='json')

    def _expected(self, role, flow):
        module, actions = GATE[flow]
        granted = set(PERMISSIONS.get(role, {}).get(module, set()))
        if flow == 'qa' and role not in QA_ROLES:
            return 403
        return 201 if granted & set(actions) else 403

    def test_all_branch_roles_on_foreign_branch(self):
        for role in ROLES:
            seed_matrix(role)
            _, _, client = make_user(f'rb_{role}', role=role, branch=self.home, access_all=True)
            for flow in GATE:
                with self.subTest(role=role, flow=flow):
                    r = self._post(flow, client, self.other)
                    self.assertEqual(r.status_code, self._expected(role, flow), getattr(r, 'data', None))

    def test_created_rows_point_at_the_picked_branch(self):
        seed_matrix('supervisor')
        _, _, client = make_user('rb_sup2', role='supervisor', branch=self.home, access_all=True)
        for flow, model, field in (('reservation', Reservation, 'branch'), ('demand', DemandRecord, 'branch'),
                                   ('shortage', ShortageList, 'branch')):
            with self.subTest(flow=flow):
                self.assertEqual(self._post(flow, client, self.other).status_code, 201)
                self.assertTrue(model.objects.filter(**{field: self.other}).exists())

    def test_purchasing_transfer_for_foreign_requesting_branch(self):
        seed_matrix('purchasing')
        _, _, client = make_user('rb_pur2', role='purchasing', branch=self.home, access_all=True)
        r = self._post('transfer', client, self.other)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(TransferRequest.objects.filter(requesting_branch=self.other).exists())

    def test_branch_bound_pharmacist_is_refused_on_foreign_branch(self):
        seed_matrix('pharmacist')
        _, _, client = make_user('rb_ph', role='pharmacist', branch=self.home)
        for flow in ('reservation', 'demand', 'transfer', 'shortage'):
            with self.subTest(flow=flow):
                self.assertEqual(self._post(flow, client, self.other).status_code, 403)


class PbxCallListsAndMeTests(TestCase):
    """Decisions 5 + 6 + the server-computed picker flag on /api/auth/me/."""

    def setUp(self):
        module_access.clear_cache()
        self.home = make_branch()
        for r in ('call_center', 'pharmacist', 'salesperson', 'viewer', 'supervisor',
                  'quality_manager', 'accountant', 'purchasing'):
            seed_matrix(r)

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role, **kw):
        return make_user(f'pc_{role}', role=role, branch=self.home, **kw)[2]

    def test_pbx_settings_follow_the_callcenter_matrix(self):
        with mock.patch('apps.pbx.extensions.extension_status', return_value={}):
            for role, ok in (('call_center', True), ('supervisor', True), ('viewer', False),
                             ('pharmacist', False)):
                with self.subTest(role=role):
                    c = self._client(role)
                    self.assertEqual(c.get('/api/pbx/extensions/status/').status_code == 200, ok)
                    code = c.post('/api/pbx/extensions/map/', {}, format='json').status_code
                    self.assertEqual(code != 403, ok)

    def test_pbx_settings_refused_when_the_matrix_denies_supervisor(self):
        RoleModuleAccess.objects.filter(role='supervisor', module='callcenter', action='edit').delete()
        module_access.clear_cache()
        c = self._client('supervisor')
        self.assertEqual(c.post('/api/pbx/extensions/map/', {}, format='json').status_code, 403)

    def test_call_list_create_follows_followups_create(self):
        for role, ok in (('call_center', True), ('pharmacist', True), ('salesperson', True),
                         ('viewer', False)):
            with self.subTest(role=role):
                code = self._client(role).post('/api/followups/call-lists/', {}, format='json').status_code
                self.assertEqual(code != 403, ok)         # allowed roles reach validation (400)

    def test_me_exposes_can_pick_any_branch(self):
        for role in ('supervisor', 'quality_manager', 'accountant', 'purchasing'):
            with self.subTest(role=role):
                r = self._client(role).get('/api/auth/me/')
                self.assertTrue(r.data['can_pick_any_branch'])
        for role in ('pharmacist', 'salesperson'):
            with self.subTest(role=role):
                r = self._client(role).get('/api/auth/me/')
                self.assertFalse(r.data['can_pick_any_branch'])
        r = make_user('pc_flag', role='pharmacist', branch=self.home, access_all=True)[2].get('/api/auth/me/')
        self.assertTrue(r.data['can_pick_any_branch'])


class PbxCredentialGuardTests(TestCase):
    """Fix round 1 (C1/I1): a call-center agent cannot take over a credentialed extension and read
    its SIP password; remaps go through the audited map endpoint; /auth/me carries can_set_webrtc."""

    def setUp(self):
        from apps.omni.crypto import encrypt_credentials
        from apps.pbx.models import AgentExtension
        module_access.clear_cache()
        for r in ('call_center', 'supervisor', 'pharmacist'):
            seed_matrix(r)
        self.home = make_branch()
        self.agent_user, self.agent, self.agent_c = make_user('cg_agent', role='call_center', branch=self.home)
        _, self.victim, _ = make_user('cg_victim', role='call_center', branch=self.home)
        self.sup_c = make_user('cg_sup', role='supervisor', branch=self.home)[2]
        self.cred = AgentExtension.objects.create(
            extension='301', staff=self.victim, webrtc_enabled=True,
            webrtc_credentials=encrypt_credentials({'password': 'S3CRET-pw'}))
        _, other, _ = make_user('cg_other', role='call_center', branch=self.home)
        self.plain = AgentExtension.objects.create(extension='302', staff=other)

    def tearDown(self):
        module_access.clear_cache()

    def test_agent_cannot_map_self_onto_a_credentialed_extension(self):
        r = self.agent_c.post('/api/pbx/extensions/map/', {'extension': '301', 'staff_id': self.agent.pk},
                              format='json')
        self.assertEqual(r.status_code, 403)
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.staff_id, self.victim.pk)
        with self.settings(PBX_WEBRTC_WSS_URL='wss://x'):
            cfg = self.agent_c.get('/api/pbx/webrtc/config/').data
        self.assertNotIn('password', cfg)

    def test_patch_staff_is_ignored(self):
        r = self.agent_c.patch(f'/api/pbx/agents/{self.cred.pk}/', {'staff': self.agent.pk}, format='json')
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.staff_id, self.victim.pk)
        self.assertIn(r.status_code, (200, 400, 403))

    def test_supervisor_can_still_remap(self):
        r = self.sup_c.post('/api/pbx/extensions/map/', {'extension': '301', 'staff_id': self.agent.pk},
                            format='json')
        self.assertEqual(r.status_code, 200)
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.staff_id, self.agent.pk)

    def test_agent_can_remap_an_extension_without_credentials(self):
        r = self.agent_c.post('/api/pbx/extensions/map/', {'extension': '302', 'staff_id': self.agent.pk},
                              format='json')
        self.assertEqual(r.status_code, 200)

    def test_me_exposes_can_set_webrtc(self):
        self.assertTrue(self.sup_c.get('/api/auth/me/').data['can_set_webrtc'])
        self.assertFalse(self.agent_c.get('/api/auth/me/').data['can_set_webrtc'])
        ph = make_user('cg_ph', role='pharmacist', branch=self.home)[2]
        self.assertFalse(ph.get('/api/auth/me/').data['can_set_webrtc'])


class PbxAgentEditGuardTests(TestCase):
    """Final review I2: the generic agents create / PATCH endpoints are audited, and on an extension
    carrying a browser-phone credential only a PBX manager may change extension / sip_peer /
    is_active (sip_peer is the WebRTC authorization user). The map endpoint applies the same rule to
    the target staff's previous extension when that one is credentialed."""

    def setUp(self):
        from apps.omni.crypto import encrypt_credentials
        from apps.pbx.models import AgentExtension
        module_access.clear_cache()
        for r in ('call_center', 'supervisor'):
            seed_matrix(r)
        self.home = make_branch()
        _, self.agent, self.agent_c = make_user('eg_agent', role='call_center', branch=self.home)
        _, self.victim, _ = make_user('eg_victim', role='call_center', branch=self.home)
        _, self.sup, self.sup_c = make_user('eg_sup', role='supervisor', branch=self.home)
        self.cred = AgentExtension.objects.create(
            extension='401', staff=self.victim, sip_peer='401', webrtc_enabled=True,
            webrtc_credentials=encrypt_credentials({'password': 'pw-401'}))
        self.plain = AgentExtension.objects.create(extension='402', sip_peer='402')

    def tearDown(self):
        module_access.clear_cache()

    def _audits(self, action, ext):
        from apps.audit.models import AuditLog
        return AuditLog.objects.filter(action=action, object_id=str(ext.pk))

    def test_agent_cannot_change_guarded_fields_of_a_credentialed_extension(self):
        for field, value in (('sip_peer', 'hijack'), ('extension', '499'), ('is_active', False)):
            with self.subTest(field=field):
                r = self.agent_c.patch(f'/api/pbx/agents/{self.cred.pk}/', {field: value}, format='json')
                self.assertEqual(r.status_code, 403)
                self.cred.refresh_from_db()
                self.assertEqual((self.cred.sip_peer, self.cred.extension, self.cred.is_active),
                                 ('401', '401', True))

    def test_agent_may_change_other_fields_of_a_credentialed_extension_audited(self):
        r = self.agent_c.patch(f'/api/pbx/agents/{self.cred.pk}/', {'queue_name': 'q2'}, format='json')
        self.assertEqual(r.status_code, 200)
        log = self._audits('pbx_extension_updated', self.cred).get()
        self.assertEqual(log.changes, {'queue_name': ['', 'q2']})
        self.assertEqual(log.user_id, self.agent.pk)

    def test_agent_edit_of_a_plain_extension_is_allowed_and_audited(self):
        r = self.agent_c.patch(f'/api/pbx/agents/{self.plain.pk}/', {'sip_peer': 'p-402'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._audits('pbx_extension_updated', self.plain).get().changes,
                         {'sip_peer': ['402', 'p-402']})

    def test_supervisor_may_change_a_credentialed_extension_audited(self):
        r = self.sup_c.patch(f'/api/pbx/agents/{self.cred.pk}/', {'sip_peer': 'new-401'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._audits('pbx_extension_updated', self.cred).get().changes,
                         {'sip_peer': ['401', 'new-401']})

    def test_create_is_audited(self):
        from apps.pbx.models import AgentExtension
        r = self.agent_c.post('/api/pbx/agents/', {'extension': '410', 'sip_peer': '410'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ext = AgentExtension.objects.get(extension='410')
        log = self._audits('pbx_extension_created', ext).get()
        self.assertEqual(log.changes['extension'], [None, '410'])

    def test_map_refuses_to_clear_the_targets_credentialed_previous_extension(self):
        # the victim holds credentialed 401; an agent maps the victim onto plain 402 — that would
        # take the victim's browser phone off 401
        r = self.agent_c.post('/api/pbx/extensions/map/', {'extension': '402', 'staff_id': self.victim.pk},
                              format='json')
        self.assertEqual(r.status_code, 403)
        self.cred.refresh_from_db()
        self.plain.refresh_from_db()
        self.assertEqual(self.cred.staff_id, self.victim.pk)
        self.assertIsNone(self.plain.staff_id)

    def test_map_supervisor_moves_the_target_off_a_credentialed_extension_audited(self):
        r = self.sup_c.post('/api/pbx/extensions/map/', {'extension': '402', 'staff_id': self.victim.pk},
                            format='json')
        self.assertEqual(r.status_code, 200)
        self.cred.refresh_from_db()
        self.assertIsNone(self.cred.staff_id)
        self.assertEqual(self._audits('pbx_extension_mapped', self.cred).get().changes,
                         {'staff': [self.victim.pk, None]})

    def test_map_agent_cannot_change_sip_peer_of_a_credentialed_extension(self):
        r = self.agent_c.post('/api/pbx/extensions/map/',
                              {'extension': '401', 'staff_id': self.victim.pk, 'sip_peer': 'hijack'},
                              format='json')
        self.assertEqual(r.status_code, 403)
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.sip_peer, '401')


class CallListCloseScopeTests(TestCase):
    """Final review I3: closing a call list (it cancels every open task) is for the list's creator,
    an all-branch user, or a user whose branches cover every branch in the list's criteria."""

    def setUp(self):
        from apps.followups.models import CallList
        module_access.clear_cache()
        for r in ('pharmacist', 'supervisor'):
            seed_matrix(r)
        self.home = make_branch()
        self.other = make_branch2()
        _, self.creator, self.creator_c = make_user('cl_creator', role='pharmacist', branch=self.home)
        self.mk = lambda branches: CallList.objects.create(
            name='L', criteria={'branch_ids': branches} if branches is not None else {'segments': ['A']},
            created_by=self.creator)

    def tearDown(self):
        module_access.clear_cache()

    def _close(self, client, cl):
        return client.post(f'/api/followups/call-lists/{cl.pk}/close/', {}, format='json').status_code

    def test_other_branch_pharmacist_is_refused(self):
        cl = self.mk([self.home.pk])
        c = make_user('cl_far', role='pharmacist', branch=self.other)[2]
        self.assertEqual(self._close(c, cl), 403)
        cl.refresh_from_db()
        self.assertEqual(cl.status, 'active')

    def test_branch_pharmacist_is_refused_on_a_company_wide_list(self):
        cl = self.mk(None)
        c = make_user('cl_near0', role='pharmacist', branch=self.home)[2]
        self.assertEqual(self._close(c, cl), 403)

    def test_creator_may_close(self):
        cl = self.mk([self.other.pk])
        self.assertEqual(self._close(self.creator_c, cl), 200)

    def test_all_branch_supervisor_may_close(self):
        cl = self.mk(None)
        c = make_user('cl_sup', role='supervisor', branch=self.home)[2]
        self.assertEqual(self._close(c, cl), 200)

    def test_branch_pharmacist_may_close_a_list_inside_their_branch(self):
        cl = self.mk([self.home.pk])
        c = make_user('cl_near', role='pharmacist', branch=self.home)[2]
        self.assertEqual(self._close(c, cl), 200)

    def test_legacy_single_branch_criteria_counts(self):
        from apps.followups.models import CallList
        cl = CallList.objects.create(name='old', criteria={'branch_id': self.home.pk}, created_by=self.creator)
        c = make_user('cl_near2', role='pharmacist', branch=self.home)[2]
        self.assertEqual(self._close(c, cl), 200)

    def test_list_rows_carry_the_close_rule(self):
        mine = self.mk([self.home.pk])
        far = self.mk([self.other.pk])
        c = make_user('cl_rows', role='pharmacist', branch=self.home)[2]
        rows = {r['id']: r['can_close'] for r in c.get('/api/followups/call-lists/').json()}
        self.assertTrue(rows[mine.pk])
        self.assertFalse(rows[far.pk])

    def test_close_rule_on_rows_keeps_the_query_count_flat(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        c = make_user('cl_flat', role='pharmacist', branch=self.home)[2]
        self.mk([self.home.pk])
        c.get('/api/followups/call-lists/')                       # warm the session / memo
        with CaptureQueriesContext(connection) as one:
            c.get('/api/followups/call-lists/')
        for _ in range(5):
            self.mk([self.home.pk])
        with CaptureQueriesContext(connection) as six:
            c.get('/api/followups/call-lists/')
        self.assertEqual(len(six), len(one))
