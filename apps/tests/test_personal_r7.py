"""
apps/tests/test_personal_r7.py — R7 per-app coverage for apps.personal (/api/personal/).

Builds on apps/tests/test_personal.py (resolve_person_key, claim create/review basics, my_tasks,
document-comment gate, revision basics) and apps/tests/security/test_personal_person_search.py
(search gating/throttle/audit) without repeating them.

Route groups → tests:
  persons/search/                       PersonSearchApiTests
  identities/ (+pending, <pk>, review)  IdentityApiTests
  me/capabilities/                      covered in test_personal.CommentWriteGateTests
  documents/comment/                    RemarkWriteApiTests.test_document_comment_restamps_revised_doc
  cheques/note/                         RemarkWriteApiTests (cheque cases)
  revision/                             RemarkWriteApiTests.test_cheque_revision
  widgets/ (+catalog, layout, <pk>)     WidgetCrudApiTests
  widgets/<pk>/data/                    WidgetDataApiTests

Permission: IdentityApiTests.test_non_admin_cannot_see_pending_queue,
            WidgetCrudApiTests.test_cannot_touch_another_users_widget.
Business rules: ProviderRuleTests (document grouping + unit price, revision drift, my_sales maths),
                WritebackGateTests (no SOFTECH UPDATE unless the doc belongs to the approved code).
SOFTECH is never contacted: queries / writeback are mocked or given a fake connection.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from apps.personal import providers, queries
from apps.personal.models import DocumentCommentEdit, DocumentRevision, PersonalWidget, SoftechIdentityClaim
from apps.personal.views import _write_warning
from apps.tests.factories import make_admin, make_branch, make_customer, make_item, make_user

API = '/api/personal'
APPROVED = SoftechIdentityClaim.STATUS_APPROVED


# ── business rules ───────────────────────────────────────────────────────────

class ProviderRuleTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.user, cls.profile, _ = make_user('r7pers_rule', role='salesperson', branch=cls.branch)

    def test_days_clamp(self):
        self.assertEqual(providers._days({}), 90)
        self.assertEqual(providers._days({'period_days': 'x'}, 30), 30)
        self.assertEqual(providers._days({'period_days': 0}), 1)
        self.assertEqual(providers._days({'period_days': 99999}), 1095)

    def test_transaction_lines_group_into_documents_with_unit_price(self):
        make_item('Catalog Name', 'PR001')
        payload = {'summary': {}, 'lines': [
            {'branchcode': '140', 'doccode': '10', 'docnumber': 5, 'docdate': '2026-11-01',
             'docvalue': 300, 'doc_comment': 'ملاحظة', 'entered_by': 'u1',
             'itemcode': 'PR001', 'item_name': '', 'qty': 4, 'line_value': 100},
            {'branchcode': '140', 'doccode': '10', 'docnumber': 5, 'docdate': '2026-11-01',
             'docvalue': 300, 'itemcode': 'PR002', 'item_name': 'B', 'qty': 0, 'line_value': 200},
            {'branchcode': '140', 'doccode': '120', 'docnumber': 6, 'docdate': '2026-11-02',
             'docvalue': 50, 'itemcode': 'PR003', 'item_name': 'C', 'qty': 3, 'line_value': 'bad'},
        ]}
        out = providers._enrich_txn_lines(payload)
        self.assertNotIn('lines', out)
        self.assertEqual(len(out['documents']), 2)
        d1, d2 = out['documents']
        self.assertEqual((d1['docnumber'], d1['comments'], d1['user'], d1['line_total']), (5, 'ملاحظة', 'u1', 300.0))
        self.assertEqual([(i['item_name'], i['unit_price']) for i in d1['items']],
                         [('Catalog Name', 25.0), ('B', None)])
        self.assertEqual((d2['line_total'], d2['items'][0]['unit_price']), (0.0, None))
        self.assertEqual(providers._enrich_txn_lines('x'), 'x')

    def test_revision_annotation_flags_drift_and_strips_stamp(self):
        from apps.personal.revision import build_marker
        DocumentRevision.objects.create(staff=self.profile, kind='document', branchcode='140', doccode='10',
                                        docnumber='5', code='R7', status=DocumentRevision.STATUS_REVISED)
        DocumentRevision.objects.create(staff=self.profile, kind='document', branchcode='140', doccode='10',
                                        docnumber='6', code='R8', status=DocumentRevision.STATUS_REVISED)
        rows = [
            {'branchcode': '140', 'doccode': '10', 'docnumber': '5.0',
             'comments': 'نص ' + build_marker('X', 'R7')},             # in sync
            {'branchcode': '140', 'doccode': '10', 'docnumber': 6, 'comments': 'نص فقط'},   # stamp lost
            {'branchcode': '140', 'doccode': '10', 'docnumber': 7, 'comments': 'جديد'},
        ]
        providers._annotate_revisions(rows, self.profile, 'document')
        self.assertEqual([(r['revised'], r.get('stamp_drift'), r['comments']) for r in rows],
                         [(True, False, 'نص'), (True, True, 'نص فقط'), (False, None, 'جديد')])
        cheques = [{'branchcode': '1', 'financialdoccode': '10', 'cheqsno': 1, 'note': 'n [[x]]'}]
        providers._annotate_revisions(cheques, self.profile, 'cheque')
        self.assertEqual((cheques[0]['revised'], cheques[0]['note']), (False, 'n'))
        self.assertEqual(providers._annotate_revisions([], self.profile, 'cheque'), [])

    def _sale(self, inv, doc, total, days_ago=1, phcode='', branch=None):
        return PurchaseHistory.objects.create(
            customer=make_customer(phone='01000000777'), softech_invoice_id=inv, branch=branch or self.branch,
            doc_code=doc, total_amount=Decimal(total), softech_user='U77', softech_phcode=phcode,
            invoice_date=timezone.now() - timedelta(days=days_ago))

    def test_my_sales_maths(self):
        item = make_item('Sold', 'PR010')
        s1 = self._sale('R7-1', '115', '100.00', phcode='P1')
        s2 = self._sale('R7-2', '115', '50.00', phcode='P1')
        self._sale('R7-3', '30', '20.00')
        self._sale('R7-4', '115', '999.00', days_ago=60)                 # outside 30 days
        PurchaseHistoryLine.objects.create(purchase=s1, item=item, quantity=2, unit_price=50,
                                           line_total=100, cost_at_sale=Decimal('30'))
        PurchaseHistoryLine.objects.create(purchase=s2, item=item, quantity=1, unit_price=50,
                                           line_total=50, cost_at_sale=Decimal('40'))
        out = providers._my_sales('U77', {}, self.profile)
        self.assertEqual(out['days'], 30)
        self.assertEqual((out['revenue'], out['invoices'], out['avg_invoice'], out['customers']),
                         (150.0, 2, 75.0, 1))
        self.assertEqual((out['units'], out['gross_profit'], out['margin']), (3.0, 50.0, 33.3))  # 150-(60+40)
        self.assertEqual((out['returns_value'], out['returns_count']), (20.0, 1))
        self.assertEqual(out['branches'], [self.branch.softech_branch_id])
        self.assertEqual(sum(t['value'] for t in out['trend']), 150.0)
        self.assertEqual(providers._my_sales('', {}), {'error': 'no usercode'})
        none = providers._my_sales('U77', {'branches': ['ZZZ']}, self.profile)
        self.assertEqual((none['revenue'], none['branches']), (0.0, [self.branch.softech_branch_id]))

    def test_my_analytics_and_narrative(self):
        from apps.insights.models import InsightFinding, InsightRun
        item = make_item('Top', 'PR011')
        s = self._sale('R7-5', '115', '80.00')
        PurchaseHistory.objects.filter(pk=s.pk).update(sales_person_type='10', sales_channel='91')
        PurchaseHistoryLine.objects.create(purchase=s, item=item, quantity=2, unit_price=40, line_total=80)
        with mock.patch.object(queries, 'channel_labels', return_value={'10|91': 'عميل نقدى'}):
            out = providers._my_analytics('U77', {}, self.profile)
        self.assertEqual(out['channels'], [{'channel': '91', 'channel_label': 'عميل نقدى',
                                            'value': 80.0, 'invoices': 1}])
        self.assertEqual(out['top_items'], [{'softech_id': 'PR011', 'name': 'Top', 'qty': 2.0, 'value': 80.0}])
        self.assertEqual(providers._my_analytics(None, {}), {'error': 'no usercode'})

        run = InsightRun.objects.create(period_type='month', period_start='2026-10-01', period_end='2026-10-31')
        InsightFinding.objects.create(run=run, rule_code='R1', category='sales', severity='warning',
                                      scope_type='salesperson', scope_key='U77', message_ar='انخفاض',
                                      value=Decimal('10'))
        out = providers._my_narrative_reports('U77', {}, self.profile)
        self.assertEqual(out['counts'], {'critical': 0, 'warning': 1, 'info': 0})
        self.assertEqual((out['findings'][0]['value'], out['findings'][0]['period']), (10.0, '2026-10-01'))
        self.assertEqual(providers._my_narrative_reports('', {}), {'error': 'no usercode'})
        self.assertEqual(providers._my_tasks(None, {}), {'error': 'no staff'})

    def test_write_warning_text(self):
        self.assertEqual(_write_warning({'hq_result': 'ok', 'branch_result': 'skipped: x'}), '')
        self.assertEqual(_write_warning({'hq_result': 'reverted', 'branch_result': 'error: down',
                                         'branch_host': '10.0.0.1'}),
                         'المركز الرئيسي: reverted · سيرفر الفرع 10.0.0.1: error: down')


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None, **kw):
        self.conn.executed.append(sql.split()[0].upper())

    def fetchone(self):
        return self.conn.rows.pop(0) if self.conn.rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self.rows, self.executed = list(rows), []

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        pass


class WritebackGateTests(TestCase):
    """SOFTECH remark writes: nothing is UPDATEd unless the document's counterparty is exactly
    the caller's approved personcode; the write switch and the length guard come first."""

    def _call(self, fn, conn, **kw):
        with mock.patch('apps.personal.writeback.writer_allowed', return_value=True), \
                mock.patch('apps.personal.writeback.get_sybase_connection', return_value=conn):
            return fn(**kw)

    def test_document_of_another_person_is_never_updated(self):
        from apps.personal.writeback import CommentWriteError, write_document_comment
        conn = _FakeConn([('9999', 'old')])
        with self.assertRaises(CommentWriteError) as cm:
            self._call(write_document_comment, conn, branchcode='140', doccode='10', docnumber='5',
                       comment='hi', expected_person_code='5014')
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(conn.executed, ['SELECT'])               # no UPDATE reached SOFTECH

    def test_owned_document_written_and_verified(self):
        from apps.personal.writeback import write_document_comment
        conn = _FakeConn([('5014', 'old'), ('new text',)])
        out = self._call(write_document_comment, conn, branchcode='NOSRV', doccode='10', docnumber='5.0',
                         comment='new text', expected_person_code='5014')
        self.assertEqual(conn.executed, ['SELECT', 'UPDATE', 'SELECT'])
        self.assertEqual(out, {'old': 'old', 'new': 'new text', 'hq_result': 'ok', 'branch_host': '',
                               'branch_result': 'skipped: no branch server'})

    def test_missing_and_reverted_and_switch_off(self):
        from apps.personal.writeback import CommentWriteError, write_cheque_note, write_document_comment
        with self.assertRaises(CommentWriteError) as cm:
            self._call(write_cheque_note, _FakeConn([]), branchcode='140', financialdoccode='10',
                       cheqsno='1', note='x', expected_person_code='5014')
        self.assertEqual(cm.exception.status, 404)
        out = self._call(write_cheque_note, _FakeConn([('5014', ''), ('different',)]), branchcode='NOSRV',
                         financialdoccode='10', cheqsno='1', transform=lambda old: old + 'A',
                         expected_person_code='5014')
        self.assertEqual((out['new'], out['hq_result']), ('A', 'reverted'))
        with mock.patch('apps.personal.writeback.writer_allowed', return_value=False), \
                mock.patch('apps.personal.writeback.get_sybase_connection') as conn:
            with self.assertRaises(CommentWriteError) as cm:
                write_document_comment(branchcode='1', doccode='10', docnumber='1', comment='x',
                                       expected_person_code='5')
        self.assertEqual(cm.exception.status, 503)
        conn.assert_not_called()
        with self.assertRaises(CommentWriteError):
            write_cheque_note(branchcode='', financialdoccode='', cheqsno='', expected_person_code='5')
        with self.assertRaises(CommentWriteError):                 # Arabic-Indic digits not cp1256
            self._call(write_document_comment, _FakeConn([]), branchcode='1', doccode='10', docnumber='1',
                       comment='٣', expected_person_code='5')


