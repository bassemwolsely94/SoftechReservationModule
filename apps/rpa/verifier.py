"""Read-only SOFTECH lookups: find the doc-125 the robot typed and compare its typed fields.

Reads only (through config.sybase). Never queries a docnumber bare: always branchcode + doccode.
Compares typed fields only (itemcode, qty, expiry, destination branch, usercode), never totals.
"""
import logging
import re
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from config import sybase

from .identity import expected_softech_usercode

logger = logging.getLogger(__name__)

DOCCODE = '125'
_Q5 = Decimal('0.00001')

# Header columns read: docnumber, usercode, cust_branch_code, docdate, comments (fixed text, all
# values bound as ? parameters).
# The reference match is exact in SQL: RPA-<id> followed by a non-digit, or at the end of the
# comments (_ref_patterns). So RPA-120.. never reaches the row cap and cannot crowd RPA-12 out;
# Python still re-checks each row (`own` in find_issue_document) as a second guard.
_REF_SQL = ('SET ROWCOUNT 50 SELECT docnumber, usercode, cust_branch_code, docdate, comments '
            'FROM SOFTECHDB9.dbo.stktransm '
            "WHERE branchcode=? AND doccode='125' AND (comments LIKE ? OR comments LIKE ?) "
            'ORDER BY docnumber DESC')
_FINGERPRINT_SQL = ('SET ROWCOUNT 50 SELECT docnumber, usercode, cust_branch_code, docdate, comments '
                    'FROM SOFTECHDB9.dbo.stktransm '
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


def _read_headers(cur, sql, params):
    """Header read with a row cap; the cap is lifted at once so the line reads are never truncated."""
    rows = _read(cur, sql, params)
    cur.execute('SET ROWCOUNT 0')               # only after a good read: never masks the first error
    return rows


_REF_IN_COMMENT = re.compile(r'RPA-(\d+)')


def _ref_patterns(reference):
    """Sybase ASE LIKE patterns for exactly `reference` (RPA-<id>, no digit after it): inside the
    comments, or at their very end. Bound as parameters, never formatted into the SQL text."""
    return [f'%{reference}[^0-9]%', f'%{reference}']


def _names_other_document(comments, document):
    return any(f'RPA-{n}' != document.reference for n in _REF_IN_COMMENT.findall(comments))


def branch_lookup_problem(branch, *, needs_server=True):
    """'' when SOFTECH can be searched for this branch's documents, else the Arabic reason.

    Without the branch code every lookup returns nothing, so the double-post guard would be off."""
    if branch is None:
        return 'الفرع غير محدد'
    if not _s(branch.softech_branch_id):
        return f'الفرع {branch.name} بلا كود SOFTECH'
    if needs_server and not _s(branch.effective_db_host):
        return f'الفرع {branch.name} بلا عنوان سيرفر SOFTECH'
    return ''


def _lines_of(cur, bcode, docnumber):
    return [{'itemcode': _s(r[0]), 'qty': _qty(r[1]), 'expiry': _date(r[2])}
            for r in _read(cur, _LINES_SQL, [bcode, DOCCODE, docnumber])]


def _found(row, how, lines, docnumber):
    return {'docnumber': docnumber, 'usercode': _s(row[1]), 'cust_branch_code': _s(row[2]),
            'matched_by': how, 'lines': lines}


def find_issue_document(document):
    """The doc-125 on the supplying branch's server for this document, or None.

    A header carrying our own RPA-<id> reference IS the document, whatever its lines say (spec
    5.3): it is returned as found and the caller's verify sends a mismatch to a person. Only a
    fingerprint candidate (no reference) has to match our lines to count."""
    job = document.job
    branch = job.branch
    problem = branch_lookup_problem(branch)
    if problem:
        raise ValueError(problem)
    bcode = _s(branch.softech_branch_id)
    wanted = _key(_doc_lines(document))
    conn = sybase.get_branch_connection(branch.effective_db_host, branch.db_port or 5000,
                                        branch.db_name or 'SOFTECHDB9')
    cur = None
    try:
        cur = conn.cursor()
        own = re.compile(rf'{re.escape(document.reference)}(?!\d)')   # second guard behind the SQL match
        for row in _read_headers(cur, _REF_SQL, [bcode, *_ref_patterns(document.reference)]):
            if own.search(_s(row[4])):
                docnumber = int(Decimal(_s(row[0])))
                return _found(row, 'reference', _lines_of(cur, bcode, docnumber), docnumber)
        usercode = expected_softech_usercode(job.created_by)
        target = _s(job.target_branch.softech_branch_id) if job.target_branch_id else ''
        if not (usercode and target and job.approved_at):
            return None
        start = timezone.localtime(job.approved_at).date()
        for row in _read_headers(cur, _FINGERPRINT_SQL, [bcode, usercode, target, start, timezone.localdate()]):
            if _names_other_document(_s(row[4]), document):          # another RPA document's
                continue
            docnumber = int(Decimal(_s(row[0])))
            lines = _lines_of(cur, bcode, docnumber)
            if _key(lines) == wanted:
                return _found(row, 'fingerprint', lines, docnumber)
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
