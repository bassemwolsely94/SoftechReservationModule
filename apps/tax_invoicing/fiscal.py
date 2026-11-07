"""
apps/tax_invoicing/fiscal.py — the deterministic fiscal arithmetic and the ETA document format.
Pure functions, no database. Nothing here decides a treatment; it applies the confirmed one.

Format source: sdk.invoicing.eta.gov.eg, documents/invoice-v1-0 and document-serialization-approach.
"""
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

Q5 = Decimal('0.00001')
HUNDRED = Decimal('100')


def q5(value) -> Decimal:
    return Decimal(str(value)).quantize(Q5, rounding=ROUND_HALF_UP)


def split_vat(amount, rate, prices_include_vat):
    """(net excluding VAT, VAT) for a line amount at `rate` percent."""
    amount, rate = Decimal(str(amount)), Decimal(str(rate))
    net = q5(amount * HUNDRED / (HUNDRED + rate)) if prices_include_vat else q5(amount)
    return net, q5(net * rate / HUNDRED)


def fiscal_line(*, description, code_type, eta_code, unit_type, internal_code, quantity, gross, net, rate,
                tax_type, subtype, prices_include_vat):
    """One ETA line from source gross and net. Returns plain Decimals; see `line_json` for the format."""
    quantity = Decimal(str(quantity))
    gross_ex, _ = split_vat(gross, rate, prices_include_vat)
    net_ex, vat = split_vat(net, rate, prices_include_vat)
    unit_value = q5(gross_ex / quantity)
    sales_total = q5(unit_value * quantity)
    discount = q5(sales_total - net_ex)
    return {
        'description': description, 'code_type': code_type, 'eta_code': eta_code, 'unit_type': unit_type,
        'internal_code': internal_code, 'quantity': quantity, 'unit_value': unit_value,
        'sales_total': sales_total, 'discount': discount, 'net': net_ex, 'rate': Decimal(str(rate)),
        'vat': vat, 'total': q5(net_ex + vat), 'tax_type': tax_type, 'subtype': subtype,
    }


def totals(lines):
    t = {k: sum((l[k] for l in lines), Decimal('0')) for k in ('sales_total', 'discount', 'net', 'vat', 'total')}
    return {k: q5(v) for k, v in t.items()}


class _Num(str):
    """A number already formatted exactly as it must appear in the JSON text."""


def _money(v) -> _Num:
    return _Num(format(q5(v), 'f'))


def _rate(v) -> _Num:
    return _Num(format(Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f'))


def _qty(v) -> _Num:
    return _Num(format(Decimal(str(v)).quantize(Decimal('0.00001'), rounding=ROUND_HALF_UP), 'f'))


def line_json(l):
    return {
        'description': l['description'],
        'itemType': l['code_type'],
        'itemCode': l['eta_code'],
        'unitType': l['unit_type'],
        'quantity': _qty(l['quantity']),
        'internalCode': l['internal_code'],
        'salesTotal': _money(l['sales_total']),
        'total': _money(l['total']),
        'valueDifference': _money(0),
        'totalTaxableFees': _money(0),
        'netTotal': _money(l['net']),
        'itemsDiscount': _money(0),
        'unitValue': {'currencySold': 'EGP', 'amountEGP': _money(l['unit_value'])},
        'discount': {'rate': _rate(0), 'amount': _money(l['discount'])},
        'taxableItems': [{'taxType': l['tax_type'], 'amount': _money(l['vat']), 'subType': l['subtype'],
                          'rate': _rate(l['rate'])}],
    }


def _address(p, *, branch_id=None):
    a = {}
    if branch_id is not None:
        a['branchId'] = branch_id
    a.update(country=p.country, governate=p.governate, regionCity=p.region_city, street=p.street,
             buildingNumber=p.building_number)
    return a


def document_json(*, doc_type, internal_id, issued_utc, issuer, buyer, lines, version, references=None):
    t = totals(lines)
    tax_types = {}
    for l in lines:
        tax_types[l['tax_type']] = tax_types.get(l['tax_type'], Decimal('0')) + l['vat']
    doc = {
        'issuer': {'type': 'B', 'id': issuer.tax_id, 'name': issuer.name,
                   'address': _address(issuer, branch_id=issuer.branch_id)},
        'receiver': {'type': buyer.receiver_type, 'id': buyer.tax_id, 'name': buyer.legal_name,
                     'address': _address(buyer)},
        'documentType': doc_type,
        'documentTypeVersion': version,
        'dateTimeIssued': issued_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'taxpayerActivityCode': issuer.activity_code,
        'internalID': internal_id,
    }
    if references:
        doc['references'] = list(references)
    doc.update({
        'invoiceLines': [line_json(l) for l in lines],
        'totalSalesAmount': _money(t['sales_total']),
        'totalDiscountAmount': _money(t['discount']),
        'netAmount': _money(t['net']),
        'taxTotals': [{'taxType': k, 'amount': _money(v)} for k, v in tax_types.items()],
        'extraDiscountAmount': _money(0),
        'totalItemsDiscountAmount': _money(0),
        'totalAmount': _money(t['total']),
    })
    return doc


def _encode(value, indent=None):
    """JSON text in which numbers keep the exact form they were formatted to."""
    if isinstance(value, _Num):
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(f'{json.dumps(k)}:{_encode(v)}' for k, v in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(_encode(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=False)


def to_text(document: dict) -> str:
    return _encode(document)


def _canon(value) -> str:
    if isinstance(value, dict):
        out = []
        for key, val in value.items():
            name = key.upper()
            if isinstance(val, list):
                out.append(f'"{name}"')
                out.extend(f'"{name}"{_canon(item)}' for item in val)
            else:
                out.append(f'"{name}"{_canon(val)}')
        return ''.join(out)
    if isinstance(value, Decimal):
        return f'"{value}"'
    if value is None:
        return '""'
    if isinstance(value, bool):
        return f'"{str(value).lower()}"'
    if isinstance(value, str):
        return '"' + json.dumps(value, ensure_ascii=False)[1:-1] + '"'
    return f'"{value}"'


def canonical(document_text: str) -> str:
    """ETA's serialized form of a document, from its exact JSON text: upper-case names, values as
    written, array items each prefixed with the array's name. `signatures` is not signed."""
    doc = json.loads(document_text, parse_float=Decimal, parse_int=Decimal)
    doc.pop('signatures', None)
    return _canon(doc)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def with_signature(document_text: str, signature_b64: str) -> str:
    """The document text with the issuer signature appended; everything before it is untouched."""
    text = document_text.rstrip()
    assert text.endswith('}')
    return f'{text[:-1]},"signatures":[{{"signatureType":"I","value":{json.dumps(signature_b64)}}}]}}'
