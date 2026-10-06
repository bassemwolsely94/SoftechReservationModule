"""
apps/pos_orders/contract_fields.py — per-contract "Contract Employee Data" field spec.

SOFTECH drives the contract claim form (companiesitems) PER CONTRACT: the table `motalba_fields`,
keyed by the contract company's personcode, gives f1..f12 (1 = field shown/required, 0 = blacked out),
t1..t12 (custom ARABIC label) and te1..te12 (custom ENGLISH label). The 12 slots map to fixed
companiesitems columns (generic storage that each contract relabels); every contract enables/labels its
own subset. We read this so our POS renders the exact same form per contract, then store each entered
value into its fixed companiesitems column. (Verified 2026-08-22 against contract 4474 "D M S 20%".)
"""
from config.sybase import get_branch_connection

# slot (1..12) → fixed companiesitems column (generic storage each contract relabels)
SLOT_COLUMN = {
    1: 'patientname', 2: 'patientno', 3: 'financialno', 4: 'fileno',
    5: 'roshettano', 6: 'membershipno', 7: 'deptname', 8: 'patientnationality',
    9: 'relativedegree', 10: 'comment', 11: 'examdate', 12: 'hi_typecode',
}
# standard default labels (SOFTECH "Corp. Customer Std. Emp. Data Titles") — used when tN/teN is NULL.
DEFAULT_LABEL_AR = {
    1: 'اسم المريض', 2: 'رقم المريض', 3: 'الرقم المالى', 4: 'رقم الملف',
    5: 'رقم الروشتة', 6: 'رقم العضوية', 7: 'الإدارة/المنطقة', 8: 'الجنسية',
    9: 'درجة القرابة', 10: 'ملاحظات الطبيب', 11: 'تاريخ الكشف', 12: 'تصنيف الطبيب',
}
DATE_SLOTS = {11}   # examdate is a date field (تاريخ الكشف / تاريخ الروشتة)


def contract_field_spec(host, port, dbname, personcode):
    """Return the per-contract emp-data field spec as a list of dicts, one per ENABLED field:
        {slot, column, label_ar, label_en, is_date}
    Blacked-out (f=0) fields are omitted. Returns [] when the contract has no motalba_fields row
    (→ no emp-data form for that contract). Read-only; graceful [] on any branch error."""
    pc = str(personcode or '').strip()
    if not pc:
        return []
    try:
        conn = get_branch_connection(host, port or 5000, dbname or 'SOFTECHDB9')
    except Exception:
        return []
    try:
        cur = conn.cursor()
        sel = ','.join(['f%d' % i for i in range(1, 13)]
                       + ['t%d' % i for i in range(1, 13)]
                       + ['te%d' % i for i in range(1, 13)])
        cur.execute("SELECT %s FROM motalba_fields WHERE RTRIM(dw2_reportname)=?" % sel, [pc])
        row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row:
        return []
    f, t, te = row[0:12], row[12:24], row[24:36]
    spec = []
    for i in range(12):
        if not (f[i] is not None and str(f[i]).strip() == '1'):
            continue                                   # blacked-out field
        slot = i + 1
        lab_ar = (str(t[i]).strip() if (t[i] is not None and str(t[i]).strip())
                  else DEFAULT_LABEL_AR[slot])
        lab_en = (str(te[i]).strip() if (te[i] is not None and str(te[i]).strip()) else None)
        spec.append({'slot': slot, 'column': SLOT_COLUMN[slot],
                     'label_ar': lab_ar, 'label_en': lab_en, 'is_date': slot in DATE_SLOTS})
    return spec


def has_contract_form(host, port, dbname, personcode) -> bool:
    """True if the contract has any configured emp-data fields (a motalba_fields row with ≥1 enabled)."""
    return bool(contract_field_spec(host, port, dbname, personcode))
