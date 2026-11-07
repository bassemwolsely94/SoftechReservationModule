"""
Data lifecycle Stage 3: the rule register and the policy service (design §4, §6 Stage 3, §8).

Same idea as SCHEDULER_JOB_GUARDS: a new FileField with no rule and no keep-forever reason fails here,
so the default stays "keep". Floors, fresh previews and the file-rule lock apply to admins too.
"""
import datetime
from unittest import mock

from django.apps import apps
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import isolate_apps
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.data_lifecycle import policy, register
from apps.data_lifecycle.models import HeldFile, LifecycleRulePolicy, LifecycleRun, LifecycleRunLine
from apps.data_lifecycle.policy import PolicyRefused, get_mode, keep_days, set_policy
from apps.data_lifecycle.register import KEEP_FOREVER, PROTECTED_APPS, PROTECTED_FILE_TARGETS, RULES
from apps.tests.factories import make_user

P56_KEYS = {'p56_engine', 'p56_notifications', 'p56_pbx', 'p56_audit', 'p56_slow', 'p56_screen_views'}


class ClassificationTests(TestCase):      # row rules' candidates() query the database
    def test_every_filefield_is_classified(self):
        self.assertEqual(register.unclassified_file_fields(), [],
                         'new FileField: add it to a rule\'s targets or to KEEP_FOREVER with a reason')

    def test_unclassified_filefield_fails(self):
        with isolate_apps('apps.data_lifecycle'):
            class FakeUpload(models.Model):
                document = models.FileField(upload_to='fake/')

                class Meta:
                    app_label = 'data_lifecycle'

            with mock.patch.object(register.apps, 'get_models', return_value=[FakeUpload]):
                self.assertEqual(register.unclassified_file_fields(), ['data_lifecycle.FakeUpload.document'])

    def test_every_classification_points_at_a_real_field(self):
        """A renamed field must not leave a stale entry that classifies nothing."""
        file_targets = [t for r in RULES.values() if r.kind == 'file' for t in r.targets]
        for target in [*file_targets, *KEEP_FOREVER]:
            app_label, model_name, field_name = target.split('.')
            field = apps.get_model(app_label, model_name)._meta.get_field(field_name)
            self.assertIsInstance(field, models.FileField, target)
        for rule in RULES.values():
            if rule.kind == 'row':
                for target in rule.targets:
                    self.assertTrue(apps.get_model(target), target)

    def test_keep_forever_has_reasons(self):
        for target, reason in KEEP_FOREVER.items():
            self.assertTrue(reason.strip(), target)
        self.assertEqual(set(KEEP_FOREVER), {'product_experience.ProductSEO.og_image',
                                             'insurance.InsuranceExportProfile.watermark_image',
                                             'vision.OcrSample.audio'})

    def test_no_rule_targets_protected_app(self):
        self.assertEqual(set(PROTECTED_APPS), {'finance', 'payments', 'insurance', 'users', 'audit', 'access'})
        self.assertEqual(set(PROTECTED_FILE_TARGETS), {'payments.ExternalPayment.screenshot',
                                                       'payments.BankStatementImport.raw_file'})
        for rule in RULES.values():
            for target in rule.targets:
                if target.split('.')[0] not in PROTECTED_APPS:
                    continue
                self.assertEqual(rule.kind, 'file', f'{rule.key} selects rows of protected {target}')
                self.assertIn(target, PROTECTED_FILE_TARGETS, f'{rule.key} targets protected {target}')
            if rule.kind == 'row':
                for qs in rule.candidates():
                    self.assertNotIn(qs.model._meta.app_label, PROTECTED_APPS, rule.key)

    def test_age_field_exists(self):
        checked = 0
        for rule in RULES.values():
            for label, field_name in (rule.age_field or {}).items():
                field = apps.get_model(label)._meta.get_field(field_name)
                self.assertIsInstance(field, models.DateField, f'{rule.key} {label}.{field_name}')
                self.assertTrue(any(t.startswith(f'{label}.') or t == label for t in rule.targets),
                                f'{rule.key}: {label} is not a target')
                checked += 1
        self.assertGreater(checked, 0)

    def test_every_field_target_of_a_dated_rule_has_an_age_field(self):
        for rule in RULES.values():
            if rule.kind == 'file' and rule.age_field is not None:
                models_named = {t.rsplit('.', 1)[0] for t in rule.targets}
                self.assertEqual(models_named, set(rule.age_field), rule.key)


