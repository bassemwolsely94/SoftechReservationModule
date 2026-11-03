"""
Egyptian phone normalisation for PBX calls <-> PIC matching (apps/pbx/cdr.py national_number /
phone_key / inbound_number / outbound_number / renormalise_pbx_numbers). Synthetic numbers only.
"""
import datetime as dt
import random
from unittest import mock
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.customers.models import Customer
from apps.pbx import cdr
from apps.pbx.models import AgentExtension, CdrCall

GW = frozenset({'goip4', 'grandstream'})
GW_META = {'goip4': {'prefix': '0', 'suffix': ''}, 'grandstream': {'prefix': '', 'suffix': ''}}


def row(src, dst, channel='SIP/goip4-0001', dstchannel='SIP/15-0002', uid='1.1', **kw):
    base = {'calldate': dt.datetime(2026, 10, 28, 9, 0, 0), 'src': src, 'dst': dst,
            'dcontext': 'ext-queues', 'channel': channel, 'dstchannel': dstchannel,
            'lastapp': 'Queue', 'duration': 10, 'billsec': 10, 'disposition': 'ANSWERED',
            'uniqueid': uid, 'recordingfile': '', 'cnam': '', 'dst_cnam': ''}
    base.update(kw)
    return base


class NationalNumberTests(SimpleTestCase):

    def test_mobile_forms(self):
        for raw in ('01000000010', '1000000010', '+201000000010', '00201000000010',
                    '201000000010', '010-0000-0010'):
            self.assertEqual(cdr.national_number(raw), '01000000010', raw)

    def test_cairo_landline_forms(self):
        for raw in ('24842067', '0224842067', '224842067', '+20224842067', '0020224842067'):
            self.assertEqual(cdr.national_number(raw), '0224842067', raw)

    def test_22_local(self):
        self.assertEqual(cdr.national_number('22290016'), '0222290016')

    def test_other_governorate_kept(self):
        self.assertEqual(cdr.national_number('0482123456'), '0482123456')

    def test_junk_and_short_codes_as_is(self):
        self.assertEqual(cdr.national_number('15'), '15')
        self.assertEqual(cdr.national_number('anonymous'), '')

    def test_twelve_digit_typo_kept(self):
        self.assertEqual(cdr.national_number('012000000066'), '012000000066')

    def test_every_line_prefix_both_forms(self):
        for p in cdr.LINE_PREFIXES:
            self.assertEqual(cdr.split_line_prefix(p + '01000000010'), (p, '01000000010'), p)
            self.assertEqual(cdr.national_number(p + '01000000010'), '01000000010', p)
            self.assertEqual(cdr.national_number(p + '1000000010'), '01000000010', p)
            self.assertEqual(cdr.national_number(p + '0224842067'), '0224842067', p)
            self.assertEqual(cdr.national_number(p + '24842067'), '0224842067', p)
            self.assertEqual(cdr.national_number(p + '012000000066'), '012000000066', p)

    def test_prefix_with_short_remainder_is_short_code(self):
        self.assertEqual(cdr.split_line_prefix('911234'), ('91', '1234'))
        self.assertEqual(cdr.national_number('911234'), '1234')
        self.assertEqual(cdr.phone_key('911234'), '')

    def test_valid_national_has_no_prefix(self):
        self.assertEqual(cdr.split_line_prefix('01000000010'), ('', '01000000010'))
        self.assertEqual(cdr.split_line_prefix('24842067'), ('', '24842067'))


class PhoneKeyTests(SimpleTestCase):

    def test_keys_agree_across_forms(self):
        self.assertEqual({cdr.phone_key(x) for x in ('01000000010', '1000000010', '+201000000010')},
                         {'01000000010'})
        self.assertEqual({cdr.phone_key(x) for x in ('0224842067', '24842067')}, {'0224842067'})

    def test_too_short(self):
        self.assertEqual(cdr.phone_key('15'), '')
        self.assertEqual(cdr.phone_key(''), '')


