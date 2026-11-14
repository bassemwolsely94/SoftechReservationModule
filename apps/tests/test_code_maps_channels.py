"""
apps/tests/test_code_maps_channels.py  (piece 4, Task 1)

The channel registry (apps/forecasting/channels.py) over ChannelBucketMap:
lazy seed on an empty map, no reseed when a row exists, unknown/blank codes,
the update-only migration step, and the sync hook that adds new SOFTECH codes.
"""
import importlib

from django.test import TestCase

from apps.forecasting import channels
from apps.forecasting.models import ChannelBucketMap


class ChannelRegistryTests(TestCase):
    def setUp(self):
        channels.invalidate_cache()

    def tearDown(self):
        channels.invalidate_cache()

    def test_empty_map_lazy_seeds_approved_table(self):
        self.assertFalse(ChannelBucketMap.objects.exists())
        self.assertEqual(channels.contract_codes(), ('10', '11', '15', '17', '33'))
        self.assertEqual(channels.favoured_codes(), {'91', '90', '30', '99'})
        self.assertEqual(channels.channel('30').group, 'permanent')
        self.assertEqual(
            ChannelBucketMap.objects.get(person_type='10', channel='10').bucket, 'credit')
        self.assertEqual(ChannelBucketMap.objects.filter(person_type='10').count(), 12)

    def test_seeded_kpi_values_match_previous_defaults(self):
        channels.ensure_defaults()
        row = ChannelBucketMap.objects.get(person_type='10', channel='90')
        self.assertEqual((row.bucket, row.subtype, row.counts_customer, row.include_in_profit),
                         ('cash', 'delivery', True, True))
        self.assertEqual(row.group, 'delivery')
        self.assertEqual(row.followup_rank, 1)

    def test_existing_row_not_reseeded(self):
        ChannelBucketMap.objects.create(person_type='10', channel='91', bucket='cash')
        info = channels.channel('10')
        self.assertFalse(info.known)
        self.assertEqual(ChannelBucketMap.objects.filter(person_type='10').count(), 1)

    def test_unknown_code_is_unclassified(self):
        info = channels.channel('77')
        self.assertEqual(info.group, 'unclassified')
        self.assertEqual(info.label, 'غير مصنف (77)')
        self.assertFalse(info.is_contract_sale)
        self.assertIsNone(info.followup_rank)
        self.assertEqual(info.bucket, 'exclude')
        self.assertFalse(info.known)

    def test_blank_code(self):
        info = channels.channel('')
        self.assertEqual(info.group, '')
        self.assertFalse(info.known)
        self.assertEqual(info.label, '')
        self.assertEqual(channels.channel(None).group, '')

    def test_rank_map_and_customer_channels_order(self):
        ranks = channels.rank_map()
        self.assertEqual(ranks['91'], 1)
        self.assertEqual(ranks['15'], 4)
        codes = [c.code for c in channels.customer_channels()]
        self.assertEqual(codes[:2], ['90', '91'])
        self.assertEqual(len(codes), 12)

    def test_cache_drops_on_save(self):
        self.assertEqual(channels.channel('30').group, 'permanent')
        row = ChannelBucketMap.objects.get(person_type='10', channel='30')
        row.group = 'other'
        row.save()
        self.assertEqual(channels.channel('30').group, 'other')

    def test_migration_update_only_keeps_bucket(self):
        mig = importlib.import_module('apps.forecasting.migrations.0014_channel_meaning')
        ChannelBucketMap.objects.create(person_type='10', channel='10',
                                        bucket='insurance', group='unclassified')
        mig.apply_channel_meanings(ChannelBucketMap)
        row = ChannelBucketMap.objects.get(person_type='10', channel='10')
        self.assertEqual(row.group, 'contract')
        self.assertTrue(row.is_contract_sale)
        self.assertEqual(row.followup_rank, 3)
        self.assertEqual(row.bucket, 'insurance')
        # update only — never creates the other codes
        self.assertEqual(ChannelBucketMap.objects.count(), 1)

    def test_ensure_channel_rows_creates_and_notifies_once(self):
        from django.contrib.auth.models import User
        from apps.notifications.models import Notification
        from apps.sync.models import SoftechPersonClassif
        from apps.users.models import StaffProfile

        admin = User.objects.create(username='codes_admin')
        sp = StaffProfile.objects.create(user=admin, role='admin')
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='77',
                                            ptclassifdescr='جديد')
        self.assertEqual(channels.ensure_channel_rows(), ['77'])
        row = ChannelBucketMap.objects.get(person_type='10', channel='77')
        self.assertEqual(row.group, 'unclassified')
        self.assertEqual(row.bucket, 'exclude')
        self.assertEqual(row.label, 'جديد')
        self.assertEqual(channels.ensure_channel_rows(), [])
        self.assertEqual(Notification.objects.filter(recipient=sp).count(), 1)

    def test_ensure_channel_rows_known_code_and_label_refresh(self):
        from apps.sync.models import SoftechPersonClassif
        ChannelBucketMap.objects.create(person_type='10', channel='91', bucket='cash',
                                        label='قديم')
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='91',
                                            ptclassifdescr='عميل نقدى')
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='15',
                                            ptclassifdescr='تأمين صحي')
        SoftechPersonClassif.objects.create(ptcode='01', ptclassifcode='15',
                                            ptclassifdescr='مورد')
        self.assertEqual(channels.ensure_channel_rows(notify=False), [])
        self.assertEqual(ChannelBucketMap.objects.get(person_type='10', channel='91').label,
                         'عميل نقدى')
        ins = ChannelBucketMap.objects.get(person_type='10', channel='15')
        self.assertEqual((ins.group, ins.bucket, ins.is_contract_sale), ('insurance', 'insurance', True))
        # other person types are never auto-inserted by the sync hook
        self.assertFalse(ChannelBucketMap.objects.filter(person_type='01').exists())

    def test_ensure_channel_rows_skips_non_customer_person_types(self):
        from apps.sync.models import SoftechPersonClassif
        SoftechPersonClassif.objects.create(ptcode='30', ptclassifcode='77', ptclassifdescr='x')
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='77', ptclassifdescr='y')
        channels.ensure_channel_rows(notify=False)
        self.assertFalse(ChannelBucketMap.objects.filter(person_type='30', channel='77').exists())
        self.assertTrue(ChannelBucketMap.objects.filter(person_type='10', channel='77').exists())


