"""No HQ branch configured: hq_code() raises HQNotConfigured (an ImproperlyConfigured, so
existing `except ImproperlyConfigured` callers keep working) and the API answers 503 with a
fixed Arabic message instead of a 500 (branch classification Task 6, fix round 1)."""
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from apps.branches.models import Branch, HQNotConfigured, _reset_hq_code_cache, hq_code
from core.exceptions import api_exception_handler

HQ_MESSAGE = 'لم يُحدَّد فرع المركز الرئيسي — راجع إعدادات الفروع'


class HqNotConfiguredTests(TestCase):
    def setUp(self):
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        Branch.objects.filter(kind=Branch.KIND_HQ).update(kind=Branch.KIND_RETAIL)
        _reset_hq_code_cache()

    def test_hq_code_raises_hq_not_configured(self):
        with self.assertRaises(HQNotConfigured) as cm:
            hq_code()
        self.assertIsInstance(cm.exception, ImproperlyConfigured)

    def test_existing_improperly_configured_callers_still_catch_it(self):
        try:
            hq_code()
        except ImproperlyConfigured:
            caught = True
        else:
            caught = False
        self.assertTrue(caught)

    def test_handler_maps_to_503_and_rolls_back(self):
        with mock.patch('core.exceptions.set_rollback') as rollback:
            r = api_exception_handler(HQNotConfigured('found 0'), {})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data, {'detail': HQ_MESSAGE, 'code': 'hq_not_configured'})
        rollback.assert_called_once_with()

    def test_503_logs_a_warning_naming_the_view(self):
        class ClosingStockStoresView:
            pass
        with self.assertLogs('core.exceptions', level='WARNING') as logs:
            api_exception_handler(HQNotConfigured('Expected exactly one Branch with kind=hq, found 0.'),
                                  {'view': ClosingStockStoresView()})
        self.assertEqual(len(logs.output), 1)
        self.assertIn('ClosingStockStoresView', logs.output[0])
        self.assertIn('found 0', logs.output[0])

    def test_other_improperly_configured_is_not_mapped(self):
        self.assertIsNone(api_exception_handler(ImproperlyConfigured('x'), {}))

    def test_endpoint_answers_503_without_hq(self):
        from .factories import make_user
        _user, _profile, client = make_user('t6_hq_admin', role='admin', access_all=True)
        r = client.get('/api/finance/gl/closing-stock-stores/')
        self.assertEqual(r.status_code, 503, r.content[:300])
        self.assertEqual(r.json()['code'], 'hq_not_configured')