class ClassifyNumberTests(SimpleTestCase):

    def inbound(self, src, **kw):
        return cdr.classify(row(src, '101', **kw), GW, GW_META)

    def test_goip4_keeps_real_leading_zero(self):
        f = self.inbound('01551000018')
        self.assertEqual((f['customer_number'], f['phone_key']), ('01551000018', '01551000018'))

    def test_goip4_ten_digit_gets_zero(self):
        self.assertEqual(self.inbound('1224747070')['customer_number'], '01224747070')

    def test_international_forms(self):
        for src in ('+201224747070', '00201224747070', '201224747070'):
            self.assertEqual(self.inbound(src)['customer_number'], '01224747070', src)

    def test_genuine_added_prefix_still_stripped(self):
        meta = {'grandstream': {'prefix': '7', 'suffix': ''}}
        f = cdr.classify(row('70224842067', '101', channel='SIP/grandstream-0001'), GW, meta)
        self.assertEqual(f['customer_number'], '0224842067')

    def test_inbound_landline_nine_digits(self):
        f = self.inbound('222900016', channel='SIP/grandstream-0001')
        self.assertEqual(f['customer_number'], '0222900016')

    def test_outbound_route_prefixed_mobile(self):
        f = cdr.classify(row('15', '8301200000066', channel='SIP/15-1', dstchannel='SIP/goip4-2',
                             dcontext='from-internal'), GW, GW_META)
        self.assertEqual(f['customer_number'], '01200000066')
        self.assertEqual(f['line_prefix'], '83')

    def test_outbound_long_typo_prefix_stripped(self):
        f = cdr.classify(row('15', '83012000000066', channel='SIP/15-1', dstchannel='SIP/goip4-2'), GW, GW_META)
        self.assertEqual(f['customer_number'], '012000000066')
        self.assertEqual(f['line_prefix'], '83')

    def test_outbound_cairo_local_and_nine_dial(self):
        def o(dst):
            return cdr.classify(row('15', dst, channel='SIP/15-1', dstchannel='SIP/grandstream-2'), GW, GW_META)
        self.assertEqual(o('24842067')['customer_number'], '0224842067')
        f = o('9111234')
        self.assertEqual((f['customer_number'], f['phone_key'], f['line_prefix']), ('11234', '', '91'))
        self.assertEqual(o('9101000000010')['customer_number'], '01000000010')

    def test_inbound_line_prefix_recorded(self):
        f = self.inbound('8101000000010')
        self.assertEqual((f['customer_number'], f['line_prefix']), ('01000000010', '81'))
        self.assertEqual(self.inbound('01000000010')['line_prefix'], '')

    def test_inbound_prefix_all_families(self):
        for p in cdr.LINE_PREFIXES:
            f = self.inbound(p + '24842067', channel='SIP/grandstream-0001')
            self.assertEqual((f['customer_number'], f['line_prefix']), ('0224842067', p), p)

    def test_outbound_prefix_all_families(self):
        for p in cdr.LINE_PREFIXES:
            f = cdr.classify(row('15', p + '01000000010', channel='SIP/15-1', dstchannel='SIP/goip4-2'),
                             GW, GW_META)
            self.assertEqual((f['customer_number'], f['line_prefix']), ('01000000010', p), p)


class NationalZeroTests(SimpleTestCase):

    def inbound(self, src):
        return cdr.classify(row(src, '101'), GW, GW_META)['customer_number']

    def test_goip4_keeps_zero_of_non_cairo_landlines(self):
        for src in ('031234567', '0842123456', '0931234567', '0402123456', '0224842067'):
            self.assertEqual(self.inbound(src), src, src)

    def test_alexandria_distinct_from_cairo(self):
        self.assertNotEqual(cdr.phone_key('031234567'), cdr.phone_key('31234567'))
        self.assertEqual(cdr.phone_key('031234567'), '031234567')

    def test_phone_key_idempotent_over_many_forms(self):
        forms = ['01000000010', '1000000010', '+201000000010', '24842067', '0224842067', '224842067',
                 '031234567', '0842123456', '0931234567', '0402123456', '012000000066', '911234',
                 '8301000000010', '9101000000010', '9124842067', '15', '', '0020224842067', '482123456']
        for x in forms:
            k = cdr.phone_key(x)
            self.assertEqual(cdr.phone_key(k), k, x)


