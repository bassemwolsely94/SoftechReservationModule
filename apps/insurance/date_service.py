"""
TEMPORARY SOFTECH receipt-date writeback (gated, per-receipt, revertible).

Use case: a prescription was returned and re-entered as a NEW sales invoice that
took today's date, but insurance requires dispensing within 7 days of the physical
prescription date.  This lets staff set the receipt's PRINTED date (stktransm.docdate
+ every stktrans line's docdate, on HQ + branch) to a valid date, reprint, then
REVERT it back — so SOFTECH's real state is only briefly changed for the printout.

Only docdate is touched (the date the receipt prints).  trans_time (the timestamp,
which also orders personnewbal) is deliberately NOT changed.  Dates are written with
a SQL string→datetime CONVERT, never a bound Python datetime (jConnect can't bind one).
"""
from datetime import date, datetime

from django.conf import settings
from django.utils import timezone

from .models import InsuranceClaim, SoftechDateEditRun, SoftechWritePlan
from .reprice_service import _hq_conn, _open_branch, RepriceError, write_enabled
from . import softech_guard as guard

_DOCCODE = '115'
LOCK_DATE_EDIT = 7_301_008      # pg advisory lock: one receipt-date apply / revert at a time (P-15)


def _lock():
    from apps.vouchers.coupon_dashboard import pg_lock
    return pg_lock(LOCK_DATE_EDIT)


