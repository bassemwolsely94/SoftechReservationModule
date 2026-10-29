"""
SOFTECH write safety — every write is audited: who / what / when / before → after
(CLAUDE.md rule 8; Batch 2, P-16a: item / catalog writes).

Before: pricing classification (items.itemorigincode / itemstoreclassif), new lookup tiers,
offers channel A (items.posdiscp) and B (specialoffers), shortage flags (items) and the
vendor-code mapping (itemssuppliers) left no AuditLog row — at best a logger line, never the
before-value, often not even who.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.tests.factories import make_user



class _Cur:
    """SELECT readbacks return `row`; everything else is recorded."""

    def __init__(self, row=('9',)):
        self.row, self.sql = row, []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return self.row

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def begin(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _row(action):
    return AuditLog.objects.filter(action=action).order_by('-id').first()


class SoftechAuditTests(TestCase):

    def setUp(self):
        self.user, self.staff, _ = make_user('audit_admin', role='admin')

    # ── pricing (discount_approvals.alignment) ────────────────────────────────

    @override_settings(PRICING_SOFTECH_WRITE_ENABLED=True)
    def test_classification_change_records_who_and_the_old_class(self):
        from apps.catalog.models import Item
        from apps.discount_approvals import alignment
        it = Item.objects.create(softech_id='91001', name='X', origin_code='3', store_classif='1')
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(_Cur(('9',)))):
            err, res = alignment.apply_classification_changes(
                [{'item_id': it.id, 'origin_code': '9'}], '19', actor=self.user)
        self.assertIsNone(err)
        row = _row('softech_item_class_written')
        self.assertIsNotNone(row, 'classification written to SOFTECH with no audit row')
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.old_data['origin_code'], '3')
        self.assertEqual(row.new_data['origin_code'], '9')

    @override_settings(PRICING_SOFTECH_WRITE_ENABLED=True)
    def test_new_tier_records_who_and_what(self):
        from apps.discount_approvals import alignment
        cols = ['custdiscpcode', 'custdiscpname', 'usercode']
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(_Cur(None))), \
                mock.patch.object(alignment, '_tier_schema', return_value=(cols, ['1', 'a', '1'],
                                                                            'custdiscpcode', ['custdiscpname'])), \
                mock.patch.object(_Cur, 'fetchone', side_effect=[None, ('X',)]):
            err, res = alignment.create_new_tier('store', 'فئة 30%', '19', code='77', actor=self.user)
        self.assertIsNone(err)
        row = _row('softech_tier_created')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['code'], '77')

    # ── offers ────────────────────────────────────────────────────────────────

    @override_settings(POS_OFFERS_POSDISCP_WRITE_ENABLED=True)
    def test_posdiscp_write_records_each_item_before_and_after(self):
        from apps.offers import channel_a
        offer = mock.MagicMock(id=5, pk=5)
        plan = {'eligible': True, 'changes': [{'item_id': 1, 'softech_id': '91001', 'name': 'X',
                                               'current_posdiscp': 5.0, 'new_posdiscp': 10.0}]}
        self.staff.softech_user_id = '19'
        with mock.patch.object(channel_a, 'plan_posdiscp', return_value=plan), \
                mock.patch.object(channel_a, '_write_posdiscp',
                                  return_value=[{'softech_id': '91001', 'ok': True, 'posdiscp': 10.0}]):
            channel_a.apply_posdiscp(offer, actor=self.staff, commit=True, confirm=True)
        row = _row('softech_posdiscp_written')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.old_data, {'91001': 5.0})
        self.assertEqual(row.new_data, {'91001': 10.0})

    @override_settings(POS_OFFERS_PROMO_WRITE_ENABLED=True)
    def test_promo_write_records_the_offer_numbers(self):
        from apps.offers import channel_b
        offer = mock.MagicMock(id=6, pk=6)
        self.staff.softech_user_id = '19'
        with mock.patch.object(channel_b, 'plan_channel_b', return_value={'eligible': True, 'rows': [{}]}), \
                mock.patch.object(channel_b, '_write_specialoffer',
                                  return_value={'applied': True, 'written': [{'offersno': 6458, 'ok': True}]}):
            channel_b.apply_channel_b(offer, actor=self.staff, commit=True, confirm=True)
        row = _row('softech_promo_written')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['written'][0]['offersno'], 6458)

    # ── shortage flags ────────────────────────────────────────────────────────

    @override_settings(SHORTAGE_SOFTECH_WRITE_ENABLED=True)
    def test_shortage_flag_write_records_who_and_the_state(self):
        from apps.catalog.models import Item
        from apps.purchasing import shortage_writer
        it = Item.objects.create(softech_id='91002', name='Y')
        with mock.patch.object(shortage_writer, '_desired_state', return_value=(True, None)), \
                mock.patch.object(shortage_writer, '_write_softech'):
            shortage_writer.push_item(it, actor=self.user)
        row = _row('softech_shortage_written')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['on_shortage'], True)

    # ── vendor-code mapping ───────────────────────────────────────────────────

    @override_settings(INVOICE_SUPPLIER_ITEM_WRITE_ENABLED=True)
    def test_vendor_code_change_records_the_old_code(self):
        from apps.invoices import supplier_items as si
        conn = mock.MagicMock()
        with mock.patch.object(si, 'read_current', return_value='OLD1'), \
                mock.patch.object(si, '_all_others', return_value=[]), \
                mock.patch.object(si, '_run_batch_lastrow', return_value=(1, 0)):
            res = si.inject_mapping(conn, '3031', '91003', 'NEW1', commit=True, approved=True,
                                    actor=self.user)
        self.assertTrue(res['committed'])
        row = _row('softech_supplier_mapping_written')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.old_data['suppitemcode'], 'OLD1')
        self.assertEqual(row.new_data['suppitemcode'], 'NEW1')


class AuditHelperTests(TestCase):

    def test_a_lost_audit_row_is_logged_not_swallowed(self):
        from core import softech_audit
        with mock.patch.object(AuditLog, 'log', return_value=None), \
                self.assertLogs('core.softech_audit', level='ERROR'):
            softech_audit.audit_softech_write('softech_test', after={'x': 1})

    def test_actor_without_staff_profile_still_named(self):
        from django.contrib.auth.models import User
        from core import softech_audit
        u = User.objects.create(username='no_profile')
        softech_audit.audit_softech_write('softech_test', actor=u, after={'x': Decimal('1.5')})
        row = _row('softech_test')
        self.assertIsNone(row.user_id)
        self.assertEqual(row.extra['actor'], 'no_profile')
        self.assertEqual(row.new_data, {'x': '1.5'})