class RegisterValueTests(SimpleTestCase):
    def test_rule_keys(self):
        self.assertEqual(set(RULES), {
            'rate_runs', 'transit_alert_notes', 'transit_audit_events', 'prescriptions', 'ocr_pos_rx',
            'conversations', 'financial_docs', 'bundle_pages', 'images_rejected', 'images_unreviewed',
            'images_obsolete', 'delivery_proof', 'staff_messages', 'unreferenced', *P56_KEYS})
        for key, rule in RULES.items():
            self.assertEqual(rule.key, key)

    def test_limits_match_the_plan(self):
        expected = {   # key: kind, floor, default, margin, ceiling
            'rate_runs': ('row', None, None, 150_000, 1_500_000),
            'transit_alert_notes': ('row', None, 90, 2_000, 200_000),
            'transit_audit_events': ('row', None, 90, 5_000, 300_000),
            'prescriptions': ('file', 1095, 1095, 200, 5_000),
            'ocr_pos_rx': ('file', 1095, 1095, 200, 5_000),
            'conversations': ('file', None, 1095, 200, 5_000),
            'financial_docs': ('file', 1825, 1825, 100, 2_000),
            'bundle_pages': ('file', None, 30, 500, 5_000),
            'images_rejected': ('file', None, 30, 100, 3_000),
            'images_unreviewed': ('file', None, 180, 100, 3_000),
            'images_obsolete': ('file', None, 90, 100, 1_000),
            'delivery_proof': ('file', None, 365, 200, 5_000),
            'staff_messages': ('file', None, 365, 500, 5_000),
            'unreferenced': ('file', None, 30, 100, 1_000),
        }
        for key, values in expected.items():
            rule = RULES[key]
            self.assertEqual((rule.kind, rule.floor_days, rule.default_days, rule.margin, rule.ceiling), values, key)
        for key in P56_KEYS:
            self.assertEqual((RULES[key].kind, RULES[key].margin, RULES[key].ceiling), ('p56', None, None), key)

    def test_field_counts_match_the_design(self):
        self.assertEqual(len(RULES['prescriptions'].targets), 5)
        self.assertEqual(len(RULES['financial_docs'].targets), 5)
        self.assertEqual(len(RULES['conversations'].targets), 3)
        self.assertEqual(len(RULES['staff_messages'].targets), 9)
        self.assertEqual(RULES['ocr_pos_rx'].targets, ('vision.OcrSample.image',))

    def test_auto_approved_counts_as_approved(self):
        self.assertIn('auto_approved', register.IMAGE_APPROVED_STATUSES)
        self.assertEqual(set(register.IMAGE_REJECTED_STATUSES), {'rejected'})
        self.assertEqual(set(register.IMAGE_UNREVIEWED_STATUSES), {'scored', 'pending_review'})
        self.assertFalse(set(register.IMAGE_APPROVED_STATUSES)
                         & {*register.IMAGE_REJECTED_STATUSES, *register.IMAGE_UNREVIEWED_STATUSES})

    def test_apply_defaults_to_none_and_p56_has_no_candidates(self):
        for key, rule in RULES.items():
            if key != 'rate_runs':      # rate_runs: apps/tests/test_lifecycle_rate_rule.py
                self.assertIsNone(rule.apply, key)
            if rule.kind == 'p56':
                self.assertIsNone(rule.candidates, key)
            else:
                self.assertTrue(callable(rule.candidates), key)


class PolicyTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.admin, _ = make_user('lifecycle_admin', role='admin')

    def _preview(self, key, age_days, **line):
        now = timezone.now() - datetime.timedelta(days=age_days)
        run = LifecycleRun.objects.create(started_at=now, finished_at=line.pop('finished_at', now), is_preview=True)
        return LifecycleRunLine.objects.create(run=run, rule_key=key, count=3, bytes=10, is_preview=True, **line)


