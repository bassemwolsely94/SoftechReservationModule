"""
Surgical re-sync of a claim against SOFTECH's CURRENT motalba state.

Unlike the initial import (which wipes all prescriptions and reloads), this applies
ONLY the delta since the last import, so local work (name edits, classification
overrides, adjustments, exclusions, re-prices) is preserved:

  جديدة   in SOFTECH, not ours          → import as a new prescription
  محذوفة  ours, gone from SOFTECH        → SOFT-EXCLUDE (reason «محذوفة من سوفتك»);
                                           if it had an applied re-price, flag it so
                                           staff can revert the SOFTECH price too
  متغيّرة  in both, header total differs  → FLAG for review (never auto-overwrite);
            beyond what our OWN logged      staff re-freeze it per-row on apply
            re-prices explain
  بدون تغيير                              → left untouched

Manual additions (is_manual prescriptions from OTHER motalbas + InsuranceClaimManualRx)
are excluded from the comparison entirely, so they are NEVER removed or altered.

Preview is CHEAP: one motalba-headers query (no per-Rx line fetch).  Lines are
re-fetched only on APPLY, for the new + the changed rows staff approve.
"""
from decimal import Decimal

from .models import (
    InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimExclusion,
    SoftechRepriceRun,
)

_Q = Decimal('0.01')
_TOL = Decimal('0.05')   # header-total tolerance (rounding noise)


def _d(v):
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal('0')


def _softech_headers(claim, motalba_no=None):
    """SOFTECH's current motalba prescriptions (header level only) keyed by docnumber:
    {docnumber: {'branch', 'docdate', 'doccode', 'gross', 'net'}}.  Reuses the import
    queries.  `motalba_no` overrides the claim's stored number (used when the claim
    has none yet).  Raises InsuranceImportError on connection/lookup failure."""
    from .importer import (
        _get_connection, _to_date, _to_int, _signed_dgt, InsuranceImportError,
    )
    from .sybase_queries import QUERY_MOTALBA_HEADER_FROM_DETAIL, QUERY_MOTALBA_LINES_BY_NO

    motalbano = (str(motalba_no).strip() if motalba_no else '') or claim.softech_motalba_no
    if not motalbano:
        raise InsuranceImportError('لا يوجد رقم مطالبة سوفتك — أدخل رقم المطالبة لجلب بياناتها.')
    try:
        motalbano = int(motalbano)
    except Exception:
        raise InsuranceImportError(f'رقم مطالبة سوفتك غير صالح: {motalbano}')

    conn = _get_connection(); cur = conn.cursor()
    personcodes = claim.subclient.get_all_personcodes()
    # prefer the personcode we actually imported from, else scan
    order = ([claim.imported_personcodes] if claim.imported_personcodes else []) + list(personcodes or [])
    pc = None
    for cand in order:
        if not cand:
            continue
        try:
            cur.execute(QUERY_MOTALBA_HEADER_FROM_DETAIL, [cand, motalbano])
            row = cur.fetchone()
            if row and row[2] is not None:
                pc = cand
                break
        except Exception:
            cur = conn.cursor()
    if not pc:
        raise InsuranceImportError(f'لم يتم العثور على المطالبة {motalbano} في سوفتك.')

    cur = conn.cursor()
    cur.execute(QUERY_MOTALBA_LINES_BY_NO, [pc, motalbano])
    out = {}
    for r in cur.fetchall():
        docnumber = str(_to_int(r[3])) if r[3] else ''
        if not docnumber or docnumber in out:
            continue
        doccode = str(r[5] or '').strip()
        dgt, dvr = _signed_dgt(r[7], r[11], doccode)
        branch_raw = r[2] if r[2] is not None else ''
        branch = branch_raw.strip() if isinstance(branch_raw, str) else str(branch_raw)
        out[docnumber] = {
            'branch': branch, 'docdate': _to_date(r[4]),
            'doccode': doccode, 'gross': _d(dgt), 'net': _d(dvr),
        }
    return out, pc


def _our_reprice_net_delta(claim, docnumber, branch):
    """Σ net_delta of OUR applied re-prices on this receipt (so a price we changed in
    SOFTECH isn't mistaken for an external edit)."""
    total = Decimal('0')
    for run in SoftechRepriceRun.objects.filter(
            docnumber=str(docnumber), branchcode=str(branch),
            status=SoftechRepriceRun.STATUS_APPLIED):
        if '_bonusqty_backfill' in (run.new_prices or {}):
            continue   # display-only fix, no net change
        total += _d(run.net_delta)
    return total


