"""
Tax Invoicing go-live pieces: which ETA system we talk to, the production gate, and EGS item-code
requests (apps/tax_invoicing/environment.py, coding.py). ETA is mocked; these tests prove our behaviour
around ETA's documented answers, not ETA's acceptance.
"""
import datetime as dt
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.tax_invoicing import coding, environment, eta_client, receipts, signing
from apps.tax_invoicing.models import (TaxAuditEvent, TaxCodeRequest, TaxIssuerProfile, TaxItemProfile, TaxReceipt,
                                       TaxReceiptBranchConfig)
from apps.tests.test_tax_invoicing import Fixture, api

CODING_ON = dict(TAX_ETA_CODING_ENABLED=True, WRITER_INSTANCE=True, TAX_ETA_ENVIRONMENT='preprod',
                 TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='', TAX_ETA_CLIENT_ID='cid', TAX_ETA_CLIENT_SECRET='sec')


def _response(status_code, body):
    r = mock.Mock(status_code=status_code)
    r.json.return_value = body
    return r


class EnvironmentTests(SimpleTestCase):

    def test_branch_secret_comes_from_the_environment_then_the_env_file(self):
        with mock.patch.dict('os.environ', {'POS_X': 'from-process'}):
            self.assertEqual(eta_client._env_secret('POS_X'), 'from-process')
        with mock.patch.dict('os.environ', {}, clear=False), mock.patch('decouple.config', return_value='from-file'):
            import os
            os.environ.pop('POS_Y', None)
            self.assertEqual(eta_client._env_secret('POS_Y'), 'from-file')
        with mock.patch('decouple.config', return_value=''):
            with self.assertRaises(eta_client.EtaNotConfigured):
                eta_client._env_secret('POS_MISSING_' + 'Z')

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


    @override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='',
                       TAX_ETA_CLIENT_ID='cid', TAX_ETA_CLIENT_SECRET='sec', TAX_ETA_CA_BUNDLE='C:/eta/preprod-root-ca.pem')
    def test_preprod_root_ca_is_trusted_for_eta_calls_only_when_named(self):
        eta_client.reset_token()
        with mock.patch.object(eta_client.requests, 'post',
                               return_value=_response(200, {'access_token': 'T', 'expires_in': 3600})) as post:
            eta_client.check_login()
        self.assertEqual(post.call_args[1]['verify'], 'C:/eta/preprod-root-ca.pem')
        eta_client.reset_token()
        with override_settings(TAX_ETA_CA_BUNDLE=''), mock.patch.object(
                eta_client.requests, 'post', return_value=_response(200, {'access_token': 'T', 'expires_in': 3600})) as post:
            eta_client.check_login()
        self.assertIs(post.call_args[1]['verify'], True)
        eta_client.reset_token()

    @override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='')
    def test_pos_login_sends_preshared_key_only_when_configured(self):
        config = mock.Mock(softech_branchcode='150', client_id='pos-id', device_serial='SN1', pos_os_version='Windows',
                           pos_model_framework='1', secret_env='POS_SECRET_150', preshared_key_env='')
        eta_client.reset_pos_tokens()
        with mock.patch.dict('os.environ', {'POS_SECRET_150': 's'}), mock.patch.object(
                eta_client.requests, 'post', return_value=_response(200, {'access_token': 'P', 'expires_in': 3600})) as post:
            eta_client.pos_token(config)
        self.assertNotIn('presharedkey', post.call_args[1]['headers'])
        eta_client.reset_pos_tokens()
        config.preshared_key_env = 'POS_PSK_150'
        with mock.patch.dict('os.environ', {'POS_SECRET_150': 's', 'POS_PSK_150': 'k'}), mock.patch.object(
                eta_client.requests, 'post', return_value=_response(200, {'access_token': 'P', 'expires_in': 3600})) as post:
            eta_client.pos_token(config)
        self.assertEqual(post.call_args[1]['headers']['presharedkey'], 'k')
        eta_client.reset_pos_tokens()


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


# ── Where a branch device's chain starts (receipts.start_chain) ────────────────────────────────

LAST = 'a' * 64
NEWER = 'b' * 64


def _search(*rows):
    return _response(200, {'receipts': list(rows), 'metadata': {'totalCount': len(rows)}})


def _device_row(uuid, serial='2VA0280VY1', status='Valid'):
    return {'uuid': uuid, 'posSerialNumber': serial, 'receiptNumber': 'R-9', 'dateTimeIssued': '2026-11-12T10:00:00Z',
            'status': status, 'submitterName': 'Invoicer POS'}