class ReadTests(PolicyTestBase):
    def test_new_rules_start_in_preview(self):
        self.assertEqual(get_mode('prescriptions'), 'preview')
        self.assertEqual(get_mode('rate_runs'), 'preview')

    def test_p56_is_always_on(self):
        for key in P56_KEYS:
            self.assertEqual(get_mode(key), 'on', key)

    def test_keep_days_default_and_override(self):
        self.assertEqual(keep_days('prescriptions'), 1095)
        LifecycleRulePolicy.objects.create(rule_key='prescriptions', keep_days_override=1200, reason='x')
        self.assertEqual(keep_days('prescriptions'), 1200)

    def test_override_below_a_later_raised_floor_does_not_win(self):
        """A floor raised in code beats a stored override, without anyone having to edit the row."""
        LifecycleRulePolicy.objects.create(rule_key='prescriptions', keep_days_override=10, reason='x')
        self.assertEqual(keep_days('prescriptions'), 1095)

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=False)
    def test_stored_on_is_read_as_preview_while_file_rules_are_locked(self):
        """A database restored from the VPS onto the office machine must not start moving files."""
        LifecycleRulePolicy.objects.create(rule_key='prescriptions', mode='on', reason='x')
        self.assertEqual(get_mode('prescriptions'), 'preview')

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=False)
    def test_stored_off_stays_off_while_file_rules_are_locked(self):
        LifecycleRulePolicy.objects.create(rule_key='prescriptions', mode='off', reason='x')
        self.assertEqual(get_mode('prescriptions'), 'off')


