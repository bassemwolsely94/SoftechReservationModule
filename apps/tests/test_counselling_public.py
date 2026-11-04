"""Project 4 — the public counselling card page (/api/public/counsel/<token>/) + opt-out."""
import uuid
from unittest import mock

from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.counselling import cards, services
from apps.counselling.models import CounselCardOptOut, CounselCardSend
from apps.customers.models import Customer
from apps.whatsapp.models import WATemplate

from .factories import make_branch, make_item, make_user
from .test_counselling_cards import FakeSender

ON = dict(COUNSELLING_CONTENT_ENABLED=True, COUNSEL_CARD_SEND_ENABLED=True)


def _url(token, opt=False):
    return f'/api/public/counsel/{token}/' + ('opt-out/' if opt else '')


@override_settings(**ON)
class PublicCardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.branch = make_branch()
        _, self.ph, _ = make_user('ph_pb', role='pharmacist', branch=self.branch)
        self.cust = Customer.objects.create(name='كريم سامي', phone='01212345678', softech_pic='PB1')
        self.item = make_item('فلاجيل 500', 'PB001')
        self.sheet = services.create_sheet(self.ph, {'how_to_use_ar': 'بعد الأكل', 'dose_ar': 'قرص',
                                                     'warnings_ar': 'لا تشرب كحولاً'}, [self.item.pk])
        services.approve(self.ph, self.sheet)
        WATemplate.objects.create(name='counsel_card', status='approved', body_text='x')
        self.send = cards.send_card(customer=self.cust, phone='', item_ids=[self.item.pk], actor=self.ph,
                                    branch=self.branch, idempotency_key=uuid.uuid4().hex, sender=FakeSender())
        self.token = cards.token_for(self.send)
        self.anon = APIClient()

    def test_valid_token_shows_cards(self):
        r = self.anon.get(_url(self.token))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['first_name'], 'كريم')
        line = r.data['items'][0]
        self.assertEqual((line['name'], line['withdrawn'], line['updated']), ('فلاجيل 500', False, False))
        self.assertEqual(line['content']['warnings_ar'], 'لا تشرب كحولاً')
        self.send.refresh_from_db()
        self.assertIsNotNone(self.send.first_opened_at)

    def test_tampered_and_expired_404(self):
        self.assertEqual(self.anon.get(_url(self.token[:-2] + 'xx')).status_code, 404)
        with override_settings(COUNSEL_CARD_TOKEN_DAYS=0):
            with mock.patch('django.core.signing.time.time', return_value=10 ** 12):
                self.assertEqual(self.anon.get(_url(self.token)).status_code, 404)
        other_salt = signing.dumps({'s': self.send.pk}, salt='counsel-other')
        self.assertEqual(self.anon.get(_url(other_salt)).status_code, 404)

    def test_one_opt_out_row_per_phone(self):
        """Deferred minor: concurrent taps must not leave duplicate rows (later taps then 500)."""
        from django.db import IntegrityError, transaction
        self.anon.post(_url(self.token, opt=True))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CounselCardOptOut.objects.create(phone_hash=self.send.phone_hash, source='link')
        self.assertEqual(self.anon.post(_url(self.token, opt=True)).status_code, 200)
        self.assertEqual(CounselCardOptOut.objects.filter(phone_hash=self.send.phone_hash).count(), 1)

    def test_junk_token_404_not_500(self):
        for junk in ('x', '%00', 'a' * 500, signing.dumps({'s': 'drop'}, salt=cards.CARD_SIGNING_SALT),
                     signing.dumps([1], salt=cards.CARD_SIGNING_SALT)):
            self.assertEqual(self.anon.get(_url(junk)).status_code, 404, junk)

    def test_page_shows_current_approved_not_draft(self):
        services.edit_sheet(self.ph, self.sheet, {'dose_ar': 'مسودة جديدة'})
        line = self.anon.get(_url(self.token)).data['items'][0]
        self.assertEqual((line['content']['dose_ar'], line['updated']), ('قرص', False))
        services.approve(self.ph, self.sheet)
        line = self.anon.get(_url(self.token)).data['items'][0]
        self.assertEqual((line['content']['dose_ar'], line['updated']), ('مسودة جديدة', True))

    def test_retired_shows_withdrawn_without_text(self):
        services.retire(self.ph, self.sheet, 'خطأ')
        line = self.anon.get(_url(self.token)).data['items'][0]
        self.assertEqual(line, {'name': 'فلاجيل 500', 'withdrawn': True})

    def test_no_personal_data_leaked(self):
        r = self.anon.get(_url(self.token))
        self.assertEqual(set(r.data), {'first_name', 'branch_name', 'branch_phone', 'sent_at', 'items'})
        body = r.content.decode('utf-8')
        for secret in ('01212345678', '1212345678', 'PB1', self.ph.full_name or 'ph_pb'):
            self.assertNotIn(secret, body)

    def test_opt_out_idempotent_and_blocks_next_send(self):
        self.assertEqual(self.anon.post(_url(self.token, opt=True)).status_code, 200)
        self.assertEqual(self.anon.post(_url(self.token, opt=True)).status_code, 200)
        self.assertEqual(CounselCardOptOut.objects.count(), 1)
        s = cards.send_card(customer=self.cust, phone='', item_ids=[self.item.pk], actor=self.ph,
                            branch=self.branch, idempotency_key='after-optout', resend=True, sender=FakeSender())
        self.assertEqual(s.status, 'blocked_optout')

    def test_staff_cookie_not_required(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer stale.jwt.token')
        self.assertEqual(c.get(_url(self.token)).status_code, 200)

    def test_failed_send_has_no_page(self):
        CounselCardSend.objects.filter(pk=self.send.pk).update(status='failed')
        self.assertEqual(self.anon.get(_url(self.token)).status_code, 404)

    def test_portal_orders_lists_counsel_cards(self):
        from apps.portal.services import exchange_magic_link, issue_magic_link
        _, tok = exchange_magic_link(issue_magic_link(self.cust))
        r = self.anon.get('/api/portal/orders/', HTTP_AUTHORIZATION=f'Portal {tok}')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['counsel_cards'][0]['item_count'], 1)
        # tokens are timestamped, so compare what they sign, not the string (a second may pass)
        self.assertEqual(signing.loads(r.data['counsel_cards'][0]['token'], salt=cards.CARD_SIGNING_SALT),
                         signing.loads(self.token, salt=cards.CARD_SIGNING_SALT))
