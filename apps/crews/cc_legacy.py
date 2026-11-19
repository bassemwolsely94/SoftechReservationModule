"""
apps/crews/cc_legacy.py

The fake «Call Center» branch (softech_branch_id 'CC') — read only by the one-shot switch tools:
the crew seed (its first rollup month dates the seed), the old-vs-crew comparison (its stored
figures, targets and forecasts) and the call-center switch that re-points its rows to the crew
and closes it. Every KPI / target / forecast reader uses
apps.forecasting.call_center.call_center_crew() instead (crews piece 2b Part B). This file is
the only place outside migrations and tests allowed to name the key (test_crews_cc_readers).
"""

LEGACY_CC_KEY = 'CC'


def legacy_cc_branch():
    from apps.branches.models import Branch
    return Branch.objects.filter(softech_branch_id=LEGACY_CC_KEY).first()
