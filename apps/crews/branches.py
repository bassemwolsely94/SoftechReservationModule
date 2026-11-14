"""
apps/crews/branches.py

The one place crews decide which branches are live (rule pickers, reports).
"""
from apps.branches.models import Branch


def live_branches():
    return Branch.objects.live()
