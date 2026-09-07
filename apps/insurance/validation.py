"""
apps/insurance/validation.py

Pre-flight readiness validation for a claim before it is issued (اصدار مطالبة).

Runs a battery of read-only checks and returns a structured report with a
health score and a can_issue gate.  Reused by the issuance wizard's "check"
step and surfaced as a readiness panel on the claim detail page.

Severities:
  error   → blocks issuance (can_issue = False)
  warning → should be reviewed, does not block
  info    → informational
  ok      → check passed
"""
from decimal import Decimal

from .models import (
    InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimExclusion,
    MotalbaCache,
)

_TOL = Decimal('1.00')   # tolerance (EGP) for total reconciliation


def _check(key, label, severity, count=0, detail='', items=None):
    return {
        'key': key, 'label': label, 'severity': severity,
        'count': count, 'detail': detail, 'items': items or [],
    }


def validate_claim_readiness(claim: InsuranceClaim) -> dict:
    """Return {can_issue, health_score, checks: [...], summary}."""
    checks = []

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )
    active_rx = [rx for rx in claim.prescriptions.all() if rx.id not in excluded_ids]

    # Effective (adjustment-aware) net per prescription — the value that actually
    # gets invoiced.  Zero/negative/softech checks must reflect this, not the raw
    # frozen snapshot, or a user who has already reclassified/overridden a rx
    # would still see phantom warnings.  Same source as invoice_builder / cover.
    from .invoice_builder import _effective_rx_values
    _eff_net = {}
    for rx in active_rx:
        try:
            _eff_net[rx.id] = Decimal(str(_effective_rx_values(rx, claim)['net_after'] or 0))
        except Exception:
            _eff_net[rx.id] = Decimal(str(rx.net_after or 0))

    # 1) Has any prescriptions at all ────────────────────────────────────────
    if not active_rx and not claim.manual_rx.exists() and not claim.supplements.exists():
        checks.append(_check('empty_claim', 'المطالبة لا تحتوي على روشتات', 'error', 0,
                             'لا يمكن إصدار مطالبة فارغة.'))
    else:
        checks.append(_check('has_rx', 'تحتوي على روشتات', 'ok', len(active_rx)))

    # 2) Zero-value prescriptions ─────────────────────────────────────────────
    zero_rx = [rx for rx in active_rx if _eff_net[rx.id] == 0]
    if zero_rx:
        checks.append(_check(
            'zero_value_rx', 'روشتات بقيمة صفرية', 'warning', len(zero_rx),
            'روشتات صافيها صفر — تحقق قبل الإصدار.',
            items=[{'docnumber': rx.softech_docnumber, 'patient': rx.patient_name} for rx in zero_rx[:50]],
        ))
    else:
        checks.append(_check('zero_value_rx', 'لا توجد روشتات صفرية', 'ok'))

    # 3) Missing patient names ────────────────────────────────────────────────
    no_name = [rx for rx in active_rx if not (rx.patient_name or '').strip()]
    if no_name:
        checks.append(_check(
            'missing_patient_name', 'روشتات بدون اسم مريض', 'warning', len(no_name),
            'قد ترفض الجهة الروشتات بدون اسم مريض.',
            items=[{'docnumber': rx.softech_docnumber} for rx in no_name[:50]],
        ))
    else:
        checks.append(_check('missing_patient_name', 'كل الروشتات لها اسم مريض', 'ok'))

    # 4) Negative-net prescriptions (returns) — informational ─────────────────
    neg_rx = [rx for rx in active_rx if _eff_net[rx.id] < 0]
    if neg_rx:
        checks.append(_check(
            'negative_net', 'روشتات بصافٍ سالب (مرتجعات)', 'info', len(neg_rx),
            'مرتجعات ستخصم من الإجمالى.',
        ))

    # 5) Classification / price drift vs current master (reuse discrepancy) ────
    try:
        from .discrepancy import compute_claim_discrepancy
        disc = compute_claim_discrepancy(claim)
        ds = disc['summary']
        if ds['changed_lines'] > 0:
            checks.append(_check(
                'master_drift', 'فروقات عن بيانات الكتالوج الحالية', 'warning',
                ds['changed_lines'],
                f"تصنيف متغيّر: {ds['category_changes']} · سعر متغيّر: {ds['price_changes']} · "
                f"فرق الصافى: {ds['net_delta']:.2f}. راجع تبويب فحص الفروقات.",
            ))
        else:
            checks.append(_check('master_drift', 'لا فروقات عن الكتالوج الحالي', 'ok'))
        if ds['items_not_found'] > 0:
            checks.append(_check(
                'items_not_in_catalog', 'أصناف غير موجودة في الكتالوج', 'info',
                ds['items_not_found'], 'تعذّر التحقق من تصنيف/سعر هذه الأصناف.',
                items=disc.get('not_found_items', [])[:100],
            ))
    except Exception:
        pass

    # 6) Per-prescription NET vs SOFTECH — Power-Query deviates BY DESIGN ───────
    # Our net uses the finance team's Power-Query formula (محلى·0.83 + مستورد·0.94),
    # NOT SOFTECH's stored docvaluerequired (which carries item-level discount
    # nuance we intentionally drop).  So a difference is EXPECTED, not an error —
    # we surface it as a WARNING (non-blocking, overridable) listing the exact
    # prescriptions so the user can review them in تبويب فحص الفروقات and decide
    # to keep (override) or revise the classification.
    try:
        Q = Decimal('0.01')
        mismatches = []
        our_tot = soft_tot = Decimal('0')
        have_ref = False
        for rx in active_rx:
            if rx.softech_net is None:
                continue
            have_ref = True
            our = _eff_net[rx.id]
            sof = Decimal(str(rx.softech_net))
            our_tot += our
            soft_tot += sof
            d = (our - sof).quantize(Q)
            if abs(d) > Q:
                mismatches.append({
                    'docnumber': rx.softech_docnumber, 'patient': rx.patient_name,
                    'our_net': float(our), 'softech_net': float(sof), 'diff': float(d),
                })
        if have_ref and mismatches:
            mismatches.sort(key=lambda m: abs(m['diff']), reverse=True)
            delta = our_tot - soft_tot
            checks.append(_check(
                'net_vs_softech',
                'صافى بعض الروشتات يختلف عن سوفتك (سلوك Power Query)',
                'warning', len(mismatches),
                f'فرق الصافى الكلي {delta:+.2f} ج.م على {len(mismatches)} روشتة — '
                f'هذا متوقع لأننا نطبّق معادلة Power Query (محلى×0.83 + مستورد×0.94) '
                f'وليس صافى سوفتك. راجع تبويب فحص الفروقات لمراجعتها أو تجاوزها.',
                items=mismatches[:50],
            ))
        elif have_ref:
            checks.append(_check('net_vs_softech', 'الصافى مطابق لسوفتك', 'ok'))
    except Exception:
        pass

    # 7) Cross-claim duplicate docnumbers (double-billing) ─────────────────────
    docnos = [rx.softech_docnumber for rx in active_rx if rx.softech_docnumber]
    if docnos:
        dupes = (InsuranceClaimPrescription.objects
                 .filter(softech_docnumber__in=docnos)
                 .exclude(claim=claim)
                 .exclude(claim__status=InsuranceClaim.STATUS_CANCELLED)
                 .values_list('softech_docnumber', 'claim__claim_number'))
        dupes = list(dupes)
        if dupes:
            checks.append(_check(
                'cross_claim_duplicates', 'فواتير مكرّرة في مطالبات أخرى', 'error', len(dupes),
                'هذه الفواتير مُدرجة في مطالبات أخرى — خطر ازدواج المطالبة.',
                items=[{'docnumber': d, 'claim': c} for d, c in dupes[:50]],
            ))
        else:
            checks.append(_check('cross_claim_duplicates', 'لا ازدواج مع مطالبات أخرى', 'ok'))

    # ── Score + gate ──────────────────────────────────────────────────────────
    errors   = [c for c in checks if c['severity'] == 'error']
    warnings = [c for c in checks if c['severity'] == 'warning']
    score = max(0, 100 - len(errors) * 40 - len(warnings) * 10)
    can_issue = len(errors) == 0

    return {
        'can_issue':    can_issue,
        'health_score': score,
        'checks':       checks,
        'summary': {
            'errors':   len(errors),
            'warnings': len(warnings),
            'rx_active': len(active_rx),
        },
    }


