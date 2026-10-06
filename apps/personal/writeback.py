"""
apps/personal/writeback.py — the ONLY SOFTECH writes in apps/personal.

Updates a single remarks field on BOTH the HQ server and the record's branch
server, mirroring the audited dual-write pattern in
apps/discount_approvals/replication.py:

  • write_document_comment → stktransm.comments   (varchar 100), key
    (branchcode, doccode, docnumber); ownership = cust_branch_code.
  • write_cheque_note      → cheques.chequenote    (varchar 250), key
    (branchcode, financialdoccode, cheqsno); ownership = personcode.

For both:
  • ownership is re-verified against SOFTECH before any write (the record's
    counterparty must equal the caller's approved personcode);
  • Arabic is sent as raw cp1256 bytes through a default connection (see
    _to_wire) — the same byte pass-through the read path relies on;
  • each write is read-back-verified — a branch trigger can silently revert a
    direct write, and we report that honestly rather than lying "ok".

They write ONLY those two remarks columns, ONLY for a record the caller already
owns. Everything else in apps/personal stays read-only.
"""
from __future__ import annotations

from config.sybase import get_sybase_connection, get_branch_connection

DB = 'SOFTECHDB9'
MAX_LEN = 100


def _to_wire(text: str) -> str:
    """
    Encode Arabic for a Sybase write the way the native SOFTECH client does:
    raw cp1256 bytes, sent through a DEFAULT (non-cp1256) jConnect connection as
    a latin-1 string so the bytes pass through unconverted. Setting CHARSET=cp1256
    instead makes jConnect try to convert into the HQ server's charset and fail
    ("Error converting characters into server's character set"). This mirrors the
    read path, which reverses the same mojibake (encode latin-1 → decode cp1256).
    """
    return (text or '').encode('cp1256', 'replace').decode('latin-1')


CHEQ_MAX_LEN = 250   # cheques.chequenote is varchar(250)


class CommentWriteError(Exception):
    def __init__(self, detail, status=400):
        self.detail = detail
        self.status = status


def _validate_text(text: str, max_len: int) -> str:
    """Trim, enforce the column length, and reject characters SOFTECH's cp1256
    charset can't hold (Arabic-Indic digits ٠–٩, emoji). Returns the clean text."""
    text = (text or '').strip()
    if len(text) > max_len:
        raise CommentWriteError(f'الحد الأقصى {max_len} حرفاً', 400)
    try:
        text.encode('cp1256')
    except UnicodeEncodeError:
        raise CommentWriteError(
            'النص يحتوي أحرفاً لا يدعمها SOFTECH (مثل الأرقام العربية ٠–٩ أو الرموز). '
            'استخدم الأحرف العربية والأرقام الإنجليزية 0–9.', 400)
    return text


def _docnum_param(docnumber):
    """docnumber arrives as '10791' / '10791.0'; bind it as the numeric it is."""
    s = str(docnumber or '').strip()
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return s


def _write_and_verify(conn, table, col, value, where_pairs) -> str:
    """
    UPDATE {table}.{col} (bytes passed through via _to_wire) then read it back and
    compare to the ORIGINAL value (the read is auto-decoded to Arabic by the
    cursor). `where_pairs` = [(colname, param), …]. Only the caller builds these —
    never client-supplied column names. Returns 'ok' | 'reverted' | 'not_found'.
    """
    where_sql = ' AND '.join(f'{k} = ?' for k, _ in where_pairs)
    wp = [p for _, p in where_pairs]
    cur = conn.cursor()
    cur.execute(f"UPDATE {table} SET {col} = ? WHERE {where_sql}", [_to_wire(value)] + wp)
    cur.execute(f"SELECT {col} FROM {table} WHERE {where_sql}", wp)
    row = cur.fetchone()
    cur.close()
    if row is None:
        return 'not_found'
    got = row[0] or ''
    return 'ok' if str(got).strip() == str(value).strip() else 'reverted'


