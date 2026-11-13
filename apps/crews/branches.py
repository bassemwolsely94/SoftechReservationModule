"""
apps/crews/branches.py

The one place crews decide which branches are live (rule pickers, reports).
"""
from apps.branches.models import Branch


def live_branches():
    # piece 1 swaps this for Branch.objects.live()
    return Branch.objects.filter(kind__in=['hq', 'retail'])
