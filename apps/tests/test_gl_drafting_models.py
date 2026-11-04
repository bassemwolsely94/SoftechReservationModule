"""Plan 2 / Task 1: drafting models constraints."""
import datetime

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.finance.models import (
    GLParty, GLSourceMap, PostingRule, GLSourceDoc, SourceException, GLDraftRun,
    GLAccountGroup, GLAccount,
)
from apps.users.models import StaffProfile

D = datetime.date(2026, 1, 5)


class GLDraftingModelTests(TestCase):
    def _doc(self, key='sales_tenders:130:2026-01-05'):
        return GLSourceDoc.objects.create(
            source_type='sales_tenders', source_key=key, doc_date=D,
            amounts={}, attrs={}, content_hash='h')

    def test_second_running_run_refused_by_db(self):
        GLDraftRun.objects.create(status='running', date_from=D, date_to=D)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GLDraftRun.objects.create(status='running', date_from=D, date_to=D)
        GLDraftRun.objects.create(status='success', date_from=D, date_to=D)
        GLDraftRun.objects.create(status='success', date_from=D, date_to=D)

    def test_party_code_unique_per_type(self):
        GLParty.objects.create(party_type='supplier', code='92', name='a')
        GLParty.objects.create(party_type='customer', code='92', name='b')
        with self.assertRaises(IntegrityError), transaction.atomic():
            GLParty.objects.create(party_type='supplier', code='92', name='c')

    def test_confirmed_personcode_unique_but_proposals_may_repeat(self):
        GLParty.objects.create(party_type='supplier', code='1', name='a',
                               softech_personcode='500', status='confirmed')
        GLParty.objects.create(party_type='supplier', code='2', name='b',
                               softech_personcode='500', status='proposed')
        GLParty.objects.create(party_type='supplier', code='3', name='c',
                               softech_personcode='500', status='proposed')
        with self.assertRaises(IntegrityError), transaction.atomic():
            GLParty.objects.create(party_type='supplier', code='4', name='d',
                                   softech_personcode='500', status='confirmed')
        # blank personcode never collides
        GLParty.objects.create(party_type='supplier', code='5', name='e', status='confirmed')
        GLParty.objects.create(party_type='supplier', code='6', name='f', status='confirmed')
        self.assertTrue(GLParty.objects.get(code='1').is_confirmed)
        self.assertFalse(GLParty.objects.get(code='2').is_confirmed)

    def test_rule_version_unique_and_delete_refused(self):
        r = PostingRule.objects.create(code='r1', version=1, source_type='sales_tenders',
                                       effective_from=D)
        self.assertEqual((r.action, r.granularity, r.book, r.priority),
                         ('post', 'document', 'general', 100))
        with self.assertRaises(IntegrityError), transaction.atomic():
            PostingRule.objects.create(code='r1', version=1, source_type='x', effective_from=D)
        PostingRule.objects.create(code='r1', version=2, source_type='x', effective_from=D)
        with self.assertRaises(Exception):
            r.delete()
        self.assertEqual(PostingRule.objects.filter(code='r1').count(), 2)

    def test_source_key_unique(self):
        self._doc()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._doc()

    def test_one_open_exception_per_code(self):
        doc = self._doc()
        SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=D)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=D)
        SourceException.objects.create(source_doc=doc, kind='unmapped_party', source_date=D)
        SourceException.objects.filter(kind='no_rule').update(status='resolved')
        SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=D)

    def test_source_map_unique_and_protect(self):
        g = GLAccountGroup.objects.create(name='g', section='balance_sheet')
        a = GLAccount.objects.create(code='1302', name='x', group=g, nature='debit', account_type='asset')
        GLSourceMap.objects.create(kind='bank', source_value='40', account=a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GLSourceMap.objects.create(kind='bank', source_value='40', account=a)

    def test_gl_drafting_system_user_exists(self):
        from apps.finance.gl.drafting import system_user
        profile = system_user()   # Ruling P12: get_or_create, survives a TransactionTestCase flush
        u = profile.user
        self.assertEqual(u.username, 'gl-drafting')
        self.assertFalse(u.is_active)
        self.assertFalse(u.has_usable_password())
        self.assertEqual(profile.role, 'viewer')
        self.assertEqual(system_user().pk, profile.pk)   # idempotent
        self.assertEqual(User.objects.filter(username='gl-drafting').count(), 1)
        self.assertEqual(StaffProfile.objects.filter(user=u).count(), 1)
