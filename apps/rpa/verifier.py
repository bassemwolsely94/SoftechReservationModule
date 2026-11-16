"""Read-only SOFTECH lookups: find the doc-125 the robot typed and compare its typed fields.

Reads only (through config.sybase). Never queries a docnumber bare: always branchcode + doccode.
Compares typed fields only (itemcode, qty, expiry, destination branch, usercode), never totals.
"""
import logging
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from config import sybase

from .identity import expected_softech_usercode

logger = logging.getLogger(__name__)

DOCCODE = '125'
_Q5 = Decimal('0.00001')

_HEADER_COLS = 'docnumber, usercode, cust_branch_code, docdate, comments'
_REF_SQL = (f'SET ROWCOUNT 5 SELECT {_HEADER_COLS} FROM SOFTECHDB9.dbo.stktransm '
            "WHERE branchcode=? AND doccode='125' AND comments LIKE ?")
_FINGERPRINT_SQL = (f'SET ROWCOUNT 50 SELECT {_HEADER_COLS} FROM SOFTECHDB9.dbo.stktransm '
                    "WHERE branchcode=? AND doccode='125' AND usercode=? AND cust_branch_code=? "
                    'AND docdate>=? AND docdate<=? ORDER BY docnumber DESC')
_LINES_SQL = ('SELECT itemcode, transqty, itemexpirydate FROM SOFTECHDB9.dbo.stktrans '
              'WHERE branchcode=? AND doccode=? AND docnumber=?')


def _s(v):
    return ('' if v is None else str(v)).strip()


def _qty(v):
    return Decimal(str(v or 0)).quantize(_Q5, rounding=ROUND_HALF_UP)


def _date(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _doc_lines(document):
    return [{'itemcode': _s(ln.itemcode), 'qty': _qty(ln.qty), 'expiry': ln.expiry}
            for ln in document.lines.filter(status='matched')]


def _key(lines):
    return Counter((ln['itemcode'], ln['qty']) for ln in lines)


def _read(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchall()


def find_issue_document(document):
    """The doc-125 on the supplying branch's server for this document, or None."""
    job = document.job
    branch = job.branch
    bcode = _s(branch.softech_branch_id)
    wanted = _key(_doc_lines(document))
    conn = sybase.get_branch_connection(branch.effective_db_host, branch.db_port or 5000,
                                        branch.db_name or 'SOFTECHDB9')
    cur = None
    try:
        cur = conn.cursor()
        candidates = [(r, 'reference') for r in
                      _read(cur, _REF_SQL, [bcode, f'%{document.reference}%'])]
        if not candidates:
            usercode = expected_softech_usercode(job.created_by)
            target = _s(job.target_branch.softech_branch_id) if job.target_branch_id else ''
            if usercode and target and job.approved_at:
                start = timezone.localtime(job.approved_at).date()
                candidates = [(r, 'fingerprint') for r in
                              _read(cur, _FINGERPRINT_SQL,
                                    [bcode, usercode, target, start, timezone.localdate()])]
        for row, how in candidates:
            docnumber = int(Decimal(_s(row[0])))
            lines = [{'itemcode': _s(r[0]), 'qty': _qty(r[1]), 'expiry': _date(r[2])}
                     for r in _read(cur, _LINES_SQL, [bcode, DOCCODE, docnumber])]
            if _key(lines) == wanted:
                return {'docnumber': docnumber, 'usercode': _s(row[1]),
                        'cust_branch_code': _s(row[2]), 'matched_by': how, 'lines': lines}
        return None
    finally:
        try:
            if cur is not None:
                cur.execute('SET ROWCOUNT 0')
        except Exception:                       # noqa: BLE001  # best effort, connection closes next
            logger.warning('rpa verifier: could not reset ROWCOUNT')
        conn.close()


def verify_issue_document(document, found):
    """Compare typed fields of the found SOFTECH doc with what we asked the robot to type."""
    job = document.job
    problems = []
    if _key(found['lines']) != _key(_doc_lines(document)):
        problems.append('أصناف أو كميات الإذن لا تطابق المطلوب')
    pool = Counter((ln['itemcode'], ln['qty'], ln['expiry']) for ln in found['lines'])
    for ln in _doc_lines(document):
        if ln['expiry'] is None:
            continue
        k = (ln['itemcode'], ln['qty'], ln['expiry'])
        if pool[k] > 0:
            pool[k] -= 1
        else:
            problems.append(f"تاريخ الصلاحية للصنف {ln['itemcode']} لا يطابق")
    target = _s(job.target_branch.softech_branch_id) if job.target_branch_id else ''
    if _s(found.get('cust_branch_code')) != target:
        problems.append('الفرع المستلم لا يطابق')
    expected = expected_softech_usercode(job.created_by)
    if _s(found.get('usercode')) != (expected or ''):
        problems.append('مستخدم SOFTECH لا يطابق')
    return {'ok': not problems, 'problems': problems}