def preview_resync(claim: InsuranceClaim, motalba_no=None) -> dict:
    """Read-only diff of SOFTECH's current motalba vs our claim."""
    soft, pc = _softech_headers(claim, motalba_no)

    # our IMPORTED prescriptions (manual additions from other motalbas are protected)
    ours = {}
    for rx in claim.prescriptions.all():
        if rx.is_manual:
            continue
        ours[str(rx.softech_docnumber)] = rx

    soft_docs, our_docs = set(soft), set(ours)

    new_docs = sorted(soft_docs - our_docs)
    removed_docs = sorted(our_docs - soft_docs)
    both = soft_docs & our_docs

    new_items = [{
        'docnumber': d, 'branch': soft[d]['branch'],
        'date': soft[d]['docdate'].isoformat() if soft[d]['docdate'] else None,
        'gross': float(soft[d]['gross']), 'net': float(soft[d]['net']),
    } for d in new_docs]

    removed_items = []
    for d in removed_docs:
        rx = ours[d]
        reprices = SoftechRepriceRun.objects.filter(
            docnumber=d, branchcode=rx.softech_branchcode,
            status=SoftechRepriceRun.STATUS_APPLIED
        ).exclude(new_prices__has_key='_bonusqty_backfill')
        removed_items.append({
            'rx_id': rx.id, 'docnumber': d, 'branch': rx.softech_branchcode,
            'patient': rx.patient_name, 'net': float(_d(rx.net_after)),
            'already_excluded': hasattr(rx, 'exclusion'),
            'has_reprice': reprices.exists(),
            'reprice_run_ids': list(reprices.values_list('id', flat=True)),
        })

    changed_items = []
    for d in sorted(both):
        rx = ours[d]
        # expected current SOFTECH net = imported net + our own reprice deltas
        our_delta = _our_reprice_net_delta(claim, d, rx.softech_branchcode)
        base_net = _d(rx.softech_net if rx.softech_net is not None else rx.net_after)
        expected_net = base_net + our_delta
        soft_net = soft[d]['net']
        if abs(soft_net - expected_net) > _TOL:
            changed_items.append({
                'rx_id': rx.id, 'docnumber': d, 'branch': rx.softech_branchcode,
                'patient': rx.patient_name,
                'our_net': float(base_net), 'our_reprice_delta': float(our_delta),
                'softech_net': float(soft_net),
                'diff': float((soft_net - expected_net).quantize(_Q)),
            })

    return {
        'motalba_no': (str(motalba_no).strip() if motalba_no else '') or claim.softech_motalba_no,
        'personcode': pc,
        'counts': {
            'new': len(new_items), 'removed': len(removed_items),
            'changed': len(changed_items),
            'unchanged': len(both) - len(changed_items),
            'protected_manual': claim.prescriptions.filter(is_manual=True).count()
                                + claim.manual_rx.count(),
        },
        'new': new_items,
        'removed': removed_items,
        'changed': changed_items,
    }


import datetime as _dt


def _jsonify(v):
    """Make a model field value JSON-safe."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v


def _snapshot_prescription(rx):
    """Full before-state of a prescription (fields + lines + exclusion + adjustment)
    so a re-frozen change can be restored byte-for-byte on revert."""
    from .models import InsuranceClaimLine
    rxd = {f.attname: _jsonify(getattr(rx, f.attname)) for f in rx._meta.concrete_fields}
    lines = [{f.attname: _jsonify(getattr(l, f.attname)) for f in l._meta.concrete_fields
              if f.attname != 'id'}
             for l in rx.lines.all()]
    excl = getattr(rx, 'exclusion', None)
    adj = getattr(rx, 'adjustment', None)
    return {
        'rx': rxd,
        'lines': lines,
        'exclusion': ({'reason': excl.reason} if excl else None),
        'adjustment': ({f.attname: _jsonify(getattr(adj, f.attname))
                        for f in adj._meta.concrete_fields if f.attname not in ('id', 'prescription_id')}
                       if adj else None),
    }


def _restore_prescription(claim, snap):
    """Recreate a prescription from a snapshot, with its original pk + lines + exclusion
    + adjustment, so downstream references (billing group, etc.) stay valid."""
    from .models import (
        InsuranceClaimPrescription, InsuranceClaimLine,
        InsuranceClaimExclusion, InsuranceClaimAdjustment,
    )
    def _coerce(model, data):
        out = {}
        for f in model._meta.concrete_fields:
            if f.attname in data:
                out[f.attname] = f.to_python(data[f.attname]) if data[f.attname] is not None else None
        return out
    rx = InsuranceClaimPrescription(**_coerce(InsuranceClaimPrescription, snap['rx']))
    rx.save(force_insert=True)                       # keep original pk
    InsuranceClaimLine.objects.bulk_create([
        InsuranceClaimLine(prescription=rx, **_coerce(InsuranceClaimLine, ld))
        for ld in snap['lines']])
    if snap.get('exclusion'):
        InsuranceClaimExclusion.objects.get_or_create(
            prescription=rx, defaults={'reason': snap['exclusion'].get('reason', '')})
    if snap.get('adjustment'):
        InsuranceClaimAdjustment.objects.create(prescription=rx, **_coerce(InsuranceClaimAdjustment, snap['adjustment']))
    return rx


def _import_one(claim, docnumber, branch, docdate, doccode, gross, net, pc,
                local_disc, imported_disc, tarsia_disc, tarsia_codes, conn):
    """Fetch ONE receipt's lines from SOFTECH and write a fresh frozen snapshot."""
    from .importer import _fetch_and_classify_lines, _write_prescription_snapshot
    from django.db.models import Max
    cur = conn.cursor()
    classified_lines, totals, patient_name = _fetch_and_classify_lines(
        cur, docnumber, branch, local_disc, imported_disc, tarsia_disc, tarsia_codes,
        docvalue_grandtotal=gross, docvalue_required=net)
    seq = (claim.prescriptions.aggregate(m=Max('sequence'))['m'] or 0) + 1
    return _write_prescription_snapshot(
        claim=claim, seq=seq, docnumber=docnumber, docdate=docdate,
        branchcode=branch, personcode=pc, patient_name=patient_name,
        classified_lines=classified_lines, totals=totals,
        local_disc=local_disc, imported_disc=imported_disc, tarsia_disc=tarsia_disc)


