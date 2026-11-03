"""
PBX CDR mirror (apps/pbx/cdr.py): classification of Issabel CDR rows, number
normalisation, and the PIC link — a shared number counts once, on the latest buyer.
Row shapes follow the live Issabel CDR; numbers and names are synthetic.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory
from apps.pbx import cdr
from apps.pbx.models import AgentExtension, CdrCall, CdrSyncRun, PBXBridgeStatus
from .factories import make_branch

GW = frozenset({'goip4', 'grandstream'})

INBOUND_ANSWERED = {
    'calldate': dt.datetime(2026, 10, 28, 9, 48, 56), 'src': '01000000301', 'dst': '101',
    'dcontext': 'ext-queues', 'channel': 'SIP/goip4-00000a01', 'dstchannel': 'SIP/15-00000a02',
    'lastapp': 'Queue', 'duration': 134, 'billsec': 134, 'disposition': 'ANSWERED',
    'uniqueid': '1700000001.101', 'recordingfile': '', 'cnam': '', 'dst_cnam': '',
}
INBOUND_ABANDONED = dict(INBOUND_ANSWERED, dstchannel='', billsec=14, duration=14,
                         uniqueid='1700000002.102')
INBOUND_VIA_BRANCH = dict(INBOUND_ANSWERED, dstchannel='Local/170@from-queue-00000a03;1',
                          uniqueid='1700000003.103')
OUTBOUND_ANSWERED = {
    'calldate': dt.datetime(2026, 10, 28, 9, 52, 46), 'src': '15', 'dst': '8201000000401',
    'dcontext': 'qlog-queuedial', 'channel': 'SIP/15-00000a04', 'dstchannel': 'SIP/goip4-00000a05',
    'lastapp': 'Dial', 'duration': 125, 'billsec': 96, 'disposition': 'ANSWERED',
    'uniqueid': '1700000004.104', 'recordingfile': 'out-15.wav',
    'cnam': 'Agent Fifteen -CC15', 'dst_cnam': '',
}
OUTBOUND_BUSY = dict(OUTBOUND_ANSWERED, dst='8201000000402', billsec=0, disposition='BUSY',
                     dcontext='from-internal', uniqueid='1700000005.105')
INTERNAL = {
    'calldate': dt.datetime(2026, 10, 28, 9, 21, 19), 'src': '56', 'dst': '85',
    'dcontext': 'from-internal', 'channel': 'SIP/56-00000a06', 'dstchannel': 'SIP/85-00000a07',
    'lastapp': 'Dial', 'duration': 495, 'billsec': 479, 'disposition': 'ANSWERED',
    'uniqueid': '1700000006.106',
}


class ClassifyTests(SimpleTestCase):

    def test_inbound_answered_by_agent(self):
        f = cdr.classify(INBOUND_ANSWERED, GW)
        self.assertEqual((f['direction'], f['status'], f['agent_ext'], f['queue']),
                         ('inbound', 'answered', '15', '101'))
        self.assertEqual(f['customer_number'], '01000000301')
        self.assertEqual(f['phone_key'], '01000000301')

    def test_inbound_without_agent_is_abandoned(self):
        self.assertEqual(cdr.classify(INBOUND_ABANDONED, GW)['status'], 'abandoned')

    def test_queue_member_behind_local_channel(self):
        self.assertEqual(cdr.classify(INBOUND_VIA_BRANCH, GW)['agent_ext'], '170')

    def test_outbound_strips_route_prefix_and_names_agent(self):
        f = cdr.classify(OUTBOUND_ANSWERED, GW)
        self.assertEqual((f['direction'], f['status'], f['agent_ext']), ('outbound', 'answered', '15'))
        self.assertEqual(f['customer_number'], '01000000401')
        self.assertEqual(f['agent_name'], 'Agent Fifteen -CC15')

    def test_outbound_busy(self):
        self.assertEqual(cdr.classify(OUTBOUND_BUSY, GW)['status'], 'busy')

    def test_internal_call_skipped(self):
        self.assertIsNone(cdr.classify(INTERNAL, GW))

    def test_transfer_leg_flagged(self):
        self.assertTrue(cdr.classify(dict(INBOUND_ANSWERED, dcontext='from-internal-xfer'), GW)['is_transfer'])

    def test_unknown_gateway_recognised_by_name(self):
        self.assertEqual(cdr.classify(dict(INBOUND_ANSWERED, channel='SIP/goip8-0001'))['direction'], 'inbound')

    def test_withheld_number(self):
        f = cdr.classify(dict(INBOUND_ANSWERED, src='unknown'), GW)
        self.assertEqual((f['customer_number'], f['phone_key']), ('', ''))

    def test_phone_key_forms(self):
        for raw in ('01000000401', '+201000000401', '00201000000401', '1000000401', '010-000-00401'):
            self.assertEqual(cdr.phone_key(raw), '01000000401', raw)
        self.assertEqual(cdr.phone_key('15'), '')

    def test_cdr_key_is_stable(self):
        self.assertEqual(cdr.cdr_key(OUTBOUND_ANSWERED), cdr.cdr_key(dict(OUTBOUND_ANSWERED)))
        self.assertNotEqual(cdr.cdr_key(OUTBOUND_ANSWERED), cdr.cdr_key(OUTBOUND_BUSY))


class LatestBuyerTests(SimpleTestCase):
    D = dt.date

    def test_latest_purchase_on_or_before_call_wins(self):
        dates = {'A': [self.D(2026, 9, 1)], 'B': [self.D(2026, 10, 1), self.D(2026, 11, 5)]}
        self.assertEqual(cdr.pick_latest_buyer(['A', 'B'], dates, self.D(2026, 10, 28)), ('B', 'shared_latest'))
        self.assertEqual(cdr.pick_latest_buyer(['A', 'B'], dates, self.D(2026, 9, 15)), ('A', 'shared_latest'))

    def test_same_day_purchase_counts(self):
        dates = {'A': [self.D(2026, 10, 28)], 'B': [self.D(2026, 10, 1)]}
        self.assertEqual(cdr.pick_latest_buyer(['A', 'B'], dates, self.D(2026, 10, 28))[0], 'A')

    def test_nobody_bought_before_then_first_buyer_after(self):
        dates = {'A': [self.D(2026, 12, 1)], 'B': [self.D(2026, 11, 3)]}
        self.assertEqual(cdr.pick_latest_buyer(['A', 'B'], dates, self.D(2026, 10, 28)), ('B', 'shared_next'))

    def test_never_bought(self):
        self.assertEqual(cdr.pick_latest_buyer(['A', 'B'], {}, self.D(2026, 10, 28)), ('', 'shared_unresolved'))


class StoreAndLinkTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.solo = Customer.objects.create(name='عميل منفرد', phone='01000000301', softech_pic='P-SOLO')
        self.mother = Customer.objects.create(name='الأم', phone='01000000401', softech_pic='P-MOM')
        self.son = Customer.objects.create(name='الابن', phone_alt='+201000000401', softech_pic='P-SON')
        Customer.objects.create(name='كود مدمج', phone='01000000401', softech_pic='P-OLD', merged_into_pic='P-MOM')
        Customer.objects.create(name='حساب', phone='01000000401', softech_pic='ACCT-1510',
                                is_account_placeholder=True)
        self._buy('P-MOM', dt.date(2026, 9, 1), 'i1')
        self._buy('P-SON', dt.date(2026, 10, 20), 'i2')
        self._buy('P-MOM', dt.date(2026, 10, 25), 'i3', doc_code='30')     # a return — not a purchase

    def _buy(self, pic, day, inv, doc_code='115'):
        PurchaseHistory.objects.create(
            customer=Customer.objects.get(softech_pic=pic), branch=self.branch, doc_code=doc_code,
            total_amount=Decimal('100'), softech_invoice_id=inv, softech_phcode=pic,
            invoice_date=timezone.make_aware(dt.datetime.combine(day, dt.time(0))))

    def _store(self, *rows):
        return cdr.store_rows(rows, cdr.PicResolver(), GW)

    def test_single_and_shared_numbers(self):
        stored, names = self._store(INBOUND_ANSWERED, OUTBOUND_ANSWERED, INTERNAL)
        self.assertEqual(stored, 2)
        solo = CdrCall.objects.get(direction='inbound')
        self.assertEqual((solo.pic, solo.pic_match, solo.customer_id, solo.shared_pics),
                         ('P-SOLO', 'single', self.solo.id, []))
        shared = CdrCall.objects.get(direction='outbound')
        # son bought 20 Oct, mother 1 Sep (her 25 Oct return is not a purchase) → the son
        self.assertEqual((shared.pic, shared.pic_match), ('P-SON', 'shared_latest'))
        self.assertEqual(shared.shared_pics, ['P-MOM', 'P-SON'])    # merged + placeholder codes excluded
        self.assertEqual(names[('15', 'Agent Fifteen -CC15')], 1)

    def test_upsert_is_idempotent(self):
        self._store(INBOUND_ANSWERED, OUTBOUND_ANSWERED)
        self._store(INBOUND_ANSWERED, OUTBOUND_ANSWERED)
        self.assertEqual(CdrCall.objects.count(), 2)

    def test_call_time_is_cairo_local(self):
        self._store(INBOUND_ANSWERED)
        self.assertEqual(timezone.localtime(CdrCall.objects.get().call_at).strftime('%Y-%m-%d %H:%M'),
                         '2026-10-28 09:48')

    def test_unknown_number(self):
        self._store(dict(INBOUND_ANSWERED, src='01000000999'))
        self.assertEqual(CdrCall.objects.get().pic_match, 'none')

    def test_relink_picks_up_new_customer(self):
        self._store(dict(INBOUND_ANSWERED, src='01000000999'))
        Customer.objects.create(name='جديد', phone='01000000999', softech_pic='P-NEW')
        self.assertEqual(cdr.relink_all(), 1)
        self.assertEqual(CdrCall.objects.get().pic, 'P-NEW')
        self.assertEqual(cdr.relink_all(), 0)

    def test_resolve_number_for_live_calls(self):
        pic, cid, match, _ = cdr.resolve_number('01000000401', timezone.make_aware(dt.datetime(2026, 9, 10)))
        self.assertEqual((pic, cid, match), ('P-MOM', self.mother.id, 'shared_latest'))

    def test_sync_records_run_and_pbx_names(self):
        AgentExtension.objects.create(extension='15', extension_type='agent')
        with mock.patch.object(cdr, '_fetch', return_value=[OUTBOUND_ANSWERED, INTERNAL]):
            run = cdr.sync_cdr(since=dt.datetime(2026, 10, 28), until=dt.datetime(2026, 10, 29))
        self.assertEqual((run.status, run.fetched, run.stored), ('success', 2, 1))
        self.assertEqual(AgentExtension.objects.get(extension='15').pbx_name, 'Agent Fifteen -CC15')

    def test_sync_failure_is_logged_not_raised(self):
        with mock.patch.object(cdr, '_fetch', side_effect=OSError('PBX unreachable')):
            run = cdr.sync_cdr(since=dt.datetime(2026, 10, 28), until=dt.datetime(2026, 10, 29))
        self.assertEqual(run.status, 'failed')
        self.assertIn('unreachable', CdrSyncRun.objects.get().error)


class BridgeSilenceTests(TestCase):

    def _call(self, minutes_ago):
        CdrCall.objects.create(cdr_key=f'k{minutes_ago}', unique_id='u', direction='inbound', status='answered',
                               call_at=timezone.now() - dt.timedelta(minutes=minutes_ago))

    def test_quiet_pbx_raises_nothing(self):
        self._call(120)
        self.assertFalse(cdr.bridge_silent_while_pbx_busy())

    def test_calls_without_bridge_events_alarm(self):
        self._call(5)
        PBXBridgeStatus.record(state='connected', last_event_at=timezone.now() - dt.timedelta(hours=2))
        self.assertTrue(cdr.bridge_silent_while_pbx_busy())

    def test_bridge_hearing_calls_is_fine(self):
        self._call(5)
        PBXBridgeStatus.record(state='connected', last_event_at=timezone.now() - dt.timedelta(minutes=1))
        self.assertFalse(cdr.bridge_silent_while_pbx_busy())
