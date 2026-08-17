"""
apps/insurance/discrepancy.py

Value-discrepancy calculator for insurance claims.

Problem
-------
When a transaction was saved in SOFTECH, each item carried a certain
classification (محلى / مستورد / ترسية) which drove its discount.  Later, item
master data may be edited — an item moved from imported→local, a contract code
changed, etc.  The claim's FROZEN snapshot (InsuranceClaimLine) still reflects
the OLD classification, while the live catalog.Item master reflects the NEW one.

This calculator re-classifies every frozen line against the CURRENT master data
(the synced catalog.Item — no Sybase round-trips) and reports where the
category / discount / net would differ if the claim were re-imported today.

Read-only: it never mutates the frozen snapshot.  It just makes the drift
obvious so staff can decide to re-import or adjust.
"""
from decimal import Decimal

from apps.catalog.models import Item
from .classifier import (
    classify_item, DEFAULT_TARSIA_CLASSIF_CODES,
    load_classification_overrides, load_review_item_codes,
)
from .models import (
    InsuranceClaim, InsuranceClaimLine, InsuranceClaimExclusion,
    ITEM_CATEGORY_LOCAL, ITEM_CATEGORY_IMPORTED, ITEM_CATEGORY_TARSIA,
    ITEM_CATEGORY_CHOICES,
)

_CAT_LABEL = dict(ITEM_CATEGORY_CHOICES)
_Q = Decimal('0.01')


def _rate_for(category: str, rates: dict) -> Decimal:
    if category == ITEM_CATEGORY_IMPORTED:
        return rates['imported']
    if category == ITEM_CATEGORY_TARSIA:
        return rates['tarsia']
    return rates['local']


def _f(v) -> float:
    return float(v) if isinstance(v, Decimal) else (v or 0)


# Per-prescription gross gap (EGP) above which a prescription is flagged as a
# likely misclassification.  itemsaleprice drift is sub-EGP per prescription; a
# real category error moves whole pounds.
_GROSS_TOL = Decimal('1.00')


def compute_softech_gross_reconciliation(claim: InsuranceClaim,
                                         tol: Decimal = _GROSS_TOL) -> dict:
    """
    Pinpoint prescriptions whose NET differs from SOFTECH's stored net.

    Our net uses the finance team's Power-Query formula
    (محلى·(1−l) + مستورد·(1−i) + ترسية·(1−t)); SOFTECH's own net
    (motalba.docvaluerequired, mirrored on rx.softech_net) carries item-level
    discount nuance we intentionally drop.  A per-prescription difference is
    EXPECTED — this report just lists exactly where, so the user can review and
    decide to keep the Power-Query value (override) or revise the classification.

    Returns (keys kept stable for the existing frontend):
      {
        can_check, [reason],
        our_gross (= our net total), softech_gross (= softech net total),
        gross_delta, mismatch_count, tolerance,
        prescriptions: [
          {prescription_id, docnumber, patient_name, docdate,
           our_gross (our net), softech_gross (softech net), diff, hint}
        ],
      }
    """
    from .models import InsuranceClaimExclusion

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    # Use EFFECTIVE (adjustment-aware) net — same source the invoice/cover use —
    # so a prescription the user has already reclassified/overridden (e.g. moved
    # value to ترسية with a net_override) reconciles against SOFTECH instead of
    # reporting a phantom gap from the stale frozen snapshot.
    from .invoice_builder import _effective_rx_values

    rows = []
    our_tot = soft_tot = Decimal('0')
    have_ref = False
    for rx in claim.prescriptions.all():
        if rx.id in excluded_ids:
            continue
        if rx.softech_net is None:
            continue
        have_ref = True
        eff = _effective_rx_values(rx, claim)
        our = Decimal(str(eff['net_after'] or 0))
        sof = Decimal(str(rx.softech_net))
        our_tot += our
        soft_tot += sof
        diff = (our - sof).quantize(_Q)
        if abs(diff) > tol:
            hint = ('صافينا أعلى — سوفتك خصم أقل على بعض الأصناف'
                    if diff > 0 else
                    'صافينا أقل — سوفتك خصم أكبر على بعض الأصناف')
            rows.append({
                'prescription_id': rx.id,
                'docnumber':       rx.softech_docnumber,
                'patient_name':    rx.patient_name,
                'docdate':         rx.softech_docdate.isoformat() if rx.softech_docdate else None,
                'our_gross':       _f(our),
                'softech_gross':   _f(sof),
                'diff':            _f(diff),
                'hint':            hint,
            })

    if not have_ref:
        return {'can_check': False,
                'reason': 'لا توجد قيمة مرجعية من سوفتك — أعد الاستيراد لتعبئتها',
                'prescriptions': [], 'mismatch_count': 0}

    rows.sort(key=lambda r: abs(r['diff']), reverse=True)
    return {
        'can_check':      True,
        'our_gross':      _f(our_tot),
        'softech_gross':  _f(soft_tot),
        'gross_delta':    _f(our_tot - soft_tot),
        'mismatch_count': len(rows),
        'tolerance':      _f(tol),
        'prescriptions':  rows,
    }


