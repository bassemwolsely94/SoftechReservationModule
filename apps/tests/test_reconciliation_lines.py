"""
apps/tests/test_reconciliation_lines.py

On-demand invoice item lines (recon_lines + /invoices/<id>/lines/) read from a
FAKE SOFTECH connection, and the invoice notes / voucher serials in the API.
"""
import datetime
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase

from apps.catalog.models import Item
from apps.finance import recon_lines
from apps.finance.models import ReconParty, APInvoice, Payment, MatchCandidate
from .factories import make_admin

BASE = '/api/finance/reconciliation'


class _Cur:
    description = [('itemcode',), ('transqty',), ('transprice',), ('pharmacydiscp',), ('transprice_total',),
                   ('itemexpirydate',), ('itemsaleprice',), ('storecode',), ('r_docnumber',)]

    def __init__(self):
        self.sql = None

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return [('128534', 1.0, 48.0, 20.0, 48.0, datetime.datetime(2028, 1, 11), 60.0, '160', 0),
                ('119902', 1.0, 160.0, 100.0, 0.0, datetime.datetime(2028, 1, 1), 188.0, '160', 0)]


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def cursor(self):
        return self.cur

    def close(self):
        pass


class LinesTests(TestCase):

    def setUp(self):
        recon_lines._CACHE.clear()
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد')
        self.inv = APInvoice.objects.create(party=self.party, branchcode='160', doccode='10', docnumber='25905',
                                            docdate=date(2026, 1, 5), doc_value=D('208'), doc_value_pay=D('0'),
                                            party_type='supplier', comments='بديل زيسروماكس')
        Item.objects.create(softech_id='128534', name='DOLIPRANE 1000MG')

    def test_lines_read_with_names_free_flag_and_dirty_read(self):
        conn = _Conn()
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            d = recon_lines.invoice_lines(self.inv)
        self.assertIn('AT ISOLATION 0', conn.cur.sql)                     # never queues behind locks
        self.assertIn("docnumber=25905", conn.cur.sql)
        self.assertEqual(d['count'], 2)
        self.assertEqual(d['lines'][0]['name'], 'DOLIPRANE 1000MG')
        self.assertTrue(d['lines'][1]['is_free'])                           # pharmacydiscp = 100 → FOC
        self.assertEqual(d['comments'], 'بديل زيسروماكس')

    def test_endpoint_and_notes_in_candidate_api(self):
        _, _, client = make_admin('lines_admin')
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn()):
            r = client.get(f'{BASE}/invoices/{self.inv.id}/lines/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['count'], 2)
        pay = Payment.objects.create(party=self.party, branchcode='160', cheqsno=58996, cheqno='25905',
                                     ourcheqsno=4410, direction='out', party_type='supplier',
                                     voucher_date=date(2026, 1, 6), amount=D('208'), note='ف 25905')
        MatchCandidate.objects.create(party=self.party, invoice=self.inv, payment=pay, proposed_amount=D('208'))
        c = client.get(f'{BASE}/candidates/').json()['results'][0]
        self.assertEqual(c['invoice_detail']['comments'], 'بديل زيسروماكس')
        self.assertEqual((c['payment_detail']['cheqno'], c['payment_detail']['ourcheqsno'],
                          c['payment_detail']['note']), ('25905', 4410, 'ف 25905'))

    def test_sync_error_maps_to_503(self):
        _, _, client = make_admin('lines_admin2')
        with mock.patch('config.sybase.get_sybase_connection', side_effect=RuntimeError('HQ down')):
            r = client.get(f'{BASE}/invoices/{self.inv.id}/lines/')
        self.assertEqual(r.status_code, 503)
