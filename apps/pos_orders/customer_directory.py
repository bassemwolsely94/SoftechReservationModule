"""
apps/pos_orders/customer_directory.py

SOFTECH-faithful customer selection for the POS: نوع العميل (type) → إسم العميل (entity),
plus the branch→stores list. Read-only, live from the branch DB (like batch_availability).

Verified sources (docs/architecture/SOFTECH_POS_FIELD_GAPS.md):
  • type catalog   persontypesclassif(ptcode, ptclassifcode, ptclassifdescr)
  • entities       personsdata WHERE ptclassifcode / ptcode  → personname, personcode,
                   personglobalcode (the PIC)
  • branch stores  branchstores(branchcode → storecode, defpos) ⋈ stores(storename)

Discount by type (NOT from a loyalty list — that was a mis-read):
  • cash/delivery/permanent → capped by seller POS limit + item's posdiscp (computed)
  • contract/insurance      → the B2B custdiscounts table (by entity personcode)
"""
from config.sybase import get_branch_connection

# POS نوع العميل list (curated to the verified, POS-relevant types). `channel` maps to our
# writeback ptclassifcode; `discount` tells the UI where the % comes from.
# ptcode='10' = customers (ptcode 20 = suppliers — must be excluded); ptclassif picks the
# specific نوع العميل within customers.
POS_CUSTOMER_TYPES = [
    {'key': 'cash',      'label': 'عميل نقدى',      'channel': 'cash',      'ptcode': '10', 'ptclassif': '91', 'discount': 'pos_limit'},
    {'key': 'delivery',  'label': 'عميل Delivery',  'channel': 'delivery',  'ptcode': '10', 'ptclassif': '90', 'discount': 'pos_limit'},
    {'key': 'permanent', 'label': 'عميل دائم',       'channel': 'permanent', 'ptcode': '10', 'ptclassif': '30', 'discount': 'pos_limit'},
    {'key': 'contract',  'label': 'تعاقد / آجل',     'channel': 'contract',  'ptcode': '10', 'ptclassif': '10', 'discount': 'b2b'},
    {'key': 'insurance', 'label': 'تأمين صحى',       'channel': 'insurance', 'ptcode': '10', 'ptclassif': '15', 'discount': 'b2b'},
    {'key': 'employee',  'label': 'موظفين',          'channel': 'employee',  'ptcode': '10', 'ptclassif': '11', 'discount': 'pos_limit'},
    {'key': 'compensation', 'label': 'تعويضات الشركات', 'channel': 'contract', 'ptcode': '10', 'ptclassif': '17', 'discount': 'b2b'},
]
_BY_KEY = {t['key']: t for t in POS_CUSTOMER_TYPES}


def _conn(db_host, db_port=5000, db_name='SOFTECHDB9'):
    return get_branch_connection(db_host, db_port or 5000, db_name or 'SOFTECHDB9')


def list_entities(db_host, type_key, q=None, limit=200, db_port=5000, db_name='SOFTECHDB9'):
    """إسم العميل — the entities of one نوع العميل. `q` filters by name (needed for the big
    contract list of ~1381). Returns [{personcode, name, pic}]."""
    t = _BY_KEY.get(type_key)
    if not t:
        return []
    where, params = [], []
    if t.get('ptcode'):
        where.append('ptcode=?'); params.append(t['ptcode'])
    if t.get('ptclassif'):
        where.append('ptclassifcode=?'); params.append(t['ptclassif'])
    where.append("personname IS NOT NULL AND personname <> ''")
    if q:
        where.append('personname LIKE ?'); params.append(f'%{q}%')
    sql = ("SELECT personcode, personname, personglobalcode FROM personsdata WHERE "
           + ' AND '.join(where) + ' ORDER BY personname')
    conn = _conn(db_host, db_port, db_name)
    try:
        cur = conn.cursor()
        cur.execute('SET ROWCOUNT %d' % int(limit))
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute('SET ROWCOUNT 0')
        return [{'personcode': str(r[0]).strip() if r[0] is not None else '',
                 'name': str(r[1]).strip() if r[1] is not None else '',
                 'pic': str(r[2]).strip() if r[2] is not None else ''} for r in rows]
    finally:
        try: conn.close()
        except Exception: pass


def salespeople(db_host, q=None, limit=50, db_port=5000, db_name='SOFTECHDB9'):
    """مسئول البيع picker source — SOFTECH `users` (usercode → userid/name). Searchable by
    EITHER usercode or name. Only the usercode is ever written to the ERP; the name is
    display-only. Active users only (user_nomore blank)."""
    # active users only: user_nomore is '0' active / '1' retired (also allow NULL/blank)
    where = ["(user_nomore = '0' OR user_nomore IS NULL OR user_nomore = '')"]
    params = []
    if q:
        where.append('(usercode LIKE ? OR userid LIKE ?)')
        params += [f'%{q}%', f'%{q}%']
    sql = ('SELECT usercode, userid FROM users WHERE ' + ' AND '.join(where) + ' ORDER BY userid')
    conn = _conn(db_host, db_port, db_name)
    try:
        cur = conn.cursor()
        cur.execute('SET ROWCOUNT %d' % int(limit))
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute('SET ROWCOUNT 0')
        return [{'usercode': str(r[0]).strip() if r[0] is not None else '',
                 'name': str(r[1]).strip() if r[1] is not None else ''} for r in rows]
    finally:
        try: conn.close()
        except Exception: pass


def branch_stores(db_host, branchcode, db_port=5000, db_name='SOFTECHDB9'):
    """من حساب مخزن — the stores associated with this branch (branch-dependent)."""
    conn = _conn(db_host, db_port, db_name)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT b.storecode, s.storename, b.defpos FROM branchstores b "
            "LEFT JOIN stores s ON s.storecode = b.storecode "
            "WHERE b.branchcode=? ORDER BY b.defpos DESC, b.storecode", [str(branchcode)])
        out = []
        for r in cur.fetchall():
            out.append({'storecode': str(r[0]).strip() if r[0] is not None else '',
                        'storename': (str(r[1]).strip() if r[1] is not None else ''),
                        'default': bool(r[2])})
        return out
    finally:
        try: conn.close()
        except Exception: pass