class QueriesTests(SimpleTestCase):
    """The live-SELECT helpers, with _rows mocked (SOFTECH never contacted)."""

    def test_search_persons_and_get_person(self):
        with mock.patch.object(queries, '_rows', return_value=[
                {'personcode': ' 5014 ', 'personname': 'مورد', 'ptcode': '20', 'ptclassifcode': ''}]) as rows:
            self.assertEqual(queries.search_persons('مور', kind='supplier'),
                             [{'person_code': '5014', 'name': 'مورد', 'ptcode': '20', 'ptclassifcode': ''}])
            self.assertIn("ptcode = '20'", rows.call_args[0][0])
            queries.search_persons('مور', kind='customer')
            self.assertIn("ptcode <> '20'", rows.call_args[0][0])
            self.assertEqual(queries.get_person('5014')['name'], 'مورد')
        self.assertEqual(queries.search_persons(''), [])
        self.assertEqual(queries.get_person(''), {})
        with mock.patch.object(queries, '_rows', return_value=[]):
            self.assertEqual(queries.get_person('1'), {})

    def test_transactions_payments_and_errors(self):
        with mock.patch.object(queries, '_rows', return_value=[{'cheqsno': 1, 'cheqvalue': 5, 'chequenote': 'n'}]):
            self.assertEqual(queries.supplier_transactions('5014', days=7)['days'], 7)
            self.assertEqual(queries.customer_transactions('4231')['days'], 180)
            pay = queries.supplier_payments('5014')['cheques'][0]
            self.assertEqual((pay['cheqsno'], pay['amount'], pay['note'], pay['bankname']), (1, 5, 'n', None))
            self.assertEqual(queries.customer_payments('4231')['days'], 180)
        with mock.patch.object(queries, '_rows', side_effect=RuntimeError('softech down')):
            self.assertEqual(queries.supplier_transactions('5014'), {'error': 'softech down'})
            self.assertEqual(queries.supplier_payments('5014')['cheques'], [{'_error': 'softech down'}])
        for fn in (queries.supplier_transactions, queries.supplier_payments,
                   queries.customer_transactions, queries.customer_payments):
            self.assertEqual(fn(''), {'error': 'no person_code'})

    def test_rows_uses_rowcount_and_closes(self):
        cur = mock.MagicMock(description=[('a',), ('b',)])
        cur.fetchall.return_value = [(1, datetime(2026, 1, 2))]
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with mock.patch.object(queries, 'get_sybase_connection', return_value=conn):
            self.assertEqual(queries._rows('SELECT 1', [], rowcount=5), [{'a': 1, 'b': '2026-01-02T00:00:00'}])
        self.assertEqual(cur.execute.call_args_list[0].args[0], 'SET ROWCOUNT 5')
        conn.close.assert_called_once()

    def test_channel_labels_cached(self):
        cache.delete('personal:channel_labels')
        with mock.patch.object(queries, '_rows', return_value=[
                {'ptcode': '10', 'ptclassifcode': '91', 'ptclassifdescr': ' عميل نقدى '},
                {'ptcode': '10', 'ptclassifcode': '', 'ptclassifdescr': 'x'}]) as rows:
            self.assertEqual(queries.channel_labels(), {'10|91': 'عميل نقدى'})
            queries.channel_labels()
        self.assertEqual(rows.call_count, 1)
        cache.delete('personal:channel_labels')