class SeedKpiConfigResetFlagTests(TestCase):
    def setUp(self):
        channels.invalidate_cache()
        from apps.sync.models import SoftechPersonClassif
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='91',
                                            ptclassifdescr='نقدي')
        # owner-edited row: both KPI and meaning fields differ from the defaults
        ChannelBucketMap.objects.create(
            person_type='10', channel='91', label='نقدي', bucket='credit', subtype='x',
            counts_customer=False, include_in_profit=False,
            group='vip', is_contract_sale=True, followup_rank=4)

    def tearDown(self):
        channels.invalidate_cache()

    def _run(self, *flags):
        from django.core.management import call_command
        from io import StringIO
        call_command('seed_kpi_config', *flags, stdout=StringIO())
        return ChannelBucketMap.objects.get(person_type='10', channel='91')

    def test_reset_defaults_touches_only_kpi_fields(self):
        from apps.audit.models import AuditLog
        row = self._run('--reset-defaults')
        d = channels.CHANNEL_DEFAULTS['91']
        for f in channels.KPI_FIELDS:
            self.assertEqual(getattr(row, f), d[f], f)
        self.assertEqual((row.group, row.is_contract_sale, row.followup_rank), ('vip', True, 4))
        self.assertFalse(AuditLog.objects.filter(action='code_map_changed').exists())

    def test_reset_meanings_touches_only_meaning_fields_and_audits(self):
        from apps.audit.models import AuditLog
        row = self._run('--reset-meanings')
        d = channels.CHANNEL_DEFAULTS['91']
        for f in channels.MEANING_FIELDS:
            self.assertEqual(getattr(row, f), d[f], f)
        self.assertEqual((row.bucket, row.subtype), ('credit', 'x'))
        logs = AuditLog.objects.filter(action='code_map_changed')
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs[0].note, 'seed_kpi_config --reset-meanings')
        self.assertIsNone(logs[0].user)
        # second run changes nothing → no new audit row
        self._run('--reset-meanings')
        self.assertEqual(AuditLog.objects.filter(action='code_map_changed').count(), 1)
