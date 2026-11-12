"""
Data lifecycle Stage 5, Task 1: the daily DataHealthSnapshot, the media scan and the problem counts.
No SOFTECH involved; customer data is counts only.
"""
import dataclasses
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.customers.models import Customer
from apps.data_lifecycle import health, problems
from apps.data_lifecycle.models import DataHealthSnapshot
from apps.data_lifecycle.references import Ref
from apps.followups.models import FollowUpTask
from apps.supply.models import SupplyCase

from .factories import make_item


def _write(root, rel, size):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)


class ScanMediaTests(TestCase):
    def test_scan_media_groups_by_folder_and_type(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            _write(root, 'logos/a.png', 100)
            _write(root, 'orphans/b.png', 50)
            _write(root, 'invoice_bundles/pages/batch_1/p1.png', 10)
            index = {'logos/a.png': {Ref('branches.Branch', 1, 'logo', 'logos/a.png')}}
            total, files, by_folder, by_type = health.scan_media(index)
        self.assertEqual((total, files), (160, 3))
        self.assertEqual(set(by_folder), {'logos', 'orphans', 'invoice_bundles/pages'})
        self.assertEqual(by_folder['logos'], {'bytes': 100, 'files': 1})
        self.assertEqual(by_type['branches.Branch.logo'], {'bytes': 100, 'files': 1})
        self.assertEqual(by_type['unreferenced']['files'], 2)

    def test_scan_media_missing_root_is_zero(self):
        with override_settings(MEDIA_ROOT='/no/such/media/root'):
            self.assertEqual(health.scan_media({}), (0, 0, {}, {}))


class ProblemCountTests(TestCase):
    def _customers(self, *phones):
        Customer.objects.bulk_create([Customer(name=f'c{i}', phone=p) for i, p in enumerate(phones)])

    def test_count_all_survives_one_failure(self):
        self._customers('01011112222', '01011112222')
        broken = problems.PROBLEMS[1]
        patched = tuple(dataclasses.replace(p, count=mock.Mock(side_effect=ValueError('01011112222')))
                        if p is broken else p for p in problems.PROBLEMS)
        with mock.patch.object(problems, 'PROBLEMS', patched), \
                self.assertLogs('elrezeiky.sync', level='ERROR') as logs:
            result = problems.count_all()
        self.assertIsNone(result[broken.key])
        self.assertEqual(result['customers_shared_phone'], 2)
        self.assertTrue(all(isinstance(v, int) for k, v in result.items() if k != broken.key))
        self.assertNotIn('01011112222', '\n'.join(logs.output))
        self.assertIn(broken.key, '\n'.join(logs.output))

    def test_shared_phone_counts_rows_not_groups(self):
        self._customers('01011112222', '01011112222', '01011112222', '01199998888', '01199998888x', '')
        self._customers('01299990000')
        self.assertEqual(problems._shared_phone(), 3)

    def test_bad_phone_format(self):
        self._customers('01012345678', '0212345678', '1234', '', '01512345678', '01312345678')
        self.assertEqual(problems._bad_phone(), 3)

    def test_followups_missed_only_past_90_days(self):
        today = timezone.localdate()
        for status, days in [('missed', 100), ('missed', 10), ('pending', 200)]:
            FollowUpTask.objects.create(status=status, due_date=today - timedelta(days=days))
        self.assertEqual(problems._followups_missed(), 1)

    def test_supply_open_excludes_terminal(self):
        item, other, third = make_item(), make_item('صنف ب', 'IT002'), make_item('صنف ج', 'IT003')
        old = timezone.now() - timedelta(days=120)
        open_case = SupplyCase.objects.create(item=item, status=SupplyCase.STATUS_DETECTED)
        done = SupplyCase.objects.create(item=other, status=SupplyCase.STATUS_FULFILLED)
        recent = SupplyCase.objects.create(item=third, status=SupplyCase.STATUS_SEARCHING)
        SupplyCase.objects.filter(pk__in=[open_case.pk, done.pk]).update(first_detected_at=old)
        self.assertEqual(problems._supply_open(), 1)     # `recent` is open but too new

    def test_every_count_runs_on_a_real_database(self):
        # count_all swallows errors, so a wrong field name would only ever show «—». Pin that none fails.
        counts = problems.count_all()
        self.assertEqual(set(counts), {p.key for p in problems.PROBLEMS})
        for key, value in counts.items():
            self.assertIsNotNone(value, key)


class TakeSnapshotTests(TestCase):
    def test_take_snapshot_same_day_updates_one_row(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            _write(root, 'x/a.bin', 10)
            first = health.take_snapshot()
            _write(root, 'x/b.bin', 20)
            second = health.take_snapshot()
        self.assertEqual(DataHealthSnapshot.objects.count(), 1)
        self.assertEqual(first.pk, second.pk)
        second.refresh_from_db()
        self.assertEqual(second.media_files, 2)
        self.assertEqual(second.media_bytes, 30)
        self.assertGreater(second.db_bytes, 0)
        self.assertIn('customers_shared_phone', second.problems)

    def test_take_snapshot_never_raises(self):
        with mock.patch.object(health, 'scan_media', side_effect=RuntimeError('boom')), \
                self.assertLogs('elrezeiky.sync', level='ERROR'):
            self.assertIsNone(health.take_snapshot())
        self.assertEqual(DataHealthSnapshot.objects.count(), 0)

    def test_daily_retention_has_data_health_step(self):
        from apps.sync import maintenance
        seen = []
        with mock.patch.object(maintenance, '_run_retention_steps',
                               side_effect=lambda steps: seen.extend(name for name, _ in steps)):
            maintenance.run_daily_retention()
        self.assertIn('retention:data_health', seen)
        self.assertEqual(seen.index('retention:data_health'), seen.index('retention:purge_held') + 1)
