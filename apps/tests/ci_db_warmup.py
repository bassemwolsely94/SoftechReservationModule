"""
apps/tests/ci_db_warmup.py — builds the test database once for CI (not part of the normal suite).

The file name does not start with "test", so `manage.py test` never discovers it. CI runs it by label
with --keepdb: Django creates test_elrezeiky_db and applies every migration exactly as it does for a
normal run, keeps it, and CI saves a dump that each test shard restores (.github/workflows/ci.yml).
"""
from django.test import TestCase


class DatabaseIsBuilt(TestCase):
    databases = '__all__'

    def test_database_answers(self):
        from django.contrib.auth.models import User
        self.assertGreaterEqual(User.objects.count(), 0)
