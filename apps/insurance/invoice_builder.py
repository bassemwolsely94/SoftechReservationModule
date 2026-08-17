"""
apps/insurance/invoice_builder.py

Builds the final invoice dataset from the frozen snapshot + adjustments.
Used by both the API (invoice-dataset endpoint) and the Excel exporter.

Dataset structure returned by build_invoice_dataset():
{
  "claim": { claim-level metadata },
  "days": [
    {
      "date": "2026-05-01",              # ISO date string or supplement label
      "is_supplement": false,
      "supplement_type": null,
      "prescriptions": [
        {
          "sequence": 1,
          "patient_name": "...",
          "local_before": 3684.00,
          "imported_before": 830.00,
          "tarsia_before": 0.00,
          "gross_before": 4514.00,
          "local_discount": 625.28,
          "imported_discount": 49.80,
          "tarsia_discount": 0.00,
          "total_discount": 675.08,
          "net_after": 3838.92,
          "is_manual": false,
          "is_adjusted": false,
          "docnumber": "...",
        },
        ...
      ],
      "day_totals": {
        "rx_count": 15,
        "local_before": ..., "imported_before": ..., "tarsia_before": ...,
        "gross_before": ..., "local_discount": ..., "imported_discount": ...,
        "tarsia_discount": ..., "total_discount": ..., "net_after": ...,
      }
    },
    ...
  ],
  "claim_totals": { ... same fields as day_totals, aggregated ... }
}
"""
from datetime import date
from decimal import Decimal
from collections import defaultdict, OrderedDict

from .models import (
    InsuranceClaim, InsuranceClaimPrescription,
    InsuranceClaimAdjustment, InsuranceClaimExclusion,
    InsuranceClaimSupplement, InsuranceClaimManualRx,
    ITEM_CATEGORY_LOCAL,
)


def _zero_totals():
    return {
        'rx_count':       0,
        'local_before':   Decimal('0'),
        'imported_before': Decimal('0'),
        'tarsia_before':  Decimal('0'),
        'gross_before':   Decimal('0'),
        'local_discount': Decimal('0'),
        'imported_discount': Decimal('0'),
        'tarsia_discount': Decimal('0'),
        'total_discount': Decimal('0'),
        'net_after':      Decimal('0'),
    }


def _add_to_totals(totals: dict, row: dict):
    for field in ('local_before', 'imported_before', 'tarsia_before', 'gross_before',
                  'local_discount', 'imported_discount', 'tarsia_discount',
                  'total_discount', 'net_after'):
        totals[field] += Decimal(str(row.get(field) or 0))
    totals['rx_count'] += 1


def _float_totals(totals: dict, claim: InsuranceClaim = None) -> dict:
    """
    Finalise a totals bucket and convert to floats.

    When `claim` is given, net / discount / per-category discounts are
    RECOMPUTED from the summed splits using the Power-Query formula
    (net = Σ split·(1−rate)).  Because net is linear in the splits this equals
    summing the per-row nets, so every level — day subtotal, cover, grand
    total — reconciles exactly with the finance team's Power-Query output.
    """
    if claim is not None:
        from .classifier import powerquery_totals_from_splits
        t = powerquery_totals_from_splits(
            totals.get('local_before', 0), totals.get('imported_before', 0),
            totals.get('tarsia_before', 0),
            claim.applied_local_disc_pct, claim.applied_imported_disc_pct,
            claim.applied_tarsia_disc_pct,
        )
        totals = dict(totals)
        totals['gross_before']      = t['gross_before']
        totals['local_discount']    = t['local_discount']
        totals['imported_discount'] = t['imported_discount']
        totals['tarsia_discount']   = t['tarsia_discount']
        totals['total_discount']    = t['total_discount']
        totals['net_after']         = t['net_after']
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in totals.items()}