class SetPolicyTests(PolicyTestBase):
    def test_floor_refused_for_admin(self):
        with self.assertRaises(PolicyRefused) as ctx:
            set_policy('prescriptions', keep_days=1000, user=self.admin, reason='x')
        self.assertIn('1095', str(ctx.exception))
        self.assertFalse(LifecycleRulePolicy.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=policy.AUDIT_ACTION).exists())

        row = set_policy('prescriptions', keep_days=1200, user=self.admin, reason='طلب المحاسب')
        self.assertEqual(row.keep_days_override, 1200)
        self.assertEqual(row.changed_by, self.admin)
        self.assertEqual(row.reason, 'طلب المحاسب')
        self.assertEqual(keep_days('prescriptions'), 1200)
        log = AuditLog.objects.get(action=policy.AUDIT_ACTION)
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.old_data, {'mode': 'preview', 'keep_days': 1095})
        self.assertEqual(log.new_data, {'mode': 'preview', 'keep_days': 1200})
        self.assertEqual(log.note, 'طلب المحاسب')
        self.assertEqual(log.object_id, str(row.pk))

    def test_period_without_a_written_floor_can_only_be_lengthened(self):
        """Design §4: admins lengthen a period, so the default is the minimum for draft rules too."""
        with self.assertRaises(PolicyRefused):
            set_policy('images_rejected', keep_days=29, user=self.admin, reason='x')
        self.assertEqual(set_policy('images_rejected', keep_days=31, user=self.admin, reason='x').keep_days_override,
                         31)

    def test_rule_with_no_day_period_refuses_a_period(self):
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', keep_days=900, user=self.admin, reason='x')

    def test_bad_period_values_are_refused(self):
        for bad in (True, '1200', 1200.5):
            with self.assertRaises(PolicyRefused, msg=repr(bad)):
                set_policy('prescriptions', keep_days=bad, user=self.admin, reason='x')

    def test_on_needs_fresh_preview(self):
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', mode='on', user=self.admin, reason='x')

        self._preview('rate_runs', age_days=8)
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', mode='on', user=self.admin, reason='x')
        self.assertEqual(get_mode('rate_runs'), 'preview')

        self._preview('rate_runs', age_days=6)
        self.assertEqual(set_policy('rate_runs', mode='on', user=self.admin, reason='x').mode, 'on')
        self.assertEqual(get_mode('rate_runs'), 'on')
        log = AuditLog.objects.get(action=policy.AUDIT_ACTION)
        self.assertEqual(log.old_data['mode'], 'preview')
        self.assertEqual(log.new_data['mode'], 'on')

    def test_another_rules_preview_does_not_count(self):
        self._preview('transit_alert_notes', age_days=1)
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', mode='on', user=self.admin, reason='x')

    def test_failed_or_unfinished_preview_does_not_count(self):
        self._preview('rate_runs', age_days=1, error='boom')
        self._preview('rate_runs', age_days=1, finished_at=None)
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', mode='on', user=self.admin, reason='x')

    def test_real_run_line_does_not_count_as_a_preview(self):
        now = timezone.now()
        run = LifecycleRun.objects.create(started_at=now, finished_at=now, is_preview=False)
        LifecycleRunLine.objects.create(run=run, rule_key='rate_runs', is_preview=False)
        with self.assertRaises(PolicyRefused):
            set_policy('rate_runs', mode='on', user=self.admin, reason='x')

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=False)
    def test_file_rule_locked_off_vps(self):
        self._preview('prescriptions', age_days=1)
        with self.assertRaises(PolicyRefused):
            set_policy('prescriptions', mode='on', user=self.admin, reason='x')
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=True)
    def test_file_rule_on_the_vps_still_needs_a_fresh_preview(self):
        with self.assertRaises(PolicyRefused):
            set_policy('prescriptions', mode='on', user=self.admin, reason='x')
        self._preview('prescriptions', age_days=1)
        self.assertEqual(set_policy('prescriptions', mode='on', user=self.admin, reason='x').mode, 'on')
        self.assertEqual(get_mode('prescriptions'), 'on')

    def test_off_and_preview_need_no_preview(self):
        self.assertEqual(set_policy('prescriptions', mode='off', user=self.admin, reason='x').mode, 'off')
        self.assertEqual(set_policy('prescriptions', mode='preview', user=self.admin, reason='x').mode, 'preview')

    def test_p56_mode_cannot_change(self):
        for kwargs in ({'mode': 'off'}, {'mode': 'preview'}, {'keep_days': 4000}):
            with self.assertRaises(PolicyRefused, msg=kwargs):
                set_policy('p56_audit', user=self.admin, reason='x', **kwargs)
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    def test_reason_is_required(self):
        for reason in ('', '   ', None):
            with self.assertRaises(PolicyRefused, msg=repr(reason)):
                set_policy('prescriptions', keep_days=1200, user=self.admin, reason=reason)
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    def test_user_is_required(self):
        with self.assertRaises(PolicyRefused):
            set_policy('prescriptions', keep_days=1200, user=None, reason='x')

    def test_unknown_rule_and_mode_are_refused(self):
        with self.assertRaises(PolicyRefused):
            set_policy('no_such_rule', mode='off', user=self.admin, reason='x')
        with self.assertRaises(PolicyRefused):
            set_policy('prescriptions', mode='sometimes', user=self.admin, reason='x')

    def test_nothing_to_change_is_refused(self):
        with self.assertRaises(PolicyRefused):
            set_policy('prescriptions', user=self.admin, reason='x')

    def test_long_reason_is_audited_in_full(self):
        reason = 'س' * 400
        set_policy('prescriptions', keep_days=1200, user=self.admin, reason=reason)
        log = AuditLog.objects.get(action=policy.AUDIT_ACTION)
        self.assertEqual(log.extra['reason'], reason)
        self.assertEqual(len(log.note), 255)

    def test_change_is_undone_when_the_audit_row_cannot_be_written(self):
        """Rule 8: AuditLog.log swallows its own failures, so a silent unaudited change must not stick."""
        with mock.patch.object(AuditLog, 'log', return_value=None):
            with self.assertRaises(PolicyRefused):
                set_policy('prescriptions', keep_days=1200, user=self.admin, reason='x')
        self.assertFalse(LifecycleRulePolicy.objects.exists())


class ModelTests(PolicyTestBase):
    def test_held_file_lists_every_cleared_reference(self):
        now = timezone.now()
        held = HeldFile.objects.create(
            original_path='reservations/2024/01/a.jpg', hold_path='prescriptions/a.jpg', rule_key='prescriptions',
            size=5, sha256='0' * 64, purge_after=now, primary_model='reservations.Reservation', primary_pk='7',
            primary_field='image',
            rows=[{'model': 'reservations.Reservation', 'pk': 7, 'field': 'image', 'value': 'reservations/2024/01/a.jpg'}])
        held.refresh_from_db()
        self.assertEqual(held.rows[0]['pk'], 7)
        self.assertIsNotNone(held.moved_at)
        self.assertIsNone(held.restored_at)

    def test_held_file_is_not_in_django_admin(self):
        from django.contrib import admin
        self.assertFalse(admin.site.is_registered(HeldFile))