@override_settings(TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='')
class ChainStartTests(Fixture, TestCase):

    def setUp(self):
        self.build('ch')
        eta_client.reset_pos_tokens()
        self.config = TaxReceiptBranchConfig.objects.create(
            softech_branchcode='150', is_enabled=True, seller_branch_code='3', device_serial='2VA0280VY1',
            client_id='pos-id', secret_env='POS_SECRET_150', activity_code='4772', governate='القاهرة',
            region_city='شنن', street='شارع', building_number='16', payment_method='C')
        env = mock.patch.dict('os.environ', {'POS_SECRET_150': 's'})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(eta_client.reset_pos_tokens)

    def _eta(self, *rows):
        token = mock.patch.object(eta_client.requests, 'post',
                                  return_value=_response(200, {'access_token': 'P', 'expires_in': 3600}))
        search = mock.patch.object(eta_client.requests, 'get', return_value=_search(*rows))
        return token, search

    def _start(self, rows, **kw):
        token, search = self._eta(*rows)
        with token, search:
            return receipts.start_chain('150', self.admin, **kw)

    def test_issuing_waits_for_the_chain_start_decision(self):
        gaps = receipts.config_gaps(self.config, TaxIssuerProfile.load())
        self.assertTrue(any('بداية سلسلة الجهاز' in g for g in gaps))

    def test_etas_no_result_404_means_no_receipts_but_another_404_does_not(self):
        token = mock.patch.object(eta_client.requests, 'post',
                                  return_value=_response(200, {'access_token': 'P', 'expires_in': 3600}))
        none = _response(404, {'target': 'NoResult', 'code': 'NotFound', 'message': 'No data found'})
        none.content = b'{}'
        with token, mock.patch.object(eta_client.requests, 'get', return_value=none):
            self.assertEqual(receipts.chain_lookup('150', self.admin)['found'], 0)
        other = _response(404, {})
        other.content = b''
        eta_client.reset_pos_tokens()
        with token, mock.patch.object(eta_client.requests, 'get', return_value=other):
            with self.assertRaises(receipts.TaxRuleError):
                receipts.chain_lookup('150', self.admin)

    def test_lookup_searches_this_device_newest_first_and_ignores_other_devices(self):
        token, search = self._eta(_device_row(LAST), _device_row(NEWER, serial='OTHER'))
        with token, search as get:
            out = receipts.chain_lookup('150', self.admin)
        params = get.call_args[1]['params']
        self.assertEqual((params['PosSerialNumber'], params['SortBy'], params['SortDir']),
                         ('2VA0280VY1', 'DateTimeIssued', 'Desc'))
        self.assertTrue(get.call_args[0][0].endswith('/api/v1/receipts/search'))
        self.assertEqual((out['found'], out['latest']['uuid']), (1, LAST))
        self.config.refresh_from_db()
        self.assertEqual(self.config.chain_start, '')     # looking changes nothing

    def test_handover_continues_from_the_last_receipt_eta_holds(self):
        config = self._start([_device_row(LAST)], mode='handover', confirm='150', other_program_stopped=True,
                             expected_uuid=LAST)
        self.assertEqual((config.chain_start, config.last_uuid, config.chain_start_uuid), ('handover', LAST, LAST))
        self.assertTrue(TaxAuditEvent.objects.filter(action='receipt_chain_started', entity_id='150').exists())
        gaps = receipts.config_gaps(config, TaxIssuerProfile.load())
        self.assertFalse(any('بداية سلسلة الجهاز' in g for g in gaps))

    def test_handover_needs_the_other_program_stopped_and_the_reviewed_receipt(self):
        for kw in (dict(other_program_stopped=False, expected_uuid=LAST),
                   dict(other_program_stopped=True, expected_uuid=NEWER),     # ETA's newest moved on
                   dict(other_program_stopped=True, expected_uuid='')):
            with self.assertRaises(receipts.TaxRuleError):
                self._start([_device_row(LAST)], mode='handover', confirm='150', **kw)
        self.config.refresh_from_db()
        self.assertEqual((self.config.chain_start, self.config.last_uuid), ('', ''))

    def test_handover_refused_when_latest_is_cancelled(self):
        with self.assertRaises(receipts.TaxRuleError):
            self._start([_device_row(LAST, status='Cancelled')], mode='handover', confirm='150',
                        other_program_stopped=True, expected_uuid=LAST)

    def test_fresh_only_when_eta_has_nothing_from_the_device(self):
        with self.assertRaises(receipts.TaxRuleError):
            self._start([_device_row(LAST)], mode='fresh', confirm='150')
        config = self._start([], mode='fresh', confirm='150')
        self.assertEqual((config.chain_start, config.last_uuid), ('fresh', ''))

    def test_could_not_ask_eta_decides_nothing(self):
        token = mock.patch.object(eta_client.requests, 'post',
                                  return_value=_response(200, {'access_token': 'P', 'expires_in': 3600}))
        with token, mock.patch.object(eta_client.requests, 'get', side_effect=requests.ConnectionError()):
            with self.assertRaises(receipts.TaxRuleError):
                receipts.start_chain('150', self.admin, mode='fresh', confirm='150')
        self.config.refresh_from_db()
        self.assertEqual(self.config.chain_start, '')

    def test_typed_branch_code_and_decided_once(self):
        with self.assertRaises(receipts.TaxRuleError):
            self._start([], mode='fresh', confirm='999')
        self._start([], mode='fresh', confirm='150')
        with self.assertRaises(receipts.TaxRuleError):
            self._start([], mode='fresh', confirm='150')

    def test_undo_only_before_anything_is_issued(self):
        self._start([_device_row(LAST)], mode='handover', confirm='150', other_program_stopped=True, expected_uuid=LAST)
        with self.assertRaises(receipts.TaxRuleError):
            receipts.undo_chain_start('150', self.admin, '')
        receipts.undo_chain_start('150', self.admin, 'wrong device')
        self.config.refresh_from_db()
        self.assertEqual((self.config.chain_start, self.config.last_uuid), ('', ''))
        self._start([_device_row(LAST)], mode='handover', confirm='150', other_program_stopped=True, expected_uuid=LAST)
        TaxReceipt.objects.create(softech_branchcode='150', doccode='31', docnumber='1', docdate='2026-11-13',
                                  sold_at=timezone.now(), uuid='c' * 64, status=TaxReceipt.ISSUED)
        with self.assertRaises(receipts.TaxRuleError):
            receipts.undo_chain_start('150', self.admin, 'too late')

    def test_views_need_finalize(self):
        r = api(self.accountant).post('/api/tax-invoicing/receipts/branch/150/chain/start/',
                                      {'mode': 'fresh', 'confirm': '150'}, format='json')
        self.assertEqual(r.status_code, 403)
        token, search = self._eta()
        with token, search:
            r = api(self.admin).post('/api/tax-invoicing/receipts/branch/150/chain/start/',
                                     {'mode': 'fresh', 'confirm': '150'}, format='json')
        self.assertEqual((r.status_code, r.json()['chain_start']), (200, 'fresh'))