def _effective_rx_values(rx: InsuranceClaimPrescription, claim: InsuranceClaim) -> dict:
    """Return effective (adjusted) financial values for a prescription.

    Uses the Power-Query net formula (net = Σ split·(1−rate)) on the effective
    (possibly adjusted) splits, except when an explicit net_override is set.
    Also exposes softech_net + the mismatch flag so templates/UI can highlight
    prescriptions whose Power-Query net differs from SOFTECH's stored net.
    """
    from .classifier import powerquery_totals_from_splits

    local_disc    = claim.applied_local_disc_pct
    imported_disc = claim.applied_imported_disc_pct
    tarsia_disc   = claim.applied_tarsia_disc_pct

    softech_net = rx.softech_net

    try:
        adj = rx.adjustment
        lb = adj.local_before    if adj.local_before    is not None else rx.local_before
        ib = adj.imported_before if adj.imported_before is not None else rx.imported_before
        tb = adj.tarsia_before   if adj.tarsia_before   is not None else rx.tarsia_before

        if adj.net_override is not None:
            gb   = Decimal(str(lb)) + Decimal(str(ib)) + Decimal(str(tb))
            net  = Decimal(str(adj.net_override))
            disc = gb - net
            ld   = disc * Decimal(str(lb)) / gb if gb else Decimal('0')
            id_  = disc * Decimal(str(ib)) / gb if gb else Decimal('0')
            td   = disc - ld - id_
        else:
            t   = powerquery_totals_from_splits(lb, ib, tb, local_disc, imported_disc, tarsia_disc)
            lb, ib, tb = t['local_before'], t['imported_before'], t['tarsia_before']
            gb, ld, id_, td = t['gross_before'], t['local_discount'], t['imported_discount'], t['tarsia_discount']
            disc, net = t['total_discount'], t['net_after']
        is_adjusted = True
    except InsuranceClaimAdjustment.DoesNotExist:
        lb, ib, tb = rx.local_before, rx.imported_before, rx.tarsia_before
        gb   = rx.gross_before
        ld   = rx.local_discount
        id_  = rx.imported_discount
        td   = rx.tarsia_discount
        disc = rx.total_discount
        net  = rx.net_after
        is_adjusted = False

    softech_diff = None
    softech_mismatch = False
    if softech_net is not None:
        softech_diff = (Decimal(str(net)) - Decimal(str(softech_net))).quantize(Decimal('0.01'))
        softech_mismatch = abs(softech_diff) > Decimal('0.01')

    return {
        'sequence':         rx.sequence,
        'patient_name':     rx.patient_name,
        'local_before':     lb,
        'imported_before':  ib,
        'tarsia_before':    tb,
        'gross_before':     gb,
        'local_discount':   ld,
        'imported_discount': id_,
        'tarsia_discount':  td,
        'total_discount':   disc,
        'net_after':        net,
        'softech_net':      softech_net,
        'softech_diff':     softech_diff,
        'softech_mismatch': softech_mismatch,
        'docnumber':        rx.softech_docnumber,
        'is_manual':        False,
        'is_adjusted':      is_adjusted,
    }


