"""PIC Analytics Task 11 — new numbers, labels and conversion (doc 33 §8)."""
from datetime import date as D

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.pbx.cdr import relink_all
from apps.pic_analytics.models import PhoneLabel
from apps.pic_analytics.queries.numbers import conversions, label_number, new_numbers
from apps.tests.test_pic_queries_calls import CallBase


class NewNumbersTests(CallBase):

    def test_aggregates_one_row_per_number(self):
        self.call(D(2026, 10, 5), '', 'inbound', 'answered', key='1000000050', hh=9, billable=100, ext='10')
        self.call(D(2026, 10, 6), '', 'inbound', 'abandoned', key='1000000050', hh=9, ext='')
        self.call(D(2026, 10, 7), '', 'outbound', 'answered', key='1000000050', hh=9, billable=20, ext='11')
        self.call(D(2026, 10, 8), 'N1', 'inbound', 'answered', key='1000000001')      # a PIC number: excluded
        res = new_numbers(self.flt(), self.mgmt, 1)
        self.assertEqual(res['count'], 1)
        r = res['rows'][0]
        self.assertEqual((r['phone_key'], r['calls_in'], r['calls_out'], r['answered'], r['missed']),
                         ('1000000050', 2, 1, 2, 1))
        self.assertEqual((r['talk_seconds'], r['last_agent']['agent_ext']), (120, '11'))
        self.assertIn('•', r['number'])
        self.assertLess(r['first_call'], r['last_call'])

    def test_no_number_and_shared_not_new(self):
        self.call(D(2026, 10, 5), '', key='', match='no_number')
        self.call(D(2026, 10, 5), '', key='1000000051', match='shared_unresolved')
        self.assertEqual(new_numbers(self.flt(), self.mgmt, 1)['count'], 0)

    def test_labelled_numbers_excluded(self):
        self.call(D(2026, 10, 5), '', key='1000000052')
        self.call(D(2026, 10, 5), '', key='1000000053')
        label_number('1000000052', 'staff', '', self.admin_p)
        res = new_numbers(self.flt(), self.mgmt, 1)
        self.assertEqual([r['phone_key'] for r in res['rows']], ['1000000053'])

    def test_mobile_vs_landline(self):
        self.call(D(2026, 10, 5), '', key='1000000054')
        self.call(D(2026, 10, 5), '', key='23456789')
        kinds = {r['phone_key']: r['kind'] for r in new_numbers(self.flt(), self.mgmt, 1)['rows']}
        self.assertEqual(kinds, {'1000000054': 'mobile', '23456789': 'landline'})

    def test_management_only(self):
        with self.assertRaises(PermissionError):
            new_numbers(self.flt(), self.mgr, 1)
        with self.assertRaises(PermissionError):
            conversions(self.flt(), self.mgr)


class ConversionTests(CallBase):

    def test_conversion_after_new_pic_relinked(self):
        self.call(D(2026, 9, 20), '', key='1000000060')
        self.call(D(2026, 10, 2), '', key='1000000060')
        self.assertEqual(new_numbers(self.flt(), self.mgmt, 1)['count'], 1)
        Customer.objects.create(name='جديد٢', softech_pic='X9', softech_id='Q-X9', phone='01000000060',
                                softech_created_at=D(2026, 10, 10))
        relink_all()
        self.assertEqual(new_numbers(self.flt(), self.mgmt, 1)['count'], 0)
        c = conversions(self.flt(), self.mgmt)
        self.assertEqual((c['became_pic'], c['became_pic_and_bought']), (1, 0))
        self.assertEqual(c['rows'][0]['pic'], 'X9')
        self.assertEqual(c['rows'][0]['first_call'][:10], '2026-09-20')
        self.assertFalse(c['rows'][0]['bought'])
        self.fact('X9', D(2026, 10, 12), self.ba, 1, 50, 30, 1, {'10': 50})
        c = conversions(self.flt(), self.mgmt)
        self.assertEqual((c['became_pic'], c['became_pic_and_bought']), (1, 1))
        self.assertTrue(c['rows'][0]['bought'])

    def test_call_after_creation_or_outside_period_not_counted(self):
        Customer.objects.create(name='ق', softech_pic='X8', softech_id='Q-X8', phone='01000000061',
                                softech_created_at=D(2026, 10, 10))
        Customer.objects.create(name='ك', softech_pic='X7', softech_id='Q-X7', phone='01000000062',
                                softech_created_at=D(2026, 8, 1))
        Customer.objects.create(name='ل', softech_pic='X6', softech_id='Q-X6', phone='01000000063')
        self.call(D(2026, 10, 15), 'X8', key='1000000061')       # only after creation
        self.call(D(2026, 7, 15), 'X7', key='1000000062')        # created outside the period
        self.call(D(2026, 7, 15), 'X6', key='1000000063')        # no created date -> skipped
        self.assertEqual(conversions(self.flt(), self.mgmt)['became_pic'], 0)


class LabelTests(CallBase):

    def test_label_audited(self):
        pl = label_number('1000000070', 'supplier', 'مورد أدوية', self.admin_p)
        self.assertEqual((pl.label, pl.created_by), ('supplier', self.admin_p))
        label_number('1000000070', 'spam', '', self.admin_p)
        self.assertEqual(PhoneLabel.objects.filter(phone_key='1000000070').count(), 1)
        logs = list(AuditLog.objects.filter(action='pic_phone_labelled').order_by('id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[1].old_data['label'], 'supplier')
        self.assertEqual(logs[1].new_data['label'], 'spam')

    def test_label_validation(self):
        with self.assertRaises(ValueError):
            label_number('1000000070', 'bogus', '', self.admin_p)
        with self.assertRaises(ValueError):
            label_number('', 'staff', '', self.admin_p)
        with self.assertRaises(ValueError):
            label_number('1' * 16, 'staff', '', self.admin_p)