def _guard(claim, branch, confirm):
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة (INSURANCE_SOFTECH_WRITE_ENABLED=False).')
    if not confirm:
        raise RepriceError('التأكيد مطلوب.')
    if claim is not None and getattr(claim, 'status', None) not in ('draft', 'ready'):
        raise RepriceError('لا يمكن تعديل التاريخ إلا لمطالبة مسودة/جاهزة.')


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _read_docdate(cur, docno, branch, doccode):
    cur.execute("SELECT docdate FROM SOFTECHDB9.dbo.stktransm "
                "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                [docno, branch, doccode])
    r = cur.fetchone()
    return _to_date(r[0]) if r else None


def _set_docdate(cur, docno, branch, doccode, yyyymmdd):
    """Set docdate on the RECEIPT (header + every line) to `yyyymmdd` (a 'YYYYMMDD'
    string).  Sybase ASE parses style 112 (yyyymmdd) reliably; docdate stored at 00:00.
    This is what a revert restores."""
    for table in ('stktransm', 'stktrans'):
        cur.execute(
            f"UPDATE SOFTECHDB9.dbo.{table} SET docdate=CONVERT(datetime,?,112) "
            "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
            [yyyymmdd, docno, branch, doccode])


def _set_motalba_docdate(cur, docno, branch, doccode, yyyymmdd):
    """Align the MOTALBA's per-receipt docdate (HQ-only; the motalba table has no
    branch-node copy).  One receipt can appear in several motalbano rows → updates
    all of them.

    Returns (rows updated, old dates). The old dates are read first and kept on the run, and
    _revert_locked puts each row back to its own date (round-2 R1, owner Q1 + follow-up
    2026-11-05; before that the motalba kept the corrected date on revert)."""
    cur.execute(
        "SELECT motalbano, docdate FROM SOFTECHDB9.dbo.motalba "
        "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
        [docno, branch, doccode])
    old = [{'motalbano': str(no).strip(), 'docdate': d.date().isoformat() if hasattr(d, 'date') else str(d)}
           for no, d in (cur.fetchall() or [])]
    cur.execute(
        "UPDATE SOFTECHDB9.dbo.motalba SET docdate=CONVERT(datetime,?,112) "
        "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
        [yyyymmdd, docno, branch, doccode])
    try:
        return cur.rowcount, old
    except Exception:
        return None, old


def date_preview(docno, branch, new_date, doccode=_DOCCODE):
    """Read-only: current docdate + branch reachability."""
    hq = _hq_conn(charset='cp1256'); cur = hq.cursor()
    try:
        current = _read_docdate(cur, docno, branch, doccode)
        if current is None:
            raise RepriceError(f'الإيصال #{docno} فرع {branch} غير موجود فى HQ.')
    finally:
        cur.close(); hq.close()
    reachable = False
    try:
        b = _open_branch(branch, charset='cp1256'); bc = b.cursor()
        reachable = _read_docdate(bc, docno, branch, doccode) is not None
        bc.close(); b.close()
    except Exception:
        reachable = False
    return {
        'docnumber': docno, 'branch': branch, 'doccode': doccode,
        'current_date': current.isoformat() if current else None,
        'new_date': new_date.isoformat() if isinstance(new_date, date) else str(new_date),
        'branch_reachable': reachable,
        'write_enabled': write_enabled(),
    }


def _parse(v):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip(), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _date_issues(claim, old, new):
    return guard.check_date(old=old, new=new, today=timezone.localdate(),
                            period_from=getattr(claim, 'period_from', None),
                            period_to=getattr(claim, 'period_to', None))


def apply_date_edit(claim, docno, branch, new_date, user=None, confirm=False, doccode=_DOCCODE,
                    expected_old=None, reason='', plan=None):
    """Set the receipt's printed date on HQ + branch (transactional, revertible).
    Re-checks the date guard on the live date (block refuses, warning needs `reason`)
    and refuses when the date changed since the preview (`expected_old`)."""
    _guard(claim, branch, confirm)
    nd = _parse(new_date)
    if nd is None:
        raise RepriceError('اختر التاريخ الجديد.')
    with _lock() as got:
        if not got:
            raise RepriceError('تعديل تاريخ آخر قيد التنفيذ — أعد المحاولة بعد لحظات.')
        # A second apply would record the already-changed date as old_date, and its revert
        # would put the WRONG date back (Batch 2, P-15) — revert the open edit first.
        open_run = SoftechDateEditRun.objects.filter(
            docnumber=str(docno), branchcode=str(branch), doccode=doccode,
            status=SoftechDateEditRun.STATUS_APPLIED).first()
        if open_run:
            raise RepriceError(f'تاريخ هذا الإيصال مُعدَّل بالفعل (العملية #{open_run.pk}) — '
                               'تراجع عنها أولاً ثم طبّق التاريخ الجديد.')
        return _apply_locked(claim, docno, branch, nd, user, doccode, expected_old, reason, plan)


def _apply_locked(claim, docno, branch, nd, user, doccode, expected_old=None, reason='', plan=None):
    nd_str = nd.strftime('%Y%m%d')

    hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()
    old = _read_docdate(hcur, docno, branch, doccode)
    if old is None:
        hcur.close(); hq.close()
        raise RepriceError(f'الإيصال #{docno} فرع {branch} غير موجود فى HQ.')
    exp = _parse(expected_old) if expected_old else None
    if exp is not None and old != exp:
        hcur.close(); hq.close()
        raise RepriceError(f'تاريخ الإيصال #{docno} تغيّر فى سوفتك منذ المعاينة ({exp} → {old}) — أعد المعاينة.')
    issues = _date_issues(claim, old, nd)
    blocks = [i['message'] for i in issues if i['level'] == 'block']
    warns = [i['message'] for i in issues if i['level'] == 'warn']
    if blocks or (warns and not guard.reason_ok(reason)):
        hcur.close(); hq.close()
        raise RepriceError(('مرفوض: ' + ' · '.join(blocks)) if blocks
                           else 'تحذيرات تتطلب كتابة سبب: ' + ' · '.join(warns))

    try:
        bconn = _open_branch(branch, charset='cp1256')
    except Exception as e:
        hcur.close(); hq.close()
        raise RepriceError(f'عُقدة الفرع غير متاحة — التطبيق محظور: {str(e)[:80]}')
    bcur = bconn.cursor()

    run = SoftechDateEditRun.objects.create(
        claim=claim, docnumber=str(docno), branchcode=str(branch), doccode=doccode,
        old_date=old, new_date=nd, nodes=['HQ', str(branch)],
        applied_by=getattr(user, 'staff_profile', None) if user else None,
        status=SoftechDateEditRun.STATUS_APPLIED, plan=plan, reason=(reason or '').strip())
    motalba_rows = None
    try:
        hq.begin(); bconn.begin()
        _set_docdate(hcur, docno, branch, doccode, nd_str)          # receipt (HQ)
        _set_docdate(bcur, docno, branch, doccode, nd_str)          # receipt (branch)
        motalba_rows, motalba_old = _set_motalba_docdate(hcur, docno, branch, doccode, nd_str)  # motalba (HQ) — stays on revert
        bconn.commit(); hq.commit()
        run.motalba_old_dates = motalba_old
        run.save(update_fields=['motalba_old_dates'])
    except Exception as e:
        try: hq.rollback()
        except Exception: pass
        try: bconn.rollback()
        except Exception: pass
        run.status = SoftechDateEditRun.STATUS_FAILED
        run.error = str(e)[:2000]
        run.save(update_fields=['status', 'error'])
        raise
    finally:
        hcur.close(); bcur.close(); hq.close(); bconn.close()

    return {'run_id': run.pk, 'old_date': old.isoformat(), 'new_date': nd.isoformat(),
            'motalba_rows_aligned': motalba_rows}


def revert_date_edit(run, user=None):
    """Restore the receipt's original printed date on HQ + branch (under the date-edit lock,
    the run re-read — Batch 2, P-15)."""
    with _lock() as got:
        if not got:
            raise RepriceError('تعديل تاريخ آخر قيد التنفيذ — أعد المحاولة بعد لحظات.')
        run.refresh_from_db()
        return _revert_locked(run, user)


def _revert_locked(run, user=None):
    if run.status != SoftechDateEditRun.STATUS_APPLIED:
        raise RepriceError('لا يمكن التراجع إلا عن عملية مُطبَّقة.')
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')
    old_str = run.old_date.strftime('%Y%m%d')
    hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()
    bconn = _open_branch(run.branchcode, charset='cp1256'); bcur = bconn.cursor()
    restored = 0
    try:
        hq.begin(); bconn.begin()
        _set_docdate(hcur, run.docnumber, run.branchcode, run.doccode, old_str)
        _set_docdate(bcur, run.docnumber, run.branchcode, run.doccode, old_str)
        # the motalba rows go back too, each to its own recorded date (owner 2026-11-05 — it used
        # to keep the corrected date). A run from before the dates were kept leaves them as is.
        for row in (run.motalba_old_dates or []):
            hcur.execute(
                "UPDATE SOFTECHDB9.dbo.motalba SET docdate=CONVERT(datetime,?,112) "
                "WHERE motalbano=? AND docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                [row['docdate'].replace('-', ''), row['motalbano'], run.docnumber, run.branchcode, run.doccode])
            restored += 1
        bconn.commit(); hq.commit()
        run.status = SoftechDateEditRun.STATUS_REVERTED
        run.reverted_at = timezone.now()
        run.save(update_fields=['status', 'reverted_at'])
    except Exception:
        try: hq.rollback()
        except Exception: pass
        try: bconn.rollback()
        except Exception: pass
        raise
    finally:
        hcur.close(); bcur.close(); hq.close(); bconn.close()
    return {'reverted': True, 'restored_date': run.old_date.isoformat(), 'motalba_restored': restored}


# ── preview → typed confirmation → apply (the only UI write path) ─────────────

def preview_date_plan(claim, docno, branch, new_date, user=None, doccode=_DOCCODE):
    """READ-ONLY on SOFTECH: current date, branch reachability and the date guard,
    stored as a SoftechWritePlan (source='date') the same user may apply once."""
    docno, branch = str(docno).strip(), str(branch).strip()
    if not docno or not branch:
        raise RepriceError('أدخل رقم الإيصال والفرع.')
    nd = _parse(new_date)
    pv = date_preview(docno, branch, nd or '', doccode)
    old = _parse(pv['current_date'])
    issues = _date_issues(claim, old, nd)
    open_run = SoftechDateEditRun.objects.filter(
        docnumber=docno, branchcode=branch, doccode=doccode,
        status=SoftechDateEditRun.STATUS_APPLIED).first()
    if open_run:
        issues.append(guard._issue('block', 'date_open',
                                   f'تاريخ هذا الإيصال مُعدَّل بالفعل (العملية #{open_run.pk}) — استرجعه أولاً.'))
    if not pv['branch_reachable']:
        issues.append(guard._issue('block', 'branch_down', f'عُقدة الفرع {branch} غير متاحة الآن.'))
    rx = claim.prescriptions.filter(softech_docnumber=docno, softech_branchcode=branch) \
        .values('patient_name', 'sequence').first() if claim else None
    summ = guard.summarize(issues)
    return SoftechWritePlan.objects.create(
        claim=claim, source='date', plan=[{'docno': docno, 'branch': branch,
                                           'new_date': nd.isoformat() if nd else None}],
        preview={**pv, 'issues': issues, 'user_id': getattr(user, 'pk', None),
                 'patient': (rx or {}).get('patient_name', ''), 'sequence': (rx or {}).get('sequence')},
        blocked=summ['blocked'], needs_reason=summ['needs_reason'], receipt_count=1,
        created_by=getattr(user, 'staff_profile', None) if user else None)


def date_plan_payload(plan):
    age = (timezone.now() - plan.created_at).total_seconds()
    return {'id': plan.pk, 'status': plan.status, 'blocked': plan.blocked,
            'needs_reason': plan.needs_reason, 'reason_min_chars': guard.REASON_MIN_CHARS,
            'expires_in': max(0, guard.PREVIEW_TTL_SECONDS - int(age)),
            'write_enabled': write_enabled(), **plan.preview,
            'docno': plan.plan[0]['docno'], 'branch': plan.plan[0]['branch'],
            'new_date': plan.plan[0]['new_date']}


def apply_date_plan(plan, user=None, confirm_text='', reason=''):
    """GATED: apply a previewed date plan once.  The user confirms by typing the
    receipt number; a warning needs a reason; the date must be unchanged since."""
    if plan.source != 'date':
        raise RepriceError('ليست معاينة تعديل تاريخ.')
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')
    if plan.claim.status not in (InsuranceClaim.STATUS_DRAFT, InsuranceClaim.STATUS_READY):
        raise RepriceError('لا يمكن تعديل التاريخ إلا لمطالبة مسودة/جاهزة.')
    if plan.status != SoftechWritePlan.STATUS_PREVIEWED:
        raise RepriceError('هذه المعاينة طُبِّقت أو أُلغيت — أعد المعاينة.')
    if (timezone.now() - plan.created_at).total_seconds() > guard.PREVIEW_TTL_SECONDS:
        raise RepriceError('انتهت صلاحية المعاينة (10 دقائق) — أعد المعاينة.')
    if plan.preview.get('user_id') != getattr(user, 'pk', None):
        raise RepriceError('المعاينة أُعدّت بواسطة مستخدم آخر — أعد المعاينة بنفسك.')
    if plan.blocked:
        raise RepriceError('المعاينة بها أخطاء مانعة — صحّحها وأعد المعاينة.')
    item = plan.plan[0]
    if str(confirm_text or '').strip().lstrip('#') != item['docno']:
        raise RepriceError(f'اكتب رقم الإيصال ({item["docno"]}) للتأكيد.')
    if plan.needs_reason and not guard.reason_ok(reason):
        raise RepriceError(f'اكتب سبب التجاوز ({guard.REASON_MIN_CHARS} أحرف على الأقل).')
    if not SoftechWritePlan.objects.filter(pk=plan.pk, status=SoftechWritePlan.STATUS_PREVIEWED) \
            .update(status=SoftechWritePlan.STATUS_APPLYING, reason=(reason or '').strip()):
        raise RepriceError('هذه المعاينة قيد التطبيق أو طُبِّقت بالفعل.')
    plan.refresh_from_db()
    try:
        res = apply_date_edit(plan.claim, item['docno'], item['branch'], item['new_date'], user=user,
                              confirm=True, expected_old=plan.preview.get('current_date'),
                              reason=reason, plan=plan)
    finally:
        plan.status = SoftechWritePlan.STATUS_APPLIED
        plan.applied_at = timezone.now()
        plan.save(update_fields=['status', 'applied_at'])
    return res
