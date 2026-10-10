"""
Help content — one file per module. Order here = order in the help center.

When you add or change a screen, tab or status, update the matching file here in the
same change (apps/tests/test_help.py fails when a route in frontend/src/App.jsx has no
help, or when a model status is not explained).
"""


def T(ar, en):
    """One bilingual text."""
    return {'ar': ar, 'en': en}


MODULE_FILES = [
    'general',
    'reservations', 'demand', 'transfers', 'followups', 'delivery', 'stockcount', 'tasks',
]
