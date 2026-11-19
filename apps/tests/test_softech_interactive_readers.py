"""
Screens that read SOFTECH live while a person waits use the fail-fast connect (interactive=True):
one 5 s attempt, and a node that failed a moment ago is skipped (design
docs/superpowers/specs/2026-11-19-softech-interactive-connect-design.md, follow-up of PR 240).

This pins the rule per module: every get_sybase_connection / get_branch_connection call in these
read-only web modules passes interactive=True. Writer paths (finance reconciliation, discount
approvals, the POS / insurance re-price writers) are deliberately not in this list: they keep the
default profile with retries.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]

# module → reason it is a read made while someone waits
INTERACTIVE_READ_MODULES = {
    'apps/usage_print/lookup.py': 'invoice lookup for the usage slip',
    'apps/catalog/views.py': 'live item search fallback (has its own 5-minute breaker too)',
    'apps/delivery/views.py': 'CRM order items and customer location fallbacks',
    'apps/transfers/views.py': 'transfer document check before linking',
    'apps/purchasing/isr_views.py': 'READ-ONLY review of an ISR push before the push',
    'apps/vouchers/coupon_views.py': 'blocked-expiry read before generating a coupon batch (fail-closed)',
    'apps/insurance/views.py': 'contract persons list, claim search and import listing (reads)',
}
CONNECTS = {'get_sybase_connection', 'get_branch_connection'}


def _connect_calls(path):
    tree = ast.parse((REPO / path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', None)
            if name in CONNECTS:
                yield node


def _is_interactive(call):
    for kw in call.keywords:
        if kw.arg == 'interactive':
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


class InteractiveReadersTests(SimpleTestCase):

    def test_every_live_read_in_screen_modules_is_interactive(self):
        missing = []
        for path in INTERACTIVE_READ_MODULES:
            calls = list(_connect_calls(path))
            self.assertTrue(calls, f'{path}: no SOFTECH connect found — update this list')
            missing += [f'{path}:{c.lineno}' for c in calls if not _is_interactive(c)]
        self.assertEqual(missing, [], 'these screen reads still use the slow sync connect profile')

    def test_writer_modules_keep_the_default_profile(self):
        for path in ('apps/finance/recon_views.py', 'apps/discount_approvals/views.py'):
            calls = list(_connect_calls(path))
            self.assertTrue(calls, path)
            self.assertFalse([c.lineno for c in calls if _is_interactive(c)],
                             f'{path}: writer paths must keep retries (not interactive)')
