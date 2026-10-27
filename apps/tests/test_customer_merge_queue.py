"""B7 merge queue — duplicate codes from HQ (read-only, fake connection) + maker-checker review."""
import datetime as dt

from django.test import TestCase

from apps.customers import duplicates as DUP
from apps.customers.models import Customer, MergeCandidate as MC

D = dt.datetime
P1, P2 = '01001234567', '01009876543'
# phcode, name, mobileno, branchcustphone, addr, street, home, floor, apt, custdate, status, lock, died, points, branch
HQ = [
    ('07HD1', 'Ahmed Ali Hassan', P1, '', 'x', 'Nile st', '5', '2', '7', D(2020, 1, 1), '1', 0, 0, 1, '160'),
    ('07HD2', 'Ahmed  Ali Hassan', '+2' + P1, '', 'y', 'Nile st', '5', '2', '7', D(2022, 1, 1), '1', 0, 0, 1, '160'),
    ('07HD3', 'Ahmed Ali', P1, '', '', '', '', '', '', D(2023, 1, 1), '1', 0, 0, 1, '160'),          # similar name
    ('07HD4', 'Mona Ali', P1, '', '', '', '', '', '', D(2019, 1, 1), '1', 0, 0, 1, '160'),            # family
    ('05HD1', 'Sara Omar', P2, '', 'a', '', '', '', '', D(2018, 1, 1), '0', 0, 0, 1, '140'),          # closed, older
    ('05HD2', 'Sara Omar', '', '', 'b', '', '', '', '', D(2021, 1, 1), '1', 0, 0, 1, '140'),          # phone via personphones
    ('05HD3', 'Sara Omar', P2, '', '', '', '', '', '', D(2017, 1, 1), '5', 0, 0, 1, '140'),           # deceased: never
    ('06HD1', 'Kamal Adel', '01111111111', '', '', '', '', '', '', None, '1', 0, 0, 1, '150'),        # placeholder
    ('06HD2', 'Kamal Adel', '01111111111', '', '', '', '', '', '', None, '1', 0, 0, 1, '150'),
    ('08HD1', 'Nour Said', '01005550001', '', '', '', '', '', '', D(2020, 1, 1), '0', 0, 0, 1, '170'),
    ('08HD2', 'Nour Said', '01005550001', '', '', '', '', '', '', D(2021, 1, 1), '0', 0, 0, 1, '170'),  # all closed
]
PHONES = [('05HD2', P2)]
BAL = [('07HD1', 100), ('07HD2', 300), ('05HD1', 9), ('05HD2', 40)]


class Cur:
    def execute(self, sql, p=None):
        self.r = PHONES if 'personphones' in sql else BAL if 'localcustomerspoints' in sql else HQ

    def fetchall(self):
        return self.r


class Conn:
    def cursor(self):
        return Cur()


class BuildTests(TestCase):
    def rows(self):
        return {r['old_pic']: r for r in DUP.build(*DUP.load(Conn()), last_sale={})}

    def test_groups_main_and_strength(self):
        rows = self.rows()
        self.assertEqual(set(rows), {'07HD2', '07HD3', '05HD1'})
        self.assertEqual(rows['07HD2']['main_pic'], '07HD1')          # older creation beats higher balance
        self.assertEqual(rows['07HD2']['strength'], 'strong')         # same name + structured address
        self.assertEqual(rows['07HD3']['strength'], 'review')
        self.assertEqual(rows['05HD1']['main_pic'], '05HD2')          # closed code is never the main
        self.assertEqual(rows['05HD1']['strength'], 'medium')
        self.assertEqual(rows['05HD1']['facts']['old']['balance'], 9)
        self.assertEqual(rows['07HD2']['facts']['shared_phones'], ['••4567'])

    def test_balance_then_last_sale_break_ties(self):
        custs, phones, bal = DUP.load(Conn())
        for p in ('07HD1', '07HD2'):
            custs[p]['custdate'] = D(2020, 1, 1)
        self.assertEqual(DUP.choose_main(['07HD1', '07HD2'], custs, bal, {}), '07HD2')
        bal = {}
        self.assertEqual(DUP.choose_main(['07HD1', '07HD2'], custs, bal, {'07HD1': D(2026, 1, 1)}), '07HD1')


class ReviewTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_branch, make_user
        b = make_branch('A', '130')
        _, self.maker, self.api1 = make_user('m1', role='call_center', branch=b)
        _, self.checker, self.api2 = make_user('m2', role='supervisor', branch=b)
        _, _, self.cashier = make_user('m3', role='cashier', branch=b)
        Customer.objects.create(name='Ahmed', phone=P1, softech_pic='07HD1')
        DUP.rebuild(Conn())

    def test_rebuild_counts_and_keeps_decisions(self):
        self.assertEqual(MC.objects.count(), 3)
        c = MC.objects.get(old_pic='07HD2')
        DUP.mark(c.pk, self.maker)
        DUP.approve(c.pk, self.checker)
        r = MC.objects.get(old_pic='07HD3')
        DUP.reject(r.pk, self.maker, 'different person')
        MC.objects.create(old_pic='09HD1', main_pic='09HD2', main_auto_pic='09HD2', cluster='09HD1',
                          strength='medium')
        n = DUP.rebuild(Conn())
        self.assertEqual((n['kept'], n['stale']), (2, 1))
        self.assertEqual(MC.objects.get(old_pic='07HD2').status, MC.APPROVED)
        self.assertEqual(MC.objects.get(old_pic='09HD1').status, MC.STALE)

    def test_maker_checker(self):
        c = MC.objects.get(old_pic='07HD2')
        with self.assertRaises(DUP.ReviewError):
            DUP.approve(c.pk, self.checker)                  # not marked yet
        DUP.mark(c.pk, self.maker)
        with self.assertRaises(DUP.ReviewError):
            DUP.approve(c.pk, self.maker)                    # own mark
        self.assertEqual(DUP.approve(c.pk, self.checker).status, MC.APPROVED)
        with self.assertRaises(DUP.ReviewError):
            DUP.reject(c.pk, self.checker, 'x')              # decided
        with self.assertRaises(DUP.ReviewError):
            DUP.reject(MC.objects.get(old_pic='07HD3').pk, self.checker, ' ')

    def test_swap_and_rebuild_keeps_it(self):
        c = MC.objects.get(old_pic='07HD2')
        DUP.mark(c.pk, self.maker)
        DUP.swap(c.pk, self.checker)
        self.assertEqual(MC.objects.get(old_pic='07HD1').main_pic, '07HD2')
        other = MC.objects.get(old_pic='07HD3')
        self.assertEqual((other.main_pic, other.strength, other.status), ('07HD2', 'review', 'proposed'))
        self.assertFalse(MC.objects.filter(old_pic='07HD2').exists())
        DUP.rebuild(Conn())
        self.assertEqual(MC.objects.get(old_pic='07HD1').main_pic, '07HD2')
        self.assertEqual(MC.objects.get(old_pic='07HD1').strength, 'strong')     # re-measured
        with self.assertRaises(DUP.ReviewError):
            DUP.swap(MC.objects.get(old_pic='05HD1').pk, self.maker)             # closed code can't be main

    def test_api(self):
        self.assertEqual(self.cashier.get('/api/customers/merge-candidates/').status_code, 403)
        r = self.api1.get('/api/customers/merge-candidates/?status=proposed&strength=strong')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['old_pic'] for x in r.data['rows']], ['07HD2'])
        self.assertEqual(r.data['rows'][0]['main_name'], 'Ahmed')
        self.assertEqual(self.api1.post('/api/customers/merge-candidates/bulk/',
                                        {'action': 'mark'}, format='json').data['done'], 1)
        self.assertEqual(self.api1.post('/api/customers/merge-candidates/bulk/',
                                        {'action': 'approve'}, format='json').data['done'], 0)
        pk = r.data['rows'][0]['id']
        self.assertEqual(self.api1.post(f'/api/customers/merge-candidates/{pk}/approve/').status_code, 400)
        self.assertEqual(self.api2.post(f'/api/customers/merge-candidates/{pk}/approve/').data['status'], 'approved')
        rej = MC.objects.get(old_pic='07HD3').pk
        self.assertEqual(self.api2.post(f'/api/customers/merge-candidates/{rej}/reject/', {}, format='json')
                         .status_code, 400)
        self.assertEqual(self.api2.get(f'/api/customers/{Customer.objects.get().pk}/').status_code, 200)
