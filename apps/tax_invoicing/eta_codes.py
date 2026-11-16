"""
apps/tax_invoicing/eta_codes.py — what ETA production already holds: a read-only mirror of the portal's code-usage
history (every status), matched to our SOFTECH items and compared with the owner's sheet. Reads ETA only.
"""
import datetime as dt
import logging
import re

from apps.catalog.models import ItemBarcode

from . import eta_recon
from .eta_client import EtaNotConfigured, EtaRefused, EtaUncertain, _json
from .eta_reader import EtaReader
from .models import EtaCodeUsage, TaxIssuerProfile

log = logging.getLogger(__name__)
PATH = '/api/v1.0/codetypes/requests/my'
ACTIVE_STATUSES = ('approved', 'active')


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get('result') or body.get('items') or []
    return []


def _date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _first(row, *names):
    for n in names:
        if row.get(n) not in (None, ''):
            return str(row[n])
    return ''


def _code_type(row, item_code):
    raw = _first(row, 'codeType', 'codeTypeName').upper()
    if 'GS1' in raw:
        return 'GS1'
    if 'EGS' in raw:
        return 'EGS'
    return 'EGS' if item_code.upper().startswith('EG-') else 'GS1'


RANK = {'approved': 3, 'active': 3, 'submitted': 2, 'pending': 2}
FIELDS = ['code_name', 'active_from', 'active_to', 'status', 'gpc', 'request_id']


def _rank(status):
    return RANK.get(str(status).lower(), 1)


def _better(new, old):
    """Approved/active beats submitted/pending beats rejected/other; a tie goes to the newer request."""
    if old is None:
        return True
    a, b = _rank(new['status']), _rank(old['status'])
    if a != b:
        return a > b
    return (new['active_from'] or dt.date.min) >= (old['active_from'] or dt.date.min)


def _collect(best, rows):
    """Folds one page into the best row per (code type, item code): a code that was rejected and later approved is
    held, whatever order the pages come in."""
    for row in rows:
        item_code = _first(row, 'itemCode').strip()
        if not item_code:
            continue
        rec = {'code_name': _first(row, 'codeName', 'codeNamePrimaryLang')[:300],
               'active_from': _date(row.get('activeFrom')), 'active_to': _date(row.get('activeTo')),
               'status': _first(row, 'status')[:30], 'gpc': _first(row, 'parentCode', 'gpcCode')[:10],
               'request_id': _first(row, 'codeUsageRequestID')[:30]}
        key = (_code_type(row, item_code), item_code)
        if _better(rec, best.get(key)):
            best[key] = rec


def _write(system, best, keep_better):
    """One upsert per batch. A partial fetch never replaces a stored better row with a worse one."""
    if keep_better:
        for u in EtaCodeUsage.objects.filter(system=system):
            key = (u.code_type, u.item_code)
            if key in best and not _better(best[key], {f: getattr(u, f) for f in FIELDS}):
                del best[key]
    objs = [EtaCodeUsage(system=system, code_type=k[0], item_code=k[1], **rec) for k, rec in best.items()]
    for i in range(0, len(objs), 1000):
        EtaCodeUsage.objects.bulk_create(objs[i:i + 1000], update_conflicts=True,
                                         unique_fields=['system', 'code_type', 'item_code'],
                                         update_fields=FIELDS + ['fetched_at'])


def _page(reader, number, size):
    """(rows, total pages ETA says it has or 0, not found)."""
    r = reader.get(PATH, {'Ps': size, 'Pn': number, 'OrderDirections': 'Descending'})
    if r.status_code == 404:
        return [], 0, True
    if r.status_code != 200:
        raise EtaUncertain(f'تعذر جلب أكواد المنظومة (HTTP {r.status_code})', r.status_code)
    body = _json(r)
    meta = body.get('metadata') if isinstance(body, dict) else None
    try:
        total = int((meta or {}).get('totalPages') or 0)
    except (TypeError, ValueError):
        total = 0
    return _rows(body), total, False


def fetch(system='production', *, page_size=100, max_pages=2000):
    """Pages through ETA's code-usage history, keeping the best row per code, and writes it once. Stops at an empty
    or short page or at totalPages; anything else that ends it early says why and leaves `complete` False, so a
    partial copy never reads as the whole."""
    reader = EtaReader(system)
    out = {'pages': 0, 'rows': 0, 'complete': False, 'error': ''}
    if not reader.enabled():
        out['error'] = reader.why_not()
        return out
    best = {}
    try:
        for number in range(1, max_pages + 1):
            rows, total, missing = _page(reader, number, page_size)
            if missing and number > 1:
                out['error'] = f'ردت المنظومة بـ 404 في الصفحة {number} قبل نهاية السجل'
                break
            if not rows:
                out['complete'] = True
                break
            _collect(best, rows)
            out['pages'] += 1
            out['rows'] += len(rows)
            if len(rows) < page_size or (total and number >= total):
                out['complete'] = True
                break
        else:
            out['error'] = f'بلغ الجلب الحد الأقصى ({max_pages} صفحة) قبل نهاية السجل'
    except (EtaUncertain, EtaRefused, EtaNotConfigured) as exc:
        out['error'] = str(exc)[:300]
    except Exception as exc:    # a malformed page must not lose what was fetched
        log.warning('eta code fetch stopped: %s', type(exc).__name__)
        out['error'] = f'توقف الجلب: {type(exc).__name__}'
    if best:
        _write(system, best, keep_better=not out['complete'])
        match(system)
    return out


def match(system):
    """Sets `itemcode` on every usage: EGS EG-<tax id>-<itemcode> → itemcode; GS1 → item barcode → softech_id."""
    issuer = TaxIssuerProfile.objects.first()
    tax = re.sub(r'\D', '', issuer.tax_id) if issuer else ''
    prefix = f'EG-{tax}-' if tax else None
    barcodes = None
    changed, count = [], 0
    for u in EtaCodeUsage.objects.filter(system=system):
        found = ''
        if u.code_type == 'EGS':
            if prefix and u.item_code.startswith(prefix):
                found = u.item_code[len(prefix):]
        else:
            if barcodes is None:
                barcodes = dict(ItemBarcode.objects.values_list('barcode', 'item__softech_id'))
            found = barcodes.get(u.item_code, '')
        if found != u.itemcode:
            u.itemcode = found
            changed.append(u)
        count += bool(found)
    EtaCodeUsage.objects.bulk_update(changed, ['itemcode'], batch_size=1000)
    return count


def report(system='production'):
    """ETA's active codes against the sheet: held on ETA but not in the sheet, and in the sheet but not held."""
    active = [u for u in EtaCodeUsage.objects.filter(system=system) if u.status.lower() in ACTIVE_STATUSES]
    sheet = eta_recon.coded_items()
    on_eta = {u.itemcode for u in active if u.itemcode}
    not_in_sheet = [{'code_type': u.code_type, 'item_code': u.item_code, 'code_name': u.code_name,
                     'status': u.status, 'itemcode': u.itemcode}
                    for u in active if u.itemcode not in sheet]
    return {'on_eta_not_in_sheet': not_in_sheet,
            'in_sheet_not_on_eta': sorted(sheet - on_eta),
            'counts': {'usages': EtaCodeUsage.objects.filter(system=system).count(), 'active': len(active),
                       'matched': len(on_eta), 'unmatched': sum(1 for u in active if not u.itemcode),
                       'sheet': len(sheet)}}