def compute_claim_discrepancy(claim: InsuranceClaim, tarsia_codes: set | None = None) -> dict:
    """
    Compare each frozen claim line's classification/discount against current
    master data.  Returns a structured report:

    {
      'summary': {
         total_lines, changed_lines, items_not_found,
         frozen_discount, current_discount, discount_delta,
         frozen_net, current_net, net_delta,
      },
      'category_moves': [ {from, from_label, to, to_label, count, line_total, net_delta}, ... ],
      'lines': [ discrepant line detail ... ],   # only lines that actually differ
    }
    """
    tarsia_codes = tarsia_codes or DEFAULT_TARSIA_CLASSIF_CODES
    _overrides = load_classification_overrides()
    rates = {
        'local':    Decimal(str(claim.applied_local_disc_pct    or 0)),
        'imported': Decimal(str(claim.applied_imported_disc_pct or 0)),
        'tarsia':   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
    }

    # Excluded prescriptions don't count toward the live invoice
    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    lines = list(
        InsuranceClaimLine.objects
        .filter(prescription__claim=claim)
        .exclude(prescription_id__in=excluded_ids)
        .select_related('prescription')
    )

    # Pre-load current master for all referenced item codes (one query)
    codes = {ln.softech_itemcode for ln in lines if ln.softech_itemcode}
    item_map = {
        i.softech_id: i
        for i in Item.objects.filter(softech_id__in=codes)
        .only('softech_id', 'name', 'is_imported', 'store_classif')
    }

    total_lines = len(lines)
    changed = 0
    not_found = 0
    not_found_items: dict = {}   # item_code -> {code, name, category, lines}
    cat_changes = price_changes = 0
    frozen_disc_tot = current_disc_tot = Decimal('0')
    frozen_net_tot  = current_net_tot  = Decimal('0')
    frozen_gross_tot = current_gross_tot = Decimal('0')

    moves: dict = {}          # (from,to) -> {count, line_total, net_delta}
    detail = []

    for ln in lines:
        qty         = Decimal(str(ln.quantity or 0))
        frozen_unit = Decimal(str(ln.unit_price or 0))
        line_total  = Decimal(str(ln.line_total or 0))   # frozen public total
        frozen_cat  = ln.item_category
        frozen_disc = Decimal(str(ln.discount_amt or 0))
        frozen_net  = Decimal(str(ln.net_amount or 0))

        item = item_map.get(ln.softech_itemcode)
        if not item:
            # Can't reclassify/reprice — keep frozen, flag as unknown
            not_found += 1
            code = ln.softech_itemcode or ''
            entry = not_found_items.get(code)
            if entry:
                entry['lines'] += 1
            else:
                not_found_items[code] = {
                    'item_code':      code,
                    'item_name':      ln.item_name,
                    'category':       frozen_cat,
                    'category_label': _CAT_LABEL.get(frozen_cat, frozen_cat),
                    'lines':          1,
                }
            current_cat   = frozen_cat
            current_unit  = frozen_unit
            current_total = line_total
            current_disc  = frozen_disc
            current_net   = frozen_net
        else:
            current_cat = classify_item(
                imported_origin='1' if item.is_imported else '0',
                store_classif=item.store_classif,
                tarsia_codes=tarsia_codes,
                item_code=ln.softech_itemcode,
                overrides=_overrides,
            )
            # Current public unit price = catalog.Item.pack_price (current itemsaleprice)
            current_unit  = Decimal(str(item.pack_price or 0))
            # Derive the current gross by SCALING the frozen gross by the price
            # ratio — NOT by re-multiplying the stored quantity.  The quantity
            # column keeps only 3 decimals (e.g. ⅓ → 0.333) while the frozen
            # line_total was computed at import with the full-precision qty, so
            # unit×qty here would drift by a piastre and flag unchanged lines as
            # "different".  Scaling preserves that precision: price unchanged →
            # current_total == frozen line_total (zero phantom diff).
            if frozen_unit > 0:
                current_total = (line_total * current_unit / frozen_unit).quantize(_Q)
            else:
                current_total = (current_unit * qty).quantize(_Q)
            current_disc  = (current_total * _rate_for(current_cat, rates) / 100).quantize(_Q)
            current_net   = current_total - current_disc

        frozen_disc_tot   += frozen_disc
        current_disc_tot  += current_disc
        frozen_net_tot    += frozen_net
        current_net_tot   += current_net
        frozen_gross_tot  += line_total
        current_gross_tot += current_total

        net_delta   = current_net   - frozen_net
        price_delta = current_unit  - frozen_unit
        cat_changed   = current_cat != frozen_cat
        price_changed = item is not None and abs(price_delta) > Decimal('0.001')

        # Discrepant if category moved, price changed, or net differs > 1 piastre
        if cat_changed or price_changed or abs(net_delta) > Decimal('0.01'):
            changed += 1
            if cat_changed:
                cat_changes += 1
                key = (frozen_cat, current_cat)
                m = moves.setdefault(key, {'count': 0,
                                           'line_total': Decimal('0'),
                                           'net_delta': Decimal('0')})
                m['count'] += 1
                m['line_total'] += line_total
                m['net_delta']  += net_delta
            if price_changed:
                price_changes += 1

            reason = ('item_not_found' if not item
                      else 'both' if (cat_changed and price_changed)
                      else 'category_change' if cat_changed
                      else 'price_change' if price_changed
                      else 'rate_change')

            detail.append({
                'prescription_id': ln.prescription_id,
                'docnumber':       ln.prescription.softech_docnumber,
                'patient_name':    ln.prescription.patient_name,
                'docdate':         ln.prescription.softech_docdate.isoformat()
                                   if ln.prescription.softech_docdate else None,
                'itemcode':        ln.softech_itemcode,
                'item_name':       ln.item_name or (item.name if item else ''),
                'quantity':        _f(qty),
                # Price (before discount)
                'frozen_unit_price':  _f(frozen_unit),
                'current_unit_price': _f(current_unit),
                'price_delta':        _f(price_delta),
                'frozen_line_total':  _f(line_total),
                'current_line_total': _f(current_total),
                # Category
                'frozen_category':  frozen_cat,
                'frozen_category_label':  _CAT_LABEL.get(frozen_cat, frozen_cat),
                'current_category': current_cat,
                'current_category_label': _CAT_LABEL.get(current_cat, current_cat),
                # Discount + net
                'frozen_discount':  _f(frozen_disc),
                'current_discount': _f(current_disc),
                'discount_delta':   _f(current_disc - frozen_disc),
                'frozen_net':       _f(frozen_net),
                'current_net':      _f(current_net),
                'net_delta':        _f(net_delta),
                'reason': reason,
            })

    # Sort discrepant lines by absolute net impact (biggest first)
    detail.sort(key=lambda d: abs(d['net_delta']), reverse=True)

    category_moves = [
        {
            'from':       frm,
            'from_label': _CAT_LABEL.get(frm, frm),
            'to':         to,
            'to_label':   _CAT_LABEL.get(to, to),
            'count':      m['count'],
            'line_total': _f(m['line_total']),
            'net_delta':  _f(m['net_delta']),
        }
        for (frm, to), m in sorted(moves.items(), key=lambda kv: abs(kv[1]['net_delta']), reverse=True)
    ]

    # Per-prescription reconciliation against SOFTECH's own stored gross — this
    # catches misclassifications made AT import (where our classifier disagreed
    # with SOFTECH), which the catalog-drift scan above cannot see.
    try:
        softech_recon = compute_softech_gross_reconciliation(claim)
    except Exception:
        softech_recon = {'can_check': False, 'prescriptions': [], 'mismatch_count': 0}

    return {
        'summary': {
            'total_lines':      total_lines,
            'changed_lines':    changed,
            'category_changes': cat_changes,
            'price_changes':    price_changes,
            'items_not_found':  not_found,
            'frozen_gross':     _f(frozen_gross_tot),
            'current_gross':    _f(current_gross_tot),
            'gross_delta':      _f(current_gross_tot - frozen_gross_tot),
            'frozen_discount':  _f(frozen_disc_tot),
            'current_discount': _f(current_disc_tot),
            'discount_delta':   _f(current_disc_tot - frozen_disc_tot),
            'frozen_net':       _f(frozen_net_tot),
            'current_net':      _f(current_net_tot),
            'net_delta':        _f(current_net_tot - frozen_net_tot),
        },
        'category_moves':        category_moves,
        'lines':                 detail,
        'not_found_items':       sorted(not_found_items.values(), key=lambda x: x['item_code']),
        'softech_reconciliation': softech_recon,
    }


