"""
apps/tests/test_code_maps_api.py  (piece 4, Task 5)

The owner's editing API for the SOFTECH code maps:
  /api/config/code-maps/channels/[<pk>/]    — ChannelBucketMap, person_type '10'
  /api/config/code-maps/item-types/[<pk>/]  — MedicineTypeMap
GET needs settings/view, PATCH settings/edit. Every real change is audited
(`code_map_changed`) and the readers see it on the next call.
"""
import datetime as dt

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.catalog.models import Item
from apps.config import item_types
from apps.config.models import MedicineTypeMap
from apps.customers.models import Customer, PurchaseHistory
from apps.forecasting import channels
from apps.forecasting.models import ChannelBucketMap
from apps.tests.factories import make_admin, make_branch, make_pharmacist, make_salesperson

CH_URL = '/api/config/code-maps/channels/'
IT_URL = '/api/config/code-maps/item-types/'


class _CodeMapsBase(TestCase):
    def setUp(self):
        channels.invalidate_cache()
        item_types.invalidate_cache()
        call_command('seed_permissions', verbosity=0)
        self.branch = make_branch()
        _, self.admin_profile, self.admin = make_admin('cm_api_admin')

    def tearDown(self):
        channels.invalidate_cache()
        item_types.invalidate_cache()
        super().tearDown()

    def _row(self, code):
        channels.ensure_defaults()
        return ChannelBucketMap.objects.get(person_type='10', channel=code)

    def _type(self, code):
        item_types.ensure_defaults()
        return MedicineTypeMap.objects.get(code=code)

    def _audits(self):
        return AuditLog.objects.filter(action='code_map_changed')