def write_document_comment(*, branchcode, doccode, docnumber, comment=None,
                           transform=None, expected_person_code) -> dict:
    """
    Verify ownership, then write the comment to HQ + the branch server.

    Pass either a literal `comment`, or a `transform(old_comment) -> new_comment`
    callback that is applied to the freshly-read remark (used by the revision
    stamp so the marker is appended atomically without a stale read).

    Returns {'old', 'new', 'hq_result', 'branch_host', 'branch_result'}.
    """
    branchcode = str(branchcode or '').strip()
    doccode = str(doccode or '').strip()
    epc = str(expected_person_code or '').strip()
    if not (branchcode and doccode and str(docnumber or '').strip() and epc):
        raise CommentWriteError('بيانات المستند غير مكتملة', 400)
    docnum = _docnum_param(docnumber)
    _key = [('branchcode', branchcode), ('doccode', doccode), ('docnumber', docnum)]
    old_comment, final = '', ''

    # 1) HQ read — the ownership + existence gate. No write happens unless the
    #    document's counterparty is exactly the caller's approved personcode.
    hq = get_sybase_connection()
    try:
        cur = hq.cursor()
        cur.execute(
            "SELECT cust_branch_code, comments FROM stktransm "
            "WHERE branchcode = ? AND doccode = ? AND docnumber = ?",
            [branchcode, doccode, docnum],
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise CommentWriteError('المستند غير موجود', 404)
        if str(row[0] or '').strip() != epc:
            raise CommentWriteError('هذا المستند ليس ضمن هويتك المعتمدة', 403)
        old_comment = row[1] or ''
        final = _validate_text(transform(old_comment) if transform else comment, MAX_LEN)

        # 2) HQ write + verify
        hq_result = _write_and_verify(hq, 'stktransm', 'comments', final, _key)
    finally:
        try:
            hq.close()
        except Exception:
            pass

    # 3) Branch write + verify (only if the branch has its own server configured)
    branch_host, branch_result = '', 'skipped: no branch server'
    try:
        from apps.branches.models import Branch
        b = Branch.objects.filter(softech_branch_id=branchcode).first()
        if b and (b.db_host or '').strip():
            branch_host = b.db_host
            bc = get_branch_connection(b.db_host, b.db_port or 5000, b.db_name or DB)
            try:
                branch_result = _write_and_verify(bc, 'stktransm', 'comments', final, _key)
            finally:
                try:
                    bc.close()
                except Exception:
                    pass
    except Exception as e:
        branch_result = f'error: {str(e)[:60]}'

    return {
        'old': old_comment,
        'new': final,
        'hq_result': hq_result,
        'branch_host': branch_host,
        'branch_result': branch_result,
    }


def write_cheque_note(*, branchcode, financialdoccode, cheqsno, note=None,
                      transform=None, expected_person_code) -> dict:
    """
    Write a cheque's remarks (cheques.chequenote, varchar(250)) to HQ + the
    cheque's branch server. Same audited dual-write as write_document_comment;
    key = (branchcode, financialdoccode, cheqsno). Pass a literal `note` or a
    `transform(old_note) -> new_note` (used by the revision stamp).
    """
    branchcode = str(branchcode or '').strip()
    fdc = str(financialdoccode or '').strip()
    epc = str(expected_person_code or '').strip()
    if not (branchcode and str(cheqsno or '').strip() and epc):
        raise CommentWriteError('بيانات الشيك غير مكتملة', 400)
    sno = _docnum_param(cheqsno)
    key = [('branchcode', branchcode), ('financialdoccode', fdc), ('cheqsno', sno)]
    old_note, final = '', ''

    hq = get_sybase_connection()
    try:
        cur = hq.cursor()
        cur.execute(
            "SELECT personcode, chequenote FROM cheques "
            "WHERE branchcode = ? AND financialdoccode = ? AND cheqsno = ?",
            [branchcode, fdc, sno],
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise CommentWriteError('الشيك غير موجود', 404)
        if str(row[0] or '').strip() != epc:
            raise CommentWriteError('هذا الشيك ليس ضمن هويتك المعتمدة', 403)
        old_note = row[1] or ''
        final = _validate_text(transform(old_note) if transform else note, CHEQ_MAX_LEN)
        hq_result = _write_and_verify(hq, 'cheques', 'chequenote', final, key)
    finally:
        try:
            hq.close()
        except Exception:
            pass

    branch_host, branch_result = '', 'skipped: no branch server'
    try:
        from apps.branches.models import Branch
        b = Branch.objects.filter(softech_branch_id=branchcode).first()
        if b and (b.db_host or '').strip():
            branch_host = b.db_host
            bc = get_branch_connection(b.db_host, b.db_port or 5000, b.db_name or DB)
            try:
                branch_result = _write_and_verify(bc, 'cheques', 'chequenote', final, key)
            finally:
                try:
                    bc.close()
                except Exception:
                    pass
    except Exception as e:
        branch_result = f'error: {str(e)[:60]}'

    return {'old': old_note, 'new': final, 'hq_result': hq_result,
            'branch_host': branch_host, 'branch_result': branch_result}
