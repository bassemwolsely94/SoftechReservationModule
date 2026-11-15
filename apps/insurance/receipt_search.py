"""
«بحث برقم الروشتة» — where a SOFTECH receipt sits across our insurance claims.

Read-only. Looks at imported prescriptions, both kinds of manual additions and the local
MotalbaCache mirror (last ~90 days of SOFTECH motalba rows) — never a live SOFTECH query.

SOFTECH numbers receipts per branch, so the same number can be two different receipts:
results are grouped by (docnumber, branch) and never merged across branches.
"""
from .models import (InsuranceAuditEvent, InsuranceClaimManualRx, InsuranceClaimPrescription,
                     MotalbaCache)

MAX_RECEIPTS = 50


def _who(staff):
    return staff.full_name if staff is not None else ''


def _claim_bits(claim):
    sub = claim.subclient
    return {
        'claim_id': claim.id,
        'claim_number': claim.claim_number,
        'client_name': sub.client.name if sub and sub.client_id else '',
        'subclient_name': sub.name if sub else '',
        'claim_status': claim.status,
        'claim_status_label': claim.get_status_display(),
        'softech_motalba_no': claim.softech_motalba_no or '',
    }


def find_receipt(docnumber, branch=None):
    """Every place receipt `docnumber` (optionally in `branch`) appears. See module docstring."""
    docnumber = (docnumber or '').strip()
    branch = (branch or '').strip() or None
    if not docnumber:
        return []

    groups = {}          # (docnumber, branch) → receipt dict, in first-seen order

    def group(branchcode, docdate, patient, net):
        key = (docnumber, branchcode or '')
        if key not in groups:
            groups[key] = {'docnumber': docnumber, 'branch': branchcode or '',
                           'docdate': docdate.isoformat() if docdate else None,
                           'patient_name': patient or '', 'net': str(net) if net is not None else None,
                           'appearances': [], 'softech': []}
        return groups[key]

    rxs = (InsuranceClaimPrescription.objects
           .filter(softech_docnumber=docnumber)
           .select_related('claim__subclient__client', 'exclusion__excluded_by', 'added_by')
           .order_by('-claim__period_from', 'claim_id'))
    manual = (InsuranceClaimManualRx.objects
              .filter(softech_docnumber=docnumber)
              .select_related('claim__subclient__client', 'added_by')
              .order_by('-claim__period_from', 'claim_id'))
    cache = MotalbaCache.objects.filter(docnumber=docnumber).order_by('-docdate', 'motalbano')
    if branch:
        rxs = rxs.filter(softech_branchcode=branch)
        manual = manual.filter(softech_branchcode=branch)
        cache = cache.filter(branchcode=branch)

    rxs = list(rxs[:MAX_RECEIPTS * 4])
    resynced = set(InsuranceAuditEvent.objects
                   .filter(action='resync_add', target_ref=docnumber,
                           claim_id__in={r.claim_id for r in rxs})
                   .values_list('claim_id', flat=True))

    for rx in rxs:
        excl = getattr(rx, 'exclusion', None)
        if rx.is_manual:
            origin, by, why = 'manual', _who(rx.added_by), rx.manual_reason
        elif rx.claim_id in resynced:
            origin, by, why = 'resync', '', ''
        else:
            origin, by, why = 'import', '', ''
        group(rx.softech_branchcode, rx.softech_docdate, rx.patient_name, rx.net_after)['appearances'].append({
            **_claim_bits(rx.claim), 'kind': 'rx', 'active': excl is None,
            'excluded_reason': excl.reason if excl else '',
            'excluded_by': _who(excl.excluded_by) if excl else '',
            'excluded_at': excl.excluded_at.isoformat() if excl else None,
            'origin': origin, 'origin_by': by, 'origin_reason': why or '',
        })

    for mrx in manual[:MAX_RECEIPTS * 4]:
        group(mrx.softech_branchcode, mrx.softech_docdate, mrx.patient_name, mrx.net_after)['appearances'].append({
            **_claim_bits(mrx.claim), 'kind': 'manual', 'active': not mrx.is_excluded,
            'excluded_reason': '', 'excluded_by': '', 'excluded_at': None,
            'origin': 'manual', 'origin_by': _who(mrx.added_by), 'origin_reason': mrx.reason or '',
        })

    for row in cache[:MAX_RECEIPTS * 4]:
        group(row.branchcode, row.docdate, '', None)['softech'].append({
            'motalbano': row.motalbano, 'personcode': row.personcode,
            'docdate': row.docdate.isoformat() if row.docdate else None, 'doccode': row.doccode,
        })

    return list(groups.values())[:MAX_RECEIPTS]
