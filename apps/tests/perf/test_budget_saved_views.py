"""C23 — /api/personal/saved-views/ (list budget): the same queries with 2 or 27 views, own and shared
by colleagues of the same role (their owner's name is select_related, not one query per row)."""
from django.test import TestCase

from apps.personal.models import SavedView

from ..factories import make_branch, make_pharmacist
from .budget import assert_budget


class SavedViewsBudget(TestCase):
    def setUp(self):
        self.n = 0
        branch = make_branch()
        _, self.me, self.client_ = make_pharmacist('perf_sv_me', branch=branch)
        _, self.colleague, _ = make_pharmacist('perf_sv_colleague', branch=branch)

    def _views(self, n=25):
        for _ in range(n):
            self.n += 1
            SavedView.objects.create(staff=self.me if self.n % 2 else self.colleague, screen='transits',
                                     name=f'عرض {self.n}', filters={'transit_status': ['in_transit']},
                                     shared_role=self.colleague.role)

    def test_saved_views_list(self):
        self._views(2)
        assert_budget(self, 'personal/saved-views', self.client_, '/api/personal/saved-views/?screen=transits',
                      grow=self._views, min_rows=25, rows_of=lambda r: len(r.data['results']))