# ── Does ETA hold the code? Per ETA system (coding.check_codes, prepare_mirror) ────────────────

def _details(active=True):
    return _response(200, {'codeID': 9, 'codeName': 'Panadol', 'active': active, 'activeFrom': '2023-01-01T00:00:00Z'})


@override_settings(**CODING_ON)
class CodeCheckTests(Fixture, TestCase):

    def setUp(self):
        self.build('cc')
        eta_client.reset_token()
        self.addCleanup(eta_client.reset_token)
        common = dict(coding_status=TaxItemProfile.CODE_APPROVED, code_type='EGS', gpc_code='10000454',
                      tax_treatment='taxable', treatment_confirmed_at=timezone.now(), vat_rate=14)
        self.real = TaxItemProfile.objects.create(softech_itemcode='60001', item_name='Panadol',
                                                  eta_code='EG-100200300-60001', **common)
        self.gone = TaxItemProfile.objects.create(softech_itemcode='60002', item_name='Brufen',
                                                  eta_code='EG-100200300-60002', **common)
        self.gs1 = TaxItemProfile.objects.create(softech_itemcode='60003', item_name='Cream', **{
            **common, 'code_type': 'GS1', 'eta_code': '6221234567890'})

    def _login(self):
        return mock.patch.object(eta_client.requests, 'post',
                                 return_value=_response(200, {'access_token': 'T', 'expires_in': 3600}))

    def _check(self, answers):
        def answer(url, **kw):
            for code, resp in answers.items():
                if code in url:
                    return resp
            return _response(404, {})
        with self._login(), mock.patch.object(eta_client.requests, 'get', side_effect=answer) as get:
            out = coding.check_codes(self.admin)
        return out, get

    def test_records_each_answer_beside_the_system(self):
        out, get = self._check({'60001': _details(), '6221234567890': _details(active=False)})
        self.assertEqual((out['found'], out['not_found'], out['inactive'], out['environment']), (1, 1, 1, 'preprod'))
        self.assertTrue(any('/api/v1.0/codetypes/EGS/codes/EG-100200300-60001' in c[0][0] for c in get.call_args_list))
        for p, status in ((self.real, 'found'), (self.gone, 'not_found'), (self.gs1, 'inactive')):
            p.refresh_from_db()
            self.assertEqual((p.eta_check_env, p.eta_check_status), ('preprod', status))
            self.assertEqual(p.coding_status, TaxItemProfile.CODE_APPROVED)    # checking never recodes

    def test_could_not_ask_stops_without_recording(self):
        with self._login(), mock.patch.object(eta_client.requests, 'get', side_effect=requests.ConnectionError()):
            out = coding.check_codes(self.admin)
        self.assertTrue(out['error'])
        self.assertEqual(TaxItemProfile.objects.exclude(eta_check_status='').count(), 0)

    def test_a_code_missing_here_blocks_the_line_here_only(self):
        from apps.tax_invoicing import services
        self._check({'60001': _details()})
        self.gone.refresh_from_db()
        status, reason = services.classify(None, self.gone)
        self.assertEqual(status, 'uncoded')
        self.assertIn('غير موجود في منظومة المصلحة الحالية', reason)
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            self.assertEqual(services.classify(None, self.gone)[0], 'approved')   # the preprod check says nothing here

    def test_a_status_from_the_test_system_never_counts_in_production(self):
        from apps.tax_invoicing import services
        self.real.coding_env = 'preprod'
        self.real.save()
        self.assertEqual(services.classify(None, self.real)[0], 'approved')
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            status, reason = services.classify(None, self.real)
        self.assertEqual(status, 'uncoded')
        self.assertIn('preprod', reason)

    def test_mirror_registers_the_existing_code_and_never_recodes_the_item(self):
        self._check({'60001': _details()})
        self.assertEqual([p.softech_itemcode for p in coding.mirror_candidates()], ['60002'])   # EGS, missing here
        out = coding.prepare_mirror([self.gone.pk, self.real.pk, self.gs1.pk], self.accountant)
        self.assertEqual(len(out['created']), 1)
        row = TaxCodeRequest.objects.get()
        self.assertEqual((row.purpose, row.item_code), ('mirror', 'EG-100200300-60002'))
        with self._login(), mock.patch.object(eta_client.requests, 'post',
                                              side_effect=[_response(200, {'access_token': 'T', 'expires_in': 3600}),
                                                           _response(200, {})]):
            coding.send([row.pk], self.admin, '1')
        self.gone.refresh_from_db()
        self.assertEqual((self.gone.coding_status, self.gone.coding_env), (TaxItemProfile.CODE_APPROVED, ''))
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': row.item_code, 'status': 'Approved'}])):
            coding.refresh(self.admin)
        self.gone.refresh_from_db()
        self.assertEqual((self.gone.coding_status, self.gone.coding_env), (TaxItemProfile.CODE_APPROVED, ''))
        self.assertEqual((self.gone.eta_check_env, self.gone.eta_check_status), ('preprod', 'found'))

    def test_mirror_refused_in_production_and_for_unchecked_items(self):
        with self.assertRaises(coding.TaxRuleError):
            with override_settings(TAX_ETA_ENVIRONMENT='production'):
                coding.prepare_mirror([self.gone.pk], self.accountant)
        out = coding.prepare_mirror([self.gone.pk], self.accountant)      # not checked yet
        self.assertEqual(out['created'], [])

    def test_new_code_approved_in_preprod_is_tagged_with_its_system(self):
        p = TaxItemProfile.objects.create(softech_itemcode='60009', item_name='New', gpc_code='10000454')
        coding.prepare([p.pk], self.accountant)
        row = TaxCodeRequest.objects.get(profile=p)
        with mock.patch.object(eta_client.requests, 'post',
                               side_effect=[_response(200, {'access_token': 'T', 'expires_in': 3600}), _response(200, {})]):
            coding.send([row.pk], self.admin, '1')
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': row.item_code, 'status': 'Approved'}])):
            coding.refresh(self.admin)
        p.refresh_from_db()
        self.assertEqual((p.coding_status, p.coding_env, p.eta_check_status), ('approved', 'preprod', 'found'))

    def test_check_view_needs_edit_and_reports(self):
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/codes/check/', {}, format='json').status_code, 403)
        with self._login(), mock.patch.object(eta_client.requests, 'get', return_value=_response(404, {})):
            r = api(self.accountant).post('/api/tax-invoicing/codes/check/', {}, format='json')
        self.assertEqual((r.status_code, r.json()['not_found']), (200, 3))
        body = api(self.accountant).get('/api/tax-invoicing/codes/').json()
        self.assertEqual(body['summary']['checks']['not_found'], 3)
        self.assertEqual(body['summary']['mirror_candidates'], 2)