def build_invoice_dataset(claim: InsuranceClaim, billing_group=None) -> dict:
    """
    Build the complete invoice dataset used by all 4 templates.
    Returns a JSON-serialisable dict (floats, not Decimals).

    billing_group: optional InsuranceClaimBillingGroup. When provided, only
    prescriptions assigned to that group are included — used to export a
    separate invoice per sub-category (sub-personcode).
    """

    # ── Collect excluded IDs ────────────────────────────────────────────────
    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    # ── Collect supplements ─────────────────────────────────────────────────
    # When exporting a billing group, only supplements assigned to THAT group
    # appear (otherwise a supplement block would show on every sub-invoice).
    sup_qs = claim.supplements.filter(is_excluded=False).order_by('sort_order', 'print_date')
    if billing_group is not None:
        sup_qs = sup_qs.filter(billing_group=billing_group)
    supplements = list(sup_qs)
    before_sups  = [s for s in supplements if s.supplement_type == InsuranceClaimSupplement.SUPPLEMENT_BEFORE]
    after_sups   = [s for s in supplements if s.supplement_type == InsuranceClaimSupplement.SUPPLEMENT_AFTER]
    within_sups  = {s.print_date: s for s in supplements if s.supplement_type == InsuranceClaimSupplement.SUPPLEMENT_WITHIN}
    standalone_sups = [s for s in supplements if s.supplement_type == InsuranceClaimSupplement.SUPPLEMENT_STANDALONE]

    # ── Collect manual Rx ────────────────────────────────────────────────────
    # When exporting a billing group, only the manual Rx assigned to THAT group
    # are included (otherwise a manual receipt would appear on every sub-invoice).
    manual_qs = claim.manual_rx.filter(is_excluded=False)
    if billing_group is not None:
        manual_qs = manual_qs.filter(billing_group=billing_group)
    manual_rx_before = list(manual_qs.filter(position=InsuranceClaimManualRx.POSITION_BEFORE).order_by('sequence'))
    manual_rx_after  = list(manual_qs.filter(position=InsuranceClaimManualRx.POSITION_AFTER).order_by('sequence'))
    manual_rx_date   = defaultdict(list)
    for mrx in manual_qs.filter(position=InsuranceClaimManualRx.POSITION_DATE).order_by('print_date', 'sequence'):
        manual_rx_date[mrx.print_date].append(mrx)

    def _mrx_row(mrx: InsuranceClaimManualRx, seq: int) -> dict:
        return {
            'sequence':         seq,
            'patient_name':     mrx.patient_name,
            'local_before':     mrx.local_before,
            'imported_before':  mrx.imported_before,
            'tarsia_before':    mrx.tarsia_before,
            'gross_before':     mrx.gross_before,
            'local_discount':   mrx.local_discount,
            'imported_discount': mrx.imported_discount,
            'tarsia_discount':  mrx.tarsia_discount,
            'total_discount':   mrx.total_discount,
            'net_after':        mrx.net_after,
            'docnumber':        mrx.softech_docnumber,
            'is_manual':        True,
            'is_adjusted':      False,
        }

    def _sup_row(sup: InsuranceClaimSupplement) -> dict:
        return {
            'sequence':         0,
            'patient_name':     sup.label,
            'local_before':     sup.local_before,
            'imported_before':  sup.imported_before,
            'tarsia_before':    sup.tarsia_before,
            'gross_before':     sup.gross_before,
            'local_discount':   sup.local_discount,
            'imported_discount': sup.imported_discount,
            'tarsia_discount':  sup.tarsia_discount,
            'total_discount':   sup.total_discount,
            'net_after':        sup.net_after,
            'docnumber':        '',
            'is_manual':        False,
            'is_adjusted':      False,
            'is_supplement':    True,
            'supplement_type':  sup.supplement_type,
        }

    # ── Group main prescriptions by date ─────────────────────────────────────
    days_map: dict[str, list] = OrderedDict()
    prescriptions = (
        claim.prescriptions
        .select_related('adjustment', 'exclusion')
        .order_by('softech_docdate', 'sequence')
    )
    if billing_group is not None:
        prescriptions = prescriptions.filter(billing_group=billing_group)
    for rx in prescriptions:
        if rx.id in excluded_ids:
            continue
        key = rx.softech_docdate.isoformat()
        if key not in days_map:
            days_map[key] = []
        days_map[key].append(_effective_rx_values(rx, claim))

    # Add within-day manual Rx
    for dt, mrx_list in manual_rx_date.items():
        key = dt.isoformat() if dt else 'unknown'
        if key not in days_map:
            days_map[key] = []
        for i, mrx in enumerate(mrx_list):
            days_map[key].append(_mrx_row(mrx, len(days_map[key]) + i + 1))

    # Sort days
    sorted_days = sorted(days_map.keys())

    # ── Assemble final days list ──────────────────────────────────────────────
    days_output  = []
    claim_totals = _zero_totals()

    # 1. Before supplements (ملحق سابق)
    for sup in before_sups:
        row = _sup_row(sup)
        day_totals = _zero_totals()
        _add_to_totals(day_totals, row)
        day_totals['rx_count'] = sup.rx_count
        days_output.append({
            'date':           sup.print_date.isoformat() if sup.print_date else 'ملحق سابق',
            'label':          sup.label,
            'is_supplement':  True,
            'supplement_type': sup.supplement_type,
            'prescriptions':  [_float_row(row)],
            'day_totals':     _float_totals(day_totals, claim),
        })
        _add_to_totals(claim_totals, row)
        # Correct rx_count: supplement represents N prescriptions not 1
        claim_totals['rx_count'] += sup.rx_count - 1

    # 2. Before manual Rx (ملحق سابق)
    if manual_rx_before:
        before_day_totals = _zero_totals()
        before_rows = []
        for i, mrx in enumerate(manual_rx_before):
            row = _mrx_row(mrx, i + 1)
            before_rows.append(_float_row(row))
            _add_to_totals(before_day_totals, row)
            _add_to_totals(claim_totals, row)   # include in grand total
        days_output.append({
            'date':           'ملحق سابق',
            'label':          'ملحق يوميات',
            'is_supplement':  True,
            'supplement_type': 'before_claim',
            'prescriptions':  before_rows,
            'day_totals':     _float_totals(before_day_totals, claim),
        })

    # 3. Main claim days
    for day_key in sorted_days:
        rows       = days_map[day_key]
        day_totals = _zero_totals()
        for row in rows:
            _add_to_totals(day_totals, row)
            _add_to_totals(claim_totals, row)

        # Insert within-day supplements
        if day_key in {s.print_date.isoformat() if s.print_date else '' for s in within_sups.values()}:
            sup = within_sups.get(date.fromisoformat(day_key) if day_key else None)
            if sup:
                row = _sup_row(sup)
                rows = [_float_row(row)] + [_float_row(r) for r in rows]
                _add_to_totals(day_totals, row)
                _add_to_totals(claim_totals, row)

        days_output.append({
            'date':           day_key,
            'label':          None,
            'is_supplement':  False,
            'supplement_type': None,
            'prescriptions':  [_float_row(r) for r in rows],
            'day_totals':     _float_totals(day_totals, claim),
        })

    # 4. After manual Rx (ملحق لاحق)
    if manual_rx_after:
        after_day_totals = _zero_totals()
        after_rows = []
        for i, mrx in enumerate(manual_rx_after):
            row = _mrx_row(mrx, i + 1)
            after_rows.append(_float_row(row))
            _add_to_totals(after_day_totals, row)
            _add_to_totals(claim_totals, row)   # include in grand total
        days_output.append({
            'date':           'ملحق لاحق',
            'label':          'ملحق يوميات',
            'is_supplement':  True,
            'supplement_type': 'after_claim',
            'prescriptions':  after_rows,
            'day_totals':     _float_totals(after_day_totals, claim),
        })

    # 5. After supplements (ملحق لاحق)
    for sup in after_sups:
        row = _sup_row(sup)
        day_totals = _zero_totals()
        _add_to_totals(day_totals, row)
        day_totals['rx_count'] = sup.rx_count
        days_output.append({
            'date':           sup.print_date.isoformat() if sup.print_date else 'ملحق لاحق',
            'label':          sup.label,
            'is_supplement':  True,
            'supplement_type': sup.supplement_type,
            'prescriptions':  [_float_row(row)],
            'day_totals':     _float_totals(day_totals, claim),
        })
        _add_to_totals(claim_totals, row)
        claim_totals['rx_count'] += sup.rx_count - 1

    # Assemble claim-level discount breakdown for cover page
    # The claim totals need to be split back by category for the cover table.
    # When exporting a billing group, the cover reflects the GROUP's totals
    # (taken from the filtered claim_totals accumulator) rather than the
    # claim-wide final_* values.
    local_disc_pct        = float(claim.applied_local_disc_pct)
    imported_disc_pct     = float(claim.applied_imported_disc_pct)
    tarsia_disc_pct       = float(claim.applied_tarsia_disc_pct)

    if billing_group is not None:
        # Power-Query-finalise the group's accumulated splits so the group cover
        # matches the same net formula as the whole-claim cover.
        cover_ft = _float_totals(claim_totals, claim)
        cover_local_before    = cover_ft['local_before']
        cover_imported_before = cover_ft['imported_before']
        cover_tarsia_before   = cover_ft['tarsia_before']
        cover_gross_before    = cover_ft['gross_before']
        cover_total_discount  = cover_ft['total_discount']
        cover_net_after       = cover_ft['net_after']
        cover_rx_count        = claim_totals['rx_count']
    else:
        cover_local_before    = float(claim.final_local_before)
        cover_imported_before = float(claim.final_imported_before)
        cover_tarsia_before   = float(claim.final_tarsia_before)
        cover_gross_before    = float(claim.final_gross_before)
        cover_total_discount  = float(claim.final_total_discount)
        cover_net_after       = float(claim.final_net_after)
        cover_rx_count        = claim.final_rx_count

    cover_local_disc      = round(cover_local_before    * local_disc_pct    / 100, 2)
    cover_imported_disc   = round(cover_imported_before * imported_disc_pct / 100, 2)
    cover_tarsia_disc     = round(cover_tarsia_before   * tarsia_disc_pct   / 100, 2)

    return {
        'claim': {
            'id':                claim.id,
            'claim_number':      claim.claim_number,
            'client_name':       claim.subclient.client.name,
            'subclient_name':    (f'{claim.subclient.name} — {billing_group.name}'
                                  if billing_group else claim.subclient.name),
            'period_from':       claim.period_from.isoformat(),
            'period_to':         claim.period_to.isoformat(),
            'status':            claim.status,
            'softech_motalba_no': claim.softech_motalba_no,
            'billing_group':     billing_group.code if billing_group else None,
            'local_disc_pct':    local_disc_pct,
            'imported_disc_pct': imported_disc_pct,
            'tarsia_disc_pct':   tarsia_disc_pct,
        },
        'cover': {
            'local_before':     cover_local_before,
            'local_discount':   cover_local_disc,
            'local_net':        round(cover_local_before - cover_local_disc, 2),
            'local_disc_pct':   local_disc_pct,
            'imported_before':  cover_imported_before,
            'imported_discount': cover_imported_disc,
            'imported_net':     round(cover_imported_before - cover_imported_disc, 2),
            'imported_disc_pct': imported_disc_pct,
            'tarsia_before':    cover_tarsia_before,
            'tarsia_discount':  cover_tarsia_disc,
            'tarsia_net':       round(cover_tarsia_before - cover_tarsia_disc, 2),
            'tarsia_disc_pct':  tarsia_disc_pct,
            'gross_before':     cover_gross_before,
            'total_discount':   cover_total_discount,
            'net_after':        cover_net_after,
            'rx_count':         cover_rx_count,
        },
        'days':         days_output,
        'claim_totals': _float_totals(claim_totals, claim),
        'standalone_supplements': [
            {
                'label':          s.label,
                'supplement_number': s.supplement_number,
                'rx_count':       s.rx_count,
                'net_after':      float(s.net_after),
                'gross_before':   float(s.gross_before),
                'total_discount': float(s.total_discount),
            }
            for s in standalone_sups
        ],
    }


def _float_row(row: dict) -> dict:
    """Convert all Decimal values in a row to float for JSON serialization."""
    return {
        k: float(v) if isinstance(v, Decimal) else v
        for k, v in row.items()
    }
