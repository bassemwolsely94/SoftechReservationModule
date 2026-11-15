"""
«بحث برقم الروشتة» — where a SOFTECH receipt sits across our insurance claims.

Read-only. Looks at imported prescriptions, both kinds of manual additions and the local
MotalbaCache mirror (last ~90 days of SOFTECH motalba rows) — never a live SOFTECH query.

SOFTECH numbers receipts per branch, so the same number can be two different receipts:
results are grouped by (docnumber, branch) and never merged across branches.
"""
from datetime import date

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


def _build(rxs, manual, cache, keep=None):
    """Group prescription / manual / cache rows into receipts keyed (docnumber, branch).
    `keep`, when given, is the set of keys allowed (and their order)."""
    groups = {}

    def group(docno, branchcode, docdate, patient, net):
        key = (docno, branchcode or '')
        if keep is not None and key not in keep:
            return None
        g = groups.get(key)
        if g is None:
            g = groups[key] = {'docnumber': docno, 'branch': branchcode or '',
                               'docdate': docdate.isoformat() if docdate else None,
                               'patient_name': patient or '', 'net': str(net) if net is not None else None,
                               'appearances': [], 'softech': []}
        elif not g['patient_name'] and patient:
            g['patient_name'], g['net'] = patient, (str(net) if net is not None else None)
        return g

    rxs = list(rxs)
    resynced = set(InsuranceAuditEvent.objects
                   .filter(action='resync_add', target_ref__in={r.softech_docnumber for r in rxs},
                           claim_id__in={r.claim_id for r in rxs})
                   .values_list('claim_id', 'target_ref'))

    for rx in rxs:
        g = group(rx.softech_docnumber, rx.softech_branchcode, rx.softech_docdate, rx.patient_name, rx.net_after)
        if g is None:
            continue
        excl = getattr(rx, 'exclusion', None)
        if rx.is_manual:
            origin, by, why = 'manual', _who(rx.added_by), rx.manual_reason
        elif (rx.claim_id, rx.softech_docnumber) in resynced:
            origin, by, why = 'resync', '', ''
        else:
            origin, by, why = 'import', '', ''
        g['appearances'].append({
            **_claim_bits(rx.claim), 'kind': 'rx', 'active': excl is None,
            'excluded_reason': excl.reason if excl else '',
            'excluded_by': _who(excl.excluded_by) if excl else '',
            'excluded_at': excl.excluded_at.isoformat() if excl else None,
            'origin': origin, 'origin_by': by, 'origin_reason': why or '',
        })

    for mrx in manual:
        g = group(mrx.softech_docnumber, mrx.softech_branchcode, mrx.softech_docdate, mrx.patient_name, mrx.net_after)
        if g is None:
            continue
        g['appearances'].append({
            **_claim_bits(mrx.claim), 'kind': 'manual', 'active': not mrx.is_excluded,
            'excluded_reason': '', 'excluded_by': '', 'excluded_at': None,
            'origin': 'manual', 'origin_by': _who(mrx.added_by), 'origin_reason': mrx.reason or '',
        })

    for row in cache:
        g = group(row.docnumber, row.branchcode, row.docdate, '', None)
        if g is None:
            continue
        g['softech'].append({
            'motalbano': row.motalbano, 'personcode': row.personcode,
            'docdate': row.docdate.isoformat() if row.docdate else None, 'doccode': row.doccode,
        })

    out = list(groups.values())
    if keep is not None:
        order = {k: i for i, k in enumerate(keep)}
        out.sort(key=lambda g: order[(g['docnumber'], g['branch'])])
    return out[:MAX_RECEIPTS]


def _rx_qs():
    return (InsuranceClaimPrescription.objects
            .select_related('claim__subclient__client', 'exclusion__excluded_by', 'added_by')
            .order_by('-claim__period_from', 'claim_id'))


def _manual_qs():
    return (InsuranceClaimManualRx.objects
            .select_related('claim__subclient__client', 'added_by')
            .order_by('-claim__period_from', 'claim_id'))


def find_receipt(docnumber, branch=None):
    """Every place receipt `docnumber` (optionally in `branch`) appears. See module docstring."""
    docnumber = (docnumber or '').strip()
    branch = (branch or '').strip() or None
    if not docnumber:
        return []
    rxs = _rx_qs().filter(softech_docnumber=docnumber)
    manual = _manual_qs().filter(softech_docnumber=docnumber)
    cache = MotalbaCache.objects.filter(docnumber=docnumber).order_by('-docdate', 'motalbano')
    if branch:
        rxs = rxs.filter(softech_branchcode=branch)
        manual = manual.filter(softech_branchcode=branch)
        cache = cache.filter(branchcode=branch)
    return _build(rxs[:MAX_RECEIPTS * 4], manual[:MAX_RECEIPTS * 4], cache[:MAX_RECEIPTS * 4])


def find_by_patient(name):
    """Receipts whose patient name matches `name` (shared wildcard rules: * and %, words in any
    order), newest first, at most MAX_RECEIPTS. Each receipt then lists EVERY claim it sits in
    (even where the name was spelled differently) plus its SOFTECH motalba.
    Returns (receipts, more) — `more` is True when matches beyond the cap were left out."""
    from apps.catalog.wildcard import parse, wq
    name = (name or '').strip()
    if len(name.replace('*', '').replace('%', '').strip()) < 2 or not parse(name)['segments']:
        return [], False
    cond = wq(name, 'patient_name')
    hits = []
    for model in (InsuranceClaimPrescription, InsuranceClaimManualRx):
        hits += list(model.objects.filter(cond)
                     .values_list('softech_docdate', 'softech_docnumber', 'softech_branchcode')
                     .order_by('-softech_docdate')[:MAX_RECEIPTS * 4])
    hits.sort(key=lambda h: h[0] or date.min, reverse=True)
    keys = []
    for _, docno, br in hits:
        k = (docno, br or '')
        if k not in keys:
            keys.append(k)
    more = len(keys) > MAX_RECEIPTS
    keys = keys[:MAX_RECEIPTS]
    docnos = {k[0] for k in keys}
    out = _build(_rx_qs().filter(softech_docnumber__in=docnos),
                 _manual_qs().filter(softech_docnumber__in=docnos),
                 MotalbaCache.objects.filter(docnumber__in=docnos).order_by('-docdate', 'motalbano'),
                 keep=keys)
    return out, more
