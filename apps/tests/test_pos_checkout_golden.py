"""
apps/tests/test_pos_checkout_golden.py — the D-18 golden-template comparison (golden.py) and the guards
of its command. Pure / no SOFTECH: the command itself is run only by a person with the owner's OK.
"""
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.pos_orders import golden


def _sale(**hdr):
    h = {'branchcode': '130', 'doccode': '115', 'docnumber': Decimal('7001'), 'docvalue': Decimal('275.40'),
         'docvaluepay': Decimal('275.40'), 'vf2': '', 'docdate': datetime(2026, 11, 19, 10, 0),
         'usercode': '123  ', 'fatstatuscode': '30'}
    h.update(hdr)
    return {
        'stktransm5': [h],
        'stktrans5': [{'itemcode': '94965', 'transqty': Decimal('1.00000'), 'transprice_total': Decimal('183.60')},
                      {'itemcode': '107295', 'transqty': Decimal('1'), 'transprice_total': Decimal('91.80')}],
        'branchesales5': [{'paymenttype': '30', 'paymentvalue': Decimal('275.40'), 'paymentsno': 1}],
        'companiesitems5': [], 'branchesalescc5': [],
    }


class GoldenDiffTests(SimpleTestCase):

    def test_identical_sale_passes_with_only_expected_differences(self):
        native = _sale()
        ours = _sale(docnumber=Decimal('7002'), vf2='POS98765', docdate=datetime(2026, 11, 19, 10, 5),
                     usercode='123')
        ours['stktrans5'].reverse()                       # row order does not matter
        ours['stktrans5'][0]['transqty'] = '1'            # numeric spelling does not matter
        ours['branchesales5'][0]['paymentsno'] = 2
        d = golden.diff_tables(native, ours)
        self.assertEqual(d['fails'], [])
        self.assertEqual(d['row_count'], [])
        self.assertEqual({c for _, _, c, _, _ in d['expected']}, {'docnumber', 'vf2', 'docdate', 'paymentsno'})
        self.assertIn('PASS', golden.report_markdown('cash 2 items', d))

    def test_a_money_difference_is_a_fail(self):
        ours = _sale(docvaluepay=Decimal('275.39'))
        d = golden.diff_tables(_sale(), ours)
        self.assertEqual([(t, c) for t, _, c, _, _ in d['fails']], [('stktransm5', 'docvaluepay')])
        self.assertIn('DIFFERENCES', golden.report_markdown('x', d))

    def test_a_missing_payment_row_is_reported(self):
        ours = _sale()
        ours['branchesales5'].append({'paymenttype': '10', 'paymentvalue': Decimal('1')})
        d = golden.diff_tables(_sale(), ours)
        self.assertEqual(d['row_count'], [('branchesales5', '', 'rows', 1, 2)])

    def test_column_present_on_one_side_only_is_compared(self):
        ours = _sale(personnewbal=Decimal('12'))
        d = golden.diff_tables(_sale(), ours)
        self.assertEqual([c for _, _, c, _, _ in d['fails']], ['personnewbal'])

    def test_ignore_list(self):
        ours = _sale(usercode='999')
        self.assertEqual(golden.diff_tables(_sale(), ours, also_ignore=['usercode'])['fails'], [])


class GoldenCommandGuardTests(SimpleTestCase):
    """The probe never runs by accident: it needs --confirm-rollback-probe, --native and the probes switch."""

    def test_refuses_without_confirm(self):
        with self.assertRaisesMessage(CommandError, '--confirm-rollback-probe'):
            call_command('pos_checkout_golden', basket='x.json', user='u', native=1)

    def test_refuses_without_native(self):
        with self.assertRaisesMessage(CommandError, '--native'):
            call_command('pos_checkout_golden', basket='x.json', user='u', confirm=True)

    def test_refuses_while_probes_switch_is_off(self):
        with mock.patch('apps.pos_orders.management.commands.pos_checkout_golden.Command._checkout') as ck:
            with self.assertRaises(CommandError):
                call_command('pos_checkout_golden', basket='x.json', user='u', native=1, confirm=True)
        ck.assert_not_called()
