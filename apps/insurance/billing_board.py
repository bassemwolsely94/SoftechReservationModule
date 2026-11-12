"""
«فئات الفوترة» board: every receipt of a claim (prescriptions, manual receipts,
non-standalone supplements) with the فئة فوترة it sits in, the groups' live totals
and a balance check (groups + unassigned = claim), plus assignment that never moves
a receipt out of another group silently.

Rows are keyed 'p<id>' (prescription), 'm<id>' (manual receipt), 's<id>' (supplement).
Excluded receipts are out of the claim: never offered, only counted.
"""
from decimal import Decimal

from django.db import transaction

from .audit import record_audit
from .models import (InsuranceClaimBillingGroup, InsuranceClaimManualRx, InsuranceClaimPrescription,
                     InsuranceClaimSupplement)

_KINDS = (('p', InsuranceClaimPrescription), ('m', InsuranceClaimManualRx), ('s', InsuranceClaimSupplement))


def _f(v):
    return float(v or 0)


def _live(claim):
    """The three querysets of receipts that can sit in a group (not excluded)."""
    return {
        'p': InsuranceClaimPrescription.objects.filter(claim=claim, exclusion__isnull=True),
        'm': InsuranceClaimManualRx.objects.filter(claim=claim, is_excluded=False),
        's': InsuranceClaimSupplement.objects.filter(claim=claim, is_excluded=False)
                                     .exclude(supplement_type='standalone'),
    }


def build_board(claim):
    groups = list(InsuranceClaimBillingGroup.objects.filter(claim=claim).order_by('sort_order', 'code'))
    for g in groups:
        g.refresh_totals()
    live = _live(claim)
    rows = []
    for rx in live['p'].order_by('sequence', 'softech_docdate', 'id'):
        rows.append({
            'key': f'p{rx.id}', 'kind': 'rx', 'id': rx.id, 'sequence': rx.sequence,
            'docnumber': rx.softech_docnumber, 'branch': rx.softech_branchcode,
            'date': rx.softech_docdate, 'patient_name': rx.patient_name,
            'relative_degree': rx.relative_degree, 'dept_name': rx.dept_name, 'patient_no': rx.patient_no,
            'gross_before': _f(rx.gross_before), 'net_after': _f(rx.net_after), 'group_id': rx.billing_group_id,
        })
    for m in live['m'].order_by('sequence', 'softech_docdate', 'id'):
        rows.append({
            'key': f'm{m.id}', 'kind': 'manual', 'id': m.id, 'sequence': m.sequence,
            'docnumber': m.softech_docnumber, 'branch': m.softech_branchcode,
            'date': m.softech_docdate, 'patient_name': m.patient_name,
            'relative_degree': '', 'dept_name': '', 'patient_no': '',
            'gross_before': _f(m.gross_before), 'net_after': _f(m.net_after), 'group_id': m.billing_group_id,
        })
    for s in live['s'].order_by('sort_order', 'id'):
        rows.append({
            'key': f's{s.id}', 'kind': 'sup', 'id': s.id, 'sequence': None,
            'docnumber': s.supplement_number, 'branch': '', 'date': s.print_date,
            'patient_name': s.label, 'relative_degree': '', 'dept_name': '', 'patient_no': '',
            'gross_before': _f(s.gross_before), 'net_after': _f(s.net_after), 'group_id': s.billing_group_id,
            'rx_count': s.rx_count,
        })

    total = sum((Decimal(str(r['net_after'])) for r in rows), Decimal('0'))
    unassigned = [r for r in rows if not r['group_id']]
    un_net = sum((Decimal(str(r['net_after'])) for r in unassigned), Decimal('0'))
    groups_net = sum((g.net_after for g in groups), Decimal('0'))
    return {
        'locked': claim.is_locked,
        'groups': [{
            'id': g.id, 'code': g.code, 'name': g.name, 'description': g.description,
            'filter_relative_degree': g.filter_relative_degree, 'filter_dept_name': g.filter_dept_name,
            'filter_hi_type_code': g.filter_hi_type_code, 'filter_patient_no_prefix': g.filter_patient_no_prefix,
            'rx_count': g.rx_count, 'row_count': sum(1 for r in rows if r['group_id'] == g.id),
            'gross_before': _f(g.gross_before), 'total_discount': _f(g.total_discount),
            'net_after': _f(g.net_after), 'sort_order': g.sort_order,
        } for g in groups],
        'rows': rows,
        'totals': {
            'rows': len(rows), 'net': _f(total),
            'groups_net': _f(groups_net), 'unassigned_count': len(unassigned), 'unassigned_net': _f(un_net),
            'excluded_count': InsuranceClaimPrescription.objects.filter(claim=claim, exclusion__isnull=False).count()
            + InsuranceClaimManualRx.objects.filter(claim=claim, is_excluded=True).count(),
            'claim_net': _f(claim.final_net_after),
            # every live receipt sits in one group or none → groups + unassigned always = rows total
            'balanced': abs((groups_net + un_net) - total) < Decimal('0.05'),
        },
    }