# ── API ──────────────────────────────────────────────────────────────────────

class _ApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.user, cls.profile, cls.client_ = make_user('r7pers_user', role='salesperson', branch=cls.branch)
        cls.other, cls.other_profile, cls.other_client = make_user('r7pers_other', role='salesperson',
                                                                   branch=cls.branch)
        cls.admin_user, cls.admin, cls.admin_client = make_admin('r7pers_admin')

    def setUp(self):
        cache.clear()


class PersonSearchApiTests(_ApiBase):

    def test_search_returns_results(self):
        hit = [{'person_code': '5014', 'name': 'مورد', 'ptcode': '20', 'ptclassifcode': ''}]
        with mock.patch.object(queries, 'search_persons', return_value=hit) as sp:
            r = self.client_.get(f'{API}/persons/search/', {'q': 'مورد', 'kind': 'bogus'})
        self.assertEqual((r.status_code, r.data['results']), (200, hit))
        self.assertIsNone(sp.call_args.kwargs['kind'])            # unknown kind dropped


class IdentityApiTests(_ApiBase):

    def test_list_only_my_claims(self):
        SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='1')
        SoftechIdentityClaim.objects.create(staff=self.other_profile, kind='supplier', person_code='2')
        r = self.client_.get(f'{API}/identities/')
        self.assertEqual([c['person_code'] for c in r.data['results']], ['1'])

    def test_claim_validation_and_label_lookup(self):
        self.assertEqual(self.client_.post(f'{API}/identities/', {'kind': 'boss', 'person_code': '1'},
                                           format='json').status_code, 400)
        self.assertEqual(self.client_.post(f'{API}/identities/', {'kind': 'supplier'},
                                           format='json').status_code, 400)
        with mock.patch.object(queries, 'get_person',
                               return_value={'name': 'شركة', 'ptcode': '20', 'ptclassifcode': '5'}):
            r = self.client_.post(f'{API}/identities/', {'kind': 'supplier', 'person_code': '77'}, format='json')
        self.assertEqual(r.status_code, 201)
        claim = SoftechIdentityClaim.objects.get(pk=r.data['id'])
        self.assertEqual((claim.label, claim.meta, claim.status),
                         ('شركة', {'ptcode': '20', 'ptclassifcode': '5'}, 'pending'))

    def test_non_admin_cannot_see_pending_queue(self):
        SoftechIdentityClaim.objects.create(staff=self.other_profile, kind='supplier', person_code='2')
        self.assertEqual(self.client_.get(f'{API}/identities/pending/').status_code, 403)
        r = self.admin_client.get(f'{API}/identities/pending/')
        self.assertEqual([c['person_code'] for c in r.data['results']], ['2'])

    def test_review_reject_bad_action_and_delete_own(self):
        claim = SoftechIdentityClaim.objects.create(staff=self.profile, kind='customer', person_code='3')
        self.assertEqual(self.admin_client.post(f'{API}/identities/{claim.pk}/review/', {'action': 'maybe'},
                                                format='json').status_code, 400)
        r = self.admin_client.post(f'{API}/identities/{claim.pk}/review/', {'action': 'reject', 'note': 'لا'},
                                   format='json')
        self.assertEqual((r.status_code, r.data['status']), (200, 'rejected'))
        self.assertEqual(self.client_.delete(f'{API}/identities/{claim.pk}/').status_code, 204)
        self.assertFalse(SoftechIdentityClaim.objects.filter(pk=claim.pk).exists())