class FuzzIdempotenceTests(SimpleTestCase):

    def test_phone_key_idempotent_for_random_digit_strings(self):
        rng = random.Random(20261103)
        pool = '0123456789'
        starts = ['', '0', '00', '20', '0020', '+20', '81', '83', '91', '95', '9', '8', '2', '1', '01']
        for _ in range(20000):
            x = rng.choice(starts) + ''.join(rng.choice(pool) for _ in range(rng.randint(0, 13)))
            k = cdr.phone_key(x)
            self.assertEqual(cdr.phone_key(k), k, x)

    def test_known_junk_forms(self):
        for x in ('901224731833', '88159655105', '08447300'):
            k = cdr.phone_key(x)
            self.assertEqual(cdr.phone_key(k), k, x)


class LinkingAndBridgeTests(TestCase):

    def test_bridge_normalize(self):
        from apps.pbx import ami_bridge
        patcher = mock.patch.object(ami_bridge, '_gateway_meta', {'goip4': {'prefix': '0', 'suffix': ''}})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(ami_bridge._normalize_caller_num('1224747070', 'goip4'), '01224747070')
        self.assertEqual(ami_bridge._normalize_caller_num('031234567', 'goip4'), '031234567')
        self.assertEqual(ami_bridge._normalize_caller_num('911234', 'goip4'), '1234')

    def test_agent_save_matches_session_by_key(self):
        from apps.pbx.linking import find_session_for_agent_call
        from apps.pbx.models import CallSession
        from apps.users.models import StaffProfile
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user(username='lk1', password='x')
        prof = StaffProfile.objects.get(user=u) if StaffProfile.objects.filter(user=u).exists()             else StaffProfile.objects.create(user=u, role='call_center')
        ext = AgentExtension.objects.create(extension='15', staff=prof)
        s = CallSession.objects.create(unique_id='lk-1', direction='outbound', state='ringing',
                                       caller_number='0224842067', agent=ext, started_at=timezone.now())
        self.assertEqual(find_session_for_agent_call(prof, '24842067'), s)
        self.assertEqual(find_session_for_agent_call(prof, '0224842067'), s)
        self.assertIsNone(find_session_for_agent_call(prof, '24842099'))

    def test_lookup_tail_empty_for_short_or_digitless(self):
        for x in ('anonymous', 'unknown', '', '15', '1234', '911234'):
            self.assertEqual(cdr.lookup_tail(x), '', x)

    def test_calllog_short_or_withheld_attaches_no_customer(self):
        from apps.callcenter.models import CallLog
        Customer.objects.create(name='Z', phone='01000000010', softech_pic='P-Z')
        for ph in ('anonymous', '15', '1234'):
            log = CallLog(phone_number=ph)
            log._try_match_customer()
            self.assertIsNone(log.customer, ph)
            self.assertEqual(log.caller_name, '')

    def test_calllog_exact_key_confirm(self):
        from apps.callcenter.models import CallLog
        Customer.objects.create(name='Mob', phone='01024842067', softech_pic='P-M')
        land = Customer.objects.create(name='Land', phone='24842067', softech_pic='P-L')
        log = CallLog(phone_number='0224842067')
        log._try_match_customer()
        self.assertEqual(log.customer, land)
        Customer.objects.filter(pk=land.pk).delete()
        log2 = CallLog(phone_number='0224842067')
        log2._try_match_customer()
        self.assertIsNone(log2.customer)       # the mobile sharing the last 8 digits is not a match

    def test_lookup_endpoint_short_input_returns_nothing(self):
        from apps.callcenter.models import CallLog
        from .factories import make_call_center
        Customer.objects.create(name='Z', phone='01000000010', softech_pic='P-Z')
        _, _, c = make_call_center()
        for ph in ('15', 'anonymous', '1234'):
            r = c.get('/api/callcenter/calls/lookup/', {'phone': ph})
            self.assertEqual(r.status_code, 200, (ph, r.content[:200]))
            self.assertEqual(r.json()['customers'], [], ph)
            self.assertEqual(r.json()['recent_calls'], [], ph)

    def test_lookup_tail(self):
        self.assertEqual(cdr.lookup_tail('0224842067'), '24842067')
        self.assertEqual(cdr.lookup_tail('01000000010'), '000000010')


