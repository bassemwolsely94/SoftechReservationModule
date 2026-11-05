"""
Insurance (apps/insurance) — R7 per-app tests: the route groups next to claims.

One view test per router registration / view in apps/insurance/urls.py except `claims`
(test_insurance_r7_claims.py), the module matrix (salesperson / pharmacist have no
`insurance` grant → 403), and the supplement money rule: gross = local + imported + tarsia,
discount = each split × the claim's applied rate (2 dp), net = gross − discount, and the claim's
final net follows. SOFTECH is mocked wherever a view would read it.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.insurance import models as m
from apps.tests.factories import make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

API = '/api/insurance/'


def mk_claim(sub, number='R7-0001', status=m.InsuranceClaim.STATUS_DRAFT, l=17, i=6, t=0,
             pf='2026-08-01', pt='2026-08-31'):
    return m.InsuranceClaim.objects.create(
        claim_number=number, subclient=sub, status=status,
        period_from=date.fromisoformat(pf), period_to=date.fromisoformat(pt),
        applied_local_disc_pct=l, applied_imported_disc_pct=i, applied_tarsia_disc_pct=t)


def add_rx(claim, doc, local=0, imported=0, tarsia=0, day='2026-08-10', branch='160', patient='',
           **kw):
    l, i, t = Decimal(local), Decimal(imported), Decimal(tarsia)
    ld = (l * Decimal(claim.applied_local_disc_pct) / 100).quantize(Decimal('0.01'))
    idd = (i * Decimal(claim.applied_imported_disc_pct) / 100).quantize(Decimal('0.01'))
    return m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=doc, softech_docdate=date.fromisoformat(day),
        softech_branchcode=branch, patient_name=patient, softech_patient_name=patient,
        local_before=l, imported_before=i, tarsia_before=t, gross_before=l + i + t,
        local_discount=ld, imported_discount=idd, total_discount=ld + idd,
        net_after=l + i + t - ld - idd, **kw)


def add_line(rx, code='111', name='صنف محلى', total='100', cat=m.ITEM_CATEGORY_LOCAL, qty='1'):
    total = Decimal(total)
    return m.InsuranceClaimLine.objects.create(
        prescription=rx, softech_itemcode=code, item_name=name, item_category=cat,
        quantity=Decimal(qty), unit_price=total / Decimal(qty), line_total=total,
        discount_pct=Decimal('17'), discount_amt=(total * Decimal('0.17')).quantize(Decimal('0.01')),
        net_amount=(total * Decimal('0.83')).quantize(Decimal('0.01')),
        softech_imported_flag=False, softech_store_classif='10')


@override_settings(RBAC_ENFORCEMENT='log')
class InsuranceR7Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.admin_user, self.admin_profile, _ = make_user('r7ins_admin', role='admin', access_all=True)
        self.api = bearer_client(self.admin_user)
        self.client_obj = m.InsuranceClient.objects.create(name='جهة R7', softech_personcode='4001')
        self.sub = m.InsuranceSubClient.objects.create(client=self.client_obj, name='فئة R7')

    def tearDown(self):
        module_access.clear_cache()

    @staticmethod
    def rows(r):
        body = r.json()
        return body.get('results', body) if isinstance(body, dict) else body


class SupplementMoneyRuleTests(InsuranceR7Base):
    """Business rule: a supplement's discount and net come from the claim's own rates."""

    def test_supplement_net_and_claim_total(self):
        claim = mk_claim(self.sub)                                   # 17% local · 6% imported · 0% tarsia
        r = self.api.post(f'{API}claims/{claim.pk}/supplements/', {
            'supplement_type': 'after_claim', 'label': 'ملحق R7', 'print_date': '',
            'local_before': '1000', 'imported_before': '500', 'tarsia_before': '33.33',
            'net_after': '1'}, format='json')                      # a sent net is ignored
        self.assertEqual(r.status_code, 201, r.content)
        sup = m.InsuranceClaimSupplement.objects.get()
        self.assertEqual(sup.gross_before, Decimal('1533.33'))
        self.assertEqual((sup.local_discount, sup.imported_discount, sup.tarsia_discount),
                         (Decimal('170.00'), Decimal('30.00'), Decimal('0.00')))
        self.assertEqual((sup.total_discount, sup.net_after), (Decimal('200.00'), Decimal('1333.33')))
        claim.refresh_from_db()
        self.assertEqual(Decimal(str(claim.final_net_after)), Decimal('1333.33'))

    def test_editing_the_before_values_recomputes_and_flags_manual_edit(self):
        claim = mk_claim(self.sub, l=10, i=5)
        sup = m.InsuranceClaimSupplement.objects.create(claim=claim, supplement_type='within_claim',
                                                        local_before=100)
        r = self.api.patch(f'{API}claims/{claim.pk}/supplements/{sup.pk}/', {'imported_before': '200.10'},
                           format='json')
        self.assertEqual(r.status_code, 200, r.content)
        sup.refresh_from_db()
        # 100 × 10% = 10.00; 200.10 × 5% = 10.005 → 10.00 (Decimal.quantize default = half-even,
        # the same rounding recalculate_claim_final_totals uses); net = 300.10 − 20.00
        self.assertEqual((sup.local_discount, sup.imported_discount), (Decimal('10.00'), Decimal('10.00')))
        self.assertEqual((sup.net_after, sup.is_manually_edited), (Decimal('280.10'), True))
        self.assertTrue(claim.audit_events.filter(action='supplement').exists())
        self.assertEqual(self.api.delete(f'{API}claims/{claim.pk}/supplements/{sup.pk}/').status_code, 204)
        self.assertEqual(self.api.delete(f'{API}claims/{claim.pk}/supplements/{sup.pk}/').status_code, 404)

    def test_standalone_supplement_stays_out_of_the_claim_total(self):
        claim = mk_claim(self.sub)
        self.api.post(f'{API}claims/{claim.pk}/supplements/', {
            'supplement_type': 'standalone', 'local_before': '1000'}, format='json')
        claim.refresh_from_db()
        self.assertEqual(Decimal(str(claim.final_net_after)), Decimal('0.00'))
        self.assertEqual(len(self.api.get(f'{API}claims/{claim.pk}/supplements/').json()), 1)


class ClientSetupViewTests(InsuranceR7Base):

    def test_clients_crud_and_softech_persons(self):
        r = self.api.post(f'{API}clients/', {'name': 'جهة جديدة', 'softech_personcode': '4002'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        names = [c['name'] for c in self.rows(self.api.get(f'{API}clients/'))]
        self.assertEqual(sorted(names), sorted(['جهة R7', 'جهة جديدة']))
        self.assertEqual(self.api.get(f'{API}clients/{self.client_obj.pk}/').json()['subclients'][0]['name'],
                         'فئة R7')
        cur = mock.MagicMock()
        cur.fetchall.return_value = [('4001', 'جهة', '15', '1')]
        conn = mock.MagicMock(**{'cursor.return_value': cur})
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            self.assertEqual(self.api.get(f'{API}clients/persons-from-softech/').json(),
                             [{'personcode': '4001', 'name': 'جهة', 'ptcode': '15', 'ptclassifcode': '1'}])
        with mock.patch('config.sybase.get_sybase_connection', side_effect=ConnectionError('down')):
            self.assertEqual(self.api.get(f'{API}clients/persons-from-softech/').status_code, 503)

    def test_subclients_filter_by_client(self):
        other = m.InsuranceClient.objects.create(name='جهة أخرى')
        r = self.api.post(f'{API}subclients/', {'client': other.pk, 'name': 'فئة 2'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows(self.api.get(f'{API}subclients/', {'client_id': other.pk}))
        self.assertEqual([s['name'] for s in rows], ['فئة 2'])

    def test_contracts_filter_by_subclient(self):
        r = self.api.post(f'{API}contracts/', {'subclient': self.sub.pk, 'effective_from': '2026-01-01',
                                              'local_discount_pct': '15'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows(self.api.get(f'{API}contracts/', {'subclient_id': self.sub.pk}))
        self.assertEqual((rows[0]['local_discount_pct'], rows[0]['imported_discount_pct']), ('15.00', '6.00'))

    def test_parent_clients(self):
        r = self.api.post(f'{API}parent-clients/', {'name': 'أب R7'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.client_obj.parent_id = r.json()['id']
        self.client_obj.save()
        self.assertEqual(self.rows(self.api.get(f'{API}parent-clients/'))[0]['clients_count'], 1)


class ClaimSetupViewTests(InsuranceR7Base):

    def test_billing_groups_assign_unassign_and_totals(self):
        claim = mk_claim(self.sub)
        rx1 = add_rx(claim, '7001', local=100, relative_degree='للعضو')
        rx2 = add_rx(claim, '7002', local=200)
        r = self.api.post(f'{API}billing-groups/', {'claim': claim.pk, 'code': 'MEM', 'name': 'الأعضاء',
                                                   'filter_relative_degree': 'للعضو'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        gid = r.json()['id']
        self.assertEqual(self.api.post(f'{API}billing-groups/{gid}/auto-assign/').json()['assigned'], 1)
        self.assertEqual(self.api.post(f'{API}billing-groups/{gid}/assign-rx/', {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(f'{API}billing-groups/{gid}/assign-rx/',
                                       {'prescription_ids': [rx2.pk]}, format='json').json(), {'updated': 1})
        grp = m.InsuranceClaimBillingGroup.objects.get(pk=gid)
        self.assertEqual((grp.rx_count, grp.gross_before, grp.net_after), (2, Decimal('300.00'), Decimal('249.00')))
        rows = self.rows(self.api.get(f'{API}billing-groups/', {'claim_id': claim.pk}))
        self.assertEqual(rows[0]['net_after'], '249.00')
        self.assertEqual(self.api.post(f'{API}billing-groups/{gid}/unassign-rx/',
                                       {'prescription_ids': [rx1.pk]}, format='json').json(), {'unassigned': 1})
        self.assertEqual(self.api.post(f'{API}billing-groups/{gid}/unassign-rx/', {}, format='json').json(),
                         {'unassigned': 1})
        self.assertEqual(self.api.post(f'{API}billing-groups/refresh-all/', {'claim_id': claim.pk},
                                       format='json').json(), {'ok': True})
        self.assertEqual(self.api.post(f'{API}billing-groups/refresh-all/', {}, format='json').status_code, 400)
        r = self.api.get(f'{API}billing-groups/{gid}/export/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))

    def test_billing_group_on_a_locked_claim_is_423(self):
        claim = mk_claim(self.sub, status=m.InsuranceClaim.STATUS_SUBMITTED)
        grp = m.InsuranceClaimBillingGroup.objects.create(claim=claim, code='X', name='x')
        for action in ('auto-assign', 'assign-rx', 'unassign-rx'):
            self.assertEqual(self.api.post(f'{API}billing-groups/{grp.pk}/{action}/', {'prescription_ids': [1]},
                                           format='json').status_code, 423, action)

    def test_export_profiles(self):
        r = self.api.post(f'{API}export-profiles/', {'name': 'R7', 'subclient': self.sub.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows(self.api.get(f'{API}export-profiles/', {'subclient_id': self.sub.pk}))
        self.assertEqual((rows[0]['name'], rows[0]['subclient_name']), ('R7', 'فئة R7'))

    def test_pivot_templates(self):
        r = self.api.post(f'{API}pivot-templates/', {'name': 'R7', 'row_dim': 'branch'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(m.InsurancePivotTemplate.objects.get().created_by, self.admin_profile)
        self.assertEqual(self.rows(self.api.get(f'{API}pivot-templates/'))[0]['measure'], 'net')

    def test_item_overrides_lookup_and_affected_claims(self):
        item = make_item(name='R7 imported', softech_id='R7I01')
        item.is_imported = True
        item.save()
        r = self.api.post(f'{API}item-overrides/', {'item_code': 'R7I01', 'forced_category': 'local'},
                          format='json')
        self.assertEqual(r.status_code, 201, r.content)
        ov = m.InsuranceItemClassificationOverride.objects.get()
        self.assertEqual(ov.item_name, 'R7 imported')                 # filled from the catalog
        body = self.api.get(f'{API}item-overrides/catalog-lookup/', {'code': 'R7I01'}).json()
        self.assertEqual((body['found'], body['current_category']), (True, 'local'))
        self.assertEqual(self.api.get(f'{API}item-overrides/catalog-lookup/', {'code': 'NOPE'}).json(),
                         {'found': False, 'item_code': 'NOPE'})
        self.assertEqual(self.api.get(f'{API}item-overrides/catalog-lookup/').status_code, 400)
        claim = mk_claim(self.sub)
        add_line(add_rx(claim, '7101', local=100), code='R7I01')
        self.assertEqual(self.api.get(f'{API}item-overrides/{ov.pk}/affected-claims/').json(),
                         [{'claim_id': claim.pk, 'claim_number': 'R7-0001', 'status': 'draft', 'lines': 1}])
        rows = self.rows(self.api.get(f'{API}item-overrides/', {'search': 'R7I', 'active': 'true'}))
        self.assertEqual(len(rows), 1)

    def test_separation_lists_and_names(self):
        r = self.api.post(f'{API}separation-lists/', {'label': 'R7 فصل'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()['id']
        body = self.api.post(f'{API}separation-lists/{sid}/names/',
                             {'names_text': 'أحمد محمد علي\n\nأحمد محمد علي\nسارة حسن'}, format='json').json()
        self.assertEqual(body, {'added': 2, 'skipped': 1, 'total': 2})
        names = self.api.get(f'{API}separation-lists/{sid}/names/').json()
        nid = names[0]['id']
        r = self.api.patch(f'{API}separation-lists/{sid}/names/{nid}/', {'name': 'سارة حسن محمود',
                                                                         'is_active': False}, format='json')
        self.assertEqual((r.json()['name'], r.json()['is_active']), ('سارة حسن محمود', False))
        self.assertEqual(self.api.patch(f'{API}separation-lists/{sid}/names/{nid}/', {'name': ' '},
                                        format='json').status_code, 400)
        self.assertEqual(self.api.patch(f'{API}separation-lists/{sid}/names/999999/', {},
                                        format='json').status_code, 404)
        other = m.InsuranceSeparationList.objects.create(label='أخرى')
        self.assertEqual(self.api.post(f'{API}separation-lists/{sid}/move-names/',
                                       {'name_ids': [nid], 'target_list_id': other.pk}, format='json').json(),
                         {'moved': 1})
        self.assertEqual(self.api.post(f'{API}separation-lists/{sid}/move-names/', {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(f'{API}separation-lists/{sid}/move-names/',
                                       {'name_ids': [nid], 'target_list_id': 999999}, format='json').status_code, 404)
        self.assertEqual(self.api.delete(f'{API}separation-lists/{other.pk}/names/{nid}/').status_code, 204)
        self.assertEqual(m.InsuranceSeparationName.objects.count(), 1)


class CacheRosterPortfolioViewTests(InsuranceR7Base):

    def test_sync_cache_stats_and_trigger(self):
        body = self.api.get(f'{API}sync-cache/').json()
        self.assertEqual((body['motalba']['rows'], body['companiesitems']['rows']), (0, 0))
        with mock.patch('apps.insurance.sync.sync_insurance_cache', return_value={'status': 'ok'}):
            self.assertEqual(self.api.post(f'{API}sync-cache/').json(), {'status': 'ok'})
        with mock.patch('apps.insurance.sync.sync_insurance_cache', side_effect=ConnectionError('down')):
            r = self.api.post(f'{API}sync-cache/')
        self.assertEqual((r.status_code, r.json()['status']), (500, 'error'))

    def test_rosters_need_a_client(self):
        self.assertEqual(self.api.get(f'{API}rosters/').status_code, 400)
        claim = mk_claim(self.sub)
        add_rx(claim, '7201', local=10, patient='أحمد محمد علي حسن')
        r = self.api.get(f'{API}rosters/', {'client_id': self.client_obj.pk, 'subclient_id': self.sub.pk})
        self.assertEqual(r.status_code, 200, r.content)

    def test_portfolio_report(self):
        claim = mk_claim(self.sub)
        add_rx(claim, '7301', local=1000)
        r = self.api.get(f'{API}portfolio/', {'from': '2026-08-01', 'to': '2026-08-31', 'sort': 'claim_number',
                                              'dir': 'desc'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x['claim_id'] for x in r.json()['motalbas']], [claim.pk])
        r = self.api.get(f'{API}portfolio/', {'from': 'bad', 'format': 'xlsx', 'order': str(claim.pk)})
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))


class InsurancePermissionR7Tests(InsuranceR7Base):

    def test_roles_without_the_insurance_grant_are_refused(self):
        claim = mk_claim(self.sub)
        for role in ('salesperson', 'pharmacist'):
            c = bearer_client(make_user(f'r7ins_{role}', role=role)[0])
            for url in ('claims/', 'clients/', 'billing-groups/', 'sync-cache/', 'portfolio/',
                        f'rosters/?client_id={self.client_obj.pk}'):
                self.assertEqual(c.get(API + url).status_code, 403, (role, url))
            r = c.post(f'{API}claims/{claim.pk}/supplements/', {'supplement_type': 'after_claim',
                                                               'local_before': '10'}, format='json')
            self.assertEqual(r.status_code, 403, role)
        self.assertFalse(m.InsuranceClaimSupplement.objects.exists())

    def test_purchasing_holds_the_grant(self):
        c = bearer_client(make_user('r7ins_buyer', role='purchasing', access_all=True)[0])
        self.assertEqual(c.get(f'{API}claims/').status_code, 200)
        self.assertEqual(c.post(f'{API}clients/', {'name': 'من المشتريات'}, format='json').status_code, 201)