def apply_resync(claim: InsuranceClaim, approved_change_ids=None,
                 confirm=False, user=None, motalba_no=None) -> dict:
    """
    Apply the SOFTECH delta: import new, soft-exclude removed, re-freeze the CHANGED
    rows staff approved (`approved_change_ids`).  Everything is logged as audit
    events.  Manual additions + unchanged prescriptions are never touched.
    """
    from django.db import transaction
    from .importer import (
        _get_connection, _signed_dgt, read_discount_rates,
        recalculate_claim_final_totals, InsuranceImportError,
    )
    from .classifier import DEFAULT_TARSIA_CLASSIF_CODES
    from .audit import record_audit

    if not confirm:
        raise InsuranceImportError('التأكيد مطلوب.')
    approved = set(int(x) for x in (approved_change_ids or []))

    pv = preview_resync(claim, motalba_no)        # re-diff at apply time
    pc = pv['personcode']
    # persist the motalba number if the claim had none (first re-sync)
    resolved_no = pv.get('motalba_no')
    if resolved_no and not claim.softech_motalba_no:
        claim.softech_motalba_no = str(resolved_no)
        claim.imported_personcodes = claim.imported_personcodes or pc
        claim.save(update_fields=['softech_motalba_no', 'imported_personcodes'])
    staff = getattr(user, 'staff_profile', None) if user else None

    conn = _get_connection()
    la, ia, ta = read_discount_rates(conn, pc)
    local_disc    = la if la > 0 else _d(claim.applied_local_disc_pct)
    imported_disc = ia if ia > 0 else _d(claim.applied_imported_disc_pct)
    tarsia_disc   = ta if ta > 0 else _d(claim.applied_tarsia_disc_pct)
    tarsia_codes  = DEFAULT_TARSIA_CLASSIF_CODES

    # need docdate/doccode/gross/net per new+changed docnumber → re-read headers
    soft, _ = _softech_headers(claim)

    from .models import ResyncRun
    added = removed = changed = 0
    reprice_flags = []
    added_rx_ids = []
    excluded_rec = []       # [{rx_id, exclusion_created}]
    changed_snaps = []      # full before-state of each re-frozen prescription
    with transaction.atomic():
        # ── NEW ────────────────────────────────────────────────────────────────
        for it in pv['new']:
            d = it['docnumber']; h = soft.get(d)
            if not h:
                continue
            rx = _import_one(claim, d, h['branch'], h['docdate'], h['doccode'],
                             _signed_dgt(h['gross'], h['net'], h['doccode'])[0], h['net'],
                             pc, local_disc, imported_disc, tarsia_disc, tarsia_codes, conn)
            added_rx_ids.append(rx.pk)
            record_audit(claim, 'resync_add', actor=staff,
                         summary=f'استيراد روشتة جديدة من سوفتك #{d} (فرع {h["branch"]})',
                         target_type='prescription', target_ref=str(d))
            added += 1

        # ── REMOVED → soft-exclude ───────────────────────────────────────────────
        for it in pv['removed']:
            rx = claim.prescriptions.filter(pk=it['rx_id']).first()
            if not rx:
                continue
            created = False
            if not hasattr(rx, 'exclusion'):
                _, created = InsuranceClaimExclusion.objects.get_or_create(
                    prescription=rx,
                    defaults={'reason': 'محذوفة من سوفتك (مزامنة)', 'excluded_by': staff})
            excluded_rec.append({'rx_id': rx.pk, 'exclusion_created': bool(created)})
            note = ''
            if it['has_reprice']:
                note = f' · لها تعديل سعر مُطبَّق (راجع الاسترجاع): {it["reprice_run_ids"]}'
                reprice_flags.append({'docnumber': it['docnumber'],
                                      'reprice_run_ids': it['reprice_run_ids']})
            record_audit(claim, 'resync_remove', actor=staff,
                         summary=f'استثناء روشتة محذوفة من سوفتك #{it["docnumber"]}{note}',
                         target_type='prescription', target_ref=str(it['docnumber']),
                         meta={'reprice_run_ids': it['reprice_run_ids']} if it['has_reprice'] else None)
            removed += 1

        # ── CHANGED (approved only) → re-freeze from SOFTECH ─────────────────────
        for it in pv['changed']:
            if it['rx_id'] not in approved:
                continue
            d = it['docnumber']; h = soft.get(d)
            if not h:
                continue
            old = claim.prescriptions.filter(pk=it['rx_id']).first()
            if not old:
                continue
            changed_snaps.append(_snapshot_prescription(old))   # capture BEFORE delete
            old.delete()
            _import_one(claim, d, h['branch'], h['docdate'], h['doccode'],
                        _signed_dgt(h['gross'], h['net'], h['doccode'])[0], h['net'],
                        pc, local_disc, imported_disc, tarsia_disc, tarsia_codes, conn)
            record_audit(claim, 'resync_change', actor=staff,
                         summary=f'إعادة تجميد روشتة تغيّرت فى سوفتك #{d} '
                                 f'(صافى {it["our_net"]} → {it["softech_net"]})',
                         target_type='prescription', target_ref=str(d),
                         before={'net': it['our_net']}, after={'net': it['softech_net']})
            changed += 1

        recalculate_claim_final_totals(claim)

        run = ResyncRun.objects.create(
            claim=claim, applied_by=staff, added=added, removed=removed, changed=changed,
            payload={'added_rx_ids': added_rx_ids, 'excluded': excluded_rec,
                     'changed': changed_snaps})

    return {'run_id': run.pk, 'added': added, 'removed': removed, 'changed': changed,
            'reprice_flags': reprice_flags}