class MatchingTests(TestCase):

    def setUp(self):
        Customer.objects.create(name='A', phone='01000000010', softech_pic='P-1')
        Customer.objects.create(name='B', phone='0224842067', softech_pic='P-2')
        Customer.objects.create(name='C', phone='24842068', softech_pic='P-3')
        Customer.objects.create(name='D', phone='1000000011', softech_pic='P-4')

    def test_resolver_matches_all_forms(self):
        for num, pic in (('1000000010', 'P-1'), ('01000000010', 'P-1'), ('+201000000010', 'P-1'),
                         ('24842067', 'P-2'), ('0224842067', 'P-2'),
                         ('24842068', 'P-3'), ('0224842068', 'P-3'),
                         ('01000000011', 'P-4')):
            got = cdr.resolve_number(num)
            self.assertEqual((num, got[0], got[2]), (num, pic, 'single'))

    def test_resolver_bulk(self):
        r = cdr.PicResolver()
        self.assertEqual(r.resolve(cdr.phone_key('24842067'), dt.date(2026, 10, 1))[0], 'P-2')
        self.assertEqual(r.resolve(cdr.phone_key('1000000011'), dt.date(2026, 10, 1))[0], 'P-4')

    def test_pic_search_by_phone(self):
        from apps.pic_analytics.models import PicDayFact
        from apps.pic_analytics.queries.pics import _search
        for pic in ('P-1', 'P-2', 'P-3'):
            PicDayFact.objects.create(pic=pic, day=dt.date(2026, 10, 1), invoices=1)
        for q, want in (('1000000010', {'P-1'}), ('01000000010', {'P-1'}), ('24842067', {'P-2'}),
                        ('0224842067', {'P-2'}), ('0224842068', {'P-3'})):
            got = set(_search(PicDayFact.objects.all(), q).values_list('pic', flat=True))
            self.assertEqual(got, want, q)

    def test_callback_matching_across_forms(self):
        from apps.callcenter.models import CallLog
        from apps.pic_analytics.queries.missed import callback_dues
        at = timezone.make_aware(dt.datetime(2026, 10, 28, 9, 0))
        call = CdrCall.objects.create(
            cdr_key='kc', unique_id='1', call_at=at, direction='inbound', status='abandoned',
            customer_number='24842067', phone_key=cdr.phone_key('24842067'))
        for ph in ('0224842067',):
            CallLog.objects.create(phone_number=ph, status='callback', callback_due=at + dt.timedelta(hours=2))
        self.assertIn(call.id, callback_dues([call]))