def find_claim_omissions(claim: InsuranceClaim) -> dict:
    """
    Find SOFTECH motalba receipts that belong to this claim's (personcode,
    motalbano) but are NOT imported as prescriptions — i.e. missed revenue.

    Uses the local MotalbaCache (fast, no Sybase).  Compares the cache's
    docnumbers for the claim's personcodes+motalbano against the claim's
    imported prescription docnumbers.

    Returns {motalba_docs, imported, missing_count, missing, value_missing,
             can_check}.
    """
    if not claim.softech_motalba_no or not claim.imported_personcodes:
        return {'can_check': False, 'reason': 'لا يوجد رقم مطالبة سوفتك مرتبط',
                'missing': [], 'missing_count': 0}

    pcs = [p.strip() for p in claim.imported_personcodes.split(',') if p.strip()]
    try:
        motalbano = int(claim.softech_motalba_no)
    except (ValueError, TypeError):
        return {'can_check': False, 'reason': 'رقم مطالبة سوفتك غير صالح',
                'missing': [], 'missing_count': 0}

    cache_rows = list(
        MotalbaCache.objects
        .filter(personcode__in=pcs, motalbano=motalbano)
        .values('docnumber', 'branchcode', 'docdate', 'docvalue_grandtotal', 'ppersoncode')
    )
    if not cache_rows:
        return {'can_check': False,
                'reason': 'لا توجد بيانات في الكاش — شغّل مزامنة التأمين أولاً',
                'missing': [], 'missing_count': 0}

    imported = set(claim.prescriptions.values_list('softech_docnumber', flat=True))

    missing = []
    value_missing = Decimal('0')
    for r in cache_rows:
        doc = str(r['docnumber'])
        if doc not in imported:
            value_missing += Decimal(str(r['docvalue_grandtotal'] or 0))
            missing.append({
                'docnumber':   doc,
                'branchcode':  r['branchcode'],
                'docdate':     r['docdate'].isoformat() if r['docdate'] else None,
                'value':       float(r['docvalue_grandtotal'] or 0),
            })
    missing.sort(key=lambda m: m['value'], reverse=True)

    return {
        'can_check':     True,
        'motalba_docs':  len(cache_rows),
        'imported':      len(imported),
        'missing_count': len(missing),
        'value_missing': float(value_missing),
        'missing':       missing,
    }
