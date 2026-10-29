"""
Authorization — `export` is not a write grant (Batch 4, Z-11a; overblock review decision 1).

Before: the middleware let a POST through with any of create / edit / approve / assign / finalize
/ export, so a role holding only view + export (quality manager on chronic, follow-ups,
reservations, call center, demand, transfers …; purchasing on customers, delivery, stock count …)
passed it on every write and the view refused — 204 overblock lines, and a matrix that over-states
what those roles can do.

Now: a POST needs a real write grant. The POST endpoints that only build an export (the transit
picking / stocking sheets) keep taking export, and QA inspections keep their view's rule (the
quality manager files them with hr view + export — Z-9c).
"""
from django.test import SimpleTestCase

from core.middleware.module_access import required



class ExportIsNotAWriteTests(SimpleTestCase):

    def test_a_plain_post_does_not_accept_export(self):
        for path in ('/api/chronic/profiles/', '/api/followups/tasks/', '/api/customers/',
                     '/api/delivery/', '/api/demand/', '/api/transfers/'):
            module, actions = required(path, 'POST')
            self.assertNotIn('export', actions, path)
            self.assertIn('create', actions, path)

    def test_post_exports_still_accept_export(self):
        for path in ('/api/transits/export-picking/', '/api/transits/export-stocking/'):
            module, actions = required(path, 'POST')
            self.assertEqual(module, 'transfers', path)
            self.assertIn('export', actions, path)

    def test_qa_inspections_keep_their_views_rule(self):
        module, actions = required('/api/qa/inspections/', 'POST')
        self.assertEqual(module, 'hr')
        self.assertIn('export', actions)