class WidgetCrudApiTests(_ApiBase):

    def test_catalog_lists_registry(self):
        r = self.client_.get(f'{API}/widgets/catalog/')
        self.assertEqual({w['widget_type'] for w in r.data['results']}, set(providers.WIDGET_REGISTRY))

    def test_create_update_layout_delete(self):
        claim = SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='5',
                                                    status=APPROVED)
        self.assertEqual(self.client_.post(f'{API}/widgets/', {'widget_type': 'nope'},
                                           format='json').status_code, 400)
        cust = SoftechIdentityClaim.objects.create(staff=self.profile, kind='customer', person_code='6')
        self.assertEqual(self.client_.post(f'{API}/widgets/', {'widget_type': 'supplier_payments',
                                                               'identity': cust.pk}, format='json').status_code, 400)
        r = self.client_.post(f'{API}/widgets/', {'widget_type': 'supplier_payments', 'identity': claim.pk,
                                                  'title': 'مدفوعات', 'column': 1, 'position': 2}, format='json')
        self.assertEqual(r.status_code, 201)
        wid = r.data['id']
        r = self.client_.patch(f'{API}/widgets/{wid}/', {'title': 'جديد', 'size': 'lg', 'enabled': False},
                               format='json')
        self.assertEqual((r.status_code, r.data['title'], r.data['size'], r.data['enabled']),
                         (200, 'جديد', 'lg', False))
        foreign = SoftechIdentityClaim.objects.create(staff=self.other_profile, kind='supplier', person_code='9')
        self.assertEqual(self.client_.patch(f'{API}/widgets/{wid}/', {'identity': foreign.pk},
                                            format='json').status_code, 400)
        r = self.client_.post(f'{API}/widgets/layout/', [{'id': wid, 'column': 3, 'position': 0, 'size': 'sm'},
                                                         {'id': 999999, 'column': 1}], format='json')
        self.assertEqual(r.data, {'updated': [wid]})
        w = PersonalWidget.objects.get(pk=wid)
        self.assertEqual((w.column, w.position, w.size), (3, 0, 'sm'))
        self.assertEqual([x['id'] for x in self.client_.get(f'{API}/widgets/').data['results']], [wid])
        self.assertEqual(self.client_.delete(f'{API}/widgets/{wid}/').status_code, 204)

    def test_cannot_touch_another_users_widget(self):
        w = PersonalWidget.objects.create(staff=self.other_profile, widget_type='my_tasks', column=1)
        self.assertEqual(self.client_.patch(f'{API}/widgets/{w.pk}/', {'column': 5}, format='json').status_code, 403)
        self.assertEqual(self.client_.delete(f'{API}/widgets/{w.pk}/').status_code, 403)
        r = self.client_.post(f'{API}/widgets/layout/', {'items': [{'id': w.pk, 'column': 9}]}, format='json')
        self.assertEqual(r.data, {'updated': []})
        w.refresh_from_db()
        self.assertEqual(w.column, 1)
        self.assertEqual(self.client_.get(f'{API}/widgets/').data['results'], [])