# ── GPC categories and GS1 reuse (gpc.py, coding.prepare_gs1) ──────────────────────────────────

@override_settings(**CODING_ON)
class GpcAndGs1Tests(Fixture, TestCase):

    def setUp(self):
        from apps.catalog.models import Category, Item
        self.build('gp')
        eta_client.reset_token()
        self.addCleanup(eta_client.reset_token)
        tab = Category.objects.create(softech_id='gp-tab', name='Tablet')

        def item(code, family, barcode=''):
            from apps.catalog.models import ItemBarcode
            row = Item.objects.create(softech_id=code, name=f'Item {code}', family_name=family, category=tab,
                                      medicine_type_name='Medicine')
            if barcode:      # the catalog keeps barcodes in SOFTECH's itembarcodes, not on the item
                ItemBarcode.objects.create(item=row, barcode='100010000000006')      # internal code: not a GTIN
                ItemBarcode.objects.create(item=row, barcode=barcode)
            return row

        for code, brick in (('71001', '10000673'), ('71002', '10000673'), ('71003', '10005845')):
            TaxItemProfile.objects.create(softech_itemcode=code, item=item(code, 'TAB: Simple coated'), item_name='x',
                                          coding_status=TaxItemProfile.CODE_APPROVED, gpc_code=brick, code_type='EGS',
                                          eta_code=f'EG-100200300-{code}')
        self.new = TaxItemProfile.objects.create(softech_itemcode='71009', item=item('71009', 'TAB: Simple coated'),
                                                 item_name='Newtab', item_name_ar='نيوتاب', gpc_code='0')
        self.gs1 = TaxItemProfile.objects.create(softech_itemcode='71010', item=item('71010', 'Hair', '4006381333931'),
                                                 item_name='Shampoo')
        self.bad_barcode = TaxItemProfile.objects.create(softech_itemcode='71011',
                                                         item=item('71011', 'Hair', '4006381333932'), item_name='Comb')

    def _workbook(self, header_rows, rows):
        import os
        import tempfile

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        for r in header_rows + rows:
            ws.append(r)
        fd, path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        wb.save(path)
        self.addCleanup(os.remove, path)
        return path

    def test_loads_bricks_from_either_workbook_layout(self):
        from apps.tax_invoicing import gpc
        from apps.tax_invoicing.models import TaxGpcBrick
        a = self._workbook([['Brick Code', 'Brick Description', 'Brick Name Arabic']],
                           [[10000673, 'Medicines', 'أدوية'], [10000673, 'Medicines', ''], ['bad', 'x', 'y']])
        b = self._workbook([['إعداد', '', ''], [None, None, None], ['BrickCode', 'BrickTitleAr', 'BrickTitle']],
                           [['10005845', 'أدوية بوصفة', 'Prescription'], ['10000673', 'أدوية', 'Medicines (new)']])
        self.assertEqual(gpc.load(gpc.read_workbook(a)), {'read': 1, 'created': 1, 'updated': 0})
        self.assertEqual(gpc.load(gpc.read_workbook(b)), {'read': 2, 'created': 1, 'updated': 1})
        self.assertEqual(TaxGpcBrick.objects.get(code='10000673').name_en, 'Medicines (new)')
        self.assertEqual(TaxGpcBrick.objects.get(code='10005845').name_ar, 'أدوية بوصفة')

    def test_once_loaded_a_request_must_name_a_listed_brick(self):
        from apps.tax_invoicing.models import TaxGpcBrick
        self.assertEqual(coding._check_fields('99999999', 'a', 'b'), [])      # nothing loaded: any 8 digits
        TaxGpcBrick.objects.create(code='10000673', name_ar='أدوية')
        self.assertEqual(len(coding._check_fields('99999999', 'a', 'b')), 1)
        self.assertEqual(coding._check_fields('10000673', 'a', 'b'), [])

    def test_suggestion_is_learned_from_our_approved_items_and_used_only_when_asked(self):
        from apps.tax_invoicing import gpc
        s = gpc.suggest(TaxItemProfile.objects.filter(pk=self.new.pk).select_related('item__category'))[self.new.pk]
        self.assertEqual((s['code'], s['basis'], s['share']), ('10000673', 'family', 67))
        out = coding.prepare([self.new.pk], self.accountant)                   # a GPC of "0" is no GPC
        self.assertEqual(out['created'], [])
        out = coding.prepare([self.new.pk], self.accountant, use_suggested=True)
        row = TaxCodeRequest.objects.get(pk=out['created'][0])
        self.assertEqual(row.parent_code, '10000673')
        event = TaxAuditEvent.objects.filter(action='code_request_prepared').latest('id')
        self.assertEqual(event.after['brick_from'], 'suggested')

    def test_gtin_check_digit(self):
        self.assertTrue(coding.gtin_ok('4006381333931'))
        self.assertFalse(coding.gtin_ok('4006381333932'))
        self.assertFalse(coding.gtin_ok('5000000001'))
        self.assertEqual([p.softech_itemcode for p in coding.gs1_candidates()], ['71010'])

    def _token(self):
        return mock.patch.object(eta_client.requests, 'post',
                                 return_value=_response(200, {'access_token': 'T', 'expires_in': 3600}))

    def test_gs1_reuse_request_codes_the_item_with_its_barcode(self):
        out = coding.prepare_gs1([self.gs1.pk, self.bad_barcode.pk], self.accountant)
        self.assertEqual(len(out['created']), 1)
        row = TaxCodeRequest.objects.get(pk=out['created'][0])
        self.assertEqual((row.purpose, row.item_code, row.parent_code), ('gs1', '4006381333931', ''))
        with self._token(), mock.patch.object(eta_client.requests, 'put', return_value=_response(200, {})) as put:
            self.assertEqual(coding.send([row.pk], self.admin, '1')['submitted'], 1)
        url, body = put.call_args[0][0], put.call_args[1]['data'].decode('utf-8')
        self.assertTrue(url.endswith('/api/v1.0/codetypes/requests/codeusages'))
        self.assertIn('"codetype": "GS1"', body)
        self.gs1.refresh_from_db()
        self.assertEqual((self.gs1.coding_status, self.gs1.code_type, self.gs1.eta_code), ('pending', 'GS1', '4006381333931'))
        with mock.patch.object(eta_client.requests, 'get',
                               return_value=_response(200, [{'itemCode': row.item_code, 'status': 'Approved'}])):
            coding.refresh(self.admin)
        self.gs1.refresh_from_db()
        self.assertEqual((self.gs1.coding_status, self.gs1.code_type, self.gs1.coding_env), ('approved', 'GS1', 'preprod'))

    def test_gs1_refused_inside_a_200_is_failed_not_submitted(self):
        row = TaxCodeRequest.objects.get(pk=coding.prepare_gs1([self.gs1.pk], self.accountant)['created'][0])
        with self._token(), mock.patch.object(eta_client.requests, 'put',
                                              return_value=_response(200, {'error': {'message': 'already has usage'}})):
            self.assertEqual(coding.send([row.pk], self.admin, '1')['failed'], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        self.gs1.refresh_from_db()
        self.assertEqual(self.gs1.coding_status, TaxItemProfile.CODE_MISSING)

    def test_views_offer_suggestions_gs1_and_brick_search(self):
        from apps.tax_invoicing.models import TaxGpcBrick
        TaxGpcBrick.objects.create(code='10000673', name_ar='أدوية')
        TaxGpcBrick.objects.create(code='10000111', name_ar='شيء آخر')
        rows = api(self.accountant).get('/api/tax-invoicing/codes/candidates/').json()
        new = next(r for r in rows if r['itemcode'] == '71009')
        self.assertEqual((new['gpc_code'], new['suggested']['code'], new['suggested']['name']), ('', '10000673', 'أدوية'))
        gs1 = api(self.accountant).get('/api/tax-invoicing/codes/candidates/', {'kind': 'gs1'}).json()
        self.assertEqual([r['barcode'] for r in gs1], ['4006381333931'])
        found = api(self.accountant).get('/api/tax-invoicing/codes/gpc/', {'q': 'أدو'}).json()
        self.assertEqual((found['loaded'], [r['code'] for r in found['rows']]), (True, ['10000673']))
        self.assertEqual(api(self.accountant).get('/api/tax-invoicing/codes/gpc/').json()['rows'][0]['code'], '10000673')
        r = api(self.accountant).post('/api/tax-invoicing/codes/prepare/', {'ids': [self.gs1.pk], 'kind': 'gs1'}, format='json')
        self.assertEqual(len(r.json()['created']), 1)
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/codes/prepare/', {'ids': [self.new.pk]},
                                                   format='json').status_code, 403)

    def test_new_catalog_items_join_the_items_that_need_a_code(self):
        from apps.catalog.models import Item
        Item.objects.create(softech_id='71500', name='Brand new syrup')
        Item.objects.create(softech_id='71501', name='Old', is_active=False)
        body = api(self.accountant).get('/api/tax-invoicing/codes/').json()
        before = body['summary']['catalog_without_profile']
        self.assertGreaterEqual(before, 1)
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/codes/add-from-catalog/', {}, format='json').status_code, 403)
        r = api(self.accountant).post('/api/tax-invoicing/codes/add-from-catalog/', {}, format='json')
        self.assertEqual(r.json()['added'], before)
        p = TaxItemProfile.objects.get(softech_itemcode='71500')
        self.assertEqual((p.coding_status, p.item_name, p.item.softech_id), ('missing', 'Brand new syrup', '71500'))
        self.assertFalse(TaxItemProfile.objects.filter(softech_itemcode='71501').exists())
        self.assertEqual(api(self.accountant).get('/api/tax-invoicing/codes/').json()['summary']['catalog_without_profile'], 0)
        self.assertTrue(TaxAuditEvent.objects.filter(action='items_added_from_catalog').exists())


