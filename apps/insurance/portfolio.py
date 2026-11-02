"""
«تقارير المطالبات» — portfolio reports over many motalbas (read-only).

For the motalbas whose claim period overlaps [date_from, date_to]:
  • per motalba: receipts, patients, محلى / مستورد / ترسية (gross + net), discount,
    net billed, patient share, cost, gross profit (total and per category), collected,
    balance, and the value bridge (import → SOFTECH edits → catalog applies →
    exclusions → manual additions (incl. receipts brought from other motalbas) →
    supplements → final);
  • per branch, motalba × branch, branch × salesperson, per financial category;
  • receipts moved between motalbas.

Cost and seller come from the local mirror of SOFTECH sale lines (stock_audit
StockLedgerLine, doccode 115): cost = newcostprice × transqty at sale time, seller =
the line's SOFTECH usercode. Revenue = what we bill the insurer + the patient's share
(receipt net in SOFTECH − the insurer's part). Deterministic; nothing is written.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum

CATS = ('local', 'imported', 'tarsia')
CAT_LABEL = {'local': 'محلى', 'imported': 'مستورد', 'tarsia': 'ترسية'}
_Q = Decimal('0.01')
INACTIVE = ('cancelled', 'rejected')


def _d(v):
    return Decimal(str(v or 0))


def _f(v):
    return float(_d(v).quantize(_Q))


def select_claims(date_from=None, date_to=None, client_id=None, subclient_id=None, statuses=None):
    from .models import InsuranceClaim
    qs = InsuranceClaim.objects.select_related('subclient__client')
    if statuses:
        qs = qs.filter(status__in=statuses)
    else:
        qs = qs.exclude(status__in=INACTIVE)
    if date_from:
        qs = qs.filter(period_to__gte=date_from)
    if date_to:
        qs = qs.filter(period_from__lte=date_to)
    if client_id:
        qs = qs.filter(subclient__client_id=client_id)
    if subclient_id:
        qs = qs.filter(subclient_id=subclient_id)
    return list(qs.order_by('period_from', 'claim_number'))


def _sellers():
    from apps.users.models import StaffProfile
    out = {}
    for p in StaffProfile.objects.exclude(softech_user_id='').select_related('user'):
        out[str(p.softech_user_id).strip()] = p.full_name
    return out


def _ledger(receipts):
    """{(branch, docnumber): {'net': Σ transprice_total, 'cost': Σ cost, 'cost_missing': n,
    'seller': usercode, 'items': {itemcode: cost}}} for the given (branch, docnumber) set."""
    from apps.stock_audit.models import StockLedgerLine
    want = {(str(b).strip(), str(d).strip()) for b, d in receipts}
    nums = sorted({int(d) for _, d in want if str(d).strip().isdigit()})
    out = {}
    for i in range(0, len(nums), 2000):
        rows = (StockLedgerLine.objects.filter(doccode='115', docnumber__in=nums[i:i + 2000])
                .values_list('branchcode', 'docnumber', 'itemcode', 'transqty', 'transprice_total',
                             'newcostprice', 'usercode'))
        for b, d, code, qty, tot, cost, user in rows:
            key = (str(b).strip(), str(d))
            if key not in want:
                continue
            e = out.setdefault(key, {'net': Decimal('0'), 'cost': Decimal('0'), 'cost_missing': 0,
                                     'seller': '', 'items': defaultdict(Decimal)})
            e['net'] += _d(tot)
            c = _d(cost) * _d(qty)
            if _d(cost) <= 0:
                e['cost_missing'] += 1
            e['cost'] += c
            e['items'][str(code).strip()] += c
            if user and not e['seller']:
                e['seller'] = str(user).strip()
    return out


def build_report(claims):
    """Every section for these claims (list of InsuranceClaim)."""
    from .models import (InsuranceApplyMasterRun, InsuranceClaimLine, InsuranceClaimManualRx,
                         InsuranceClaimPrescription, SoftechRepriceRun)
    from apps.branches.models import Branch
    ids = [c.pk for c in claims]
    branch_names = {str(b.softech_branch_id): b.name for b in Branch.objects.exclude(softech_branch_id='')}
    sellers = _sellers()

    rxs = list(InsuranceClaimPrescription.objects.filter(claim_id__in=ids)
               .values('id', 'claim_id', 'softech_docnumber', 'softech_branchcode', 'patient_name',
                       'net_after', 'softech_net', 'exclusion__reason'))
    active = [r for r in rxs if r['exclusion__reason'] is None]
    manual = list(InsuranceClaimManualRx.objects.filter(claim_id__in=ids)
                  .values('id', 'claim_id', 'softech_docnumber', 'softech_branchcode', 'patient_name',
                          'net_after', 'local_before', 'imported_before', 'tarsia_before',
                          'local_discount', 'imported_discount', 'tarsia_discount', 'is_excluded',
                          'original_client_warning'))
    manual_active = [m for m in manual if not m['is_excluded']]
    led = _ledger([(r['softech_branchcode'], r['softech_docnumber']) for r in active] +
                  [(m['softech_branchcode'], m['softech_docnumber']) for m in manual_active])

    # per-category net + cost from claim lines (active receipts); manual receipts by their split
    cat_net = defaultdict(lambda: defaultdict(Decimal))
    cat_gross = defaultdict(lambda: defaultdict(Decimal))
    cat_cost = defaultdict(lambda: defaultdict(Decimal))
    active_ids = {r['id']: r for r in active}
    for rx_id, code, cat, gross, net in (InsuranceClaimLine.objects.filter(prescription_id__in=active_ids.keys())
                                         .values_list('prescription_id', 'softech_itemcode', 'item_category',
                                                      'line_total', 'net_amount')):
        r = active_ids[rx_id]
        cat = cat if cat in CATS else 'local'
        cat_net[r['claim_id']][cat] += _d(net)
        cat_gross[r['claim_id']][cat] += _d(gross)
        e = led.get((str(r['softech_branchcode']).strip(), str(r['softech_docnumber']).strip()))
        if e and str(code).strip() in e['items']:
            cat_cost[r['claim_id']][cat] += e['items'].pop(str(code).strip())   # each cost counted once
    for m in manual_active:
        for cat in CATS:
            before = _d(m[f'{cat}_before'])
            cat_gross[m['claim_id']][cat] += before
            cat_net[m['claim_id']][cat] += before - _d(m[f'{cat}_discount'])

    # receipts → branch / seller rows
    by_claim = defaultdict(lambda: {'rx': 0, 'patients': set(), 'patient_share': Decimal('0'),
                                    'cost': Decimal('0'), 'cost_missing': 0, 'not_in_softech': 0})
    branch_rows = defaultdict(lambda: {'rx': 0, 'net': Decimal('0'), 'patient_share': Decimal('0'),
                                       'cost': Decimal('0')})
    seller_rows = defaultdict(lambda: {'rx': 0, 'net': Decimal('0'), 'patient_share': Decimal('0'),
                                       'cost': Decimal('0')})
    receipts = [(r['claim_id'], r['softech_branchcode'], r['softech_docnumber'], r['patient_name'],
                 _d(r['net_after']), r['softech_net']) for r in active]
    receipts += [(m['claim_id'], m['softech_branchcode'], m['softech_docnumber'], m['patient_name'],
                  _d(m['net_after']), None) for m in manual_active]
    for cid, br, doc, name, net, insurer_part in receipts:
        br = str(br or '').strip()
        e = led.get((br, str(doc).strip()))
        c = by_claim[cid]
        c['rx'] += 1
        if name:
            c['patients'].add(name.strip())
        share = Decimal('0')
        cost = Decimal('0')
        seller = ''
        if e:
            if insurer_part is not None:
                share = max(Decimal('0'), e['net'] - _d(insurer_part))
            cost = e['cost']
            c['cost_missing'] += e['cost_missing']
            seller = e['seller']
        else:
            c['not_in_softech'] += 1
        c['patient_share'] += share
        c['cost'] += cost
        for row in (branch_rows[(cid, br)], seller_rows[(br, seller)]):
            row['rx'] += 1
            row['net'] += net
            row['patient_share'] += share
            row['cost'] += cost

    # value bridge pieces
    reprice = defaultdict(lambda: [0, Decimal('0')])
    for cid, delta in (SoftechRepriceRun.objects.filter(claim_id__in=ids, status='applied')
                       .exclude(new_prices__has_key='_bonusqty_backfill').values_list('claim_id', 'net_delta')):
        reprice[cid][0] += 1
        reprice[cid][1] += _d(delta)
    catalog = defaultdict(Decimal)
    for cid, before, after in (InsuranceApplyMasterRun.objects.filter(claim_id__in=ids, reverted=False)
                               .values_list('claim_id', 'net_before', 'net_after')):
        catalog[cid] += _d(after) - _d(before)
    excluded = defaultdict(lambda: {'count': 0, 'net': Decimal('0'), 'wrong_allocation': 0})
    all_rx_net = defaultdict(Decimal)
    for r in rxs:
        all_rx_net[r['claim_id']] += _d(r['net_after'])
    for r in rxs:
        if r['exclusion__reason'] is not None:
            x = excluded[r['claim_id']]
            x['count'] += 1
            x['net'] += _d(r['net_after'])
            if 'تخصيص خاطئ' in (r['exclusion__reason'] or ''):
                x['wrong_allocation'] += 1

    # receipts brought from other motalbas: the same receipt on another claim, excluded there
    claim_no = {c.pk: c.claim_number for c in claims}
    from .models import InsuranceClaim
    keys = {(str(m['softech_branchcode']).strip(), str(m['softech_docnumber']).strip()) for m in manual_active}
    origin = {}
    if keys:
        for cid, cno, br, doc in (InsuranceClaimPrescription.objects
                                  .filter(softech_docnumber__in={k[1] for k in keys})
                                  .values_list('claim_id', 'claim__claim_number', 'softech_branchcode',
                                               'softech_docnumber')):
            origin.setdefault((str(br).strip(), str(doc).strip()), []).append((cid, cno))
    moves = []
    added = defaultdict(lambda: {'count': 0, 'net': Decimal('0'), 'from_other': 0, 'from_other_net': Decimal('0')})
    for m in manual_active:
        a = added[m['claim_id']]
        a['count'] += 1
        a['net'] += _d(m['net_after'])
        src = [o for o in origin.get((str(m['softech_branchcode']).strip(), str(m['softech_docnumber']).strip()), [])
               if o[0] != m['claim_id']]
        if src or m['original_client_warning']:
            a['from_other'] += 1
            a['from_other_net'] += _d(m['net_after'])
            moves.append({'to_claim': claim_no.get(m['claim_id'], ''), 'from_claims': [s[1] for s in src],
                          'docnumber': m['softech_docnumber'], 'branch': m['softech_branchcode'],
                          'branch_name': branch_names.get(str(m['softech_branchcode']).strip(), ''),
                          'patient': m['patient_name'], 'net': _f(m['net_after']),
                          'note': m['original_client_warning'][:120]})
    supp = defaultdict(lambda: [0, Decimal('0')])
    from .models import InsuranceClaimSupplement
    for cid, n, net in (InsuranceClaimSupplement.objects.filter(claim_id__in=ids, is_excluded=False)
                        .exclude(supplement_type='standalone').values_list('claim_id', 'rx_count', 'net_after')):
        supp[cid][0] += n or 0
        supp[cid][1] += _d(net)
    paid = defaultdict(Decimal)
    from .models import InsurancePayment
    for cid, amt in InsurancePayment.objects.filter(claim_id__in=ids).values_list('claim_id', 'amount'):
        paid[cid] += _d(amt)

    # ── per motalba ──
    motalbas, tot = [], defaultdict(Decimal)
    for c in claims:
        b = by_claim[c.pk]
        rates = {'local': _d(c.applied_local_disc_pct), 'imported': _d(c.applied_imported_disc_pct),
                 'tarsia': _d(c.applied_tarsia_disc_pct)}
        net = _d(c.final_net_after)
        revenue = net + b['patient_share']
        cost = b['cost']
        row = {
            'claim_id': c.pk, 'claim_number': c.claim_number, 'softech_motalba_no': c.softech_motalba_no,
            'client': c.subclient.client.name, 'client_id': c.subclient.client_id,
            'subclient': c.subclient.name, 'status': c.status,
            'period_from': c.period_from.isoformat() if c.period_from else None,
            'period_to': c.period_to.isoformat() if c.period_to else None,
            'rx_count': b['rx'], 'patients': len(b['patients']),
            'local_before': _f(c.final_local_before), 'imported_before': _f(c.final_imported_before),
            'tarsia_before': _f(c.final_tarsia_before), 'gross': _f(c.final_gross_before),
            'discount': _f(c.final_total_discount), 'net': _f(net),
            'patient_share': _f(b['patient_share']), 'revenue': _f(revenue), 'cost': _f(cost),
            'gp': _f(revenue - cost), 'gp_pct': _f((revenue - cost) / revenue * 100) if revenue else 0.0,
            'cost_missing_lines': b['cost_missing'], 'not_in_softech': b['not_in_softech'],
            'collected': _f(paid[c.pk]), 'balance': _f(net - paid[c.pk]),
        }
        for cat in CATS:
            cn, cc = cat_net[c.pk][cat], cat_cost[c.pk][cat]
            row[f'{cat}_net'] = _f(cn)
            row[f'{cat}_cost'] = _f(cc)
            row[f'{cat}_gp'] = _f(cn - cc)
            row[f'{cat}_gp_pct'] = _f((cn - cc) / cn * 100) if cn else 0.0
            row[f'{cat}_rate'] = _f(rates[cat])
        x, a, s = excluded[c.pk], added[c.pk], supp[c.pk]
        # value at import = every imported receipt (excluded ones too) before catalog
        # applies — snapshot_net_after is refreshed by a re-sync, so it is not used
        import_net = all_rx_net[c.pk] - catalog[c.pk]
        bridge = {
            'import_net': _f(import_net),
            'softech_edits': reprice[c.pk][0], 'softech_edits_delta': _f(reprice[c.pk][1]),
            'catalog_delta': _f(catalog[c.pk]),
            'excluded_count': x['count'], 'excluded_net': _f(x['net']), 'wrong_allocation': x['wrong_allocation'],
            'manual_count': a['count'], 'manual_net': _f(a['net']),
            'from_other_count': a['from_other'], 'from_other_net': _f(a['from_other_net']),
            'supplements_count': s[0], 'supplements_net': _f(s[1]),
            'final_net': _f(net),
        }
        explained = (import_net + catalog[c.pk] - x['net'] + a['net'] + s[1])
        bridge['other_adjustments'] = _f(net - explained)
        row['bridge'] = bridge
        motalbas.append(row)
        for k in ('rx_count', 'patients', 'local_before', 'imported_before', 'tarsia_before', 'gross', 'discount',
                  'net', 'patient_share', 'revenue', 'cost', 'gp', 'collected', 'balance'):
            tot[k] += _d(row[k])
        for cat in CATS:
            for k in ('net', 'cost', 'gp'):
                tot[f'{cat}_{k}'] += _d(row[f'{cat}_{k}'])
        for k, v in bridge.items():
            tot[f'bridge_{k}'] += _d(v)
    totals = {k: _f(v) for k, v in tot.items()}
    totals['motalbas'] = len(motalbas)
    totals['gp_pct'] = _f(tot['gp'] / tot['revenue'] * 100) if tot['revenue'] else 0.0

    def _gp(row):
        rev = row['net'] + row['patient_share']
        out = {k: _f(v) if isinstance(v, Decimal) else v for k, v in row.items()}
        out['revenue'] = _f(rev)
        out['gp'] = _f(rev - row['cost'])
        out['gp_pct'] = _f((rev - row['cost']) / rev * 100) if rev else 0.0
        return out

    by_branch_claim = [{'claim_number': claim_no.get(cid, ''), 'claim_id': cid, 'branch': br,
                        'branch_name': branch_names.get(br, br), **_gp(v)}
                       for (cid, br), v in branch_rows.items()]
    branch_tot = defaultdict(lambda: {'rx': 0, 'net': Decimal('0'), 'patient_share': Decimal('0'),
                                      'cost': Decimal('0'), 'motalbas': set()})
    for (cid, br), v in branch_rows.items():
        t = branch_tot[br]
        for k in ('rx', 'net', 'patient_share', 'cost'):
            t[k] += v[k]
        t['motalbas'].add(cid)
    branches = []
    for br, v in branch_tot.items():
        m = len(v.pop('motalbas'))
        branches.append({'branch': br, 'branch_name': branch_names.get(br, br), 'motalbas': m, **_gp(v)})
    sellers_out = [{'branch': br, 'branch_name': branch_names.get(br, br), 'usercode': u,
                    'seller': sellers.get(u, '') or (f'مستخدم {u}' if u else 'غير معروف'), **_gp(v)}
                   for (br, u), v in seller_rows.items()]
    categories = []
    for cat in CATS:
        n, c_ = tot[f'{cat}_net'], tot[f'{cat}_cost']
        g = sum((cat_gross[cid][cat] for cid in ids), Decimal('0'))
        categories.append({'category': cat, 'label': CAT_LABEL[cat], 'gross': _f(g), 'net': _f(n), 'cost': _f(c_),
                           'gp': _f(n - c_), 'gp_pct': _f((n - c_) / n * 100) if n else 0.0})
    months = defaultdict(lambda: defaultdict(Decimal))
    for row in motalbas:
        mk = (row['period_from'] or '')[:7]
        for k in ('net', 'revenue', 'cost', 'gp'):
            months[mk][k] += _d(row[k])
    trend = [{'month': k, **{kk: _f(vv) for kk, vv in v.items()}} for k, v in sorted(months.items())]
    return {'totals': totals, 'motalbas': motalbas, 'branches': sorted(branches, key=lambda r: -r['net']),
            'by_branch_claim': by_branch_claim, 'sellers': sorted(sellers_out, key=lambda r: -r['net']),
            'categories': categories, 'moves': moves, 'trend': trend}
