"""
Tax Invoicing go-live pieces: which ETA system we talk to, the production gate, and EGS item-code
requests (apps/tax_invoicing/environment.py, coding.py). ETA is mocked; these tests prove our behaviour
around ETA's documented answers, not ETA's acceptance.
"""
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase, override_settings

from apps.tax_invoicing import coding, environment, eta_client, signing
from apps.tax_invoicing.models import TaxAuditEvent, TaxCodeRequest, TaxIssuerProfile, TaxItemProfile
from apps.tests.test_tax_invoicing import Fixture, api

CODING_ON = dict(TAX_ETA_CODING_ENABLED=True, WRITER_INSTANCE=True, TAX_ETA_ENVIRONMENT='preprod',
                 TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='', TAX_ETA_CLIENT_ID='cid', TAX_ETA_CLIENT_SECRET='sec')


def _response(status_code, body):
    r = mock.Mock(status_code=status_code)
    r.json.return_value = body
    return r


class EnvironmentTests(SimpleTestCase):

    @override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='')
    def test_preprod_uses_published_addresses(self):
        self.assertEqual(environment.api_base(), 'https://api.preprod.invoicing.eta.gov.eg')
        self.assertEqual(environment.id_base(), 'https://id.preprod.eta.gov.eg')
        self.assertFalse(environment.is_production())

    @override_settings(TAX_ETA_ENVIRONMENT='', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='')
    def test_nothing_set_reaches_nothing(self):
        self.assertEqual(environment.api_base(), '')
        with self.assertRaises(eta_client.EtaNotConfigured):
            eta_client._api('/x')

    @override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='https://api.invoicing.eta.gov.eg/',
                       TAX_ETA_ID_BASE_URL='')
    def test_explicit_production_url_counts_as_production_whatever_the_name(self):
        self.assertTrue(environment.is_production())

    @override_settings(TAX_ETA_ENVIRONMENT='production', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='',
                       WRITER_INSTANCE=True, TAX_ETA_PRODUCTION_ALLOWED=False)
    def test_production_send_refused_without_owner_switch(self):
        with mock.patch.object(eta_client.requests, 'post') as post:
            for call in (lambda: eta_client.submit_documents('{}'), lambda: eta_client.create_egs_codes([{}])):
                with self.assertRaises(eta_client.EtaNotConfigured):
                    call()
            post.assert_not_called()

    @override_settings(TAX_ETA_ENVIRONMENT='production', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='',
                       WRITER_INSTANCE=False, TAX_ETA_PRODUCTION_ALLOWED=True)
    def test_production_switch_counts_only_on_the_writer_instance(self):
        with self.assertRaises(environment.ProductionNotAllowed):
            environment.assert_may_send()

    @override_settings(TAX_ALLOW_MOCK_SIGNER=True, TAX_ETA_ENVIRONMENT='production', TAX_ETA_API_BASE_URL='',
                       TAX_ETA_ID_BASE_URL='')
    def test_mock_signer_refused_against_production_by_environment_name(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live(signing.MockSigner())

    @override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='',
                       TAX_ETA_CLIENT_ID='cid', TAX_ETA_CLIENT_SECRET='sec')
    def test_login_goes_to_preprod_identity_service(self):
        eta_client.reset_token()
        with mock.patch.object(eta_client.requests, 'post',
                               return_value=_response(200, {'access_token': 'T', 'expires_in': 3600})) as post:
            self.assertTrue(eta_client.check_login())
        self.assertEqual(post.call_args[0][0], 'https://id.preprod.eta.gov.eg/connect/token')
        eta_client.reset_token()


