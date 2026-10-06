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

from .models import SoftechDateEditRun
from .reprice_service import _hq_conn, _open_branch, RepriceError, write_enabled

_DOCCODE = '115'


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
    all of them.  NOT reverted (the motalba keeps the corrected date)."""
    cur.execute(
        "UPDATE SOFTECHDB9.dbo.motalba SET docdate=CONVERT(datetime,?,112) "
        "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
        [yyyymmdd, docno, branch, doccode])
    try:
        return cur.rowcount
    except Exception:
        return None


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


def apply_date_edit(claim, docno, branch, new_date, user=None, confirm=False, doccode=_DOCCODE):
    """Set the receipt's printed date on HQ + branch (transactional, revertible)."""
    _guard(claim, branch, confirm)
    nd = new_date if isinstance(new_date, date) else datetime.strptime(str(new_date), '%Y-%m-%d').date()
    nd_str = nd.strftime('%Y%m%d')

    hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()
    old = _read_docdate(hcur, docno, branch, doccode)
    if old is None:
        hcur.close(); hq.close()
        raise RepriceError(f'الإيصال #{docno} فرع {branch} غير موجود فى HQ.')

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
        status=SoftechDateEditRun.STATUS_APPLIED)
    motalba_rows = None
    try:
        hq.begin(); bconn.begin()
        _set_docdate(hcur, docno, branch, doccode, nd_str)          # receipt (HQ)
        _set_docdate(bcur, docno, branch, doccode, nd_str)          # receipt (branch)
        motalba_rows = _set_motalba_docdate(hcur, docno, branch, doccode, nd_str)  # motalba (HQ) — stays on revert
        bconn.commit(); hq.commit()
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
    """Restore the receipt's original printed date on HQ + branch."""
    if run.status != SoftechDateEditRun.STATUS_APPLIED:
        raise RepriceError('لا يمكن التراجع إلا عن عملية مُطبَّقة.')
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')
    old_str = run.old_date.strftime('%Y%m%d')
    hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()
    bconn = _open_branch(run.branchcode, charset='cp1256'); bcur = bconn.cursor()
    try:
        hq.begin(); bconn.begin()
        _set_docdate(hcur, run.docnumber, run.branchcode, run.doccode, old_str)
        _set_docdate(bcur, run.docnumber, run.branchcode, run.doccode, old_str)
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
    return {'reverted': True, 'restored_date': run.old_date.isoformat()}