def apply_current_master(claim: InsuranceClaim, tarsia_codes: set | None = None,
                         apply_price: bool = True, apply_category: bool = True,
                         user=None) -> dict:
    """
    Re-freeze the claim's lines + prescription totals to CURRENT item master data.

    This is a deliberate, user-triggered correction (NOT automatic).  It rewrites
    each InsuranceClaimLine's category / unit_price / line_total / discount / net
    from the synced catalog.Item, then re-aggregates the parent prescription's
    frozen totals and the claim snapshot + final totals.

    Flags let the caller choose what to apply:
      apply_category — adopt the current محلى/مستورد/ترسية classification
      apply_price    — adopt the current سعر الجمهور (unit price before discount)

    Manual per-prescription adjustments (InsuranceClaimAdjustment) are left
    intact — they continue to layer on top in the invoice builder.

    Returns a summary {lines_updated, prescriptions_updated, net_before,
    net_after, net_delta}.
    """
    from django.db import transaction as _txn
    from .classifier import calculate_line_discount
    from .importer import recalculate_claim_final_totals

    tarsia_codes = tarsia_codes or DEFAULT_TARSIA_CLASSIF_CODES
    _overrides = load_classification_overrides()
    rates = {
        'local':    Decimal(str(claim.applied_local_disc_pct    or 0)),
        'imported': Decimal(str(claim.applied_imported_disc_pct or 0)),
        'tarsia':   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
    }

    net_before = Decimal(str(claim.final_net_after or 0))
    prescriptions = list(claim.prescriptions.prefetch_related('lines'))
    codes = {ln.softech_itemcode
             for rx in prescriptions for ln in rx.lines.all() if ln.softech_itemcode}
    item_map = {
        i.softech_id: i
        for i in Item.objects.filter(softech_id__in=codes)
        .only('softech_id', 'is_imported', 'store_classif', 'pack_price')
    }

    lines_updated = 0
    rx_updated = 0

    from .models import InsuranceApplyMasterRun, InsuranceClaimLineBackup

    # Capture full pre-mutation state (prescription + claim totals) so undo is
    # lossless even when prescriptions were dgt-scaled (line sums ≠ rx totals).
    pre_state = {
        'claim': {f: str(getattr(claim, f)) for f in (
            'final_local_before', 'final_imported_before', 'final_tarsia_before',
            'final_gross_before', 'final_total_discount', 'final_net_after', 'final_rx_count',
            'snapshot_local_before', 'snapshot_imported_before', 'snapshot_tarsia_before',
            'snapshot_gross_before', 'snapshot_total_discount', 'snapshot_net_after', 'snapshot_rx_count',
        )},
        'prescriptions': {
            str(rx.pk): {f: str(getattr(rx, f)) for f in (
                'local_before', 'imported_before', 'tarsia_before', 'gross_before',
                'local_discount', 'imported_discount', 'tarsia_discount',
                'total_discount', 'net_after',
            )}
            for rx in prescriptions
        },
    }

    with _txn.atomic():
        # Audit run header — created up front; line backups recorded before mutate
        run = InsuranceApplyMasterRun.objects.create(
            claim=claim, applied_by=user,
            apply_price=apply_price, apply_category=apply_category,
            net_before=net_before, pre_state=pre_state,
        )
        backups = []   # bulk-created after the loop

        for rx in prescriptions:
            rx_lines = list(rx.lines.all())
            rx_dirty = False
            agg = {ITEM_CATEGORY_LOCAL: Decimal('0'),
                   ITEM_CATEGORY_IMPORTED: Decimal('0'),
                   ITEM_CATEGORY_TARSIA: Decimal('0')}

            line_objs_to_save = []
            for ln in rx_lines:
                item = item_map.get(ln.softech_itemcode)
                qty  = Decimal(str(ln.quantity or 0))

                new_cat   = ln.item_category
                new_unit  = Decimal(str(ln.unit_price or 0))
                if item:
                    if apply_category:
                        new_cat = classify_item(
                            imported_origin='1' if item.is_imported else '0',
                            store_classif=item.store_classif,
                            tarsia_codes=tarsia_codes,
                            item_code=ln.softech_itemcode,
                            overrides=_overrides,
                        )
                    if apply_price:
                        new_unit = Decimal(str(item.pack_price or 0))

                new_total = (new_unit * qty).quantize(_Q)
                disc, net = calculate_line_discount(
                    new_cat, new_total, rates['local'], rates['imported'], rates['tarsia'],
                )

                if (new_cat != ln.item_category
                        or new_unit != Decimal(str(ln.unit_price or 0))
                        or new_total != Decimal(str(ln.line_total or 0))):
                    # Snapshot BEFORE values for undo/audit
                    backups.append(InsuranceClaimLineBackup(
                        run=run, line=ln,
                        item_category=ln.item_category,
                        unit_price=ln.unit_price,
                        line_total=ln.line_total,
                        discount_pct=ln.discount_pct,
                        discount_amt=ln.discount_amt,
                        net_amount=ln.net_amount,
                    ))
                    ln.item_category = new_cat
                    ln.unit_price    = new_unit
                    ln.line_total    = new_total
                    ln.discount_pct  = _rate_for(new_cat, rates)
                    ln.discount_amt  = disc
                    ln.net_amount    = net
                    line_objs_to_save.append(ln)
                    lines_updated += 1
                    rx_dirty = True

                agg[new_cat] += new_total

            if line_objs_to_save:
                InsuranceClaimLine.objects.bulk_update(
                    line_objs_to_save,
                    ['item_category', 'unit_price', 'line_total',
                     'discount_pct', 'discount_amt', 'net_amount'],
                )

            if rx_dirty:
                lb, ib, tb = agg[ITEM_CATEGORY_LOCAL], agg[ITEM_CATEGORY_IMPORTED], agg[ITEM_CATEGORY_TARSIA]
                gross = lb + ib + tb
                ld = (lb * rates['local']    / 100).quantize(_Q)
                idd = (ib * rates['imported'] / 100).quantize(_Q)
                td = (tb * rates['tarsia']   / 100).quantize(_Q)
                rx.local_before     = lb
                rx.imported_before  = ib
                rx.tarsia_before    = tb
                rx.gross_before     = gross
                rx.local_discount   = ld
                rx.imported_discount = idd
                rx.tarsia_discount  = td
                rx.total_discount   = ld + idd + td
                rx.net_after        = gross - (ld + idd + td)
                rx.save(update_fields=[
                    'local_before', 'imported_before', 'tarsia_before', 'gross_before',
                    'local_discount', 'imported_discount', 'tarsia_discount',
                    'total_discount', 'net_after',
                ])
                rx_updated += 1

        # Persist line backups (one bulk insert)
        if backups:
            InsuranceClaimLineBackup.objects.bulk_create(backups, batch_size=1000)

        # Re-aggregate claim final totals (and refresh snapshot to match)
        recalculate_claim_final_totals(claim)
        claim.refresh_from_db()
        _sync_snapshot_to_final(claim)

        # Finalize the audit run.  If nothing actually changed, drop the empty run.
        if lines_updated == 0:
            run.delete()
            run = None
        else:
            run.lines_updated         = lines_updated
            run.prescriptions_updated = rx_updated
            run.net_after             = Decimal(str(claim.final_net_after or 0))
            run.save(update_fields=['lines_updated', 'prescriptions_updated', 'net_after'])

    net_after = Decimal(str(claim.final_net_after or 0))
    return {
        'run_id':                run.pk if run else None,
        'lines_updated':         lines_updated,
        'prescriptions_updated': rx_updated,
        'net_before':            _f(net_before),
        'net_after':             _f(net_after),
        'net_delta':             _f(net_after - net_before),
    }