def revert_resync(run, user=None) -> dict:
    """Undo a re-sync run: delete added rx, drop exclusions we created, and restore
    the re-frozen prescriptions from their captured snapshots."""
    from django.db import transaction
    from .importer import recalculate_claim_final_totals, InsuranceImportError
    from .models import (
        ResyncRun, InsuranceClaimPrescription, InsuranceClaimExclusion,
    )
    from django.utils import timezone
    if run.status != ResyncRun.STATUS_APPLIED:
        raise InsuranceImportError('لا يمكن التراجع إلا عن مزامنة مُطبَّقة.')
    p = run.payload or {}
    claim = run.claim
    with transaction.atomic():
        # 1) delete newly-imported prescriptions
        InsuranceClaimPrescription.objects.filter(
            pk__in=p.get('added_rx_ids', []), claim=claim).delete()
        # 2) undo exclusions WE created (leave pre-existing ones)
        for rec in p.get('excluded', []):
            if rec.get('exclusion_created'):
                InsuranceClaimExclusion.objects.filter(prescription_id=rec['rx_id']).delete()
        # 3) restore re-frozen prescriptions from their snapshots (delete the current
        #    re-imported one for that docnumber first)
        for snap in p.get('changed', []):
            docno = snap['rx'].get('softech_docnumber')
            InsuranceClaimPrescription.objects.filter(
                claim=claim, softech_docnumber=docno).delete()
            _restore_prescription(claim, snap)
        recalculate_claim_final_totals(claim)
        run.status = ResyncRun.STATUS_REVERTED
        run.reverted_at = timezone.now()
        run.save(update_fields=['status', 'reverted_at'])
    return {'reverted': True, 'added_removed': len(p.get('added_rx_ids', [])),
            'exclusions_undone': sum(1 for r in p.get('excluded', []) if r.get('exclusion_created')),
            'changed_restored': len(p.get('changed', []))}
