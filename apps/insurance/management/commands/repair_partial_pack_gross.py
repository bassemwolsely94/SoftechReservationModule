"""
Repair partial-pack gross-before-discount drift on frozen insurance lines.

Background
----------
`InsuranceClaimLine.quantity` stores only 3 decimals, so a fractional pack qty
(e.g. JUSPRIN ⅔ = 0.66667) is truncated to 0.667.  A prior `apply_current_master`
run recomputed the line gross as `unit_price × quantity` from that truncated qty
(81 × 0.667 = 54.03) instead of SOFTECH's true gross (81 × 0.66667 = 54.00).  The
apply-master path is now fixed to scale by the price ratio, but lines already
corrupted (and delivered — e.g. the August motalbas) keep the inflated gross.

This command re-derives the AUTHORITATIVE gross from SOFTECH — exactly the way the
importer freezes it: `itemsaleprice × transqty` at FULL precision — and rewrites
only the value-discrepancy-flagged lines, re-deriving each line's discount/net
(frozen category × the claim's applied rates) and re-aggregating the prescription
and claim totals with the finance-team Power-Query formula.

Safety
------
* READ-ONLY on SOFTECH (a single SELECT per prescription).
* Dry-run by DEFAULT — pass --apply to write.
* Only touches lines the local detector flags as value_discrepancy (fractional qty
  whose gross == round(unit_price × qty_3dp, 2)); never manually-edited lines;
  never excluded prescriptions.
* Skips a line whose correction exceeds --tol EGP (default 1.00) — that is not a
  rounding artefact and is surfaced for manual review instead of auto-changed.
* Records an audited, REVERTIBLE InsuranceApplyMasterRun (+ per-line backups), so
  the repair can be undone from the same «سجل التطبيق»/undo path as apply-master.

Usage
-----
  manage.py repair_partial_pack_gross --claim 42                 # dry-run one claim
  manage.py repair_partial_pack_gross --claim 42 --apply         # write it
  manage.py repair_partial_pack_gross --all --status draft --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as _txn

from apps.insurance.models import (
    InsuranceClaim, InsuranceClaimLine, InsuranceClaimExclusion,
    InsuranceApplyMasterRun, InsuranceClaimLineBackup,
    ITEM_CATEGORY_LOCAL, ITEM_CATEGORY_IMPORTED, ITEM_CATEGORY_TARSIA,
)
from apps.insurance.classifier import (
    calculate_line_discount, powerquery_totals_from_splits,
)
from apps.insurance.discrepancy import line_variance_map, _sync_snapshot_to_final
from apps.insurance.importer import (
    _get_connection, _to_qty, _to_decimal, _safe, recalculate_claim_final_totals,
)
from apps.insurance.sybase_queries import QUERY_PRESCRIPTION_LINES_CLASSIFIED
from apps.insurance.audit import record_audit

_Q = Decimal('0.01')


class Command(BaseCommand):
    help = 'Re-derive partial-pack gross-before-discount from SOFTECH for value-discrepancy lines.'

    def add_arguments(self, parser):
        parser.add_argument('--claim', type=int, action='append', default=[],
                            help='Claim id to repair (repeatable).')
        parser.add_argument('--all', action='store_true',
                            help='Repair every matching claim (optionally narrowed by --status).')
        parser.add_argument('--status', type=str, default=None,
                            help='With --all: only claims in this status (e.g. draft).')
        parser.add_argument('--apply', action='store_true',
                            help='Write the corrections. Omitted = dry-run (default).')
        parser.add_argument('--tol', type=str, default='1.00',
                            help='Max per-line correction (EGP) to auto-apply. Default 1.00.')

    def handle(self, *args, **opts):
        apply = opts['apply']
        tol = Decimal(str(opts['tol']))
        if opts['claim']:
            claims = list(InsuranceClaim.objects.filter(pk__in=opts['claim']))
            missing = set(opts['claim']) - {c.pk for c in claims}
            if missing:
                raise CommandError(f'Claim(s) not found: {sorted(missing)}')
        elif opts['all']:
            qs = InsuranceClaim.objects.all()
            if opts['status']:
                qs = qs.filter(status=opts['status'])
            claims = list(qs)
        else:
            raise CommandError('Pass --claim <id> (repeatable) or --all.')

        mode = self.style.WARNING('APPLY') if apply else self.style.NOTICE('DRY-RUN')
        self.stdout.write(f'{mode} · tol={tol} EGP · {len(claims)} claim(s)')

        conn = None
        try:
            for claim in claims:
                if conn is None:
                    conn = _get_connection()
                self._repair_claim(claim, conn, tol, apply)
        finally:
            if conn is not None:
                try: conn.close()
                except Exception: pass

    # ── per-claim ─────────────────────────────────────────────────────────────
    def _repair_claim(self, claim, conn, tol, apply):
        excluded_ids = set(
            InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
            .values_list('prescription_id', flat=True))
        lines = list(
            InsuranceClaimLine.objects
            .filter(prescription__claim=claim)
            .exclude(prescription_id__in=excluded_ids)
            .select_related('prescription'))
        vmap = line_variance_map(claim, lines)

        # Candidate lines: value-discrepancy-flagged, not manually edited.
        candidates = [ln for ln in lines
                      if (vmap.get(ln.pk) or {}).get('value_discrepancy')
                      and not ln.is_manually_edited]
        if not candidates:
            self.stdout.write(f'  claim {claim.pk} «{claim.claim_number}»: no flagged lines.')
            return

        rates = {
            ITEM_CATEGORY_LOCAL:    Decimal(str(claim.applied_local_disc_pct    or 0)),
            ITEM_CATEGORY_IMPORTED: Decimal(str(claim.applied_imported_disc_pct or 0)),
            ITEM_CATEGORY_TARSIA:   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
        }

        # Group candidates by prescription so we hit SOFTECH once per receipt.
        by_rx = {}
        for ln in candidates:
            by_rx.setdefault(ln.prescription_id, []).append(ln)

        cur = conn.cursor()
        # planned = list of (line, correct_gross); skipped = list of (line, reason, delta)
        planned, skipped = [], []
        rx_map = {ln.prescription_id: ln.prescription for ln in candidates}

        for rx_id, rx_lines in by_rx.items():
            rx = rx_map[rx_id]
            docno, branch = rx.softech_docnumber, rx.softech_branchcode
            try:
                cur.execute(QUERY_PRESCRIPTION_LINES_CLASSIFIED, [docno, branch])
                rows = cur.fetchall()
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ! SOFTECH fetch failed for #{docno}/{branch}: {e}'))
                for ln in rx_lines:
                    skipped.append((ln, 'softech_fetch_failed', None))
                continue

            # (itemcode, qty_3dp) -> queue of authoritative gross values.  Keying on
            # the rounded qty too pairs the right rows when the SAME item appears on
            # several lines with different quantities (e.g. a strip line + a full-pack
            # line), which pure positional order could cross-match.
            soft = {}
            for r in rows:
                code = _safe(r[0])
                tq = _to_qty(r[2])
                key = (code, tq.quantize(Decimal('0.001')))       # frozen qty is round(transqty,3)
                gross = (_to_decimal(r[10]) * tq).quantize(_Q)    # itemsaleprice × transqty
                soft.setdefault(key, []).append(gross)

            used = {}
            for ln in sorted(rx_lines, key=lambda x: x.pk):
                key = (ln.softech_itemcode, Decimal(str(ln.quantity or 0)).quantize(Decimal('0.001')))
                queue = soft.get(key, [])
                idx = used.get(key, 0)
                if idx >= len(queue):
                    skipped.append((ln, 'no_softech_match', None))
                    continue
                used[key] = idx + 1
                correct = queue[idx]
                delta = (correct - Decimal(str(ln.line_total or 0))).quantize(_Q)
                if delta == 0:
                    continue
                if abs(delta) > tol:
                    skipped.append((ln, 'exceeds_tol', delta))
                    continue
                planned.append((ln, correct))
        cur.close()

        self.stdout.write(
            f'  claim {claim.pk} «{claim.claim_number}»: '
            f'{len(planned)} to fix, {len(skipped)} skipped '
            f'(of {len(candidates)} flagged).')
        for ln, correct in planned[:200]:
            self.stdout.write(
                f'      #{ln.prescription.softech_docnumber} {ln.softech_itemcode} '
                f'{ln.item_name[:22]:22}  {ln.line_total} → {correct}')
        for ln, reason, delta in skipped:
            extra = f' (Δ={delta})' if delta is not None else ''
            self.stdout.write(self.style.WARNING(
                f'      SKIP {reason}: #{ln.prescription.softech_docnumber} '
                f'{ln.softech_itemcode}{extra}'))

        if not planned or not apply:
            return

        self._write_repair(claim, planned, rates)

    # ── write (atomic + audited + revertible) ───────────────────────────────────
    def _write_repair(self, claim, planned, rates):
        _CAT_BEFORE = {
            ITEM_CATEGORY_LOCAL:    'local_before',
            ITEM_CATEGORY_IMPORTED: 'imported_before',
            ITEM_CATEGORY_TARSIA:   'tarsia_before',
        }
        net_before = Decimal(str(claim.final_net_after or 0))
        by_rx = {}
        for ln, correct in planned:
            by_rx.setdefault(ln.prescription_id, []).append((ln, correct))

        from apps.insurance.models import InsuranceClaimPrescription
        rx_objs = {rx.pk: rx for rx in
                   InsuranceClaimPrescription.objects.filter(pk__in=by_rx.keys())}

        pre_state = {
            'claim': {f: str(getattr(claim, f)) for f in (
                'final_local_before', 'final_imported_before', 'final_tarsia_before',
                'final_gross_before', 'final_total_discount', 'final_net_after', 'final_rx_count',
                'snapshot_local_before', 'snapshot_imported_before', 'snapshot_tarsia_before',
                'snapshot_gross_before', 'snapshot_total_discount', 'snapshot_net_after', 'snapshot_rx_count',
            )},
            'prescriptions': {
                str(pk): {f: str(getattr(rx_objs[pk], f)) for f in (
                    'local_before', 'imported_before', 'tarsia_before', 'gross_before',
                    'local_discount', 'imported_discount', 'tarsia_discount',
                    'total_discount', 'net_after',
                )} for pk in by_rx
            },
        }

        with _txn.atomic():
            run = InsuranceApplyMasterRun.objects.create(
                claim=claim, applied_by=None, apply_price=True, apply_category=False,
                scope_line_ids=sorted(ln.pk for ln, _ in planned),
                net_before=net_before, pre_state=pre_state)
            backups, line_objs, lines_updated = [], [], 0

            for rx_id, items in by_rx.items():
                rx = rx_objs[rx_id]
                splits = {
                    ITEM_CATEGORY_LOCAL:    Decimal(str(rx.local_before    or 0)),
                    ITEM_CATEGORY_IMPORTED: Decimal(str(rx.imported_before or 0)),
                    ITEM_CATEGORY_TARSIA:   Decimal(str(rx.tarsia_before   or 0)),
                }
                for ln, correct in items:
                    old_total = Decimal(str(ln.line_total or 0))
                    disc, net = calculate_line_discount(
                        ln.item_category, correct,
                        rates[ITEM_CATEGORY_LOCAL], rates[ITEM_CATEGORY_IMPORTED],
                        rates[ITEM_CATEGORY_TARSIA])
                    backups.append(InsuranceClaimLineBackup(
                        run=run, line=ln, item_category=ln.item_category,
                        unit_price=ln.unit_price, line_total=ln.line_total,
                        discount_pct=ln.discount_pct, discount_amt=ln.discount_amt,
                        net_amount=ln.net_amount))
                    ln.line_total  = correct
                    ln.discount_amt = disc
                    ln.net_amount   = net
                    line_objs.append(ln)
                    lines_updated += 1
                    # shift the corrected value inside its own category bucket
                    splits[ln.item_category] += (correct - old_total)

                lb, ib, tb = (splits[ITEM_CATEGORY_LOCAL], splits[ITEM_CATEGORY_IMPORTED],
                              splits[ITEM_CATEGORY_TARSIA])
                t = powerquery_totals_from_splits(
                    lb, ib, tb, rates[ITEM_CATEGORY_LOCAL],
                    rates[ITEM_CATEGORY_IMPORTED], rates[ITEM_CATEGORY_TARSIA])
                for f in ('local_before', 'imported_before', 'tarsia_before', 'gross_before',
                          'local_discount', 'imported_discount', 'tarsia_discount',
                          'total_discount', 'net_after'):
                    setattr(rx, f, t[f])
                rx.save(update_fields=[
                    'local_before', 'imported_before', 'tarsia_before', 'gross_before',
                    'local_discount', 'imported_discount', 'tarsia_discount',
                    'total_discount', 'net_after'])
                if rx.billing_group_id:
                    rx.billing_group.refresh_totals()

            InsuranceClaimLine.objects.bulk_update(
                line_objs, ['line_total', 'discount_amt', 'net_amount'])
            if backups:
                InsuranceClaimLineBackup.objects.bulk_create(backups, batch_size=1000)

            recalculate_claim_final_totals(claim)
            claim.refresh_from_db()
            _sync_snapshot_to_final(claim)

            run.lines_updated = lines_updated
            run.prescriptions_updated = len(by_rx)
            run.net_after = Decimal(str(claim.final_net_after or 0))
            run.save(update_fields=['lines_updated', 'prescriptions_updated', 'net_after'])

            record_audit(
                claim, 'gross_repair', actor=None,
                summary=(f'إصلاح إجمالى العبوات الجزئية: {lines_updated} بند فى '
                         f'{len(by_rx)} روشتة (مطابقة سوفتك)'),
                target_type='claim', target_ref=str(claim.pk),
                before={'net': float(net_before)},
                after={'net': float(claim.final_net_after), 'run_id': run.pk})

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ claim {claim.pk}: fixed {lines_updated} line(s); '
            f'net {net_before} → {claim.final_net_after} (run #{run.pk}, revertible).'))
