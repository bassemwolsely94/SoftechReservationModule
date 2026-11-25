"""/api/help/glossary/audit/ («طبّق القاموس على الكل», report budget): the same queries with 1 or 13
glossary terms and 0 or 12 trainer-edited screens. Terms, screen edits, workflow-tour and quiz edits
are each read once for the whole check; the help text itself comes from the code, not the database."""
from django.test import TestCase

from apps.help import registry
from apps.help.models import HelpGlossaryTerm, HelpOverride

from ..factories import make_admin
from .budget import assert_budget

# words the current help text uses on many screens, so growing the glossary grows the result
COMMON = ['الشاشة', 'اضغط', 'العميل', 'الصنف', 'الفرع', 'الحالة', 'القائمة', 'التفاصيل', 'الجدول',
          'البحث', 'الطلب', 'الكمية']


class GlossaryAuditBudget(TestCase):
    def setUp(self):
        _, self.admin, self.client_ = make_admin('perf_gl_admin')
        HelpGlossaryTerm.objects.create(preferred='الكاشير', avoid=['الخزنة'])

    def _grow(self):
        for i, w in enumerate(COMMON):
            HelpGlossaryTerm.objects.create(preferred=f'كلمة{i}', avoid=[w])
        _, screens = registry.load()
        for k in list(screens)[:12]:
            HelpOverride.objects.create(screen_key=k, data={'summary': {'ar': 'اضغط هنا في الشاشة', 'en': 'x'}},
                                        updated_by=self.admin)

    def test_glossary_audit(self):
        assert_budget(self, 'help/glossary/audit', self.client_, '/api/help/glossary/audit/',
                      grow=self._grow, min_rows=12, rows_of=lambda r: len(r.data['items']))
