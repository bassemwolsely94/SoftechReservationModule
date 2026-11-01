"""N4 / Task 2 - the SOFTECH gate decision: role x zone x scope, log first."""
from types import SimpleNamespace

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.access import context as access_context
from apps.access import softech_gate as gate
from apps.access.models import ZonePolicy
from apps.audit.models import AuditLog
from apps.sync.softech_load import scope as softech_scope
from apps.tests.factories import make_user

FULL, READ, NONE = gate.FULL, gate.READ, gate.NONE


def ctx(zone='Z1', user=7, net='internal', failed=False, role='x'):
    return SimpleNamespace(zone=zone, user_id=user, failed=failed, role=role, device=None,
                           network=SimpleNamespace(zone=net, ip='10.0.0.5'))


def prof(role, external_softech_write=False):
    return SimpleNamespace(role=role, external_softech_write=external_softech_write)


CASES = [
    ('job:sync_stock',           None,                              None,               FULL, None),
    ('cmd:shell',                None,                              None,               FULL, None),
    ('web',                      None,                              None,               NONE, 'no_context'),
    ('web:external:anon',        ctx(zone=None, user=None, net='external'), None,       NONE, 'anonymous'),
    ('web:internal:anon',        ctx(failed=True, net='internal', user=None, zone=None), None, FULL, 'context_failed'),
    ('web:external:anon',        ctx(failed=True, net='external', user=None, zone=None), None, NONE, 'context_failed'),
    ('web:internal:salesperson', ctx(zone='Z1'),                    prof('salesperson'), FULL, None),
    ('web:internal:salesperson', ctx(zone='Z2'),                    prof('salesperson'), READ, 'zone_no_write'),
    ('web:external:salesperson', ctx(zone='Z3', net='external'),    prof('salesperson'), NONE, 'zone_no_read'),
    ('web:external:supervisor',  ctx(zone='Z3', net='external'),    prof('supervisor'),  READ, 'zone_no_write'),
    ('web:external:admin',       ctx(zone='Z3', net='external'),    prof('admin'),       READ, 'zone_no_write'),
    ('web:external:admin',       ctx(zone='Z3', net='external'),
     prof('admin', external_softech_write=True),                                         FULL, None),
    ('web:external:delivery',    ctx(zone='Z4', net='external'),    prof('delivery'),    NONE, 'zone_no_read'),
]


class DecideTableTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_table(self):
        for scope, c, p, grant, reason in CASES:
            with self.subTest(scope=scope, zone=getattr(c, 'zone', None), role=getattr(p, 'role', None)):
                d = gate.decide(scope, c, p)
                self.assertEqual((d.grant, d.reason), (grant, reason))

    def test_role_without_rows_inside_full_outside_none(self):
        ZonePolicy.objects.filter(role='viewer').delete()
        cache.clear()
        self.assertEqual(gate.decide('web', ctx(zone='Z2'), prof('viewer')).grant, FULL)
        d = gate.decide('web', ctx(zone='Z3', net='external'), prof('viewer'))
        self.assertEqual((d.grant, d.reason), (NONE, 'zone_no_read'))


class CheckTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user, self.profile, _ = make_user('gate_sales', role='salesperson')
        net = SimpleNamespace(zone='external', ip='1.2.3.4', site=None)
        self.ctx = access_context.AccessContext(network=net, user_id=self.user.pk, role='salesperson',
                                                device=None, zone='Z4')
        self.token = access_context.access_context.set(self.ctx)

    def tearDown(self):
        access_context.access_context.reset(self.token)
        cache.clear()

    def _count(self):
        return AuditLog.objects.filter(action='softech_gate_denied').count()

    @override_settings(SOFTECH_GATE_ENFORCEMENT='log')
    def test_check_log_mode_returns_full_and_audits_once(self):
        with softech_scope('web:external:salesperson'):
            first = gate.check('probe')
            second = gate.check('probe')
        self.assertEqual(first.grant, FULL)
        self.assertEqual(second.grant, FULL)
        self.assertEqual(self._count(), 1)
        row = AuditLog.objects.get(action='softech_gate_denied')
        self.assertEqual(row.extra['reason'], 'zone_no_read')
        self.assertFalse(row.extra['enforced'])

    @override_settings(SOFTECH_GATE_ENFORCEMENT='log')
    def test_check_log_mode_read_keeps_read_grant(self):
        self.profile.role = 'supervisor'
        self.profile.save()
        object.__setattr__(self.ctx, 'zone', 'Z3')
        with softech_scope('web:external:supervisor'):
            d = gate.check('probe')
        self.assertEqual((d.grant, d.reason), (READ, 'zone_no_write'))

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_ENFORCE_GUARD=True,
                       NETWORK_HEADER_TRUSTED=False)
    def test_check_enforce_unsafe_runs_as_log(self):
        self.assertEqual(gate.mode(), 'log')
        with softech_scope('web:external:salesperson'):
            self.assertEqual(gate.check('probe').grant, FULL)

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_ENFORCE_GUARD=False)
    def test_check_enforce_returns_none(self):
        with softech_scope('web:external:salesperson'):
            d = gate.check('probe')
        self.assertEqual((d.grant, d.reason), (NONE, 'zone_no_read'))
        self.assertTrue(AuditLog.objects.get(action='softech_gate_denied').extra['enforced'])

    @override_settings(SOFTECH_GATE_ENFORCEMENT='off')
    def test_check_off_never_audits(self):
        with softech_scope('web:external:salesperson'):
            self.assertEqual(gate.check('probe').grant, FULL)
        self.assertEqual(self._count(), 0)

    @override_settings(SOFTECH_GATE_ENFORCEMENT='bogus')
    def test_unknown_mode_is_log(self):
        self.assertEqual(gate.mode(), 'log')

    @override_settings(SOFTECH_GATE_ENFORCEMENT='log')
    def test_system_scope_is_full_and_silent(self):
        with softech_scope('job:sync_stock'):
            self.assertEqual(gate.check('probe').grant, FULL)
        self.assertEqual(self._count(), 0)