class ChannelsApiTests(_CodeMapsBase):
    def test_list_returns_twelve_seeded_channels(self):
        r = self.admin.get(CH_URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data), 12)
        by_code = {row['code']: row for row in r.data}
        self.assertEqual(by_code['10']['group'], 'contract')
        self.assertEqual(by_code['10']['group_label'], 'تعاقد')
        self.assertTrue(by_code['10']['is_contract_sale'])
        self.assertEqual(by_code['10']['followup_rank'], 3)
        self.assertEqual(by_code['10']['bucket'], 'credit')
        self.assertEqual(by_code['10']['bucket_label'], 'آجل')
        self.assertEqual(set(by_code['91']), {'id', 'code', 'label', 'group', 'group_label', 'bucket',
                                              'bucket_label', 'is_contract_sale', 'followup_rank',
                                              'sales_90d'})
        # rank, then code
        self.assertEqual([row['code'] for row in r.data][:4], ['90', '91', '30', '99'])

    def test_list_only_customer_rows_and_unclassified_first(self):
        channels.ensure_defaults()
        ChannelBucketMap.objects.create(person_type='20', channel='01', label='مورد')
        ChannelBucketMap.objects.create(person_type='10', channel='77', group='unclassified')
        r = self.admin.get(CH_URL)
        codes = [row['code'] for row in r.data]
        self.assertEqual(len(codes), 13)
        self.assertEqual(codes[0], '77')
        self.assertNotIn('01', codes)

    def test_sales_90d_counts_recent_sales_per_channel(self):
        now = timezone.now()
        cust = Customer.objects.create(name='س')
        rows = [('91', '115', 5), ('91', '115', 40), ('91', '115', 120), ('91', '30', 5), ('90', '115', 1)]
        for n, (ch, doc, days) in enumerate(rows):
            PurchaseHistory.objects.create(customer=cust, branch=self.branch, doc_code=doc,
                                           docnumber=str(n), sales_channel=ch,
                                           invoice_date=now - dt.timedelta(days=days),
                                           softech_invoice_id=f'B01-{doc}-{n}')
        r = self.admin.get(CH_URL)
        by_code = {row['code']: row for row in r.data}
        self.assertEqual(by_code['91']['sales_90d'], 2)
        self.assertEqual(by_code['90']['sales_90d'], 1)
        self.assertEqual(by_code['10']['sales_90d'], 0)

    def test_admin_patch_group_is_live_and_audited(self):
        row = self._row('99')
        self.assertEqual(channels.channel('99').group, 'vip')
        r = self.admin.patch(f'{CH_URL}{row.pk}/', {'group': 'cash'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['group'], 'cash')
        self.assertEqual(channels.channel('99').group, 'cash')
        logs = list(self._audits())
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].old_data, {'group': 'vip'})
        self.assertEqual(logs[0].new_data, {'group': 'cash'})
        self.assertEqual(logs[0].user, self.admin_profile)
        self.assertEqual(logs[0].object_id, str(row.pk))

    def test_patch_ignores_bucket_and_other_keys(self):
        row = self._row('91')
        r = self.admin.patch(f'{CH_URL}{row.pk}/',
                             {'bucket': 'exclude', 'label': 'x', 'channel': '55', 'followup_rank': 2},
                             format='json')
        self.assertEqual(r.status_code, 200, r.data)
        row.refresh_from_db()
        self.assertEqual((row.bucket, row.label, row.channel, row.followup_rank),
                         ('cash', '', '91', 2))
        log = self._audits().get()
        self.assertEqual(log.old_data, {'followup_rank': 1})
        self.assertEqual(log.new_data, {'followup_rank': 2})

    def test_patch_contract_flag_and_null_rank(self):
        row = self._row('12')
        r = self.admin.patch(f'{CH_URL}{row.pk}/', {'is_contract_sale': True, 'followup_rank': None},
                             format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('12', channels.contract_codes())
        self.assertNotIn('12', channels.rank_map())

    def test_patch_rejects_bad_values(self):
        row = self._row('91')
        for body in ({'followup_rank': 0}, {'followup_rank': 5}, {'followup_rank': 'x'},
                     {'group': 'nonsense'}, {'group': ''}):
            r = self.admin.patch(f'{CH_URL}{row.pk}/', body, format='json')
            self.assertEqual(r.status_code, 400, body)
            self.assertIn('detail', r.data)
        row.refresh_from_db()
        self.assertEqual((row.group, row.followup_rank), ('cash', 1))
        self.assertFalse(self._audits().exists())

    def test_patch_without_change_writes_no_audit(self):
        row = self._row('91')
        r = self.admin.patch(f'{CH_URL}{row.pk}/', {'group': 'cash', 'followup_rank': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(self._audits().exists())

    def test_patch_non_customer_row_is_404(self):
        other = ChannelBucketMap.objects.create(person_type='20', channel='01')
        r = self.admin.patch(f'{CH_URL}{other.pk}/', {'group': 'cash'}, format='json')
        self.assertEqual(r.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.group, 'unclassified')

    def test_salesperson_cannot_patch(self):
        row = self._row('99')
        _, _, sales = make_salesperson('cm_api_sales', branch=self.branch)
        r = sales.patch(f'{CH_URL}{row.pk}/', {'group': 'cash'}, format='json')
        self.assertEqual(r.status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.group, 'vip')

    def test_view_only_role_reads_but_cannot_patch(self):
        row = self._row('99')
        _, _, pharma = make_pharmacist('cm_api_pharma', branch=self.branch)
        self.assertEqual(pharma.get(CH_URL).status_code, 200)
        self.assertEqual(pharma.patch(f'{CH_URL}{row.pk}/', {'group': 'cash'},
                                      format='json').status_code, 403)

    def test_unauthenticated_is_401(self):
        row = self._row('99')
        anon = APIClient()
        self.assertEqual(anon.get(CH_URL).status_code, 401)
        self.assertEqual(anon.patch(f'{CH_URL}{row.pk}/', {'group': 'cash'},
                                    format='json').status_code, 401)


class ItemTypesApiTests(_CodeMapsBase):
    def test_list_shows_60_excluded_with_item_counts(self):
        for sid, t, active in (('A1', '10', True), ('A2', '10', True), ('A3', '10', False),
                               ('A4', '60', True)):
            Item.objects.create(softech_id=sid, name=sid, pack_price=10, medicine_type=t,
                                is_active=active)
        r = self.admin.get(IT_URL)
        self.assertEqual(r.status_code, 200, r.data)
        by_code = {row['code']: row for row in r.data}
        self.assertEqual(len(by_code), 8)
        self.assertTrue(by_code['60']['excluded_from_planning'])
        self.assertEqual(by_code['60']['group'], 'gift')
        self.assertEqual(by_code['60']['group_label'], 'هدايا عملاء')
        self.assertTrue(by_code['10']['is_medicine'])
        self.assertEqual(by_code['10']['item_count'], 2)
        self.assertEqual(by_code['60']['item_count'], 1)
        self.assertEqual(by_code['50']['item_count'], 0)
        self.assertEqual(set(by_code['10']), {'id', 'code', 'label', 'group', 'group_label',
                                              'is_medicine', 'excluded_from_planning', 'item_count'})

    def test_patch_excluded_is_live_and_audited(self):
        t70 = self._type('70')
        self.assertNotIn('70', item_types.planning_excluded_codes())
        r = self.admin.patch(f'{IT_URL}{t70.pk}/', {'excluded_from_planning': True, 'code': '99'},
                             format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('70', item_types.planning_excluded_codes())
        t70.refresh_from_db()
        self.assertEqual(t70.code, '70')
        log = self._audits().get()
        self.assertEqual(log.old_data, {'excluded_from_planning': False})
        self.assertEqual(log.new_data, {'excluded_from_planning': True})
        self.assertEqual(log.model_name, 'MedicineTypeMap')

    def test_patch_refuses_empty_medicine_set(self):
        t10 = self._type('10')
        r = self.admin.patch(f'{IT_URL}{t10.pk}/', {'is_medicine': False}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.assertEqual(item_types.medicine_codes(), ['10'])
        self.assertFalse(self._audits().exists())
        # with another medicine code in place the same change is allowed
        self.admin.patch(f'{IT_URL}{self._type("50").pk}/', {'is_medicine': True}, format='json')
        r = self.admin.patch(f'{IT_URL}{t10.pk}/', {'is_medicine': False}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(item_types.medicine_codes(), ['50'])

    def test_patch_rejects_bad_group(self):
        t = self._type('20')
        r = self.admin.patch(f'{IT_URL}{t.pk}/', {'group': 'cash'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_patch_without_change_writes_no_audit(self):
        t = self._type('60')
        r = self.admin.patch(f'{IT_URL}{t.pk}/', {'excluded_from_planning': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(self._audits().exists())

    def test_permissions(self):
        t = self._type('60')
        _, _, sales = make_salesperson('cm_it_sales', branch=self.branch)
        self.assertEqual(sales.patch(f'{IT_URL}{t.pk}/', {'excluded_from_planning': False},
                                     format='json').status_code, 403)
        self.assertEqual(APIClient().get(IT_URL).status_code, 401)
        t.refresh_from_db()
        self.assertTrue(t.excluded_from_planning)
