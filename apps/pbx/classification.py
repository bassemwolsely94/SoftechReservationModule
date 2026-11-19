"""
apps/pbx/classification.py

PBX extension typing from data, not code (crews spec 2026-11-13 section 5.6). Priority per extension:
  1. an extension identity of a live call_center crew on the day  -> agent   (source crew:<name>)
  2. an Employee.pbx_extensions entry -> hq / branch by the employee's dated assignment that day
     (source employee:<hr_number>). NOTE: this tier reads the CURRENT Employee.pbx_extensions,
     not the dated EmployeeAssignment.pbx_extensions; only the branch comes from the assignment.
  3. the owner-confirmed data file                                -> (source confirmed)
Within one tier, when two employees (or two crews) claim the same extension the FIRST claim is
kept — employees in hr_number order (text order), crews in name order — and the clash is
reported in `conflicts` ({extension, kept, dropped}); the command prints it for the owner.
Gateways are never touched. No SOFTECH access.
"""
import json
from datetime import date
from pathlib import Path

from django.db import transaction

from apps.audit.models import AuditLog
from apps.branches.models import Branch, HQNotConfigured, hq_code
from apps.crews.membership import identities
from apps.crews.models import Crew
from apps.hr.assignments import assignment_on
from apps.hr.models import Employee
from apps.pbx.models import AgentExtension

DATA_FILE = Path(__file__).parent / 'data' / 'confirmed_extension_types.json'
_TYPE = {'agent': AgentExtension.TYPE_AGENT, 'hq': AgentExtension.TYPE_HQ,
         'branch': AgentExtension.TYPE_BRANCH}


def _confirmed() -> dict:
    data = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    return {str(x): _TYPE[k] for k in _TYPE for x in data.get(k, [])}


def _claim(tier: dict, ext: str, hit: tuple, conflicts) -> None:
    """First claim in a tier wins; a different later claim is recorded as a conflict."""
    if ext not in tier:
        tier[ext] = hit
    elif tier[ext][1] != hit[1] and conflicts is not None:
        conflicts.append({'extension': ext, 'kept': tier[ext][1], 'dropped': hit[1]})


def proposed_types(today: date, conflicts: list | None = None) -> dict:
    """extension -> (type, source); the highest-priority source wins. Same-tier clashes are
    appended to `conflicts` when a list is given."""
    out = {x: (t, 'confirmed') for x, t in _confirmed().items()}

    try:
        hq = hq_code()
    except HQNotConfigured:
        hq = None
    retail = set(Branch.objects.retail().values_list('id', flat=True))
    hq_ids = set(Branch.objects.filter(softech_branch_id=hq).values_list('id', flat=True)) if hq else set()
    by_employee = {}
    for emp in Employee.objects.exclude(pbx_extensions=[]).order_by('hr_number'):
        a = assignment_on(emp.pk, today)
        if a is None or a.branch_id is None:
            continue
        t = (AgentExtension.TYPE_HQ if a.branch_id in hq_ids
             else AgentExtension.TYPE_BRANCH if a.branch_id in retail else None)
        if t:
            for x in emp.pbx_extensions or []:
                _claim(by_employee, str(x), (t, f'employee:{emp.hr_number}'), conflicts)
    out.update(by_employee)

    by_crew = {}
    for crew in Crew.objects.filter(type='call_center', is_archived=False).order_by('name'):
        for ident in identities(crew, today, today):
            if ident.kind == 'extension':
                _claim(by_crew, ident.value, (AgentExtension.TYPE_AGENT, f'crew:{crew.name}'),
                       conflicts)
    out.update(by_crew)
    return out


def classify(apply: bool, user=None, today: date | None = None, conflicts: list | None = None) -> list:
    """The change list [{extension, old, new, source}]; with apply, saves it and audits once.
    Same-tier clashes (two employees / two crews on one extension) go to `conflicts` when given."""
    from django.utils import timezone
    found = [] if conflicts is None else conflicts
    proposed = proposed_types(today or timezone.localdate(), found)
    exts = AgentExtension.objects.exclude(
        extension_type=AgentExtension.TYPE_GATEWAY).order_by('extension')
    changes = []
    with transaction.atomic():
        for ext in exts:
            hit = proposed.get(ext.extension)
            if not hit or hit[0] == ext.extension_type:
                continue
            changes.append({'extension': ext.extension, 'old': ext.extension_type,
                            'new': hit[0], 'source': hit[1]})
            if apply:
                ext.extension_type = hit[0]
                ext.save(update_fields=['extension_type', 'updated_at'])
        if apply and changes:
            AuditLog.log('pbx_extensions_classified', user=user,
                         new_data={'changes': changes, 'conflicts': found})
    return changes
