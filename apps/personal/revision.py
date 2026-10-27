"""
apps/personal/revision.py — the revision STAMP embedded in a SOFTECH remark.

Format (cp1256-safe: Arabic letters + Western date + code, delimited so it's
cleanly separable from the user's own note):

    <user note> [[راجعها BASSEM 26-08-14 R42]]

The `[[ … ]]` delimiter lets us strip/replace the stamp idempotently and detect
whether it's still present (drift check) without disturbing the user's text.
"""
import re
from datetime import date

# A trailing (or anywhere) [[ … ]] block — our stamp.
_MARK_RE = re.compile(r'\s*\[\[[^\[\]]*\]\]\s*')


def numstr(v) -> str:
    """Canonical doc/cheque number string: 10791.0 → '10791' (stable ledger key)."""
    s = str(v if v is not None else '').strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


def strip_marker(remark: str) -> str:
    """Remove every [[ … ]] stamp, leaving only the user's note."""
    return _MARK_RE.sub(' ', remark or '').strip()


def build_marker(name: str, code: str) -> str:
    d = date.today().strftime('%y-%m-%d')
    nm = (name or '').strip()[:24]
    return f'[[راجعها {nm} {d} {code}]]'


def apply_marker(remark: str, marker: str) -> str:
    """Return the user's note with the stamp appended (or removed if marker='')."""
    base = strip_marker(remark)
    if not marker:
        return base
    return f'{base} {marker}'.strip()


def marker_present(remark: str, code: str) -> bool:
    """True if the current remark still carries this revision's stamp."""
    return bool(remark) and bool(code) and f'{code}]]' in remark