def _pick(claim, ids):
    """{'p': qs, 'm': qs, 's': qs} limited to the given ids (live receipts of this claim only)."""
    live = _live(claim)
    return {k: live[k].filter(id__in=[int(i) for i in ids.get(k) or []]) for k, _m in _KINDS}


def assign(group, ids, *, move=False, actor=None):
    """Put receipts into `group`. ids = {'p': [...], 'm': [...], 's': [...]}.
    Receipts already in ANOTHER group are moved only with move=True; otherwise nothing
    changes and they come back as conflicts. Returns (assigned, conflicts)."""
    picked = _pick(group.claim, ids)
    names = dict(InsuranceClaimBillingGroup.objects.filter(claim=group.claim).values_list('id', 'name'))
    conflicts = []
    for k, qs in picked.items():
        for r in qs.filter(billing_group__isnull=False).exclude(billing_group=group):
            conflicts.append({'key': f'{k}{r.id}', 'group_id': r.billing_group_id,
                              'group': names.get(r.billing_group_id, ''),
                              'docnumber': getattr(r, 'softech_docnumber', None) or getattr(r, 'supplement_number', ''),
                              'patient_name': getattr(r, 'patient_name', None) or getattr(r, 'label', '')})
    if conflicts and not move:
        return 0, conflicts
    with transaction.atomic():
        sources = set()
        assigned, moved = 0, 0
        for k, qs in picked.items():
            todo = qs.exclude(billing_group=group)
            sources |= set(todo.exclude(billing_group__isnull=True).values_list('billing_group_id', flat=True))
            moved += todo.filter(billing_group__isnull=False).count()
            assigned += todo.update(billing_group=group)
        group.refresh_totals()
        for g in InsuranceClaimBillingGroup.objects.filter(id__in=sources):
            g.refresh_totals()
    if assigned:
        record_audit(group.claim, 'billing_group', actor=actor, target_type='billing_group', target_ref=group.code,
                     summary=f'فئة فوترة {group.name}: أُضيف {assigned}' + (f' (منها {moved} نُقلت من فئة أخرى)' if moved else ''),
                     meta={'group_id': group.id, 'ids': {k: list(map(int, v or []))[:300] for k, v in ids.items()},
                           'moved_from': sorted(sources)})
    return assigned, conflicts


def unassign(group, ids=None, *, actor=None):
    """Take receipts out of `group` (all of them when ids is None)."""
    live = _live(group.claim)
    # excluded receipts leave too — they must never hold a group
    all_qs = {'p': InsuranceClaimPrescription.objects.filter(claim=group.claim),
              'm': InsuranceClaimManualRx.objects.filter(claim=group.claim),
              's': InsuranceClaimSupplement.objects.filter(claim=group.claim)}
    n = 0
    with transaction.atomic():
        for k, _m in _KINDS:
            qs = (all_qs if ids is None else live)[k].filter(billing_group=group)
            if ids is not None:
                qs = qs.filter(id__in=[int(i) for i in ids.get(k) or []])
            n += qs.update(billing_group=None)
        group.refresh_totals()
    if n:
        record_audit(group.claim, 'billing_group', actor=actor, target_type='billing_group', target_ref=group.code,
                     summary=f'فئة فوترة {group.name}: أُلغى تخصيص {n}',
                     meta={'group_id': group.id, 'all': ids is None})
    return n