def _apply_category_decisions(claim: InsuranceClaim, decisions: dict, user=None) -> dict:
    """
    SURGICAL apply of a {item_code: category} decision map to a draft claim.

    Unlike apply_current_master (which re-freezes the WHOLE claim against master
    data and re-aggregates every prescription from its lines), this ONLY touches
    lines whose item is in `decisions` AND whose category actually changes.
    Everything else — prices, non-decided line categories, and the frozen
    prescription totals (incl. any dgt-scaling) — is left byte-for-byte intact.

    For each changed line the item's public value simply moves from its old
    محلى/مستورد/ترسية bucket to the decided one (gross unchanged); the
    prescription's discount/net are re-derived from the shifted splits.  Records
    an audited, revertible run (reuses revert_apply_run).

    Shared by the global force-override apply and the per-motalba review decision.
    """
    from django.db import transaction as _txn
    from .classifier import calculate_line_discount
    from .importer import recalculate_claim_final_totals
    from .models import (
        InsuranceApplyMasterRun, InsuranceClaimLineBackup, InsuranceClaimLine,
    )

    overrides = decisions or {}
    rates = {
        ITEM_CATEGORY_LOCAL:    Decimal(str(claim.applied_local_disc_pct    or 0)),
        ITEM_CATEGORY_IMPORTED: Decimal(str(claim.applied_imported_disc_pct or 0)),
        ITEM_CATEGORY_TARSIA:   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
    }
    _CAT_BEFORE = {
        ITEM_CATEGORY_LOCAL:    'local_before',
        ITEM_CATEGORY_IMPORTED: 'imported_before',
        ITEM_CATEGORY_TARSIA:   'tarsia_before',
    }

    net_before = Decimal(str(claim.final_net_after or 0))
    prescriptions = list(claim.prescriptions.prefetch_related('lines'))

    # Pre-scan: which prescriptions have a line that actually changes category?
    affected = {}   # rx -> [(line, forced_cat)]
    for rx in prescriptions:
        hits = []
        for ln in rx.lines.all():
            forced = overrides.get(str(ln.softech_itemcode).strip()) if ln.softech_itemcode else None
            if forced and forced != ln.item_category:
                hits.append((ln, forced))
        if hits:
            affected[rx.pk] = (rx, hits)

    if not affected:
        return {'run_id': None, 'lines_updated': 0, 'prescriptions_updated': 0,
                'net_before': _f(net_before), 'net_after': _f(net_before), 'net_delta': 0.0}

    # Lossless pre-state for undo — only the prescriptions we touch, plus claim.
    pre_state = {
        'claim': {f: str(getattr(claim, f)) for f in (
            'final_local_before', 'final_imported_before', 'final_tarsia_before',
            'final_gross_before', 'final_total_discount', 'final_net_after', 'final_rx_count',
            'snapshot_local_before', 'snapshot_imported_before', 'snapshot_tarsia_before',
            'snapshot_gross_before', 'snapshot_total_discount', 'snapshot_net_after', 'snapshot_rx_count',
        )},
        'prescriptions': {
            str(rx.pk): {f: str(getattr(rx, f)) for f in (
                'local_before', 'imported_before', 'tarsia_before', 'gross_before',
                'local_discount', 'imported_discount', 'tarsia_discount',
                'total_discount', 'net_after',
            )}
            for (rx, _) in affected.values()
        },
    }

    lines_updated = 0
    with _txn.atomic():
        run = InsuranceApplyMasterRun.objects.create(
            claim=claim, applied_by=user,
            apply_price=False, apply_category=True,
            net_before=net_before, pre_state=pre_state,
        )
        backups = []
        for rx, hits in affected.values():
            splits = {
                ITEM_CATEGORY_LOCAL:    Decimal(str(rx.local_before    or 0)),
                ITEM_CATEGORY_IMPORTED: Decimal(str(rx.imported_before or 0)),
                ITEM_CATEGORY_TARSIA:   Decimal(str(rx.tarsia_before   or 0)),
            }
            line_objs = []
            for ln, forced in hits:
                total = Decimal(str(ln.line_total or 0))
                # Move the item's public value between buckets (gross unchanged)
                splits[ln.item_category] -= total
                splits[forced]           += total
                # Re-price this line at the corrected rate
                disc, net = calculate_line_discount(
                    forced, total, rates[ITEM_CATEGORY_LOCAL],
                    rates[ITEM_CATEGORY_IMPORTED], rates[ITEM_CATEGORY_TARSIA],
                )
                backups.append(InsuranceClaimLineBackup(
                    run=run, line=ln,
                    item_category=ln.item_category, unit_price=ln.unit_price,
                    line_total=ln.line_total, discount_pct=ln.discount_pct,
                    discount_amt=ln.discount_amt, net_amount=ln.net_amount,
                ))
                ln.item_category = forced
                ln.discount_pct  = _rate_for(forced, rates)
                ln.discount_amt  = disc
                ln.net_amount    = net
                line_objs.append(ln)
                lines_updated += 1

            InsuranceClaimLine.objects.bulk_update(
                line_objs, ['item_category', 'discount_pct', 'discount_amt', 'net_amount'])

            # Re-derive the prescription discount/net from the shifted splits.
            lb, ib, tb = splits[ITEM_CATEGORY_LOCAL], splits[ITEM_CATEGORY_IMPORTED], splits[ITEM_CATEGORY_TARSIA]
            ld  = (lb * rates[ITEM_CATEGORY_LOCAL]    / 100).quantize(_Q)
            idd = (ib * rates[ITEM_CATEGORY_IMPORTED] / 100).quantize(_Q)
            td  = (tb * rates[ITEM_CATEGORY_TARSIA]   / 100).quantize(_Q)
            rx.local_before      = lb
            rx.imported_before   = ib
            rx.tarsia_before     = tb
            # gross_before intentionally UNCHANGED (value only moved buckets)
            rx.local_discount    = ld
            rx.imported_discount = idd
            rx.tarsia_discount   = td
            rx.total_discount    = ld + idd + td
            rx.net_after         = Decimal(str(rx.gross_before or 0)) - (ld + idd + td)
            rx.save(update_fields=[
                'local_before', 'imported_before', 'tarsia_before',
                'local_discount', 'imported_discount', 'tarsia_discount',
                'total_discount', 'net_after',
            ])

        if backups:
            InsuranceClaimLineBackup.objects.bulk_create(backups, batch_size=1000)

        recalculate_claim_final_totals(claim)
        claim.refresh_from_db()
        _sync_snapshot_to_final(claim)

        run.lines_updated         = lines_updated
        run.prescriptions_updated = len(affected)
        run.net_after             = Decimal(str(claim.final_net_after or 0))
        run.save(update_fields=['lines_updated', 'prescriptions_updated', 'net_after'])

    net_after = Decimal(str(claim.final_net_after or 0))
    return {
        'run_id':                run.pk,
        'lines_updated':         lines_updated,
        'prescriptions_updated': len(affected),
        'net_before':            _f(net_before),
        'net_after':             _f(net_after),
        'net_delta':             _f(net_after - net_before),
    }


