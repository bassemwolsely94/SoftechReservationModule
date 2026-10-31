"""
Owner decision B-2 (2026-10-30) — customers.

A customer can buy at any branch, so any staff member may FIND any customer — but only by their
full phone number. Browsing, name search, editing and the churn list stay limited to the user's own
branch(es); other branches' phone numbers are masked; call center (and the other all-branch roles)
may edit any customer. `can_see_all_customers` widens name search to every branch, still masked and
still edit-own-only.
"""
from django.test import TestCase, override_settings

from apps.customers.models import Customer
from apps.tests.factories import make_branch, make_user

from .fixtures import bearer_client, seed_code_matrix

PHONE_A = '01011112222'
PHONE_B = '01033334444'


def _rows(resp):
    data = resp.json()
    return data.get('results', data) if isinstance(data, dict) else data


@override_settings(RBAC_ENFORCEMENT='enforce')
class CustomerAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.a = make_branch('Cust A', softech_id='CA1')
        cls.b = make_branch('Cust B', softech_id='CB1')
        cls.cust_a = Customer.objects.create(name='Canary Ahmed', phone=PHONE_A, phone_alt='0223334444',
                                             whatsapp_phone=PHONE_A, preferred_branch=cls.a)
        cls.cust_b = Customer.objects.create(name='Canary Bassem', phone=PHONE_B, preferred_branch=cls.b)
        cls.pharm_b = make_user('ca_pharm_b', role='pharmacist', branch=cls.b)[1]
        cls.cc = make_user('ca_cc', role='call_center', branch=cls.b)[1]

    def client_for(self, profile):
        return bearer_client(profile.user)

    # ── finding ──────────────────────────────────────────────────────────────────
    def test_browse_list_shows_own_branch_only(self):
        ids = {r['id'] for r in _rows(self.client_for(self.pharm_b).get('/api/customers/'))}
        self.assertIn(self.cust_b.pk, ids)
        self.assertNotIn(self.cust_a.pk, ids)

    def test_name_search_does_not_cross_branches(self):
        ids = {r['id'] for r in _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': 'Canary'}))}
        self.assertEqual(ids, {self.cust_b.pk})

    def test_full_phone_finds_other_branch_customer_masked(self):
        rows = _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': PHONE_A}))
        self.assertEqual([r['id'] for r in rows], [self.cust_a.pk])
        body = str(rows)
        self.assertNotIn(PHONE_A, body)
        self.assertNotIn('0223334444', body)

    def test_partial_phone_does_not_fish_other_branches(self):
        ids = {r['id'] for r in _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': '0101111'}))}
        self.assertNotIn(self.cust_a.pk, ids)

    def test_recognize_follows_the_same_rule(self):
        c = self.client_for(self.pharm_b)
        partial = c.get('/api/customers/recognize/', {'q': '0101111'}).json()['matches']
        self.assertNotIn(self.cust_a.pk, [m['id'] for m in partial])
        full = c.get('/api/customers/recognize/', {'q': PHONE_A}).json()['matches']
        self.assertEqual([m['id'] for m in full], [self.cust_a.pk])
        self.assertNotIn(PHONE_A, str(full))
        by_name = c.get('/api/customers/recognize/', {'q': 'Canary'}).json()['matches']
        self.assertEqual([m['id'] for m in by_name], [self.cust_b.pk])

    def test_universal_search_follows_the_same_rule(self):
        c = self.client_for(self.pharm_b)
        found = c.get('/api/search/universal', {'q': 'Canary', 'types': 'customers'}).json()['results']['customers']
        self.assertEqual([r['id'] for r in found], [self.cust_b.pk])
        found = c.get('/api/search/universal', {'q': PHONE_A, 'types': 'customers'}).json()['results']['customers']
        self.assertEqual([r['id'] for r in found], [self.cust_a.pk])
        self.assertNotIn(PHONE_A, str(found))

    def test_own_customer_phone_is_visible(self):
        rows = _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': PHONE_B}))
        self.assertEqual(rows[0]['phone'], PHONE_B)

    def test_can_see_customer_phone_off_masks_everything(self):
        self.pharm_b.can_see_customer_phone = False
        self.pharm_b.save()
        rows = _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': PHONE_B}))
        self.assertNotIn(PHONE_B, str(rows))

    def test_can_see_all_customers_widens_name_search_still_masked(self):
        self.pharm_b.can_see_all_customers = True
        self.pharm_b.save()
        rows = _rows(self.client_for(self.pharm_b).get('/api/customers/', {'search': 'Canary'}))
        self.assertEqual({r['id'] for r in rows}, {self.cust_a.pk, self.cust_b.pk})
        self.assertNotIn(PHONE_A, str(rows))

    # ── serving at POS: the detail opens, masked ──────────────────────────────────
    def test_other_branch_customer_opens_masked_for_pos(self):
        r = self.client_for(self.pharm_b).get(f'/api/customers/{self.cust_a.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(PHONE_A, r.content.decode())

    # ── editing ──────────────────────────────────────────────────────────────────
    def test_branch_user_cannot_edit_other_branch_customer(self):
        c = self.client_for(self.pharm_b)
        for method, url, body in (
            ('patch', f'/api/customers/{self.cust_a.pk}/', {'name': 'X'}),
            ('patch', f'/api/customers/{self.cust_a.pk}/update_conditions/', {'chronic_conditions': 'X'}),
            ('post', f'/api/customers/{self.cust_a.pk}/notes/', {'note': 'X'}),
            ('patch', f'/api/customers/{self.cust_a.pk}/health-profile/', {'has_diabetes': True}),
        ):
            with self.subTest(url=url):
                r = getattr(c, method)(url, body, format='json')
                self.assertEqual(r.status_code, 403, r.content[:200])
        self.cust_a.refresh_from_db()
        self.assertEqual(self.cust_a.name, 'Canary Ahmed')
        self.assertFalse(self.cust_a.notes.exists())

    def test_branch_user_edits_own_branch_customer(self):
        r = self.client_for(self.pharm_b).patch(f'/api/customers/{self.cust_b.pk}/', {'name': 'Renamed'},
                                                 format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])

    def test_call_center_edits_any_customer_and_sees_phones(self):
        c = self.client_for(self.cc)
        r = c.patch(f'/api/customers/{self.cust_a.pk}/', {'name': 'CC edit'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        rows = _rows(c.get('/api/customers/', {'search': 'Canary'}))
        self.assertIn(PHONE_A, str(rows))

    # ── lists that act as exports ────────────────────────────────────────────────
    def test_churn_list_is_own_branch_only(self):
        Customer.objects.filter(pk__in=[self.cust_a.pk, self.cust_b.pk]).update(churn_score=0.9)
        rows = self.client_for(self.pharm_b).get('/api/customers/churn-at-risk/').json()['results']
        self.assertEqual({r['id'] for r in rows}, {self.cust_b.pk})
