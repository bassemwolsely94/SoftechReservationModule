"""
apps/forecasting/call_center.py

The one place that finds the legacy fake «Call Center» branch (softech_branch_id='CC').
Every CC reader calls legacy_cc_branch() so the lookup can later be pointed at the call-center
crew in one edit (crews piece 2b, Part B). Same rows as the old inline lookups.
"""

LEGACY_CC_KEY = 'CC'


def legacy_cc_branch():
    from apps.branches.models import Branch
    return Branch.objects.filter(softech_branch_id=LEGACY_CC_KEY).first()