def apply_overrides_to_claim(claim: InsuranceClaim, user=None) -> dict:
    """Apply the active GLOBAL force-overrides to a draft claim (surgical, audited)."""
    return _apply_category_decisions(claim, load_classification_overrides(), user)


def apply_review_decision(claim: InsuranceClaim, item_code: str, category: str, user=None) -> dict:
    """
    Apply a PER-MOTALBA decision for one dual-origin (review) item: set every line
    of `item_code` in this claim to `category` (surgical, audited, revertible).
    """
    if category not in (ITEM_CATEGORY_LOCAL, ITEM_CATEGORY_IMPORTED, ITEM_CATEGORY_TARSIA):
        return {'error': 'تصنيف غير صالح'}
    return _apply_category_decisions(claim, {str(item_code).strip(): category}, user)


def review_items_for_claim(claim: InsuranceClaim) -> dict:
    """
    READ-ONLY: for every ACTIVE review (dual-origin) item present in this claim,
    report the lines, their CURRENT frozen category, the suggested default, and
    the per-item value split by prescription — so staff can decide per motalba.
    """
    review = load_review_item_codes()   # {item_code: suggested_category}
    _LBL = dict(ITEM_CATEGORY_CHOICES)
    if not review:
        return {'items': []}

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    from .models import InsuranceClaimLine
    lines = (InsuranceClaimLine.objects
             .filter(prescription__claim=claim,
                     softech_itemcode__in=list(review.keys()))
             .exclude(prescription_id__in=excluded_ids)
             .select_related('prescription')
             .order_by('softech_itemcode', 'prescription__softech_docnumber'))

    agg = {}   # item_code -> {…}
    for ln in lines:
        code = ln.softech_itemcode
        if code not in agg:
            agg[code] = {
                'item_code':        code,
                'item_name':        ln.item_name,
                'suggested':        review.get(code),
                'suggested_label':  _LBL.get(review.get(code), review.get(code)),
                'line_count':       0,
                'total_value':      Decimal('0'),
                'categories':       {},   # current frozen category -> count
                'lines':            [],
            }
        a = agg[code]
        a['line_count'] += 1
        a['total_value'] += Decimal(str(ln.line_total or 0))
        a['categories'][ln.item_category] = a['categories'].get(ln.item_category, 0) + 1
        a['lines'].append({
            'docnumber':      ln.prescription.softech_docnumber,
            'current':        ln.item_category,
            'current_label':  _LBL.get(ln.item_category, ln.item_category),
            'line_total':     _f(ln.line_total),
        })

    items = []
    for code, a in agg.items():
        cur_cats = sorted(a['categories'].keys())
        items.append({
            'item_code':       a['item_code'],
            'item_name':       a['item_name'],
            'suggested':       a['suggested'],
            'suggested_label': a['suggested_label'],
            'line_count':      a['line_count'],
            'total_value':     _f(a['total_value']),
            'current_categories': [{'category': c, 'label': _LBL.get(c, c),
                                    'count': a['categories'][c]} for c in cur_cats],
            'is_mixed':        len(cur_cats) > 1,
            'lines':           a['lines'][:100],
        })
    items.sort(key=lambda x: x['item_code'])
    return {'items': items}