@override_settings(**CODING_ON)
class CodeRequestTests(Fixture, TestCase):

    def setUp(self):
        self.build('cr')
        eta_client.reset_token()
        self.p1 = TaxItemProfile.objects.create(softech_itemcode='50001', item_name='Panadol 500 tab',
                                                item_name_ar='بانادول ٥٠٠', gpc_code='10000454')
        self.p2 = TaxItemProfile.objects.create(softech_itemcode='50002', item_name='Brufen syrup', gpc_code='')
        self.coded = TaxItemProfile.objects.create(softech_itemcode='50003', item_name='X', gpc_code='10000454',
                                                   eta_code='EG-100200300-50003', coding_status=TaxItemProfile.CODE_APPROVED)

    def tearDown(self):
        eta_client.reset_token()

    def _token_then(self, *responses):
        return [_response(200, {'access_token': 'T', 'expires_in': 3600}), *responses]

    def test_prepare_builds_our_code_and_skips_what_cannot_go(self):
        out = coding.prepare([self.p1.pk, self.p2.pk, self.coded.pk], self.accountant)
        self.assertEqual(len(out['created']), 1)
        row = TaxCodeRequest.objects.get()
        self.assertEqual(row.item_code, 'EG-100200300-50001')
        self.assertEqual((row.parent_code, row.code_name_ar), ('10000454', 'بانادول ٥٠٠'))
        whys = {s['itemcode']: s['why'] for s in out['skipped']}
        self.assertIn('GPC', whys['50002'])
        self.assertIn('50003', whys)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.coding_status, TaxItemProfile.CODE_MISSING)   # preparing moves nothing

    def test_one_open_request_per_item(self):
        coding.prepare([self.p1.pk], self.accountant)
        out = coding.prepare([self.p1.pk], self.accountant)
        self.assertEqual(out['created'], [])
        self.assertEqual(TaxCodeRequest.objects.count(), 1)

    def test_prepare_needs_company_tax_id(self):
        i = TaxIssuerProfile.load()
        i.tax_id = ''
        i.save()
        with self.assertRaises(coding.TaxRuleError):
            coding.prepare([self.p1.pk], self.accountant)

    @override_settings(TAX_ETA_CODING_ENABLED=False)
    def test_send_closed_by_default_switch(self):
        coding.prepare([self.p1.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post') as post:
            with self.assertRaises(coding.TaxRuleError):
                coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '1')
            post.assert_not_called()

    def test_send_needs_typed_count(self):
        coding.prepare([self.p1.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post') as post:
            with self.assertRaises(coding.TaxRuleError):
                coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '7')
            post.assert_not_called()

    def test_send_posts_eta_fields_and_marks_item_pending(self):
        coding.prepare([self.p1.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post', side_effect=self._token_then(_response(200, {}))) as post:
            out = coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '1')
        self.assertEqual(out['submitted'], 1)
        url = post.call_args_list[1][0][0]
        self.assertEqual(url, 'https://api.preprod.invoicing.eta.gov.eg/api/v1.0/codetypes/requests/codes')
        import json
        item = json.loads(post.call_args_list[1][1]['data'])['items'][0]
        self.assertEqual(item['codeType'], 'EGS')
        self.assertEqual(item['itemCode'], 'EG-100200300-50001')
        self.assertEqual(item['parentCode'], '10000454')
        self.assertTrue(item['activeFrom'].endswith('T00:00:00Z'))
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.coding_status, self.p1.eta_code), (TaxItemProfile.CODE_PENDING, 'EG-100200300-50001'))
        self.assertTrue(TaxAuditEvent.objects.filter(action='code_request_sent').exists())
        self.assertEqual(TaxCodeRequest.objects.get().environment, 'preprod')

    def test_refused_request_leaves_item_uncoded_and_can_be_resent(self):
        coding.prepare([self.p1.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post',
                               side_effect=self._token_then(_response(404, {'error': 'parent not found'}))):
            out = coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '1')
        self.assertEqual(out['failed'], 1)
        row = TaxCodeRequest.objects.get()
        self.assertEqual(row.status, TaxCodeRequest.FAILED)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.coding_status, TaxItemProfile.CODE_MISSING)
        with mock.patch.object(eta_client.requests, 'post', return_value=_response(200, {})):
            self.assertEqual(coding.send([row.pk], self.admin, '1')['submitted'], 1)

    def test_timeout_stops_the_batch_and_is_checked_before_resend(self):
        p3 = TaxItemProfile.objects.create(softech_itemcode='50004', item_name='Y', gpc_code='10000454')
        coding.prepare([self.p1.pk, p3.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post',
                               side_effect=self._token_then(requests.Timeout())) as post:
            out = coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '2')
        self.assertEqual((out['uncertain'], post.call_count), (1, 2))   # token + one request, then stop
        self.assertTrue(out['stopped'])
        uncertain = TaxCodeRequest.objects.get(status=TaxCodeRequest.UNCERTAIN)
        # An uncertain request is not resent by "send".
        with self.assertRaises(coding.TaxRuleError):
            coding.send([uncertain.pk], self.admin, '1')
        # ETA has it: becomes submitted and the item pending.
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': uncertain.item_code, 'status': 'Submitted',
                                                             'codeUsageRequestID': 77}])):
            coding.refresh(self.admin)
        uncertain.refresh_from_db()
        self.assertEqual((uncertain.status, uncertain.eta_request_id), (TaxCodeRequest.SUBMITTED, '77'))
        uncertain.profile.refresh_from_db()
        self.assertEqual(uncertain.profile.coding_status, TaxItemProfile.CODE_PENDING)

    def test_uncertain_that_eta_never_saw_becomes_resendable(self):
        coding.prepare([self.p1.pk], self.accountant)
        row = TaxCodeRequest.objects.get()
        TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.UNCERTAIN)
        with mock.patch.object(eta_client.requests, 'post', return_value=_response(200, {'access_token': 'T'})), \
                mock.patch.object(eta_client.requests, 'get', return_value=_response(200, [])):
            coding.refresh(self.admin)
        row.refresh_from_db()
        self.assertEqual(row.status, TaxCodeRequest.FAILED)

    def test_could_not_ask_changes_nothing(self):
        coding.prepare([self.p1.pk], self.accountant)
        row = TaxCodeRequest.objects.get()
        TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.UNCERTAIN)
        with mock.patch.object(eta_client.requests, 'post', return_value=_response(200, {'access_token': 'T'})), \
                mock.patch.object(eta_client.requests, 'get', side_effect=requests.ConnectionError()):
            out = coding.refresh(self.admin)
        self.assertTrue(out['error'])
        row.refresh_from_db()
        self.assertEqual(row.status, TaxCodeRequest.UNCERTAIN)

    def _submitted(self):
        coding.prepare([self.p1.pk], self.accountant)
        with mock.patch.object(eta_client.requests, 'post', side_effect=self._token_then(_response(200, {}))):
            coding.send(TaxCodeRequest.objects.values_list('pk', flat=True), self.admin, '1')
        return TaxCodeRequest.objects.get()

    def test_eta_approval_codes_the_item(self):
        row = self._submitted()
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': row.item_code, 'status': 'Approved',
                                                             'activeFrom': '2026-11-13T00:00:00Z'}])):
            out = coding.refresh(self.admin)
        self.assertEqual(out['approved'], 1)
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.coding_status, self.p1.code_type), (TaxItemProfile.CODE_APPROVED, 'EGS'))
        self.assertTrue(TaxAuditEvent.objects.filter(action='item_coding_from_eta', entity_id=str(self.p1.pk)).exists())

    def test_eta_rejection_keeps_item_blocked_and_allows_a_new_request(self):
        row = self._submitted()
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': row.item_code, 'status': 'Rejected'}])):
            coding.refresh(self.admin)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.coding_status, TaxItemProfile.CODE_REJECTED)
        self.assertIn(self.p1, list(coding.candidates()))
        self.assertEqual(len(coding.prepare([self.p1.pk], self.accountant)['created']), 1)

    def test_prepared_request_can_be_corrected_but_not_after_sending(self):
        coding.prepare([self.p1.pk], self.accountant)
        row = TaxCodeRequest.objects.get()
        coding.edit(row.pk, self.accountant, {'parent_code': '10000455', 'code_name': 'Panadol'})
        with self.assertRaises(coding.TaxRuleError):
            coding.edit(row.pk, self.accountant, {'parent_code': '123'})
        TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.SUBMITTED)
        with self.assertRaises(coding.TaxRuleError):
            coding.edit(row.pk, self.accountant, {'code_name': 'Other'})
        with self.assertRaises(coding.TaxRuleError):
            coding.cancel(row.pk, self.accountant, 'x')

    # ── Views and permissions ──────────────────────────────────────────────────────────────────

    def test_accountant_prepares_but_cannot_send(self):
        r = api(self.accountant).post('/api/tax-invoicing/codes/prepare/', {'ids': [self.p1.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        ids = list(TaxCodeRequest.objects.values_list('pk', flat=True))
        with mock.patch.object(eta_client.requests, 'post') as post:
            r = api(self.accountant).post('/api/tax-invoicing/codes/send/', {'ids': ids, 'confirm': '1'}, format='json')
            self.assertEqual(r.status_code, 403)
            post.assert_not_called()

    def test_admin_sends_through_the_view(self):
        coding.prepare([self.p1.pk], self.accountant)
        ids = list(TaxCodeRequest.objects.values_list('pk', flat=True))
        with mock.patch.object(eta_client.requests, 'post', side_effect=self._token_then(_response(200, {}))):
            r = api(self.admin).post('/api/tax-invoicing/codes/send/', {'ids': ids, 'confirm': '1'}, format='json')
        self.assertEqual((r.status_code, r.json()['submitted']), (200, 1))

    def test_pharmacist_cannot_see_code_requests(self):
        self.assertEqual(api(self.pharmacist).get('/api/tax-invoicing/codes/').status_code, 403)

    def test_list_and_candidates(self):
        coding.prepare([self.p1.pk], self.accountant)
        body = api(self.accountant).get('/api/tax-invoicing/codes/').json()
        self.assertEqual(body['rows'][0]['item_code'], 'EG-100200300-50001')
        self.assertFalse(body['summary']['environment']['is_production'])
        cands = api(self.accountant).get('/api/tax-invoicing/codes/candidates/').json()
        self.assertEqual([c['itemcode'] for c in cands], ['50002'])   # p1 has an open request, 50003 is coded

    def test_eta_status_shows_no_secret(self):
        body = api(self.accountant).get('/api/tax-invoicing/eta/status/').json()
        self.assertEqual(body['environment'], 'preprod')
        self.assertNotIn('sec', str(body))

    def test_login_check_needs_finalize_and_reports_failure_without_raising(self):
        self.assertEqual(api(self.accountant).post('/api/tax-invoicing/eta/check-login/').status_code, 403)
        with mock.patch.object(eta_client.requests, 'post', return_value=_response(401, {})):
            r = api(self.admin).post('/api/tax-invoicing/eta/check-login/')
        self.assertEqual((r.status_code, r.json()['ok']), (200, False))
