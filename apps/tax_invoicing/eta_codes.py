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


def _store(system, rows):
    n = 0
    for row in rows:
        item_code = _first(row, 'itemCode').strip()
        if not item_code:
            continue
        EtaCodeUsage.objects.update_or_create(
            system=system, code_type=_code_type(row, item_code), item_code=item_code,
            defaults={'code_name': _first(row, 'codeName', 'codeNamePrimaryLang')[:300],
                      'active_from': _date(row.get('activeFrom')), 'active_to': _date(row.get('activeTo')),
                      'status': _first(row, 'status')[:30], 'gpc': _first(row, 'parentCode', 'gpcCode')[:10]})
        n += 1
    return n


def _page(reader, number, size):
    r = reader.get(PATH, {'Ps': size, 'Pn': number, 'OrderDirections': 'Descending'})
    if r.status_code == 404:
        return []
    if r.status_code != 200:
        raise EtaUncertain(f'تعذر جلب أكواد المنظومة (HTTP {r.status_code})', r.status_code)
    return _rows(_json(r))


def fetch(system='production', *, page_size=100, max_pages=2000):
    """Pages through ETA's code-usage history until an empty page, upserting every row. A failure keeps what was
    stored and says so (`complete` False): a partial copy must never read as the whole."""
    reader = EtaReader(system)
    out = {'pages': 0, 'rows': 0, 'complete': False, 'error': ''}
    if not reader.enabled():
        out['error'] = reader.why_not()
        return out
    try:
        for number in range(1, max_pages + 1):
            rows = _page(reader, number, page_size)
            if not rows:
                out['complete'] = True
                break
            out['rows'] += _store(system, rows)
            out['pages'] += 1
    except (EtaUncertain, EtaRefused, EtaNotConfigured) as exc:
        out['error'] = str(exc)[:300]
    except Exception as exc:    # a malformed page must not lose what was stored
        log.warning('eta code fetch stopped: %s', type(exc).__name__)
        out['error'] = f'توقف الجلب: {type(exc).__name__}'
    if out['pages']:
        match(system)
    return out


def match(system):
    """Sets `itemcode` on every usage: EGS EG-<tax id>-<itemcode> → itemcode; GS1 → item barcode → softech_id."""
    issuer = TaxIssuerProfile.objects.first()
    tax = re.sub(r'\D', '', issuer.tax_id) if issuer else ''
    prefix = f'EG-{tax}-' if tax else None
    barcodes = None
    count = 0
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
            EtaCodeUsage.objects.filter(pk=u.pk).update(itemcode=found)
        count += bool(found)
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
