"""
Batch 5b — the phone canary sweep (owner decision B-2 outside the customers screens).

A customer of branch A gets a known number, and so does every phone-like field of every record we
can plant for them (reservations, delivery orders, follow-ups, vouchers, calls, campaign messages,
leads, conversations…). Every protected GET list route, plus the detail and lookup routes that
take a customer id or a typed number, is then called by:

  • a branch-B pharmacist holding every module action — another branch's customer: the full number
    must never come back (a typed FULL number may find the customer, masked);
  • a branch-A pharmacist with can_see_customer_phone = False — their own customer: never either;
  • an admin — positive control: the number really is in the responses.

A match = NUMBER_TOKEN (digits from the middle of the number — mask() keeps only the last 3) in
the response body. Reviewed exceptions: baselines/phone_canary_leaks.txt.
"""
import logging

from django.db import transaction
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .baseline import assert_matches_baseline
from .canary import Planter
from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire, handles
from .sweep import SWEEP_ID, protected_routes

NUMBER = '01093847561'
NUMBER_TOKEN = '93847'
PARTIAL = '7561'          # a typed fragment, not a full number


def _body(resp):
    ctype = resp.get('Content-Type', '')
    if 'json' not in ctype and not ctype.startswith('text/'):
        return ''
    try:
        return resp.content.decode('utf-8', 'replace')
    except Exception:          # noqa: BLE001 — streaming responses
        return ''


def _get(client, path):
    try:
        with transaction.atomic():
            r = client.get(path)
            transaction.set_rollback(True)
        return r.status_code, _body(r)
    except Exception as exc:   # noqa: BLE001
        return f'raised {type(exc).__name__}', ''


def _extra_routes(cid):
    """Detail / lookup routes the list sweep can't reach (they need an id or a typed number)."""
    return [
        f'/api/customers/{cid}/',
        f'/api/customers/{cid}/pos-summary/',
        f'/api/customers/{cid}/receipt/',
        f'/api/customers/{cid}/patient-profile/',
        f'/api/loyalty/customers/{cid}/softech-balance/',
        f'/api/delivery/customers/{cid}/locations/',
        f'/api/delivery/customer-profile/?phone={PARTIAL}',
        f'/api/delivery/customer-profile/?phone={NUMBER}',
        f'/api/callcenter/calls/lookup/?phone={PARTIAL}',
        f'/api/callcenter/calls/lookup/?phone={NUMBER}',
        f'/api/referral/customers/{cid}/leads/list/',
    ]


@override_settings(RBAC_ENFORCEMENT='enforce')
class PhoneCanarySweepTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role='pharmacist').update(is_allowed=True)
        module_access.clear_cache()
        a = make_branch('Phone A', softech_id='PHA')
        b = make_branch('Phone B', softech_id='PHB')
        user_a, prof_a, _ = make_user('ph_a', role='pharmacist', branch=a)
        prof_a.can_see_customer_phone = False
        prof_a.save(update_fields=['can_see_customer_phone'])
        user_b, _, _ = make_user('ph_b', role='pharmacist', branch=b)
        admin, _, _ = make_user('ph_admin', role='admin', branch=b, access_all=True)
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                cls.planter = Planter(a, user_a, prof_a, phone=NUMBER).plant_phones()
                cid = cls.planter.customer.pk
                routes = sorted(p for p in protected_routes() if SWEEP_ID not in p and handles(p, 'GET'))
                routes += _extra_routes(cid)
                clients = {'other_branch': bearer_client(user_b), 'no_phone_flag': bearer_client(user_a)}
                adm = bearer_client(admin)
                cls.leaks, cls.admin_sees = set(), set()
                for path in routes:
                    if NUMBER_TOKEN in _get(adm, path)[1]:
                        cls.admin_sees.add(path)
                    for who, c in clients.items():
                        code, body = _get(c, path)
                        if code == 200 and NUMBER_TOKEN in body:
                            cls.leaks.add(f"{who} GET {path.replace(f'/{cid}/', '/<cid>/')}")
        finally:
            logging.disable(previous)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()

    def test_the_customer_and_phone_records_were_planted(self):
        self.assertIsNotNone(self.planter.customer)
        self.assertGreater(len(self.planter.planted), 40)

    def test_admin_sees_the_number(self):
        """Positive control."""
        self.assertGreater(len(self.admin_sees), 10)

    def test_no_unmasked_number_for_staff_who_may_not_see_it(self):
        assert_matches_baseline(self, 'phone_canary_leaks', self.leaks)
