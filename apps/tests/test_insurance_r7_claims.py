"""
Insurance claims route group (/api/insurance/claims/…) — R7 per-app tests.

Covers the claim actions that run on our own data (create, status, receipts, adjust / exclude,
names, payments, deductions, the read-only reports and exports, pivot, roster decisions) plus the
SOFTECH-fed ones with SOFTECH mocked. test_insurance.py already covers the lock guards, the
re-price write gates, RBAC on claims and the audit trail; nothing here repeats those.
"""
from decimal import Decimal
from unittest import mock

from apps.insurance import models as m
from apps.tests.security.baseline import pending
from apps.tests.test_insurance_r7 import API, InsuranceR7Base, add_line, add_rx, mk_claim

C = f'{API}claims/'


class ClaimCrudTests(InsuranceR7Base):

    def test_create_takes_rates_from_the_contract_and_numbers_the_claim(self):
        contract = m.InsuranceContract.objects.create(subclient=self.sub, effective_from='2026-01-01',
                                                      local_discount_pct=Decimal('15'),
                                                      imported_discount_pct=Decimal('5'))
        r = self.api.post(C, {'subclient': self.sub.pk, 'contract': contract.pk,
                              'period_from': '2026-08-01', 'period_to': '2026-08-31'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        claim = m.InsuranceClaim.objects.get(pk=r.json()['id'])
        self.assertRegex(claim.claim_number, r'^MT-\d{4}-00001$')
        self.assertEqual((claim.applied_local_disc_pct, claim.applied_imported_disc_pct),
                         (Decimal('15.00'), Decimal('5.00')))
        self.assertEqual(claim.created_by, self.admin_profile)
        self.assertEqual(self.api.post(C, {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(C, {'subclient': 999999}, format='json').status_code, 400)

    def test_create_without_period_is_400(self):
        self.api.raise_request_exception = False
        r = self.api.post(C, {'subclient': self.sub.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_filters_and_detail(self):
        a = mk_claim(self.sub, number='R7-A')
        other_sub = m.InsuranceSubClient.objects.create(client=self.client_obj, name='فئة 2')
        mk_claim(other_sub, number='R7-B', pf='2025-08-01', pt='2025-08-31')
        rows = self.rows(self.api.get(C, {'client_id': self.client_obj.pk, 'subclient_id': self.sub.pk,
                                          'year': '2026'}))
        self.assertEqual([c['claim_number'] for c in rows], ['R7-A'])
        add_rx(a, '8001', local=100)
        body = self.api.get(f'{C}{a.pk}/', {'include_lines': '1'}).json()
        self.assertEqual(body['claim_number'], 'R7-A')
        self.assertEqual(self.api.patch(f'{C}{a.pk}/', {'status': 'paid'}, format='json').status_code, 405)

    def test_change_status_to_submitted_stamps_the_date(self):
        claim = mk_claim(self.sub)
        r = self.api.post(f'{C}{claim.pk}/change-status/', {'status': 'submitted', 'notes': 'sent',
                                                            'expected_payment_date': '2026-10-01'},
                          format='json')
        self.assertEqual(r.status_code, 200)
        claim.refresh_from_db()
        self.assertIsNotNone(claim.submitted_at)
        self.assertEqual((claim.notes, str(claim.expected_payment_date)), ('sent', '2026-10-01'))
        self.assertEqual(self.api.post(f'{C}{claim.pk}/change-status/', {'status': 'nope'},
                                       format='json').status_code, 400)


class ReceiptEditTests(InsuranceR7Base):

    def setUp(self):
        super().setUp()
        self.claim = mk_claim(self.sub)
        self.rx = add_rx(self.claim, '8101', local=1000, imported=500, patient='أحمد محمد')
        self.line = add_line(self.rx, total='1000')

    def test_prescription_lines_with_variance(self):
        rows = self.api.get(f'{C}{self.claim.pk}/prescriptions/{self.rx.pk}/lines/').json()
        self.assertEqual([r['softech_itemcode'] for r in rows], ['111'])
        self.assertIn('variance', rows[0])
        self.assertEqual(self.api.get(f'{C}{self.claim.pk}/prescriptions/999999/lines/').status_code, 404)

    def test_adjust_overrides_the_split_then_removal_restores_it(self):
        url = f'{C}{self.claim.pk}/prescriptions/{self.rx.pk}/adjust/'
        r = self.api.post(url, {'local_before': '500', 'reason': 'تصحيح'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.claim.refresh_from_db()
        # 500 × 0.83 + 500 × 0.94 = 415 + 470
        self.assertEqual(Decimal(str(self.claim.final_net_after)), Decimal('885.00'))
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.claim.refresh_from_db()
        self.assertEqual(Decimal(str(self.claim.final_net_after)), Decimal('1300.00'))
        self.assertEqual(self.api.post(url, {}, format='json').status_code, 400)        # reason required

    def test_exclude_and_reinclude(self):
        url = f'{C}{self.claim.pk}/prescriptions/{self.rx.pk}/exclude/'
        self.assertEqual(self.api.post(url, {'reason': 'مكرر'}, format='json').status_code, 201)
        self.assertEqual(self.api.post(url, {'reason': 'مكرر'}, format='json').status_code, 200)
        self.claim.refresh_from_db()
        self.assertEqual(Decimal(str(self.claim.final_net_after)), Decimal('0.00'))
        # the same receipt active in another claim of the period blocks the re-include
        other = mk_claim(self.sub, number='R7-OTHER')
        add_rx(other, '8101', local=1000)
        self.assertEqual(self.api.delete(url, {}, format='json').status_code, 409)
        self.assertEqual(self.api.delete(url, {'force': True}, format='json').status_code, 204)
        self.claim.refresh_from_db()
        self.assertEqual(Decimal(str(self.claim.final_net_after)), Decimal('1300.00'))

    def test_patient_name_edit_and_revert(self):
        url = f'{C}{self.claim.pk}/prescriptions/{self.rx.pk}/patient/'
        self.assertEqual(self.api.patch(url, {}, format='json').status_code, 400)
        r = self.api.patch(url, {'patient_name': ' أحمد محمد علي '}, format='json')
        self.assertEqual(r.json()['patient_name'], 'أحمد محمد علي')
        r = self.api.patch(url, {'revert': True}, format='json')
        self.assertEqual(r.json()['patient_name'], 'أحمد محمد')
        self.assertEqual(self.claim.audit_events.filter(action='patient_edit').count(), 2)

    def test_name_suggestions_and_bulk_apply(self):
        older = mk_claim(self.sub, number='R7-OLD', pf='2026-07-01', pt='2026-07-31')
        for n in range(3):
            add_rx(older, f'81{n}0', local=10, day='2026-07-10', patient='أحمد محمد علي حسن')
        r = self.api.get(f'{C}{self.claim.pk}/patient-name-suggest/', {'q': 'أحمد محمد'})
        self.assertIn('أحمد محمد علي حسن', [x['name'] for x in r.json()])
        self.assertEqual(self.api.get(f'{C}{self.claim.pk}/patient-name-suggest/', {'q': 'أ'}).json(), [])
        body = self.api.get(f'{C}{self.claim.pk}/name-suggestions/').json()
        self.assertEqual(body['count'], len(body['rows']))
        r = self.api.post(f'{C}{self.claim.pk}/name-suggestions/apply/',
                          {'choices': {str(self.rx.pk): 'أحمد محمد علي حسن'}}, format='json')
        self.assertEqual(r.json(), {'applied': 1})
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.patient_name, 'أحمد محمد علي حسن')
        self.assertEqual(self.api.post(f'{C}{self.claim.pk}/name-suggestions/apply/', {},
                                       format='json').status_code, 400)

    def test_apply_name_suggestions_bad_key_is_400(self):
        self.api.raise_request_exception = False
        r = self.api.post(f'{C}{self.claim.pk}/name-suggestions/apply/', {'choices': {'abc': 'x'}}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bulk_exclude_and_mark_reviewed(self):
        rx2 = add_rx(self.claim, '8102', local=100)
        url = f'{C}{self.claim.pk}/'
        self.assertEqual(self.api.post(url + 'bulk-exclude/', {}, format='json').status_code, 400)
        r = self.api.post(url + 'bulk-exclude/', {'prescription_ids': [rx2.pk]}, format='json')
        self.assertEqual(r.json(), {'excluded': 1, 'claim_net_after': 1300.0})
        self.assertEqual(self.api.post(url + 'mark-reviewed/', {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(url + 'mark-reviewed/', {'prescription_ids': [self.rx.pk]},
                                       format='json').json(), {'updated': 1, 'reviewed': True})

    def test_locked_claim_refuses_receipt_edits(self):
        self.claim.status = m.InsuranceClaim.STATUS_SUBMITTED
        self.claim.save()
        base = f'{C}{self.claim.pk}/prescriptions/{self.rx.pk}/'
        self.assertEqual(self.api.post(base + 'adjust/', {'reason': 'x'}, format='json').status_code, 423)
        self.assertEqual(self.api.patch(base + 'patient/', {'patient_name': 'x'}, format='json').status_code, 423)
        self.assertEqual(self.api.post(f'{C}{self.claim.pk}/bulk-exclude/', {'prescription_ids': [1]},
                                       format='json').status_code, 423)


class CollectionsTests(InsuranceR7Base):

    @pending('I-1')
    def test_recording_a_payment_from_the_screen_payload(self):
        claim = mk_claim(self.sub)
        # exactly what InsuranceClaimDetailPage.jsx sends: payment_date, amount, reference, notes
        r = self.api.post(f'{C}{claim.pk}/payments/', {'payment_date': '2026-09-15', 'amount': '500.00',
                                                       'reference': '', 'notes': ''}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.api.get(f'{C}{claim.pk}/payments/').json()[0]['amount'], '500.00')

    def test_payments_list_and_post_with_claim_in_body(self):
        claim = mk_claim(self.sub)
        r = self.api.post(f'{C}{claim.pk}/payments/', {'claim': claim.pk, 'payment_date': '2026-09-15',
                                                       'amount': '500.00'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.api.get(f'{C}{claim.pk}/payments/').json()[0]['amount'], '500.00')
        self.assertTrue(claim.audit_events.filter(action='payment').exists())

    def test_deductions(self):
        claim = mk_claim(self.sub)
        rx = add_rx(claim, '8201', local=100)
        r = self.api.post(f'{C}{claim.pk}/deductions/', {'docnumber': '#8201', 'amount': '12.50',
                                                         'reason_code': 'not_member'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(m.InsuranceDeduction.objects.get().prescription, rx)
        self.assertEqual(self.api.post(f'{C}{claim.pk}/deductions/', {'docnumber': '9999', 'amount': '1'},
                                       format='json').status_code, 400)
        self.assertEqual(self.api.post(f'{C}{claim.pk}/deductions/', {'reason_code': 'not_member', 'amount': '1'},
                                       format='json').status_code, 400)
        self.assertEqual(len(self.api.get(f'{C}{claim.pk}/deductions/').json()), 1)
        self.assertEqual(claim.audit_events.filter(action='deduction').count(), 1)


class ReportAndExportTests(InsuranceR7Base):

    def setUp(self):
        super().setUp()
        self.claim = mk_claim(self.sub)
        self.rx = add_rx(self.claim, '8301', local=1000, patient='سارة حسن محمود علي')
        add_line(self.rx, code='R7X01', name='بانادول', total='1000')
        m.InsuranceClaimSupplement.objects.create(claim=self.claim, supplement_type='after_claim',
                                                  local_before=100, gross_before=100,
                                                  local_discount=17, total_discount=17, net_after=83)

    def test_read_only_reports_answer(self):
        for action in ('invoice-dataset', 'readiness', 'omissions', 'discrepancy', 'overrides-preview',
                       'claim-items', 'review-items', 'separation-matches', 'roster-check',
                       'billing-group-suggestions', 'apply-history', 'resync/runs', 'softech-reprice/runs',
                       'softech-date/runs'):
            r = self.api.get(f'{C}{self.claim.pk}/{action}/')
            self.assertEqual(r.status_code, 200, (action, r.content[:300]))

    def test_readiness_scores_the_claim(self):
        body = self.api.get(f'{C}{self.claim.pk}/readiness/').json()
        self.assertEqual(body['summary']['rx_active'], 1)
        e, w = body['summary']['errors'], body['summary']['warnings']
        self.assertEqual(body['health_score'], max(0, 100 - e * 40 - w * 10))
        self.assertEqual(body['can_issue'], e == 0)

    def test_prescriptions_by_item(self):
        r = self.api.get(f'{C}{self.claim.pk}/prescriptions-by-item/', {'q': 'R7X'}).json()
        self.assertEqual(r, {'prescription_ids': [self.rx.pk],
                             'matched_items': [{'code': 'R7X01', 'name': 'بانادول'}]})
        self.assertEqual(self.api.get(f'{C}{self.claim.pk}/prescriptions-by-item/', {'q': 'x'}).json(),
                         {'prescription_ids': [], 'matched_items': []})

    def test_files(self):
        xlsx = 'application/vnd.openxmlformats'
        for action, ctype in (('export/excel', xlsx), ('export/statistical', xlsx),
                              ('discrepancy-export', xlsx), ('cover-letter', xlsx),
                              ('submission-package', 'application/zip')):
            r = self.api.get(f'{C}{self.claim.pk}/{action}/')
            self.assertEqual(r.status_code, 200, action)
            self.assertTrue(r['Content-Type'].startswith(ctype), (action, r['Content-Type']))
        r = self.api.get(f'{C}{self.claim.pk}/export/excel/', {'layout': 'flat', 'sort_by': 'date',
                                                              'sort_dir': 'desc'})
        self.assertEqual(r.status_code, 200)

    def test_apply_overrides_and_review_decision(self):
        m.InsuranceItemClassificationOverride.objects.create(item_code='R7X01', forced_category='imported')
        r = self.api.post(f'{C}{self.claim.pk}/apply-overrides/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(self.claim.audit_events.filter(action='apply_overrides').exists())
        self.assertEqual(self.api.post(f'{C}{self.claim.pk}/apply-review-decision/', {},
                                       format='json').status_code, 400)

    def test_apply_current_master_validates_line_ids(self):
        url = f'{C}{self.claim.pk}/apply-current-master/'
        self.assertEqual(self.api.post(url, {'line_ids': ['x']}, format='json').status_code, 400)
        self.assertEqual(self.api.post(url, {'line_ids': []}, format='json').status_code, 400)
        r = self.api.post(url, {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.api.post(f'{C}{self.claim.pk}/apply-runs/999999/revert/', {},
                                       format='json').status_code, 404)

    def test_audit_log_filter_and_limit(self):
        self.api.post(f'{C}{self.claim.pk}/change-status/', {'status': 'ready'}, format='json')
        body = self.api.get(f'{C}{self.claim.pk}/audit-log/', {'action': 'status_change', 'limit': 'x'}).json()
        self.assertEqual(body['count'], 1)

    def test_roster_decision(self):
        url = f'{C}{self.claim.pk}/roster-decision/'
        self.assertEqual(self.api.post(url, {'verdict': 'member'}, format='json').status_code, 400)
        self.assertEqual(self.api.post(url, {'prescription_ids': [self.rx.pk], 'verdict': 'not_member',
                                             'target': {'client_id': 999999}}, format='json').status_code, 400)
        r = self.api.post(url, {'prescription_ids': [self.rx.pk], 'verdict': 'member', 'note': 'ok'},
                          format='json')
        self.assertEqual(r.json(), {'updated': 1, 'verdict': 'member'})
        self.assertTrue(self.claim.audit_events.filter(action='roster_decision').exists())

    def test_pivot(self):
        cfg = self.api.get(f'{C}pivot-config/').json()
        self.assertIn('branch', [d['key'] for d in cfg['dimensions']])
        body = self.api.get(f'{C}pivot/', {'row': 'branch', 'claim_id': self.claim.pk}).json()
        self.assertFalse(body['multi'])
        body = self.api.get(f'{C}pivot/', {'rows': 'branch', 'cols': 'month', 'source': 'prescriptions'}).json()
        self.assertTrue(body['multi'])
        self.assertEqual(self.api.get(f'{C}pivot/', {'row': 'nope'}).status_code, 400)
        r = self.api.get(f'{C}pivot-export/', {'row': 'branch', 'col': 'patient'})
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))
        r = self.api.get(f'{C}pivot-export/', {'rows': 'item', 'source': 'lines', 'measure': 'line_total'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.api.get(f'{C}pivot-export/', {'row': 'nope'}).status_code, 400)


class SoftechFedClaimTests(InsuranceR7Base):
    """Claim actions that read SOFTECH — the read is mocked."""

    def test_list_motalbas(self):
        self.assertEqual(self.api.get(f'{C}list-motalbas/').status_code, 400)
        self.assertEqual(self.api.get(f'{C}list-motalbas/', {'subclient_id': 999999}).status_code, 404)
        cur = mock.MagicMock()
        cur.fetchall.return_value = [('12.0', '2026-08-01', '2026-08-31', 4, 1500.5), ('15', None, None, 1, 10)]
        conn = mock.MagicMock(**{'cursor.return_value': cur})
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            body = self.api.get(f'{C}list-motalbas/', {'subclient_id': self.sub.pk}).json()
        self.assertEqual([x['motalbano'] for x in body], [15, 12])
        self.assertEqual(body[1], {'motalbano': 12, 'motfromdate': '2026-08-01', 'mottodate': '2026-08-31',
                                   'rxcount': 4, 'docvaluetotal': 1500.5, 'personcode': '4001'})
        with mock.patch('config.sybase.get_sybase_connection', side_effect=ConnectionError('down')):
            self.assertEqual(self.api.get(f'{C}list-motalbas/', {'subclient_id': self.sub.pk}).status_code, 503)

    def test_import_from_softech(self):
        claim = mk_claim(self.sub)
        body = {'subclient_id': self.sub.pk, 'period_from': '2026-08-01', 'period_to': '2026-08-31'}
        with mock.patch('apps.insurance.views.import_claim_from_softech',
                        return_value={'prescriptions': 3}) as imp:
            r = self.api.post(f'{C}{claim.pk}/import-from-softech/', body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['summary'], {'prescriptions': 3})
        self.assertEqual(imp.call_args.kwargs['personcodes'], ['4001'])
        claim.refresh_from_db()
        self.assertEqual(claim.imported_personcodes, '4001')
        from apps.insurance.importer import InsuranceImportError
        with mock.patch('apps.insurance.views.import_claim_from_softech', side_effect=InsuranceImportError('x')):
            self.assertEqual(self.api.post(f'{C}{claim.pk}/import-from-softech/', body,
                                           format='json').status_code, 400)
        claim.status = m.InsuranceClaim.STATUS_PAID
        claim.save()
        self.assertEqual(self.api.post(f'{C}{claim.pk}/import-from-softech/', body, format='json').status_code, 400)

    def test_lookup_rx_warns_about_a_duplicate(self):
        claim = mk_claim(self.sub)
        other = mk_claim(self.sub, number='R7-DUP')
        add_rx(other, '8401', local=10)
        self.assertEqual(self.api.get(f'{C}{claim.pk}/lookup-rx/').status_code, 400)
        with mock.patch('apps.insurance.views.fetch_single_rx_from_softech',
                        return_value={'softech_docnumber': '8401', 'softech_branchcode': '160'}):
            body = self.api.get(f'{C}{claim.pk}/lookup-rx/', {'docnumber': '8401'}).json()
        self.assertEqual([d['claim_number'] for d in body['duplicate_in']], ['R7-DUP'])

    def test_resync_preview_softech_down_is_502(self):
        claim = mk_claim(self.sub)
        with mock.patch('apps.insurance.resync.preview_resync', side_effect=ConnectionError('down')):
            self.assertEqual(self.api.get(f'{C}{claim.pk}/resync/preview/').status_code, 502)