# ── A test-only branch mapping (receipts.env_guard, end_test_mapping) ──────────────────────────

@override_settings(TAX_ETA_ENVIRONMENT='preprod', WRITER_INSTANCE=True)
class TestMappingTests(Fixture, TestCase):

    def setUp(self):
        self.build('tm')
        self.config = TaxReceiptBranchConfig.objects.create(
            softech_branchcode='150', is_enabled=True, seller_branch_code='3', device_serial='2VA0280VY1',
            client_id='pos-id', secret_env='POS_SECRET_150', activity_code='4772', governate='القاهرة',
            region_city='شنن', street='شارع', building_number='16', payment_method='C', chain_start='fresh', send_from=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))

    def _receipt(self, number, *, uuid='', env='', status=TaxReceipt.READY):
        return TaxReceipt.objects.create(softech_branchcode='150', doccode='10', docnumber=number,
                                         docdate=timezone.localdate(), sold_at=timezone.now(), status=status,
                                         uuid=uuid, previous_uuid='p' if uuid else '', payload_text='{}' if uuid else '',
                                         environment=env, issued_at=timezone.now() if uuid else None)

    def test_marking_test_only_is_for_the_test_system_and_audited(self):
        r = api(self.admin).post('/api/tax-invoicing/receipts/configs/', {'branch': '150', 'test_only': True}, format='json')
        self.assertEqual((r.status_code, r.json()['test_env']), (200, 'preprod'))
        self.assertTrue(TaxAuditEvent.objects.filter(action='receipt_config_changed', entity_id='150').exists())
        TaxReceiptBranchConfig.objects.create(softech_branchcode='151')
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            r = api(self.admin).post('/api/tax-invoicing/receipts/configs/', {'branch': '151', 'test_only': True}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_test_only_setup_is_refused_outside_its_system(self):
        self.config.test_env = 'preprod'
        self.config.save()
        receipts.env_guard(self.config, '150')                          # its own test system: fine
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            with self.assertRaises(receipts.TaxRuleError):
                receipts.env_guard(self.config, '150')
        with self.assertRaises(receipts.TaxRuleError):
            with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
                receipts.issue_next('150', self.admin)

    def test_a_real_setup_never_sends_while_test_receipts_remain(self):
        self._receipt('1', uuid='a' * 64, env='preprod', status=TaxReceipt.ACCEPTED)
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            with self.assertRaises(receipts.TaxRuleError):
                receipts.env_guard(self.config, '150')

    def test_ending_puts_test_receipts_back_to_ready_and_clears_the_device(self):
        self.config.test_env, self.config.last_uuid = 'preprod', 'a' * 64
        self.config.save()
        sent = self._receipt('1', uuid='a' * 64, env='preprod', status=TaxReceipt.ACCEPTED)
        untouched = self._receipt('2')
        with self.assertRaises(receipts.TaxRuleError):
            receipts.end_test_mapping('150', self.admin, '')
        r = api(self.admin).post('/api/tax-invoicing/receipts/branch/150/test/end/', {'reason': 'انتهت التجربة'}, format='json')
        self.assertEqual(r.status_code, 200)
        sent.refresh_from_db()
        self.assertEqual((sent.status, sent.uuid, sent.environment, sent.payload_text), (TaxReceipt.READY, '', '', ''))
        untouched.refresh_from_db()
        self.assertEqual(untouched.status, TaxReceipt.READY)
        self.config.refresh_from_db()
        self.assertEqual((self.config.test_env, self.config.device_serial, self.config.last_uuid, self.config.chain_start,
                          self.config.is_enabled), ('', '', '', '', False))
        event = TaxAuditEvent.objects.get(action='receipt_test_mapping_ended')
        self.assertEqual(event.after['receipts_reset'], 1)
        with override_settings(TAX_ETA_ENVIRONMENT='production', WRITER_INSTANCE=False):
            receipts.env_guard(self.config, '150')                      # nothing left from the test


# ── Where a branch's sending starts (receipts.set_send_from) ───────────────────────────────────

class SendFromTests(Fixture, TestCase):

    def setUp(self):
        self.build('sf')
        self.config = TaxReceiptBranchConfig.objects.create(
            softech_branchcode='150', is_enabled=True, seller_branch_code='3', device_serial='D1', client_id='c',
            secret_env='S', activity_code='4772', governate='g', region_city='r', street='s', building_number='1',
            payment_method='C', chain_start='fresh')
        self.now = timezone.now()

    def _receipt(self, number, hours_ago, *, uuid=''):
        return TaxReceipt.objects.create(softech_branchcode='150', doccode='10', docnumber=number,
                                         docdate=timezone.localdate(), sold_at=self.now - dt.timedelta(hours=hours_ago),
                                         status=TaxReceipt.READY, uuid=uuid)

    def test_no_start_is_a_gap_before_the_first_receipt(self):
        gaps = receipts.config_gaps(self.config, TaxIssuerProfile.load())
        self.assertTrue(any('بداية الإرسال' in g for g in gaps))

    def test_sales_before_the_start_are_held_and_never_issued(self):
        old, new = self._receipt('1', 48), self._receipt('2', 1)
        config, rechecked = receipts.set_send_from('150', self.admin, self.now - dt.timedelta(hours=3), 'go-live')
        self.assertEqual(rechecked, 2)
        old.refresh_from_db()
        self.assertEqual(old.status, TaxReceipt.HELD)
        self.assertEqual(old.hold_reasons[0]['code'], receipts.BEFORE_START)
        new.refresh_from_db()
        self.assertNotEqual(new.hold_reasons[:1], [{'code': receipts.BEFORE_START}])
        self.assertFalse(any(h['code'] == receipts.BEFORE_START for h in new.hold_reasons))
        event = TaxAuditEvent.objects.get(action='receipt_send_from_set')
        self.assertEqual(event.reason, 'go-live')

    def test_after_issuing_the_start_only_moves_later(self):
        receipts.set_send_from('150', self.admin, self.now - dt.timedelta(hours=3))
        self._receipt('9', 1, uuid='a' * 64)
        with self.assertRaises(receipts.TaxRuleError):
            receipts.set_send_from('150', self.admin, self.now - dt.timedelta(hours=10))
        receipts.set_send_from('150', self.admin, self.now - dt.timedelta(hours=2))      # later: fine
        with self.assertRaises(receipts.TaxRuleError):
            receipts.set_send_from('150', self.admin, None)

    def test_view_needs_send_permission_and_returns_the_branch(self):
        when = (self.now - dt.timedelta(hours=1)).isoformat()
        self.assertEqual(api(self.accountant).post('/api/tax-invoicing/receipts/branch/150/send-from/',
                                                   {'send_from': when}, format='json').status_code, 403)
        r = api(self.admin).post('/api/tax-invoicing/receipts/branch/150/send-from/', {'send_from': when, 'reason': 'x'},
                                 format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['send_from'])