def claim_items_for_revision(claim: InsuranceClaim) -> dict:
    """
    READ-ONLY: ONE ROW PER DISPENSED ITEM across the whole motalba (non-excluded),
    with the discount actually applied — for reviewing/revising every item's
    classification in one place.

    Per item: code, name, line_count, total_qty, gross (public value), the applied
    discount amount + net (summed from the frozen lines), the current category
    (or 'mixed' when the same code was dispensed under >1 category), the effective
    discount %, and flags: whether it's on the force-override or review list, and
    its CURRENT catalog classification (for reference).
    """
    review = load_review_item_codes()          # {code: suggested}
    force  = load_classification_overrides()    # {code: forced}
    _LBL = dict(ITEM_CATEGORY_CHOICES)
    rates = {
        ITEM_CATEGORY_LOCAL:    Decimal(str(claim.applied_local_disc_pct    or 0)),
        ITEM_CATEGORY_IMPORTED: Decimal(str(claim.applied_imported_disc_pct or 0)),
        ITEM_CATEGORY_TARSIA:   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
    }

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    from .models import InsuranceClaimLine
    lines = (InsuranceClaimLine.objects
             .filter(prescription__claim=claim)
             .exclude(prescription_id__in=excluded_ids)
             .only('softech_itemcode', 'item_name', 'item_category',
                   'quantity', 'line_total', 'discount_amt', 'net_amount'))

    # Current catalog classification + item-card fields (المنشأ / تصنيف خصم
    # التعاقدات / خصم أساسى), synced from SOFTECH — one query.
    codes = {ln.softech_itemcode for ln in lines if ln.softech_itemcode}
    item_map = {
        i.softech_id: i for i in
        Item.objects.filter(softech_id__in=codes).only(
            'softech_id', 'is_imported', 'store_classif', 'store_classif_name',
            'origin_name', 'origin_name_ar', 'pharmacy_discp')
    }

    agg = {}
    for ln in lines:
        code = ln.softech_itemcode or ''
        a = agg.get(code)
        if a is None:
            a = agg[code] = {
                'item_code': code, 'item_name': ln.item_name,
                'line_count': 0, 'total_qty': Decimal('0'), 'gross': Decimal('0'),
                'discount': Decimal('0'), 'net': Decimal('0'), 'cats': {},
            }
        a['line_count'] += 1
        a['total_qty']  += Decimal(str(ln.quantity or 0))
        a['gross']      += Decimal(str(ln.line_total or 0))
        a['discount']   += Decimal(str(ln.discount_amt or 0))
        a['net']        += Decimal(str(ln.net_amount or 0))
        a['cats'][ln.item_category] = a['cats'].get(ln.item_category, 0) + 1

    items = []
    for code, a in agg.items():
        cats = sorted(a['cats'].keys())
        is_mixed = len(cats) > 1
        cur_cat = cats[0] if len(cats) == 1 else None
        item = item_map.get(code)
        catalog_cat = None
        if item is not None:
            catalog_cat = classify_item(
                imported_origin='1' if item.is_imported else '0',
                store_classif=item.store_classif, item_code=code,
            )
        gross = a['gross']
        eff_pct = (a['discount'] / gross * 100) if gross else Decimal('0')
        items.append({
            'item_code':       code,
            'item_name':       a['item_name'],
            'line_count':      a['line_count'],
            'total_qty':       _f(a['total_qty']),
            'gross':           _f(gross),
            'discount':        _f(a['discount']),
            'net':             _f(a['net']),
            'discount_pct':    round(float(eff_pct), 2),
            'category':        cur_cat,               # None when mixed
            'category_label':  _LBL.get(cur_cat) if cur_cat else 'مختلط',
            'is_mixed':        is_mixed,
            'categories':      [{'category': c, 'label': _LBL.get(c, c), 'count': a['cats'][c]} for c in cats],
            'on_force':        code in force,
            'on_review':       code in review,
            'catalog_category': catalog_cat,
            'catalog_label':   _LBL.get(catalog_cat) if catalog_cat else None,
            # ── SOFTECH item-card fields (from synced catalog.Item) ────────────
            'origin':          (item.origin_name or item.origin_name_ar) if item else None,      # المنشأ
            'contract_classif_code': item.store_classif if item else None,                       # تصنيف خصم التعاقدات (code)
            'contract_classif':      (item.store_classif_name or item.store_classif) if item else None,  # …(name)
            'basic_discount':  _f(item.pharmacy_discp) if item else None,                        # خصم أساسى %
        })
    items.sort(key=lambda x: x['gross'], reverse=True)
    return {
        'items':       items,
        'item_count':  len(items),
        'rates':       {'local': _f(rates[ITEM_CATEGORY_LOCAL]),
                        'imported': _f(rates[ITEM_CATEGORY_IMPORTED]),
                        'tarsia': _f(rates[ITEM_CATEGORY_TARSIA])},
    }


