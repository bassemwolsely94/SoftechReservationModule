from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.tests.factories import make_branch
from apps.rpa.models import RpaDocument, RpaJob, RpaRecipe, RpaRun, RpaScreen
from apps.users.models import StaffProfile


class RpaModelsTests(TestCase):
    def _staff(self):
        user = get_user_model().objects.create_user(username='rpa_t2', password='x')
        return StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]

    def _job(self):
        branch = make_branch('T2', 'T2')
        return RpaJob.objects.create(screen=RpaScreen.objects.get(key='issue_125'), branch=branch,
                                     created_by=self._staff())

    def test_screens_seeded_off(self):
        screens = RpaScreen.objects.all()
        self.assertEqual(screens.count(), 4)
        self.assertEqual({s.key for s in screens}, {'issue_125', 'stockcount', 'purchase_10', 'return_120'})
        self.assertFalse(any(s.enabled or s.live for s in screens))

    def test_reference_format(self):
        doc = RpaDocument.objects.create(job=self._job(), seq=1)
        self.assertEqual(doc.reference, f'RPA-{doc.pk}')

    def test_approved_recipe_is_immutable(self):
        recipe = RpaRecipe.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), version=1, status='approved',
            created_by=self._staff(), line_cells=[{'kind': 'field', 'value': 'itemcode'}])
        recipe.line_cells = []
        with self.assertRaisesMessage(ValidationError, 'recipe is immutable once approved'):
            recipe.save()
        recipe = RpaRecipe.objects.get(pk=recipe.pk)
        recipe.status = 'retired'          # status alone may move
        recipe.save()
        self.assertEqual(RpaRecipe.objects.get(pk=recipe.pk).status, 'retired')

    def test_approved_recipe_keeps_its_last_editor(self):
        # the editor is the four-eyes evidence: frozen with the content once approved
        staff = self._staff()
        recipe = RpaRecipe.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), version=1, status='approved',
            created_by=staff, edited_by=staff)
        recipe.edited_by = None
        with self.assertRaisesMessage(ValidationError, 'recipe is immutable once approved'):
            recipe.save()
        self.assertEqual(RpaRecipe.objects.get(pk=recipe.pk).edited_by_id, staff.id)

    def test_draft_recipe_is_editable(self):
        recipe = RpaRecipe.objects.create(screen=RpaScreen.objects.get(key='issue_125'), version=1,
                                          created_by=self._staff())
        recipe.line_cells = [{'kind': 'keys', 'value': '{TAB}'}]
        recipe.save()
        self.assertEqual(RpaRecipe.objects.get(pk=recipe.pk).line_cells[0]['value'], '{TAB}')

    def test_approved_recipe_cannot_go_back_to_draft(self):
        recipe = RpaRecipe.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), version=1, status='approved',
            created_by=self._staff())
        recipe.status = 'draft'
        with self.assertRaisesMessage(ValidationError, 'recipe is immutable once approved'):
            recipe.save()
        self.assertEqual(RpaRecipe.objects.get(pk=recipe.pk).status, 'approved')

    def test_retired_recipe_stays_retired(self):
        recipe = RpaRecipe.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), version=1, status='retired',
            created_by=self._staff())
        recipe.status = 'draft'
        with self.assertRaisesMessage(ValidationError, 'recipe is immutable once approved'):
            recipe.save()

    def test_float_decimal_equality_does_not_false_alarm(self):
        recipe = RpaRecipe.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), version=1, status='approved',
            created_by=self._staff())
        recipe.cell_delay = 0.2          # same value as the stored Decimal('0.20')
        recipe.save()
