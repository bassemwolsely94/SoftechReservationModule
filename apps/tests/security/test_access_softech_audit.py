from types import SimpleNamespace

from django.test import TestCase

from apps.access import context as access_context
from apps.audit.models import AuditLog
from apps.sync.softech_load import scope as softech_scope
from core.softech_audit import audit_softech_write


class WriteAuditOriginTests(TestCase):
    def test_write_audit_has_ip_device_zone(self):
        net = SimpleNamespace(zone='external', ip='1.2.3.4', site=None)
        ctx = access_context.AccessContext(network=net, user_id=None, role='salesperson',
                                           device=SimpleNamespace(public_id='dev-1'), zone='Z4')
        token = access_context.access_context.set(ctx)
        try:
            with softech_scope('web:test'):
                row = audit_softech_write('softech_test_written', zone='mine')
        finally:
            access_context.access_context.reset(token)
        row = AuditLog.objects.get(pk=row.pk)
        self.assertEqual(row.extra['ip'], '1.2.3.4')
        self.assertEqual(row.extra['device_id'], 'dev-1')
        self.assertEqual(row.extra['network'], 'external')
        self.assertEqual(row.extra['scope'], 'web:test')
        self.assertEqual(row.extra['zone'], 'mine')   # caller's own value wins

    def test_write_audit_without_context_has_scope_only(self):
        with softech_scope('job:x'):
            row = audit_softech_write('softech_test_written')
        extra = AuditLog.objects.get(pk=row.pk).extra
        self.assertEqual(extra, {'scope': 'job:x'})
