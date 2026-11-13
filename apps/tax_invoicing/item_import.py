"""
apps/tax_invoicing/item_import.py — load a coded-items workbook through an explicit column mapping.

Three steps, each from the uploaded file: `inspect` lists sheets and real headers; `preview` is the
dry run with row-level validation, duplicates and conflicts, and writes nothing; `apply` needs the
hash that preview returned for this exact file and mapping, so what is applied is what was reviewed.

Nothing is guessed from column names. Codes stay text, including leading zeros. VAT columns load as
what the sheet says (`source_vat_*`): confirming a tax treatment is the accountant's separate step.
"""
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Item
from core.upload_safety import capped_rows

from .models import TaxItemProfile
from .services import TaxRuleError, audit, revalidate_drafts_for_items

FIELDS = {
    'itemcode': 'كود الصنف في SOFTECH (مطلوب)',
    'eta_code': 'كود المصلحة EGS / GS1',
    'code_type': 'نوع الكود',
    'item_name': 'اسم الصنف',
    'item_name_ar': 'اسم الصنف بالعربية',
    'gpc_code': 'كود GPC',
    'active_from': 'ساري من',
    'active_to': 'ساري حتى',
    'unit_type': 'الوحدة',
    'list_flag': 'عمود القائمة (بيضاء / سوداء)',
    'reason': 'السبب',
    'vat_rate': 'نسبة الضريبة في الملف',
    'vat_code': 'كود الضريبة في الملف',
}
ISSUES_PER_KIND = 50


def cell_text(value):
    """(text, was_number). A number in Excel has already lost any leading zero: the caller warns."""
    if value is None:
        return '', False
    if isinstance(value, bool):
        return str(value), False
    if isinstance(value, int):
        return str(value), True
    if isinstance(value, float):
        return (str(int(value)) if value.is_integer() else format(Decimal(str(value)), 'f')), True
    if isinstance(value, Decimal):
        return format(value, 'f'), True
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat(), False
    return str(value).strip(), False


def _workbook(fileobj):
    fileobj.seek(0)
    return openpyxl.load_workbook(fileobj, read_only=True, data_only=True)


def _sheet(wb, name):
    if name not in wb.sheetnames:
        raise TaxRuleError(f'الورقة غير موجودة: {name}')
    return wb[name]


def inspect_workbook(fileobj, *, header_row=1, sample_rows=3):
    wb = _workbook(fileobj)
    sheets = []
    for ws in wb.worksheets:
        rows = list(_first_rows(ws, header_row + sample_rows))
        head = rows[header_row - 1] if len(rows) >= header_row else ()
        samples = rows[header_row:]
        sheets.append({'name': ws.title, 'rows': ws.max_row, 'columns': [
            {'index': i, 'header': cell_text(h)[0], 'samples': [cell_text(r[i])[0][:60] for r in samples if i < len(r)]}
            for i, h in enumerate(head)]})
    wb.close()
    return {'sheets': sheets, 'fields': FIELDS}


def _first_rows(ws, n):
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= n:
            return
        yield row


def clean_options(raw):
    raw = raw if isinstance(raw, dict) else json.loads(raw or '{}')
    mapping = {f: int(i) for f, i in (raw.get('mapping') or {}).items() if i not in (None, '') and f in FIELDS}
    if 'itemcode' not in mapping:
        raise TaxRuleError('حدد عمود كود الصنف')
    status = raw.get('coded_status') or TaxItemProfile.CODE_PENDING
    if status not in (TaxItemProfile.CODE_PENDING, TaxItemProfile.CODE_APPROVED):
        raise TaxRuleError('حالة الأكواد المرمزة: قيد الاعتماد أو معتمد')
    if 'list_flag' in mapping and not (raw.get('black_values') or raw.get('white_values')):
        raise TaxRuleError('حدد قيم عمود القائمة: ماذا يعني أسود وماذا يعني أبيض')
    return {'sheet': raw.get('sheet') or '', 'header_row': int(raw.get('header_row') or 1), 'mapping': mapping,
            'black_values': sorted(str(v).strip() for v in raw.get('black_values') or []),
            'white_values': sorted(str(v).strip() for v in raw.get('white_values') or []),
            'coded_status': status, 'overwrite_conflicts': bool(raw.get('overwrite_conflicts'))}


