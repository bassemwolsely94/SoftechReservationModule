"""
apps/tests/test_code_maps_new_values.py  (piece 4, Task 5)

Drift and new-value guards:
  • every channel the POS writer stamps (apps.pos_orders.models.CHANNEL_TO_PTCLASSIF,
    read only) is in the registry with the matching meaning;
  • a channel code SOFTECH adds later flows through every consumer as «غير مصنف»:
    not contract, not favoured, chronic 'unclassified', listed first on the API;
  • an item-category code SOFTECH adds later is not medicine, not excluded from
    planning, and listed first on the API.
"""
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Item
from apps.config import item_types
from apps.forecasting import channels
from apps.sync.models import SoftechPersonClassif
from apps.tests.factories import make_admin, make_branch, make_item

POS_NAME_TO_GROUP = {
    'cash': 'cash', 'delivery': 'delivery', 'contract': 'contract', 'insurance': 'insurance',
    'employee': 'employee', 'vip': 'vip', 'permanent': 'permanent',
    'compensation': 'compensation', 'donation': 'donation', 'card_receipt': 'card',
}


class _RegistryCacheMixin:
    def setUp(self):
        channels.invalidate_cache()
        item_types.invalidate_cache()
        super().setUp()

    def tearDown(self):
        channels.invalidate_cache()
        item_types.invalidate_cache()
        super().tearDown()


class PosChannelDriftTests(_RegistryCacheMixin, TestCase):
    def test_pos_channels_registered(self):
        from apps.pos_orders.models import CHANNEL_TO_PTCLASSIF
        self.assertEqual(set(CHANNEL_TO_PTCLASSIF), set(POS_NAME_TO_GROUP),
                         'POS channel list changed — map the new name here and in the registry')
        for name, code in CHANNEL_TO_PTCLASSIF.items():
            info = channels.channel(code)
            self.assertTrue(info.known, (name, code))
            self.assertEqual(info.group, POS_NAME_TO_GROUP[name], (name, code))


class NewChannelFlowsUnclassifiedTests(_RegistryCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        channels.ensure_defaults()
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='77', ptclassifdescr='جديد')
        self.assertEqual(channels.ensure_channel_rows(notify=False), ['77'])

    def test_new_channel_flows_unclassified(self):
        from apps.chronic.classifier import customer_type
        from apps.customers.models import Customer
        from apps.followups.models import FollowUpTask
        from apps.replacement import config as replacement_config

        info = channels.channel('77')
        self.assertTrue(info.known)
        self.assertEqual(info.group, 'unclassified')

        branch = make_branch()
        task = FollowUpTask.objects.create(item=make_item('NEWCH', 'IT777'), branch=branch,
                                           task_type='refill', status='pending',
                                           due_date=timezone.localdate(), sales_channel='77')
        _, _, admin = make_admin('cm_new_admin')
        r = admin.get('/api/followups/tasks/', {'page_size': 50})
        self.assertEqual(r.status_code, 200)
        rows = r.data.get('results', r.data) if isinstance(r.data, dict) else r.data
        self.assertIn(task.pk, [row['id'] for row in rows])
        self.assertEqual(task.sales_channel_label, 'غير مصنف (77) — جديد')
        self.assertFalse(task.channel_is_favoured)
        self.assertNotIn('77', channels.favoured_codes())

        self.assertNotIn('77', replacement_config.contract_channels())
        self.assertNotIn('77', channels.contract_codes())
        self.assertEqual(customer_type(Customer(name='x'), '77'), 'unclassified')

        call_command('seed_permissions', verbosity=0)
        r = admin.get('/api/config/code-maps/channels/')
        self.assertEqual(r.status_code, 200, r.data)
        row = r.data['rows'][0]
        self.assertEqual(row['code'], '77')
        self.assertEqual(row['group'], 'unclassified')
        self.assertEqual(row['group_label'], 'غير مصنف')
        self.assertEqual(row['label'], 'جديد')          # SOFTECH's raw name for the owner
        self.assertFalse(row['is_contract_sale'])
        self.assertIsNone(row['followup_rank'])

    def test_unclassified_row_with_blank_label(self):
        from apps.forecasting.models import ChannelBucketMap
        ChannelBucketMap.objects.create(person_type='10', channel='78', group='unclassified')
        channels.invalidate_cache()
        self.assertEqual(channels.channel('78').label, 'غير مصنف (78)')
        self.assertEqual(channels.channel('79').label, 'غير مصنف (79)')   # no row at all


class NewItemTypeFlowsUnclassifiedTests(_RegistryCacheMixin, TestCase):
    def test_new_item_type_flows_unclassified(self):
        item_types.ensure_defaults()
        self.assertEqual(item_types.sync_item_types({'85': ('New cat', 'تصنيف جديد')}, notify=False),
                         ['85'])
        Item.objects.create(softech_id='T85', name='T85', pack_price=10, medicine_type='85')

        self.assertNotIn('85', item_types.medicine_codes())
        self.assertNotIn('85', item_types.planning_excluded_codes())
        self.assertEqual(item_types.medicine_codes(), ['10'])

        call_command('seed_permissions', verbosity=0)
        _, _, admin = make_admin('cm_new_it_admin')
        r = admin.get('/api/config/code-maps/item-types/')
        self.assertEqual(r.status_code, 200, r.data)
        first = r.data['rows'][0]
        self.assertEqual((first['code'], first['group'], first['is_medicine'],
                          first['excluded_from_planning'], first['item_count']),
                         ('85', 'unclassified', False, False, 1))