class WidgetDataApiTests(_ApiBase):

    def _widget(self, **kw):
        claim = SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='5014',
                                                    status=APPROVED)
        return PersonalWidget.objects.create(staff=self.profile, widget_type='supplier_payments',
                                             identity=claim, **kw)

    def test_live_widget_cached_then_refreshed(self):
        w = self._widget()
        with mock.patch.object(queries, 'supplier_payments',
                               return_value={'days': 180, 'cheques': [{'cheqsno': 1, 'note': 'n'}]}) as q:
            r1 = self.client_.get(f'{API}/widgets/{w.pk}/data/')
            r2 = self.client_.get(f'{API}/widgets/{w.pk}/data/')
            r3 = self.client_.get(f'{API}/widgets/{w.pk}/data/', {'refresh': '1'})
        self.assertEqual((r1.status_code, r1.data['_cached'], r2.data['_cached'], r3.data['_cached']),
                         (200, False, True, False))
        self.assertEqual(q.call_count, 2)
        self.assertEqual(q.call_args.args[0], '5014')              # code from the approved claim
        self.assertEqual(r1.data['data']['cheques'][0]['revised'], False)

    def test_live_error_not_cached_and_provider_crash_is_502(self):
        w = self._widget()
        with mock.patch.object(queries, 'supplier_payments', return_value={'error': 'down'}) as q:
            self.client_.get(f'{API}/widgets/{w.pk}/data/')
            self.client_.get(f'{API}/widgets/{w.pk}/data/')
        self.assertEqual(q.call_count, 2)
        with mock.patch.object(queries, 'supplier_payments', side_effect=RuntimeError('x')):
            self.assertEqual(self.client_.get(f'{API}/widgets/{w.pk}/data/').status_code, 502)

    def test_unknown_type_and_unapproved_identity(self):
        bad = PersonalWidget.objects.create(staff=self.profile, widget_type='legacy_gone')
        self.assertEqual(self.client_.get(f'{API}/widgets/{bad.pk}/data/').status_code, 400)
        pending = SoftechIdentityClaim.objects.create(staff=self.profile, kind='customer', person_code='4')
        w = PersonalWidget.objects.create(staff=self.profile, widget_type='customer_transactions', identity=pending)
        self.assertEqual(self.client_.get(f'{API}/widgets/{w.pk}/data/').status_code, 403)


