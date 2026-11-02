"""
Bridge between the catalog-apply in «فحص الفروقات» and the SOFTECH re-price writer.

- catalog_sync_receipts(claim): the prices «تطبيق بيانات الكتالوج» changed on the
  claim, grouped per receipt (all items of one receipt together) — the plan the
  user previously had to re-type item by item in «تعديلات سوفتك».
- softech_status_map(claim): per receipt, what SOFTECH looks like after our applied
  re-price runs (its current net from the run's recorded after-values) and which
  catalog price changes are still not written to SOFTECH.

Read-only on SOFTECH and on the claim; the write itself stays in reprice_service
(preview → typed confirmation → apply).
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from .models import (
    InsuranceClaimExclusion, InsuranceClaimLine, InsuranceClaimLineBackup,
    SoftechRepriceEdit, SoftechRepriceRun,
)


def _price(v):
    try:
        return Decimal(str(v)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return None


def catalog_sync_receipts(claim):
    """[{docno, branch, prices: {itemcode: price}}] for every claim line whose price a
    live (not undone) catalog apply changed, + info about what was left out."""
    runs = claim.apply_runs.filter(reverted=False, apply_price=True)
    # the earliest backup of a line = its price before any catalog apply (= SOFTECH at import)
    first = {}
    for line_id, price in (InsuranceClaimLineBackup.objects.filter(run__in=runs)
                           .order_by('run__applied_at', 'id').values_list('line_id', 'unit_price')):
        first.setdefault(line_id, price)
    excluded = set(InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
                   .values_list('prescription_id', flat=True))
    per_receipt = defaultdict(dict)
    conflicts, skipped_excluded = [], 0
    lines = (InsuranceClaimLine.objects.filter(pk__in=first.keys())
             .select_related('prescription'))
    for ln in lines:
        new, old = _price(ln.unit_price), _price(first[ln.pk])
        if new is None or new == old or not ln.softech_itemcode:
            continue
        rx = ln.prescription
        if rx.id in excluded:
            skipped_excluded += 1
            continue
        key = (str(rx.softech_docnumber), str(rx.softech_branchcode))
        code = str(ln.softech_itemcode).strip()
        have = per_receipt[key].get(code)
        if have is not None and have != str(new):
            conflicts.append({'docno': key[0], 'branch': key[1], 'itemcode': code})
            continue
        per_receipt[key][code] = str(new)
    for c in conflicts:   # two lines of one item on one receipt disagree → leave it to a human
        per_receipt[(c['docno'], c['branch'])].pop(c['itemcode'], None)
    receipts = [{'docno': d, 'branch': b, 'prices': p} for (d, b), p in per_receipt.items() if p]
    receipts.sort(key=lambda r: (r['branch'], r['docno']))
    return receipts, {'conflicts': conflicts, 'skipped_excluded': skipped_excluded,
                      'apply_runs': runs.count()}


def softech_status_map(claim):
    """{(docno, branch): {softech_net, run_ids, pending_items, status}}.

    softech_net = the receipt's SOFTECH net after the latest applied re-price run
    (HQ stktransm.docvalue as written), None when no run touched it.
    status: 'pending' (a catalog price change is not yet in SOFTECH),
            'edited'  (re-priced in SOFTECH, nothing pending), 'none'."""
    out = {}
    applied = SoftechRepriceRun.objects.filter(claim=claim, status=SoftechRepriceRun.STATUS_APPLIED)
    written = defaultdict(dict)   # (docno, branch) → {itemcode: price written}
    for run in applied.order_by('id'):
        key = (str(run.docnumber), str(run.branchcode))
        entry = out.setdefault(key, {'softech_net': None, 'run_ids': [], 'pending_items': []})
        entry['run_ids'].append(run.pk)
        for code, p in (run.new_prices or {}).items():
            written[key][str(code).strip()] = _price(p)
    for run_id, docno, branch, after in (SoftechRepriceEdit.objects
            .filter(run__in=applied, node='HQ', table='stktransm', field='docvalue')
            .order_by('run_id').values_list('run_id', 'run__docnumber', 'run__branchcode', 'after')):
        out[(str(docno), str(branch))]['softech_net'] = _price(after)
    receipts, _info = catalog_sync_receipts(claim)
    for r in receipts:
        key = (r['docno'], r['branch'])
        pend = [c for c, p in r['prices'].items() if written.get(key, {}).get(c) != _price(p)]
        if pend:
            out.setdefault(key, {'softech_net': None, 'run_ids': [], 'pending_items': []})['pending_items'] = pend
    for e in out.values():
        e['status'] = 'pending' if e['pending_items'] else ('edited' if e['run_ids'] else 'none')
    return out