def _parse_date(text):
    if not text:
        return None, False
    try:
        return dt.date.fromisoformat(text[:10]), False
    except ValueError:
        return None, True


def _read_rows(fileobj, opts):
    wb = _workbook(fileobj)
    ws = _sheet(wb, opts['sheet']) if opts['sheet'] else wb.worksheets[0]
    m = opts['mapping']
    out = []
    iterator = capped_rows(ws.iter_rows(values_only=True))
    for number, row in enumerate(iterator, start=1):
        if number <= opts['header_row']:
            continue
        values, numeric = {}, set()
        for field, idx in m.items():
            text, was_number = cell_text(row[idx]) if idx < len(row) else ('', False)
            values[field] = text
            if was_number:
                numeric.add(field)
        if not any(values.values()):
            continue
        out.append((number, values, numeric))
    wb.close()
    return out


def validate(fileobj, opts):
    """Every row with its problems. An error keeps the row out; a warning is shown and allowed."""
    rows = _read_rows(fileobj, opts)
    seen_item, seen_code = {}, {}
    for number, v, _ in rows:
        if v.get('itemcode'):
            seen_item.setdefault(v['itemcode'], []).append(number)
        if v.get('eta_code'):
            seen_code.setdefault(v['eta_code'], []).append(number)
    catalog = set(Item.objects.filter(softech_id__in=list(seen_item)).values_list('softech_id', flat=True))
    existing = {p.softech_itemcode: p for p in TaxItemProfile.objects.filter(softech_itemcode__in=list(seen_item))}

    parsed, issues = [], []
    counts = dict(rows=len(rows), valid=0, errors=0, warnings=0, new=0, unchanged=0, updated=0, conflicts=0, coded=0,
                  not_coded=0, black=0, white=0, unlisted=0, duplicates=0)

    def issue(number, level, code, message, itemcode=''):
        counts['errors' if level == 'error' else 'warnings'] += 1
        issues.append({'row': number, 'level': level, 'code': code, 'message': message, 'itemcode': itemcode})

    for number, v, numeric in rows:
        code = v.get('itemcode', '')
        errors_before = counts['errors']
        if not code:
            issue(number, 'error', 'no_itemcode', 'لا يوجد كود صنف')
        elif len(code) > 10:
            issue(number, 'error', 'long_itemcode', f'كود صنف أطول من 10: {code}', code)
        if code and len(seen_item.get(code, [])) > 1:
            counts['duplicates'] += 1
            issue(number, 'error', 'duplicate_item', f'كود الصنف مكرر في الصفوف {seen_item[code]}', code)
        eta_code = v.get('eta_code', '')
        if eta_code and len(seen_code.get(eta_code, [])) > 1:
            counts['duplicates'] += 1
            issue(number, 'error', 'duplicate_eta_code', f'كود المصلحة مكرر في الصفوف {seen_code[eta_code]}', code)
        if len(eta_code) > 60:
            issue(number, 'error', 'long_eta_code', 'كود المصلحة طويل', code)
        code_type = v.get('code_type', '').upper()
        if code_type and code_type not in ('GS1', 'EGS'):
            issue(number, 'error', 'bad_code_type', f'نوع كود غير معروف: {code_type}', code)
            code_type = ''
        if code_type == 'EGS' and eta_code and not re.fullmatch(r'EG-\d+-\S+', eta_code):
            issue(number, 'warning', 'egs_format', f'الكود لا يطابق EG-رقم-كود: {eta_code}', code)
        if eta_code.startswith('EG-') and code and eta_code.split('-', 2)[-1] != code:
            issue(number, 'warning', 'code_mismatch', f'لاحقة الكود {eta_code} لا تطابق كود الصنف {code}', code)
        if code and code not in catalog:
            issue(number, 'warning', 'not_in_catalog', f'الصنف {code} ليس في الكتالوج', code)
        if 'eta_code' in numeric and eta_code:
            issue(number, 'warning', 'numeric_code', 'كود المصلحة مخزن كرقم في Excel؛ أي صفر في أوله ضاع قبل القراءة', code)
        if 'itemcode' in numeric and code.startswith('0'):
            issue(number, 'warning', 'numeric_itemcode', 'كود الصنف رقمي ويبدأ بصفر', code)

        list_status = None
        if 'list_flag' in opts['mapping']:
            flag = v.get('list_flag', '')
            if flag in opts['black_values']:
                list_status = TaxItemProfile.LIST_BLACK
            elif flag in opts['white_values']:
                list_status = TaxItemProfile.LIST_WHITE
            else:
                issue(number, 'error', 'bad_list_flag', f'قيمة القائمة غير معروفة: {flag!r}', code)

        active_from, bad_from = _parse_date(v.get('active_from', ''))
        active_to, bad_to = _parse_date(v.get('active_to', ''))
        if bad_from or bad_to:
            issue(number, 'warning', 'bad_date', f'تاريخ غير صحيح: {v.get("active_from") if bad_from else v.get("active_to")}', code)

        vat_rate = None
        raw_rate = v.get('vat_rate', '')
        if raw_rate:
            try:
                vat_rate = Decimal(raw_rate)
                if 0 < vat_rate < 1:      # the sheet writes 0.14 for 14%
                    vat_rate *= 100
                vat_rate = vat_rate.quantize(Decimal('0.01'))
                if not 0 <= vat_rate <= 100:
                    raise InvalidOperation
            except InvalidOperation:
                issue(number, 'error', 'bad_vat', f'نسبة ضريبة غير صحيحة: {raw_rate}', code)
                vat_rate = None

        coded = bool(eta_code and code_type)
        if eta_code and not code_type:
            issue(number, 'warning', 'code_without_type', 'يوجد كود بدون نوع، فيُعتبر الصنف غير مرمز', code)
        if list_status == TaxItemProfile.LIST_BLACK and coded:
            issue(number, 'warning', 'black_but_coded', 'في القائمة السوداء ومرمز في نفس الوقت', code)
        if list_status == TaxItemProfile.LIST_WHITE and not coded:
            issue(number, 'warning', 'white_not_coded', 'في القائمة البيضاء وبدون ترميز كامل', code)
        if coded and 'gpc_code' in opts['mapping'] and v.get('gpc_code', '') in ('', '0'):
            issue(number, 'warning', 'no_gpc', 'مرمز بدون كود GPC', code)

        row = {'row': number, 'itemcode': code, 'eta_code': eta_code, 'code_type': code_type, 'coded': coded,
               'item_name': v.get('item_name', '')[:200], 'item_name_ar': v.get('item_name_ar', '')[:200],
               'gpc_code': '' if v.get('gpc_code', '') == '0' else v.get('gpc_code', '')[:10], 'active_from': active_from, 'active_to': active_to,
               'unit_type': v.get('unit_type', '')[:10], 'list_status': list_status, 'reason': v.get('reason', '')[:300],
               'vat_rate': vat_rate, 'vat_code': v.get('vat_code', '')[:10], 'conflicts': []}
        if counts['errors'] != errors_before:
            continue
        counts['valid'] += 1
        counts['coded' if coded else 'not_coded'] += 1
        counts[{'black': 'black', 'white': 'white'}.get(list_status, 'unlisted')] += 1

        old = existing.get(code)
        if old is None:
            counts['new'] += 1
        else:
            for field, new_value, old_value in (('eta_code', eta_code, old.eta_code), ('code_type', code_type, old.code_type),
                                                ('list_status', list_status, old.list_status),
                                                ('source_vat_code', row['vat_code'], old.source_vat_code)):
                if new_value not in (None, '') and old_value not in ('', TaxItemProfile.LIST_NONE) and new_value != old_value:
                    row['conflicts'].append({'field': field, 'current': old_value, 'file': new_value})
            if row['conflicts']:
                counts['conflicts'] += 1
                issue(number, 'warning', 'conflict', 'يختلف عن المسجل: ' + '، '.join(c['field'] for c in row['conflicts']), code)
            else:
                counts['updated'] += 1
        parsed.append(row)
    return parsed, issues, counts