class RemarkWriteApiTests(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.claim = SoftechIdentityClaim.objects.create(staff=cls.admin, kind='supplier', person_code='5014',
                                                        status=APPROVED)
        cls.widget = PersonalWidget.objects.create(staff=cls.admin, widget_type='supplier_payments',
                                                   identity=cls.claim)

    def _cheque(self, **extra):
        body = {'widget_id': self.widget.pk, 'branchcode': '140', 'financialdoccode': '10',
                'cheqsno': '88', 'note': 'دفعة'}
        body.update(extra)
        return self.admin_client.post(f'{API}/cheques/note/', body, format='json')

    @mock.patch('apps.personal.writeback.write_cheque_note')
    def test_cheque_note_written_and_audited(self, wr):
        wr.return_value = {'old': 'قديم', 'hq_result': 'ok', 'branch_host': '', 'branch_result': 'skipped: x'}
        r = self._cheque()
        self.assertEqual((r.status_code, r.data['ok'], r.data['note']), (200, True, 'دفعة'))
        self.assertEqual(wr.call_args.kwargs['expected_person_code'], '5014')
        edit = DocumentCommentEdit.objects.get(docnumber='88')
        self.assertEqual((edit.doccode, edit.old_comment, edit.new_comment), ('10', 'قديم', 'دفعة'))

    def test_cheque_note_errors(self):
        from apps.personal.writeback import CommentWriteError
        with mock.patch('apps.personal.writeback.write_cheque_note', side_effect=CommentWriteError('لا', 403)):
            self.assertEqual(self._cheque().status_code, 403)
        with mock.patch('apps.personal.writeback.write_cheque_note', side_effect=OSError('down')):
            self.assertEqual(self._cheque().status_code, 502)
        self.assertFalse(DocumentCommentEdit.objects.exists())
        r = self.client_.post(f'{API}/cheques/note/', {'widget_id': self.widget.pk}, format='json')
        self.assertEqual(r.status_code, 403)                     # no ERP-comment permission

    @mock.patch('apps.personal.writeback.write_cheque_note')
    def test_cheque_revision(self, wr):
        wr.return_value = {'old': '', 'new': 'x', 'hq_result': 'ok', 'branch_host': '', 'branch_result': 'ok'}
        r = self.admin_client.post(f'{API}/revision/', {'widget_id': self.widget.pk, 'kind': 'cheque',
                                                        'branchcode': '140', 'doccode': '10',
                                                        'docnumber': '88.0', 'revised': True}, format='json')
        self.assertEqual((r.status_code, r.data['revised']), (200, True))
        rec = DocumentRevision.objects.get(staff=self.admin, kind='cheque')
        self.assertEqual((rec.docnumber, rec.code, rec.status), ('88', f'R{rec.pk}', 'revised'))
        self.assertEqual(wr.call_args.kwargs['cheqsno'], '88')
        stamped = wr.call_args.kwargs['transform']('ملاحظة')
        self.assertTrue(stamped.startswith('ملاحظة [[راجعها') and stamped.endswith(f'{rec.code}]]'))
        bad = self.admin_client.post(f'{API}/revision/', {'widget_id': self.widget.pk, 'kind': 'x'}, format='json')
        self.assertEqual(bad.status_code, 400)

    @mock.patch('apps.personal.writeback.write_document_comment')
    def test_document_comment_restamps_revised_doc(self, wr):
        wr.return_value = {'old': '', 'hq_result': 'ok', 'branch_host': '', 'branch_result': 'ok'}
        DocumentRevision.objects.create(staff=self.admin, kind='document', branchcode='140', doccode='10',
                                        docnumber='5', code='R42', status=DocumentRevision.STATUS_REVISED)
        r = self.admin_client.post(f'{API}/documents/comment/', {'widget_id': self.widget.pk, 'branchcode': '140',
                                                                 'doccode': '10', 'docnumber': '5.0',
                                                                 'comment': 'تم'}, format='json')
        self.assertEqual(r.status_code, 200)
        kw = wr.call_args.kwargs
        self.assertNotIn('comment', kw)
        self.assertTrue(kw['transform']('anything').startswith('تم [[راجعها'))
        self.assertTrue(kw['transform']('').endswith('R42]]'))
