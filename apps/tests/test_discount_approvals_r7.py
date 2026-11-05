"""
Pricing approvals (apps/discount_approvals) — R7 per-app tests.

One view test per route family in apps/discount_approvals/urls.py (replication/scan is covered
by test_discount_approvals_replication_scan.py), the role matrix on top (pharmacist may file but
not approve; salesperson has no `approvals` grant), and the deterministic price rule the HQ write
uses: unit_price = pack_price / packqty, pack_price_tax = pack_price × (1 + tax%), 4 dp half-up.

SOFTECH is never reached: every connection is a mock.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.discount_approvals import alignment
from apps.discount_approvals.models import (
    ItemPriceChangeRequest as Req, ReplicationGap, ReplicationPolicy, ReplicationScan,
    SupplierDiscountPolicy,
)
from apps.discount_approvals.services import _build_values, compute_derived_preview
from apps.tests.factories import make_branch, make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

BASE = '/api/pricing-approvals/'
WRITES_ON = dict(WRITER_INSTANCE=True, PRICING_SOFTECH_WRITE_ENABLED=True)
REPAIR_ON = dict(WRITER_INSTANCE=True, REPLICATION_REPAIR_ENABLED=True)


def _conn(fetchone=None, fetchall=None, description=None):
    """A mock SOFTECH connection whose cursor answers fetchone/fetchall in order."""
    cur = mock.MagicMock()
    if isinstance(fetchone, list):
        cur.fetchone.side_effect = fetchone
    else:
        cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall or []
    cur.description = description
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ── Business rule (pure) ──────────────────────────────────────────────────────

class DerivedPriceRuleTests(SimpleTestCase):

    def test_preview_derives_unit_and_taxed_price(self):
        self.assertEqual(compute_derived_preview('100', 3, '14'),
                         {'unit_price': '33.3333', 'pack_price_tax': '114.0000'})

    def test_preview_rounds_half_up_and_floors_pack_qty_at_one(self):
        self.assertEqual(compute_derived_preview('10.00005', 0, '0'),
                         {'unit_price': '10.0001', 'pack_price_tax': '10.0001'})
        self.assertEqual(compute_derived_preview('abc', 1, '0'), {})

    def test_build_values_adds_dependents_only_for_pack_price(self):
        item = mock.Mock(pack_qty=4, sale_tax_pct=Decimal('5'))
        values = _build_values(mock.Mock(item=item, new_values={'pack_price': '50', 'pos_discp': '7'}))
        self.assertEqual(values, {'pack_price': Decimal('50'), 'pos_discp': Decimal('7'),
                                  'unit_price': Decimal('12.5000'),
                                  'pack_price_tax': Decimal('52.5000')})
        only_disc = _build_values(mock.Mock(item=item, new_values={'pharmacy_discp': '18'}))
        self.assertEqual(only_disc, {'pharmacy_discp': Decimal('18')})


class AlignmentRuleTests(SimpleTestCase):

    def _item(self, **kw):
        base = dict(id=1, softech_id='A1', name='x', supplier_code='S1', supplier_name='',
                    origin_code='O1', origin_name='Med: Imported 18 %', origin_name_ar='مستورد',
                    store_classif='C1', store_classif_name='Imported 18 %',
                    pack_price=Decimal('100'), cost_price=Decimal('70'),
                    pharmacy_discp=Decimal('18'), additional_discp=0, special_discp=0,
                    pos_discp=None, is_active=True, no_more_use=False)
        base.update(kw)
        return mock.Mock(**base)

    def test_parse_tier_pct(self):
        self.assertEqual(alignment.parse_tier_pct('Local 12.5%'), Decimal('12.5'))
        self.assertIsNone(alignment.parse_tier_pct('no pct'))
        self.assertIsNone(alignment.parse_tier_pct(''))

    def test_family_of(self):
        self.assertEqual(alignment.family_of('مستورد خاص'), 'imported')
        self.assertEqual(alignment.family_of('Local 20%'), 'local')
        self.assertIsNone(alignment.family_of('zzz'))

    def test_aligned_item_has_no_flags(self):
        row = alignment.evaluate_item(self._item(), {})
        self.assertEqual(row['flags'], [])
        self.assertFalse(row['misaligned'])
        self.assertEqual(row['target_pct'], '18')
        self.assertEqual(row['target_family'], 'imported')

    def test_label_and_master_drift_are_flagged(self):
        policy = mock.Mock(expected_discount=Decimal('20'))
        item = self._item(pharmacy_discp=Decimal('15'), store_classif_name='Imported 25 %')
        row = alignment.evaluate_item(item, {('supplier', 'S1'): policy},
                                      origin_idx={('imported', 20.0): {'code': 'O9', 'name': 'Imp 20'}})
        self.assertEqual(row['flags'], ['origin_vs_discount', 'store_vs_discount',
                                        'origin_vs_store', 'master_vs_discount'])
        self.assertEqual(row['master_pct'], '20')
        self.assertEqual(row['target_pct'], '20')
        self.assertEqual(row['suggested_origin_code'], 'O9')


# ── Views ─────────────────────────────────────────────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.item = make_item(name='R7 price item', softech_id='R7P01')
        self.item.pack_qty = 3
        self.item.sale_tax_pct = Decimal('14')
        self.item.pack_price = Decimal('90')
        self.item.save()
        self.admin_user, self.admin_profile, _ = make_user('r7da_admin', role='admin', access_all=True)
        self.admin_profile.softech_user_id = 'U77'
        self.admin_profile.softech_username = 'r7 admin'
        self.admin_profile.save()
        self.admin = bearer_client(self.admin_user)
        self.pharm_user = make_user('r7da_pharm', role='pharmacist')[0]
        self.pharm = bearer_client(self.pharm_user)

    def tearDown(self):
        module_access.clear_cache()

    def _req(self, status=Req.STATUS_PENDING, new=None, user=None, **kw):
        return Req.objects.create(item=self.item, requested_by=user or self.pharm_user,
                                  old_values={'pack_price': '90', 'pos_discp': '0'},
                                  new_values=new or {'pack_price': '100'}, reason='r7',
                                  status=status, **kw)


class RequestViewTests(_Base):

    def test_create_snapshots_old_values_and_lists_own_requests(self):
        r = self.pharm.post(BASE, {'item': self.item.pk, 'new_values': {'pack_price': '99.50'},
                                   'reason': 'r7 file'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        obj = Req.objects.get()
        self.assertEqual(obj.requested_by, self.pharm_user)
        self.assertEqual(obj.status, Req.STATUS_PENDING)
        self.assertEqual(obj.old_values['pack_price'], '90.000')
        self.assertIn('unit_price', obj.old_values)
        # someone else's request stays out of the pharmacist's list; the admin sees both
        self._req(user=self.admin_user)
        rows = self.pharm.get(BASE).json()
        rows = rows.get('results', rows)
        self.assertEqual([x['id'] for x in rows], [obj.id])
        rows = self.admin.get(BASE, {'status': 'pending', 'item': self.item.pk}).json()
        self.assertEqual(len(rows.get('results', rows)), 2)

    def test_create_rejects_unknown_and_negative_fields(self):
        r = self.pharm.post(BASE, {'item': self.item.pk, 'new_values': {'cost_price': '1'},
                                   'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.pharm.post(BASE, {'item': self.item.pk, 'new_values': {'pos_discp': '-1'},
                                   'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Req.objects.exists())

    def test_detail_is_scoped_to_the_requester(self):
        mine = self._req()
        other = self._req(user=self.admin_user)
        self.assertEqual(self.pharm.get(f'{BASE}{mine.pk}/').status_code, 200)
        self.assertEqual(self.pharm.get(f'{BASE}{other.pk}/').status_code, 404)
        self.assertEqual(self.admin.get(f'{BASE}{mine.pk}/').json()['item_softech_id'], 'R7P01')


class ApproveRejectTests(_Base):

    def test_approve_refused_while_writes_are_off(self):
        req = self._req()
        r = self.admin.post(f'{BASE}{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 503)
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_PENDING)

    @override_settings(**WRITES_ON)
    def test_approve_needs_a_linked_softech_user(self):
        self.admin_profile.softech_user_id = ''
        self.admin_profile.save()
        r = self.admin.post(f'{BASE}{self._req().pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['error_code'], 'no_softech_user')

    @override_settings(**WRITES_ON)
    def test_approve_writes_one_hq_update_with_derived_prices(self):
        req = self._req()
        conn, cur = _conn(fetchone=(100.0, 33.3333, 114.0))
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            r = self.admin.post(f'{BASE}{req.pk}/approve/', {'notes': 'ok'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        sql, params = cur.execute.call_args_list[0][0]
        self.assertEqual(sql, 'UPDATE SOFTECHDB9.dbo.items SET itemsaleprice = ?, unitsaleprice = ?, '
                              'itemsaleprice_tax = ?, usercode = ?, itemlastupdate = GETDATE() '
                              'WHERE itemcode = ?')
        self.assertEqual(params, [100.0, 33.3333, 114.0, 'U77', 'R7P01'])
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_EXECUTED)
        self.assertEqual(req.reviewed_by, self.admin_user)
        self.assertEqual(req.erp_usercode, 'U77')
        self.assertEqual(req.executed_values['unit_price'], '33.3333')
        self.assertEqual(req.executed_values['pack_price_tax'], '114.0000')
        self.item.refresh_from_db()
        self.assertEqual(self.item.pack_price, Decimal('100.000'))

    @override_settings(**WRITES_ON)
    def test_readback_mismatch_marks_the_request_failed(self):
        req = self._req()
        conn, _ = _conn(fetchone=(90.0, 30.0, 102.6))
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            r = self.admin.post(f'{BASE}{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 207)
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_FAILED)
        self.assertIn('readback mismatch', req.erp_error)
        self.item.refresh_from_db()
        self.assertEqual(self.item.pack_price, Decimal('90.000'))

    def test_approve_rejects_a_done_request_and_unknown_id(self):
        self.assertEqual(self.admin.post(f'{BASE}{self._req(status=Req.STATUS_REJECTED).pk}/approve/',
                                         {}, format='json').status_code, 400)
        self.assertEqual(self.admin.post(f'{BASE}999999/approve/', {}, format='json').status_code, 404)

    def test_reject_records_reviewer(self):
        req = self._req()
        r = self.admin.post(f'{BASE}{req.pk}/reject/', {'notes': 'no'}, format='json')
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual((req.status, req.review_notes, req.reviewed_by), (Req.STATUS_REJECTED, 'no', self.admin_user))
        self.assertEqual(self.admin.post(f'{BASE}{req.pk}/reject/', {}, format='json').status_code, 400)
        self.assertEqual(self.admin.post(f'{BASE}999999/reject/', {}, format='json').status_code, 404)

    def test_rollback_creates_a_reverse_pending_request(self):
        src = self._req(status=Req.STATUS_EXECUTED)
        r = self.pharm.post(f'{BASE}{src.pk}/rollback/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        new = Req.objects.get(rolled_back_from=src)
        self.assertEqual(new.new_values, {'pack_price': '90'})
        self.assertEqual((new.source, new.status), ('rollback', Req.STATUS_PENDING))
        self.assertEqual(self.pharm.post(f'{BASE}{new.pk}/rollback/', {}, format='json').status_code, 400)


class HelperViewTests(_Base):

    def test_item_prices_and_preview(self):
        r = self.pharm.get(f'{BASE}items/R7P01/prices/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['pack_qty'], r.json()['sale_tax_pct']), (3, '14.00'))
        self.assertEqual(self.pharm.get(f'{BASE}items/NOPE1/prices/').status_code, 404)
        r = self.pharm.get(f'{BASE}preview/', {'pack_price': '100', 'pack_qty': '3', 'sale_tax_pct': '14'})
        self.assertEqual(r.json(), {'unit_price': '33.3333', 'pack_price_tax': '114.0000'})

    def test_preview_bad_pack_qty_is_400(self):
        self.pharm.raise_request_exception = False
        r = self.pharm.get(f'{BASE}preview/', {'pack_price': '100', 'pack_qty': 'abc'})
        self.assertEqual(r.status_code, 400)

    def test_approver_info_pending_count_and_sla(self):
        self.assertEqual(self.admin.get(f'{BASE}approver-info/').json(),
                         {'erp_usercode': 'U77', 'erp_username': 'r7 admin', 'is_linked': True})
        old = self._req()
        Req.objects.filter(pk=old.pk).update(requested_at=timezone.now() - timedelta(hours=30))
        self._req()
        self.assertEqual(self.pharm.get(f'{BASE}pending-count/').json(), {'count': 2})
        body = self.pharm.get(f'{BASE}sla/').json()
        self.assertEqual(body['total_pending'], 2)
        self.assertEqual(body['buckets'], {'lt1h': 1, 'h1_4': 0, 'h4_24': 0, 'gt24h': 1})
        self.assertEqual(body['requests'][0]['id'], old.id)

    def test_import_csv_creates_and_skips_rows(self):
        csv = ('itemcode,pack_price,pos_discp,reason\n'
               'R7P01,120,5,bulk\n'
               'NOPE1,10,,x\n'
               'R7P01,-3,,neg\n'
               'R7P01,,,empty\n').encode()
        r = self.pharm.post(f'{BASE}import/', {'file': SimpleUploadedFile('p.csv', csv, 'text/csv')},
                            format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['created'], 1)
        self.assertEqual([s['row'] for s in body['skipped']], [3, 4, 5])
        obj = Req.objects.get()
        self.assertEqual((obj.source, obj.new_values), ('import', {'pack_price': '120', 'pos_discp': '5'}))

    def test_import_needs_a_supported_file(self):
        self.assertEqual(self.pharm.post(f'{BASE}import/', {}, format='multipart').status_code, 400)
        r = self.pharm.post(f'{BASE}import/', {'file': SimpleUploadedFile('p.txt', b'x')}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_price_history(self):
        self._req(status=Req.STATUS_EXECUTED, executed_values={'pack_price': '100', '_hq': 'ok'})
        body = self.pharm.get(f'{BASE}history/R7P01/').json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['events'][0]['executed_values'], {'pack_price': '100'})
        self.assertEqual(self.pharm.get(f'{BASE}history/NOPE1/').status_code, 404)


class ReplicationViewTests(_Base):

    STATUS = {'softech_id': 'R7P01', 'branches': [{'code': '120', 'status': 'replicated'}]}

    def test_request_replication_status(self):
        mine = self._req()
        other = self._req(user=self.admin_user)
        with mock.patch('apps.discount_approvals.replication.check_item', return_value=self.STATUS):
            self.assertEqual(self.pharm.get(f'{BASE}{mine.pk}/replication/').json(), self.STATUS)
            self.assertEqual(self.pharm.get(f'{BASE}{other.pk}/replication/').status_code, 403)
            self.assertEqual(self.pharm.get(f'{BASE}999999/replication/').status_code, 404)

    def test_force_replication_gated_by_switch(self):
        req = self._req()
        self.assertEqual(self.admin.post(f'{BASE}{req.pk}/force-replication/', {}, format='json').status_code, 503)
        with override_settings(**REPAIR_ON), \
                mock.patch('apps.discount_approvals.replication.force_replication',
                           return_value={'ok': True}) as fr:
            r = self.admin.post(f'{BASE}{req.pk}/force-replication/', {'mode': 'push'}, format='json')
        self.assertEqual(r.json(), {'ok': True})
        fr.assert_called_once_with('R7P01', mode='push')

    def test_scans_list_and_detail(self):
        scan = ReplicationScan.objects.create(status=ReplicationScan.STATUS_DONE, items_with_gaps=1)
        ReplicationGap.objects.create(scan=scan, item_softech_id='R7P01', branch_code='120')
        ReplicationGap.objects.create(scan=scan, item_softech_id='R7P01', branch_code='130',
                                      status=ReplicationGap.STATUS_REPAIRED)
        rows = self.admin.get(f'{BASE}replication/scans/').json()
        self.assertEqual(rows[0]['gap_branches'], {'120': 1})
        body = self.admin.get(f'{BASE}replication/scans/{scan.pk}/', {'status': 'stale'}).json()
        self.assertEqual([g['branch_code'] for g in body['gaps']], ['120'])
        self.assertEqual(self.admin.get(f'{BASE}replication/scans/999999/').status_code, 404)

    def test_repair_marks_confirmed_gaps(self):
        scan = ReplicationScan.objects.create(status=ReplicationScan.STATUS_DONE)
        gap = ReplicationGap.objects.create(scan=scan, item_softech_id='R7P01', branch_code='120')
        self.assertEqual(self.admin.post(f'{BASE}replication/repair/', {}, format='json').status_code, 503)
        with override_settings(**REPAIR_ON):
            self.assertEqual(self.admin.post(f'{BASE}replication/repair/', {}, format='json').status_code, 400)
            with mock.patch('apps.discount_approvals.replication.force_replication', return_value={'ok': 1}), \
                    mock.patch('apps.discount_approvals.replication.check_item', return_value=self.STATUS):
                r = self.admin.post(f'{BASE}replication/repair/', {'scan_id': scan.pk}, format='json')
        self.assertEqual(r.json()['gaps_confirmed_repaired'], 1)
        gap.refresh_from_db()
        self.assertEqual((gap.status, gap.repaired_by), (ReplicationGap.STATUS_REPAIRED, self.admin_user))

    def test_item_status_answers_503_when_softech_is_down(self):
        with mock.patch('apps.discount_approvals.replication.check_item', return_value=self.STATUS):
            self.assertEqual(self.pharm.get(f'{BASE}replication/item/R7P01/').json(), self.STATUS)
        with mock.patch('apps.discount_approvals.replication.check_item', side_effect=ConnectionError('down')):
            self.assertEqual(self.pharm.get(f'{BASE}replication/item/R7P01/').status_code, 503)


class InsightViewTests(_Base):

    def test_branch_health_from_latest_scan(self):
        from apps.branches.models import Branch
        Branch.objects.filter(pk=make_branch().pk).update(db_host='10.0.0.1', is_operational=True)
        code = make_branch().softech_branch_id
        scan = ReplicationScan.objects.create(status=ReplicationScan.STATUS_DONE)
        ReplicationGap.objects.create(scan=scan, item_softech_id='R7P01', branch_code=code)
        body = self.admin.get(f'{BASE}branch-health/').json()
        self.assertEqual(body['latest_scan_id'], scan.pk)
        row = next(b for b in body['branches'] if b['branch_code'] == code)
        self.assertEqual((row['stale_items'], row['health']), (1, 'lagging'))

    def test_who_changed_what(self):
        conn, _ = _conn(fetchall=[('U77', 4), ('U1', 1)])
        Req.objects.filter(pk=self._req(status=Req.STATUS_EXECUTED).pk).update(
            erp_executed_at=timezone.now(), reviewed_by=self.admin_user, erp_username='r7 admin')
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn), \
                mock.patch('apps.discount_approvals.replication._usercode_name_map',
                           return_value={'U77': 'Admin'}):
            body = self.admin.get(f'{BASE}who-changed-what/', {'days': '7'}).json()
        self.assertEqual((body['days'], body['total_hq_edits'], body['module_executed']), (7, 5, 1))
        self.assertEqual(body['module_share_pct'], 20.0)
        self.assertEqual(body['by_user_softech'][0], {'usercode': 'U77', 'name': 'Admin', 'edits': 4})

    def test_who_changed_what_softech_down_is_502(self):
        with mock.patch('config.sybase.get_sybase_connection', side_effect=ConnectionError('x')):
            self.assertEqual(self.admin.get(f'{BASE}who-changed-what/').status_code, 502)

    def test_discount_impact_compares_before_and_after(self):
        from apps.purchasing.models import SalesTransactionLine
        executed = timezone.now() - timedelta(days=40)
        req = self._req(status=Req.STATUS_EXECUTED, new={'pos_discp': '5'})
        Req.objects.filter(pk=req.pk).update(erp_executed_at=executed)
        d = executed.date()
        for day, qty in ((d - timedelta(days=10), 30), (d + timedelta(days=10), 60)):
            SalesTransactionLine.objects.create(
                softech_branchcode='120', softech_itemcode='R7P01', doccode='115',
                docnumber=f'R7{qty}', doc_date=day, item=self.item, transqty=Decimal(qty),
                net_qty=Decimal(qty), net_revenue=Decimal(qty * 10))
        body = self.admin.get(f'{BASE}discount-impact/', {'window': '30'}).json()
        ch = body['changes'][0]
        self.assertEqual((ch['before']['qty'], ch['after']['qty']), (30.0, 60.0))
        self.assertEqual(ch['qty_lift_pct'], 100.0)
        self.assertEqual(ch['maturity'], 'mature')
        self.assertTrue(ch['changed']['pos_discp']['is_discount'])
        self.assertEqual(body['summary']['positive_count'], 1)

    def test_discount_impact_bad_window_is_400(self):
        self.admin.raise_request_exception = False
        self.assertEqual(self.admin.get(f'{BASE}discount-impact/', {'window': 'abc'}).status_code, 400)

    def test_policy_read_and_update(self):
        r = self.admin.post(f'{BASE}policy/', {'auto_repair_enabled': True, 'max_items_per_run': '0',
                                               'daily_window_days': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)
        pol = ReplicationPolicy.get()
        self.assertTrue(pol.auto_repair_enabled)
        self.assertEqual((pol.max_items_per_run, pol.daily_window_days), (1, 30))
        self.assertEqual(self.admin.get(f'{BASE}policy/').json()['updated_by'], 'r7da_admin')


class AlignmentViewTests(_Base):

    def setUp(self):
        super().setUp()
        self.item.origin_code = 'O1'
        self.item.origin_name = 'Med: Imported 18 %'
        self.item.pharmacy_discp = Decimal('15')
        self.item.save()

    def test_scan_flags_the_drifted_item(self):
        body = self.pharm.get(f'{BASE}alignment/', {'search': 'R7 price', 'flag': 'origin_vs_discount'}).json()
        self.assertEqual([r['softech_id'] for r in body['rows']], ['R7P01'])
        self.assertEqual(body['stats']['flagged'], 1)
        body = self.pharm.get(f'{BASE}alignment/', {'only_misaligned': '0', 'limit': 'x',
                                                   'supplier_code': 'NONE'}).json()
        self.assertEqual(body['rows'], [])

    def test_policies_upsert_is_admin_only(self):
        payload = {'scope': 'supplier', 'code': 'S1', 'expected_discount': '18.5'}
        self.assertEqual(self.pharm.post(f'{BASE}alignment/policies/', payload, format='json').status_code, 403)
        r = self.admin.post(f'{BASE}alignment/policies/', payload, format='json')
        self.assertEqual(r.json()['expected_discount'], '18.5')
        self.assertEqual(self.admin.post(f'{BASE}alignment/policies/', {'scope': 'bad', 'code': 'S'},
                                         format='json').status_code, 400)
        self.assertEqual(self.admin.post(f'{BASE}alignment/policies/', {'code': 'S', 'expected_discount': 'x'},
                                         format='json').status_code, 400)
        self.assertEqual(SupplierDiscountPolicy.objects.get().expected_discount, Decimal('18.50'))
        self.assertEqual(self.pharm.get(f'{BASE}alignment/policies/').json()[0]['code'], 'S1')

    def test_tiers_lists_catalog_origins(self):
        body = self.pharm.get(f'{BASE}alignment/tiers/').json()
        self.assertIn({'code': 'O1', 'name': 'Med: Imported 18 %', 'pct': '18', 'family': 'imported'},
                      body['origins'])

    def test_apply_is_admin_only_and_needs_the_switch(self):
        body = {'item_ids': [self.item.pk], 'origin_code': 'O2'}
        self.assertEqual(self.pharm.post(f'{BASE}alignment/apply/', body, format='json').status_code, 403)
        self.assertEqual(self.admin.post(f'{BASE}alignment/apply/', {}, format='json').status_code, 400)
        r = self.admin.post(f'{BASE}alignment/apply/', body, format='json')
        self.assertEqual(r.status_code, 400)                  # writes switched off
        self.assertIn('PRICING_SOFTECH_WRITE_ENABLED', r.json()['detail'])

    @override_settings(**WRITES_ON)
    def test_apply_writes_and_verifies_the_new_origin(self):
        conn, cur = _conn(fetchone=('O2',))
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            r = self.admin.post(f'{BASE}alignment/apply/',
                                {'changes': [{'item_id': self.item.pk, 'origin_code': 'O2'},
                                             {'item_id': 999999, 'origin_code': 'O2'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['applied'], r.json()['failed']), (1, 1))
        self.assertEqual(cur.execute.call_args_list[0][0][1], ['O2', 'U77', 'R7P01'])
        self.item.refresh_from_db()
        self.assertEqual(self.item.origin_code, 'O2')

    def test_tier_preview(self):
        self.assertEqual(self.pharm.get(f'{BASE}alignment/tier-preview/').status_code, 400)
        conn, _ = _conn(fetchone=[('1', 'Local 10 %', 'U1'), (5,), None],
                        description=[('itemorigincode',), ('itemoriginname',), ('usercode',)])
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            body = self.pharm.get(f'{BASE}alignment/tier-preview/', {'kind': 'origin', 'label': 'Imported 22 %'}).json()
        self.assertEqual((body['new_code'], body['code_exists'], body['desc_cols']), ('6', False, ['itemoriginname']))
        self.assertEqual(body['proposed_row']['itemoriginname'], 'Imported 22 %')

    @override_settings(**WRITES_ON)
    def test_tier_create(self):
        self.assertEqual(self.pharm.post(f'{BASE}alignment/tier-create/', {'label': 'x'},
                                         format='json').status_code, 403)
        conn, cur = _conn(fetchone=[('1', 'Local 10 %', 'U1', None), (5,), None, ('Imported 22 %',)],
                          description=[('itemorigincode',), ('itemoriginname',), ('usercode',),
                                       ('importedorigin',)])
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            r = self.admin.post(f'{BASE}alignment/tier-create/',
                                {'kind': 'origin', 'label': 'Imported 22 %'}, format='json')
        self.assertEqual(r.json(), {'code': '6', 'table': 'itemsorigin', 'ok': True})
        insert_params = cur.execute.call_args_list[3][0][1]
        self.assertEqual(insert_params, ['6', 'Imported 22 %', 'U77', '1'])


class PricingPermissionTests(_Base):

    def test_pharmacist_cannot_approve_or_reject(self):
        req = self._req()
        self.assertEqual(self.pharm.post(f'{BASE}{req.pk}/approve/', {}, format='json').status_code, 403)
        self.assertEqual(self.pharm.post(f'{BASE}{req.pk}/reject/', {}, format='json').status_code, 403)
        self.assertEqual(self.pharm.get(f'{BASE}policy/').status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_PENDING)

    def test_salesperson_has_no_pricing_access(self):
        sales = bearer_client(make_user('r7da_sales', role='salesperson')[0])
        self.assertEqual(sales.get(BASE).status_code, 403)
        self.assertEqual(sales.get(f'{BASE}sla/').status_code, 403)
        self.assertEqual(sales.post(f'{BASE}{self._req(status=Req.STATUS_EXECUTED).pk}/rollback/',
                                    {}, format='json').status_code, 403)
        self.assertEqual(Req.objects.count(), 1)