def preview_overrides_for_claim(claim: InsuranceClaim) -> dict:
    """
    READ-ONLY: report which frozen lines an override would move and the projected
    net change — WITHOUT mutating anything.  Powers the confirm dialog before
    apply.  Returns {can_apply, affected_lines, affected_rx, net_before,
    net_projected, net_delta, lines:[...]}.
    """
    overrides = load_classification_overrides()
    _LBL = dict(ITEM_CATEGORY_CHOICES)
    rates = {
        ITEM_CATEGORY_LOCAL:    Decimal(str(claim.applied_local_disc_pct    or 0)),
        ITEM_CATEGORY_IMPORTED: Decimal(str(claim.applied_imported_disc_pct or 0)),
        ITEM_CATEGORY_TARSIA:   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
    }

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    net_before = Decimal(str(claim.final_net_after or 0))
    lines_out = []
    net_delta = Decimal('0')
    affected_rx = set()

    prescriptions = claim.prescriptions.exclude(id__in=excluded_ids).prefetch_related('lines')
    for rx in prescriptions:
        for ln in rx.lines.all():
            forced = overrides.get(str(ln.softech_itemcode).strip()) if ln.softech_itemcode else None
            if not forced or forced == ln.item_category:
                continue
            total = Decimal(str(ln.line_total or 0))
            old_net = total * (Decimal('1') - _rate_for(ln.item_category, rates) / 100)
            new_net = total * (Decimal('1') - _rate_for(forced,           rates) / 100)
            d = (new_net - old_net).quantize(_Q)
            net_delta += d
            affected_rx.add(rx.id)
            lines_out.append({
                'prescription_id': rx.id,
                'docnumber':       rx.softech_docnumber,
                'item_code':       ln.softech_itemcode,
                'item_name':       ln.item_name,
                'from_category':   ln.item_category,
                'from_label':      _LBL.get(ln.item_category, ln.item_category),
                'to_category':     forced,
                'to_label':        _LBL.get(forced, forced),
                'line_total':      _f(total),
                'net_delta':       _f(d),
            })

    lines_out.sort(key=lambda r: abs(r['net_delta']), reverse=True)
    return {
        'can_apply':      bool(lines_out),
        'affected_lines': len(lines_out),
        'affected_rx':    len(affected_rx),
        'net_before':     _f(net_before),
        'net_projected':  _f(net_before + net_delta),
        'net_delta':      _f(net_delta),
        'lines':          lines_out,
    }