def _hash(data, opts):
    body = {k: v for k, v in opts.items() if k != 'overwrite_conflicts'}
    return hashlib.sha256(data + json.dumps(body, sort_keys=True).encode()).hexdigest()


def _read_all(fileobj):
    fileobj.seek(0)
    return fileobj.read()


def preview(fileobj, raw_options):
    opts = clean_options(raw_options)
    parsed, issues, counts = validate(fileobj, opts)
    by_code = {}
    for i in issues:
        by_code[i['code']] = by_code.get(i['code'], 0) + 1
    # A limit per kind: a common warning must not hide a rare problem.
    shown, seen = [], {}
    for i in issues:
        seen[i['code']] = seen.get(i['code'], 0) + 1
        if seen[i['code']] <= ISSUES_PER_KIND:
            shown.append(i)
    return {'dry_run': True, 'counts': counts, 'issue_counts': by_code, 'issues': shown,
            'issues_truncated': len(shown) < len(issues), 'preview_hash': _hash(_read_all(fileobj), opts),
            'sample': [{**r, 'active_from': str(r['active_from'] or ''), 'active_to': str(r['active_to'] or ''),
                        'vat_rate': None if r['vat_rate'] is None else str(r['vat_rate'])} for r in parsed[:25]]}


def apply(fileobj, raw_options, actor, preview_hash):
    opts = clean_options(raw_options)
    if preview_hash != _hash(_read_all(fileobj), opts):
        raise TaxRuleError('الملف أو الربط تغير بعد المعاينة؛ أعد المعاينة ثم الاعتماد')
    parsed, _, counts = validate(fileobj, opts)
    items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=[r['itemcode'] for r in parsed])}
    existing = {p.softech_itemcode: p for p in TaxItemProfile.objects.filter(softech_itemcode__in=[r['itemcode'] for r in parsed])}
    written = skipped = 0
    now = timezone.now()
    with transaction.atomic():
        for r in parsed:
            if r['conflicts'] and not opts['overwrite_conflicts']:
                skipped += 1
                continue
            p = existing.get(r['itemcode']) or TaxItemProfile(softech_itemcode=r['itemcode'])
            p.item = items.get(r['itemcode']) or p.item
            p.item_name = r['item_name'] or p.item_name or (p.item.name if p.item else '')
            p.item_name_ar = r['item_name_ar'] or p.item_name_ar
            if r['coded']:      # a code without its type is not a code: the item stays uncoded, with no code to check
                p.eta_code = r['eta_code'] or p.eta_code
            p.code_type = r['code_type'] or p.code_type
            p.gpc_code = r['gpc_code'] or p.gpc_code
            p.active_from = r['active_from'] or p.active_from
            p.active_to = r['active_to'] or p.active_to
            p.unit_type = r['unit_type'] or p.unit_type
            if r['coded']:
                p.coding_status = opts['coded_status']
            elif not p.pk:
                p.coding_status = TaxItemProfile.CODE_MISSING
            if r['list_status']:
                p.list_status = r['list_status']
                p.listed_reason = r['reason'] or p.listed_reason
                if r['list_status'] == TaxItemProfile.LIST_BLACK:
                    p.disposition = TaxItemProfile.DISP_REVIEW
            if r['vat_rate'] is not None:
                p.source_vat_rate = r['vat_rate']
            p.source_vat_code = r['vat_code'] or p.source_vat_code
            p.imported_at = now
            p.save()
            written += 1
        audit('items_imported', actor=actor, entity='item_import', entity_id=preview_hash[:16],
              after={'written': written, 'conflicts_skipped': skipped, 'counts': counts, 'mapping': opts['mapping'],
                     'coded_status': opts['coded_status'], 'black_values': opts['black_values'],
                     'white_values': opts['white_values']})
        revalidated = revalidate_drafts_for_items({r['itemcode'] for r in parsed})
    return {'written': written, 'conflicts_skipped': skipped, 'revalidated_drafts': revalidated, 'counts': counts}