class RenormaliseCommandTests(TestCase):

    def setUp(self):
        Customer.objects.create(name='A', phone='01000000010', softech_pic='P-1')
        Customer.objects.create(name='B', phone='0224842067', softech_pic='P-2')
        at = timezone.make_aware(dt.datetime(2026, 10, 28, 9, 0))
        self.old = CdrCall.objects.create(
            cdr_key='k1', unique_id='1', call_at=at, direction='inbound', status='answered',
            customer_number='1000000010', phone_key='1000000010', src='01000000010', dst='101',
            channel='SIP/goip4-0001', dstchannel='SIP/15-0002', pic_match='none')
        self.land = CdrCall.objects.create(
            cdr_key='k2', unique_id='2', call_at=at, direction='outbound', status='answered',
            customer_number='24842067', phone_key='24842067', src='15', dst='24842067',
            channel='SIP/15-0002', dstchannel='SIP/grandstream-0001', pic_match='none')
        AgentExtension.objects.create(extension='goip4', extension_type=AgentExtension.TYPE_GATEWAY,
                                      call_prefix='0')

    def run_cmd(self, *args):
        out = StringIO()
        call_command('renormalise_pbx_numbers', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        self.run_cmd()
        self.old.refresh_from_db()
        self.assertEqual(self.old.phone_key, '1000000010')

    def test_commit_renormalises_and_relinks_idempotently(self):
        self.run_cmd('--commit')
        self.old.refresh_from_db()
        self.land.refresh_from_db()
        self.assertEqual((self.old.customer_number, self.old.phone_key, self.old.pic, self.old.pic_match),
                         ('01000000010', '01000000010', 'P-1', 'single'))
        self.assertEqual((self.land.customer_number, self.land.phone_key, self.land.pic),
                         ('0224842067', '0224842067', 'P-2'))
        self.assertIn('changed 0', self.run_cmd('--commit'))

    def test_label_collisions_keep_newest_and_report(self):
        from apps.pic_analytics.models import PhoneLabel
        PhoneLabel.objects.create(phone_key='1000000010', label='spam')
        PhoneLabel.objects.create(phone_key='01000000010', label='staff')
        out = self.run_cmd('--commit')
        self.assertIn('collision', out)
        self.assertEqual(list(PhoneLabel.objects.values_list('phone_key', 'label')), [('01000000010', 'staff')])

    def test_phone_labels_follow_new_key(self):
        from apps.pic_analytics.models import PhoneLabel
        PhoneLabel.objects.create(phone_key='1000000010', label='spam')
        self.run_cmd('--commit')
        self.assertTrue(PhoneLabel.objects.filter(phone_key='01000000010').exists())


class RenormaliseLabelKeyTests(TestCase):
    """Labels follow their calls' recomputed key, including non-Cairo landlines whose stored key lost the 0."""

    def setUp(self):
        at = timezone.make_aware(dt.datetime(2026, 10, 28, 9, 0))
        AgentExtension.objects.create(extension='goip4', extension_type=AgentExtension.TYPE_GATEWAY, call_prefix='0')
        for i, (raw, oldkey) in enumerate([('034812345', '34812345'), ('0402345678', '402345678'),
                                           ('01000000010', '1000000010'), ('0224842067', '24842067')]):
            CdrCall.objects.create(
                cdr_key=f'lk{i}', unique_id=str(i), call_at=at, direction='inbound', status='answered',
                customer_number=oldkey, phone_key=oldkey, src=raw, dst='101',
                channel='SIP/goip4-0001', dstchannel='SIP/15-0002', pic_match='none')
        from apps.pic_analytics.models import PhoneLabel
        for k in ('34812345', '402345678', '1000000010', '24842067'):
            PhoneLabel.objects.create(phone_key=k, label='staff')

    def test_labels_stay_linked_to_their_calls(self):
        from apps.pic_analytics.models import PhoneLabel
        call_command('renormalise_pbx_numbers', '--commit', stdout=StringIO())
        call_keys = set(CdrCall.objects.values_list('phone_key', flat=True))
        label_keys = set(PhoneLabel.objects.values_list('phone_key', flat=True))
        self.assertEqual(call_keys, label_keys)
        self.assertEqual(len(label_keys), 4)

    def test_collision_drop_is_audited(self):
        from apps.audit.models import AuditLog
        from apps.pic_analytics.models import PhoneLabel
        PhoneLabel.objects.create(phone_key='01000000010', label='spam', note='n1')
        call_command('renormalise_pbx_numbers', '--commit', stdout=StringIO())
        keep = PhoneLabel.objects.get(phone_key='01000000010')
        e = AuditLog.objects.get(action='pbx_phone_label_merged')
        self.assertEqual(e.extra['old_key'], '1000000010')
        self.assertEqual(e.extra['new_key'], '01000000010')
        self.assertEqual(e.extra['label'], 'staff')
        self.assertEqual(e.extra['merged_into'], keep.pk)
        self.assertEqual(e.extra['actor'], 'system:renormalise_pbx_numbers')

    def test_arabic_indic_digits_normalise(self):
        from apps.pbx.cdr import phone_key
        ar = '01000000010'.translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))
        ext = '01000000010'.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        self.assertEqual(phone_key(ar), '01000000010')
        self.assertEqual(phone_key(ext), '01000000010')