def _sync_snapshot_to_final(claim: InsuranceClaim) -> None:
    """Mirror the claim's final_* totals onto its snapshot_* fields."""
    claim.snapshot_local_before    = claim.final_local_before
    claim.snapshot_imported_before = claim.final_imported_before
    claim.snapshot_tarsia_before   = claim.final_tarsia_before
    claim.snapshot_gross_before    = claim.final_gross_before
    claim.snapshot_total_discount  = claim.final_total_discount
    claim.snapshot_net_after       = claim.final_net_after
    claim.snapshot_rx_count        = claim.final_rx_count
    claim.save(update_fields=[
        'snapshot_local_before', 'snapshot_imported_before', 'snapshot_tarsia_before',
        'snapshot_gross_before', 'snapshot_total_discount', 'snapshot_net_after',
        'snapshot_rx_count',
    ])


def revert_apply_run(run, user=None) -> dict:
    """
    Undo an apply-current-master run: restore each backed-up line to its
    pre-apply values, re-aggregate the affected prescriptions and claim totals.
    Returns {lines_restored, net_before, net_after, net_delta}.
    """
    from django.db import transaction as _txn
    from django.utils import timezone
    from .importer import recalculate_claim_final_totals
    from .models import InsuranceClaimLine

    if run.reverted:
        return {'error': 'سبق التراجع عن هذه العملية'}

    claim = run.claim
    net_before = Decimal(str(claim.final_net_after or 0))

    backups = list(run.line_backups.select_related('line__prescription'))
    pre = run.pre_state or {}
    if not backups and not pre:
        return {'error': 'لا توجد نسخة محفوظة للتراجع'}

    with _txn.atomic():
        # 1) Restore line values exactly
        restore_lines = []
        for b in backups:
            ln = b.line
            ln.item_category = b.item_category
            ln.unit_price    = b.unit_price
            ln.line_total    = b.line_total
            ln.discount_pct  = b.discount_pct
            ln.discount_amt  = b.discount_amt
            ln.net_amount    = b.net_amount
            restore_lines.append(ln)
        if restore_lines:
            InsuranceClaimLine.objects.bulk_update(
                restore_lines,
                ['item_category', 'unit_price', 'line_total',
                 'discount_pct', 'discount_amt', 'net_amount'],
            )

        # 2) Restore prescription totals DIRECTLY from pre_state (preserves dgt
        #    scaling — never re-aggregate from raw lines).
        rx_pre = (pre.get('prescriptions') or {})
        if rx_pre:
            from .models import InsuranceClaimPrescription
            rx_objs = list(InsuranceClaimPrescription.objects.filter(
                pk__in=[int(k) for k in rx_pre.keys()]
            ))
            for rx in rx_objs:
                vals = rx_pre.get(str(rx.pk))
                if not vals:
                    continue
                for f, v in vals.items():
                    setattr(rx, f, Decimal(v))
            InsuranceClaimPrescription.objects.bulk_update(
                rx_objs,
                ['local_before', 'imported_before', 'tarsia_before', 'gross_before',
                 'local_discount', 'imported_discount', 'tarsia_discount',
                 'total_discount', 'net_after'],
            )

        # 3) Restore claim totals DIRECTLY from pre_state
        claim_pre = (pre.get('claim') or {})
        if claim_pre:
            for f, v in claim_pre.items():
                if f.endswith('rx_count'):
                    setattr(claim, f, int(Decimal(v)))
                else:
                    setattr(claim, f, Decimal(v))
            claim.save(update_fields=list(claim_pre.keys()))
        else:
            recalculate_claim_final_totals(claim)
            claim.refresh_from_db()
            _sync_snapshot_to_final(claim)

        run.reverted    = True
        run.reverted_at = timezone.now()
        run.reverted_by = user
        run.save(update_fields=['reverted', 'reverted_at', 'reverted_by'])

    net_after = Decimal(str(claim.final_net_after or 0))
    return {
        'lines_restored': len(backups),
        'net_before':     _f(net_before),
        'net_after':      _f(net_after),
        'net_delta':      _f(net_after - net_before),
    }
