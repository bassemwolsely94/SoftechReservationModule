"""
UAT W5a P2 — creating a shortage list or a call-center case answered 201 without the new
id (the write serializers carry only the input fields), so the screens could not open the
new record. Both now answer with the same row the list / detail endpoints return.
"""
from django.test import TestCase

from apps.callcenter.models import CustomerCase
from apps.shortage.models import ShortageList

from .factories import make_branch, make_call_center, make_customer, make_user


class ShortageListCreateReturnsRowTests(TestCase):
    def setUp(self):
        self.branch = make_branch('فرع W5a', 'W5A')
        _u, _p, self.api = make_user('w5a_pharm', role='pharmacist', branch=self.branch)

    def test_create_returns_id_and_list_row(self):
        r = self.api.post('/api/shortage/lists/', {'branch': self.branch.pk, 'title': 'زيارة المندوب'},
                          format='json')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        sl = ShortageList.objects.get(pk=body['id'])
        self.assertEqual(sl.branch_id, self.branch.pk)
        self.assertEqual(body['title'], 'زيارة المندوب')
        self.assertEqual(body['item_count'], 0)
        self.assertEqual(body['status'], sl.status)
        self.assertIn('status_label', body)
        # the new list is the one the screen then opens
        self.assertEqual(self.api.get(f'/api/shortage/lists/{sl.pk}/').status_code, 200)


class CallCenterCaseCreateReturnsIdTests(TestCase):
    def setUp(self):
        _u, _p, self.api = make_call_center('w5a_cc')
        self.customer = make_customer('عميل W5a', '01000000991')

    def test_create_returns_id_and_detail(self):
        r = self.api.post('/api/callcenter/cases/', {
            'customer': self.customer.pk, 'category': 'complaint', 'priority': 'normal',
            'title': '  تأخير توصيل  ', 'description': 'x',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        case = CustomerCase.objects.get(pk=body['id'])
        self.assertEqual(body['case_number'], case.case_number)
        self.assertEqual(body['title'], 'تأخير توصيل')
        self.assertTrue(body['events'])                     # the opening event is in the answer
        detail = self.api.get(f'/api/callcenter/cases/{case.pk}/')
        self.assertEqual(detail.status_code, 200, detail.content)
        # same phone masking as the detail endpoint
        self.assertEqual(body['customer_phone'], detail.json()['customer_phone'])

    def test_invalid_case_still_400(self):
        r = self.api.post('/api/callcenter/cases/', {
            'customer': self.customer.pk, 'category': 'complaint', 'title': '   '}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(CustomerCase.objects.exists())
