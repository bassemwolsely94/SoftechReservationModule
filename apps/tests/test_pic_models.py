"""PIC Analytics — model grain, phone-label uniqueness, settings helper (doc 33)."""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.pic_analytics.models import PhoneLabel, PicAnalyticsAccess, PicDayFact, PicRollup
from apps.pic_analytics.settings import setting
from apps.users.models import StaffProfile
from django.contrib.auth import get_user_model


def _staff(name='pic_t'):
    user = get_user_model().objects.create_user(username=name, password='x')
    return StaffProfile.objects.get(user=user) if hasattr(user, 'staffprofile') else \
        StaffProfile.objects.create(user=user)


class PicModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # The grain includes branch; Postgres treats NULLs as distinct, so builders must set it.
        cls.branch = Branch.objects.create(softech_branch_id='901', name='Test Branch')

    def _fact(self, **kw):
        base = dict(pic='P1', branch=self.branch, day=date(2026, 11, 1), salesperson='u1', channel_bucket='walkin',
                    invoices=1, net='10.00')
        base.update(kw)
        return PicDayFact.objects.create(**base)

    def test_day_fact_unique_grain(self):
        self._fact()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._fact()
        self._fact(channel_bucket='delivery')   # different grain member is fine

    def test_day_fact_defaults_non_null(self):
        f = PicDayFact.objects.create(pic='', day=date(2026, 11, 1), branch=self.branch)
        self.assertEqual((f.salesperson, f.channel_bucket), ('', ''))

    def test_phone_label_unique(self):
        s = _staff()
        PhoneLabel.objects.create(phone_key='1000000001', label='staff', created_by=s)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhoneLabel.objects.create(phone_key='1000000001', label='spam', created_by=s)

    def test_rollup_pic_unique(self):
        PicRollup.objects.create(pic='P1', as_of=date(2026, 11, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            PicRollup.objects.create(pic='P1', as_of=date(2026, 11, 1))

    def test_access_single_active_grant(self):
        s = _staff('pic_a')
        PicAnalyticsAccess.objects.create(staff=s)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PicAnalyticsAccess.objects.create(staff=s)

    def test_audit_actions_registered(self):
        keys = {k for k, _ in AuditLog.ACTION_CHOICES}
        self.assertTrue({'pic_analytics_exported', 'pic_analytics_access_granted',
                         'pic_analytics_access_revoked', 'pic_phone_labelled'} <= keys)

    def test_setting_default_then_override(self):
        self.assertEqual(setting('pic_loyal_months'), 10)
        self.assertEqual(setting('pic_overdue_factor'), 1.5)
        SystemSetting.objects.create(key='pic_loyal_months', label='x', value='8', value_type='integer')
        self.assertEqual(setting('pic_loyal_months'), 8)
