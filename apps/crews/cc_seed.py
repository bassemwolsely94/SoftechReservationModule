"""
apps/crews/cc_seed.py

Seeds the call-center crew «الكول سنتر» from CallCenterConfig (piece 2b). One dated, open-ended
manual include row per SOFTECH usercode and per PBX extension, starting the first day of the
earliest month with a CC KpiActualRollup so history resolves. Active PBX extensions typed «agent»
that CallCenterConfig does not list join too, dated with the seed (owner ruling C, 2026-11-18;
opt out with include_pbx_agent_extensions=False). The rows are written directly (not through
services.add_manual, whose month floor refuses past dates) and the seed is audited.
No SOFTECH access.
"""
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.hr.attendance.employee_import import normalise_code
from apps.hr.models import Employee

from .models import Crew, CrewManualMember


class CcCrewNameTaken(Exception):
    """A live crew of another type already holds the call-center crew's name."""


CC_CREW_NAME = 'الكول سنتر'
SEED_REASON = 'بذرة الكول سنتر من إعداد الكول سنتر (piece 2b)'


def _find_crew():
    """The live call-center crew, or None. A live crew of another type with the name is refused,
    never adopted."""
    crew = Crew.objects.filter(name=CC_CREW_NAME, is_archived=False).first()
    if crew is not None and crew.type != 'call_center':
        raise CcCrewNameTaken(f'يوجد طاقم نشط باسم «{CC_CREW_NAME}» من نوع آخر ({crew.type}) — '
                              f'غيّر اسمه أو أرشفه قبل البذر.')
    return crew


def seed_start() -> date:
    from apps.forecasting.call_center import legacy_cc_branch
    from apps.forecasting.models import KpiActualRollup
    cc = legacy_cc_branch()
    if cc is not None:
        first = (KpiActualRollup.objects.filter(branch=cc).order_by('year', 'month')
                 .values_list('year', 'month').first())
        if first:
            return date(first[0], first[1], 1)
    return timezone.localdate().replace(day=1)


def _num_key(v):
    s = str(v)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def extra_pbx_agent_extensions() -> list:
    """Active PBX extensions typed «agent» that CallCenterConfig does not list, sorted numerically."""
    from apps.forecasting.models import CallCenterConfig
    from apps.pbx.models import AgentExtension
    cfg = {str(e) for e in CallCenterConfig.get_solo().call_agent_extensions}
    exts = {str(e) for e in AgentExtension.objects.filter(
        extension_type=AgentExtension.TYPE_AGENT, is_active=True).values_list('extension', flat=True)}
    return sorted(exts - cfg, key=_num_key)


def _employee_by_usercode(code):
    found = list(Employee.objects.filter(softech_usercode=code)[:2])
    return found[0] if len(found) == 1 else None


def _employee_by_extension(ext):
    found = [e for e in Employee.objects.exclude(pbx_extensions=[]) if ext in (e.pbx_extensions or [])]
    return found[0] if len(found) == 1 else None


def seed_plan(include_pbx_agent_extensions=True) -> list:
    from apps.forecasting.models import CallCenterConfig
    cfg = CallCenterConfig.get_solo()
    plan = []
    for raw in cfg.sales_agent_usercodes or []:
        code = normalise_code(raw)
        if not code:
            continue
        emp = _employee_by_usercode(code)
        plan.append({'kind': 'usercode', 'value': code, 'employee_id': emp.pk if emp else None,
                     'label': '' if emp else f'مندوب {code}'})
    exts = [str(e).strip() for e in cfg.call_agent_extensions or [] if str(e).strip()]
    if include_pbx_agent_extensions:
        exts += extra_pbx_agent_extensions()
    for ext in exts:
        emp = _employee_by_extension(ext)
        plan.append({'kind': 'extension', 'value': ext, 'employee_id': emp.pk if emp else None,
                     'label': '' if emp else f'داخلي {ext}'})
    return plan


def _existing(crew, item) -> bool:
    field = 'softech_usercode' if item['kind'] == 'usercode' else 'pbx_extension'
    return crew.manual_members.filter(mode='include', valid_to__isnull=True, voided_at__isnull=True,
                                      **{field: item['value']}).exists()


@transaction.atomic
def seed(user=None, include_pbx_agent_extensions=True, dry_run=False, _action='crew_cc_seeded',
         _old=None) -> dict:
    plan = seed_plan(include_pbx_agent_extensions)
    start = seed_start()
    crew = _find_crew()
    created, skipped = [], []
    if dry_run:
        for item in plan:
            (skipped if crew and _existing(crew, item) else created).append(item)
        return {'crew_id': crew.pk if crew else None, 'created': created, 'skipped': skipped,
                'start': start}
    if crew is None:
        crew = Crew.objects.create(name=CC_CREW_NAME, type='call_center', created_by=user,
                                   updated_by=user, description='بذرة من إعداد الكول سنتر')
    for item in plan:
        if _existing(crew, item):
            skipped.append(item)
            continue
        CrewManualMember.objects.create(
            crew=crew, mode='include', employee_id=item['employee_id'],
            softech_usercode=item['value'] if item['kind'] == 'usercode' else '',
            pbx_extension=item['value'] if item['kind'] == 'extension' else '',
            label=item['label'], reason=SEED_REASON, valid_from=start, created_by=user)
        created.append(item)
    if created or _action != 'crew_cc_seeded':      # an all-skipped re-run writes no audit row
        AuditLog.log(_action, user=user, obj=crew, old_data=_old,
                     new_data={'created': created, 'skipped': skipped, 'start': start.isoformat()},
                     extra={'crew_id': crew.pk, 'row': None, 'row_id': None})
    return {'crew_id': crew.pk, 'created': created, 'skipped': skipped, 'start': start}


def _row_snapshot(r) -> dict:
    def d(v):
        return v.isoformat() if v else None
    return {'id': r.pk, 'mode': r.mode, 'employee_id': r.employee_id,
            'softech_usercode': r.softech_usercode, 'pbx_extension': r.pbx_extension,
            'label': r.label, 'valid_from': d(r.valid_from), 'valid_to': d(r.valid_to),
            'voided_at': d(r.voided_at), 'reason': r.reason}


@transaction.atomic
def reseed(user=None, **kw) -> dict:
    """Delete ONLY the seed's own manual rows (reason == SEED_REASON; rows added by hand survive),
    then seed again. The deleted rows are recorded as old_data on the 'crew_cc_reseeded' audit
    entry. The crew's KpiActualRollup rows are the board's figures (Part B) and are kept;
    build_crew_rollups refreshes them."""
    crew = _find_crew()
    old = {'deleted_rows': []}
    if crew is not None:
        rows = list(crew.manual_members.filter(reason=SEED_REASON))
        old['deleted_rows'] = [_row_snapshot(r) for r in rows]
        CrewManualMember.objects.filter(pk__in=[r.pk for r in rows]).delete()
    return seed(user=user, _action='crew_cc_reseeded', _old=old, **kw)
