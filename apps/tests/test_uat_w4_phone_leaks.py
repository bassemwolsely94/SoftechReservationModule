"""
UAT W4 P0s (2026-11-17): a member of staff with `can_see_customer_phone = False` saw full numbers
in the reservations export / receipt / WhatsApp share (role-only check), and viewers — and
privileged roles with the flag off — saw every follow-up customer's number. Both now use the
shared record-phone rule (apps/customers/access.record_phones_visible: D3 flag, D4/D7 viewer).
"""
import io

from django.test import TestCase, override_settings

from apps.customers.models import Customer
from apps.followups.models import FollowUpTask

from .factories import make_item, make_user
from .test_reservations_r7 import _Base, _u

PHONE = '01000000001'
CUST_PHONE = '01055556666'


@override_settings(RBAC_ENFORCEMENT='log')
class ReservationPhoneRuleTests(_Base):
    def setUp(self):
        super().setUp()
        self.pharm.can_see_customer_phone = False
        self.pharm.save(update_fields=['can_see_customer_phone'])

    def test_export_has_no_phone_for_phone_hidden_pharmacist(self):
        import openpyxl
        res = self.res()
        r = self.pharm_c.post(_u('bulk'), {'action': 'export', 'ids': [res.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        cells = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
        self.assertNotIn(PHONE, cells)

    def test_receipt_has_no_phone_for_phone_hidden_pharmacist(self):
        res = self.res()
        r = self.pharm_c.get(_u(res.id, 'print'))
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertNotIn(PHONE, r.content.decode())

    def test_share_has_no_phone_for_phone_hidden_pharmacist(self):
        res = self.res()
        r = self.pharm_c.post(_u(res.id, 'share-whatsapp'), {}, format='json')
        self.assertNotIn(PHONE, r.content.decode())

    def test_pharmacist_with_the_flag_still_sees_it(self):
        self.pharm.can_see_customer_phone = True
        self.pharm.save(update_fields=['can_see_customer_phone'])
        res = self.res()
        r = self.pharm_c.get(_u(res.id, 'print'))
        self.assertIn(PHONE, r.content.decode())


class FollowUpPhoneRuleTests(TestCase):
    def setUp(self):
        from .factories import make_branch
        self.branch = make_branch('فرع متابعة', 'FU1')
        self.cust = Customer.objects.create(name='عميل متابعة', phone=CUST_PHONE, whatsapp_phone=CUST_PHONE,
                                            preferred_branch=self.branch)
        self.task = FollowUpTask.objects.create(customer=self.cust, item=make_item(), branch=self.branch,
                                                due_date='2026-11-20', status='pending')

    def _body(self, role, **flags):
        _, prof, client = make_user(f'fu_{role}_{len(flags)}', role=role, branch=self.branch, access_all=True)
        for k, v in flags.items():
            setattr(prof, k, v)
        prof.save()
        return client.get(f'/api/followups/tasks/{self.task.pk}/').content.decode()

    def test_viewer_sees_no_number(self):
        self.assertNotIn(CUST_PHONE, self._body('viewer'))

    def test_admin_with_the_flag_off_sees_no_number(self):
        self.assertNotIn(CUST_PHONE, self._body('admin', can_see_customer_phone=False))

    def test_pharmacist_with_the_flag_sees_the_number(self):
        self.assertIn(CUST_PHONE, self._body('pharmacist'))
