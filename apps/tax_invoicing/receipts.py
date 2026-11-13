"""
apps/tax_invoicing/receipts.py — e-receipts for branch POS sales. Doc 36.

Separate from the claim invoice workflow; shares item mapping, audit, VAT arithmetic, signing and ETA
transport. A SOFTECH sale (doc 115) or return (30) is identified by branchcode + doccode + docnumber +
docdate: docnumber alone repeats across dates. Each channel's rule says whether it gets a receipt, is
covered by a claim invoice, or has no decision (held, never dropped).

A receipt with any unresolved line is held whole. The UUID chain is per device, so receipts are issued
one at a time under the branch's lock and sent in chain order. Only read-only SELECTs touch SOFTECH.
"""
import datetime as dt
import json
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from config.writers import writer_allowed

from . import eta_client, fiscal, signing
from .models import (TaxChannelRule, TaxIssuerProfile, TaxItemProfile, TaxReceipt, TaxReceiptAttempt,
                     TaxReceiptBranchConfig, TaxReceiptLine)
from .services import TaxRuleError, _subtype, audit, classify

FLAG = 'TAX_ERECEIPT_SUBMIT_ENABLED'
TYPE_VERSION = '1.2'
ZERO = Decimal('0')
BUYER_ID_THRESHOLD = Decimal('150000')   # receipt v1.2: a person's ID is required from this value

SALES_SQL = """
    SELECT m.branchcode, m.doccode, m.docnumber, m.docdate, m.ptclassifcode, m.docvalue,
           l.itemcode, i.itemname, l.transqty, l.transprice, l.transprice_total, l.additionaldiscp,
           l.trans_time, l.r_doccode, l.r_docnumber, l.r_docdate
    FROM stktransm m, stktrans l, items i
    WHERE l.branchcode = m.branchcode AND l.doccode = m.doccode AND l.docnumber = m.docnumber
      AND l.docdate = m.docdate AND i.itemcode = l.itemcode
      AND m.branchcode = ? AND m.docdate = ? AND m.doccode IN ('115', '30')
"""


def fetch_day(conn, branchcode, day):
    """Rows of one branch day from SOFTECH. Read only."""
    cur = conn.cursor()
    cur.execute(SALES_SQL, (branchcode, day.isoformat()))
    return cur.fetchall()


def _to_docs(rows):
    docs = {}
    for r in rows:
        key = (str(r[0]).strip(), str(r[1]).strip(), str(int(float(str(r[2])))), r[3])
        d = docs.setdefault(key, {'channel': str(r[4] or '').strip(), 'value': Decimal(str(r[5] or 0)), 'lines': [],
                                  'time': None, 'refs': set()})
        d['time'] = d['time'] or r[12]
        if r[14]:
            d['refs'].add((str(r[13] or '').strip(), str(int(float(str(r[14])))), r[15]))
        d['lines'].append({'itemcode': str(r[6]).strip(), 'item_name': str(r[7] or '').strip()[:200],
                           'quantity': Decimal(str(r[8] or 0)), 'unit_price': Decimal(str(r[9] or 0)),
                           'total': Decimal(str(r[10] or 0)), 'source_vat_rate': Decimal(str(r[11] or 0))})
    return docs


def _parse_day(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.datetime.fromisoformat(str(value)[:19]).date()


def _parse_time(value, day):
    if isinstance(value, dt.datetime):
        moment = value
    else:
        try:
            moment = dt.datetime.fromisoformat(str(value)[:19])
        except ValueError:
            moment = dt.datetime.combine(day, dt.time(12))
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def import_rows(rows, actor=None):
    """Upsert documents from SOFTECH rows, idempotent on the document key. Issued receipts never change."""
    created = updated = 0
    rules = {r.ptclassifcode: r for r in TaxChannelRule.objects.all()}
    touched = []
    for (branch, doccode, docnumber, docdate), d in _to_docs(rows).items():
        day = _parse_day(docdate)
        rule = rules.get(d['channel'])
        with transaction.atomic():
            receipt, is_new = TaxReceipt.objects.select_for_update().get_or_create(
                softech_branchcode=branch, doccode=doccode, docnumber=docnumber, docdate=day,
                defaults={'channel': d['channel'], 'source_value': d['value'],
                          'sold_at': _parse_time(d['time'], day), 'status': TaxReceipt.HELD})
            if not is_new and receipt.status not in (TaxReceipt.HELD, TaxReceipt.BY_INVOICE):
                continue
            receipt.channel, receipt.source_value = d['channel'], d['value']
            refs = sorted(d['refs'], key=str)
            receipt.original_ref = [[a, b, str(c)] for a, b, c in refs]
            receipt.save()
            receipt.lines.all().delete()
            TaxReceiptLine.objects.bulk_create([TaxReceiptLine(receipt=receipt, **l) for l in d['lines']])
            evaluate(receipt, rule)
            created += int(is_new)
            updated += int(not is_new)
            touched.append(receipt.pk)
    return {'created': created, 'updated': updated, 'documents': len(touched)}


def import_branch_day(branchcode, day, actor=None):
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection
    branch = Branch.objects.filter(softech_branch_id=branchcode).first() or Branch.objects.filter(code=branchcode).first()
    if branch is None or not branch.db_host:
        raise TaxRuleError(f'الفرع {branchcode} بدون سيرفر مسجل')
    conn = get_branch_connection(branch.db_host, branch.db_port or 5000)
    try:
        rows = fetch_day(conn, branchcode, day)
    finally:
        conn.close()
    result = import_rows(rows, actor)
    audit('receipts_imported', actor=actor, entity='receipt_import', entity_id=f'{branchcode}:{day}', after=result)
    return result


# ── Evaluation ─────────────────────────────────────────────────────────────────────────────────

def evaluate(receipt, rule=None):
    """Decide the receipt's state from the channel rule and each line. Held is the safe default."""
    if receipt.status not in (TaxReceipt.HELD, TaxReceipt.BY_INVOICE, TaxReceipt.READY):
        return receipt
    if rule is None:
        rule = TaxChannelRule.objects.filter(ptclassifcode=receipt.channel).first()
    issues = []
    lines = list(receipt.lines.all())
    profiles = {p.softech_itemcode: p for p in
                TaxItemProfile.objects.filter(softech_itemcode__in={l.itemcode for l in lines})}
    issuer = TaxIssuerProfile.load()
    for l in lines:
        p = profiles.get(l.itemcode)
        l.status, l.status_reason = classify(None, p)
        l.code_type = p.code_type if p else ''
        l.eta_code = p.eta_code if p else ''
        l.unit_type = (p.unit_type if p else '') or issuer.default_unit_type
        l.tax_treatment = p.tax_treatment if p else TaxItemProfile.TREATMENT_UNCLASSIFIED
        l.vat_rate = p.vat_rate if p and p.tax_treatment == TaxItemProfile.TREATMENT_TAXABLE else ZERO
        if l.status in ('approved', 'exempt') and l.source_vat_rate != l.vat_rate:
            l.status = 'pending'
            l.status_reason = f'نسبة الضريبة في SOFTECH {l.source_vat_rate}% تختلف عن المؤكدة {l.vat_rate}%'
        if l.status in ('approved', 'exempt') and l.quantity <= 0:
            l.status = 'pending'
            l.status_reason = 'كمية غير موجبة'
        net, vat = fiscal.split_vat(l.total, l.vat_rate, issuer.prices_include_vat)
        l.net_ex_vat, l.vat_amount, l.total_incl_vat = net, vat, fiscal.q5(net + vat)
        l.save()
        if l.status not in ('approved', 'exempt'):
            issues.append({'code': l.status, 'itemcode': l.itemcode, 'message': l.status_reason})

    t = _totals(lines)
    receipt.net_amount, receipt.vat_amount, receipt.total_amount = t['net'], t['vat'], t['total']
    if rule is None or rule.mode == TaxChannelRule.MODE_UNDECIDED:
        issues.insert(0, {'code': 'no_channel_rule', 'message': f'لا يوجد قرار للقناة {receipt.channel}'})
    elif rule.mode == TaxChannelRule.MODE_INVOICE:
        receipt.status, receipt.hold_reasons = TaxReceipt.BY_INVOICE, []
        receipt.save()
        return receipt
    if receipt.doccode == '30':
        if len(receipt.original_ref) != 1:
            issues.append({'code': 'return_reference', 'message': 'المرتجع يشير إلى عدد فواتير غير واحد'})
        elif _original_of(receipt) is None:
            issues.append({'code': 'return_reference', 'message': 'الإيصال الأصلي غير صادر من هذا النظام'})
    if receipt.total_amount >= BUYER_ID_THRESHOLD:
        issues.append({'code': 'buyer_id', 'message': 'الإيصال فوق حد بيانات المشتري'})
    receipt.hold_reasons = issues
    receipt.status = TaxReceipt.HELD if issues else TaxReceipt.READY
    receipt.save()
    return receipt


def _totals(lines):
    t = {'net': ZERO, 'vat': ZERO, 'total': ZERO}
    for l in lines:
        t['net'] += l.net_ex_vat
        t['vat'] += l.vat_amount
        t['total'] += l.total_incl_vat
    return {k: fiscal.q5(v) for k, v in t.items()}


def _original_of(receipt):
    doccode, docnumber, docdate = receipt.original_ref[0]
    # On SOFTECH returns r_doccode is mostly '0' or blank and means the sale (mirror, 2026-11: 17,817 of
    # 17,864 returns). Anything else (50, -30) is not a sale document, so it does not match here.
    if doccode not in ('', '0', '115'):
        return None
    day = _parse_day(docdate)
    return TaxReceipt.objects.filter(softech_branchcode=receipt.softech_branchcode, doccode='115',
                                     docnumber=docnumber, docdate=day).exclude(uuid='').first()


def revalidate_for_items(itemcodes):
    ids = set(TaxReceiptLine.objects.filter(itemcode__in=list(itemcodes),
                                            receipt__status__in=[TaxReceipt.HELD, TaxReceipt.READY]
                                            ).values_list('receipt_id', flat=True))
    for receipt in TaxReceipt.objects.filter(pk__in=ids):
        evaluate(receipt)
    return len(ids)


def reevaluate_channel(ptclassifcode):
    n = 0
    for receipt in TaxReceipt.objects.filter(channel=ptclassifcode, status__in=[TaxReceipt.HELD, TaxReceipt.READY, TaxReceipt.BY_INVOICE]):
        evaluate(receipt)
        n += 1
    return n


# ── Payload and chain ──────────────────────────────────────────────────────────────────────────

def config_gaps(config, issuer):
    gaps = []
    for field, label in (('seller_branch_code', 'كود فرع المصلحة'), ('device_serial', 'سيريال الجهاز'),
                         ('activity_code', 'كود النشاط'), ('governate', 'المحافظة'), ('region_city', 'المدينة'),
                         ('street', 'الشارع'), ('building_number', 'رقم المبنى'), ('payment_method', 'طريقة الدفع')):
        if not getattr(config, field):
            gaps.append(label)
    for field, label in (('name', 'اسم الممول'), ('tax_id', 'الرقم الضريبي'), ('vat_tax_type', 'نوع الضريبة')):
        if not getattr(issuer, field):
            gaps.append(label)
    if not issuer.vat_basis_confirmed_at:
        gaps.append('تأكيد المحاسب: هل الأسعار شاملة الضريبة')
    if not config.chain_start:
        gaps.append('بداية سلسلة الجهاز (جهاز جديد أم استلام من برنامج سابق)')
    return gaps


# ── Where a device's chain starts ──────────────────────────────────────────────────────────────
# A device ETA already knows (registered and used by Invoicer) carries a chain: each receipt names the one
# before it. Our first receipt must follow the device's last one, and the other program must have stopped on
# that device. A new device starts empty. This is decided once per branch, before the first receipt, from what
# ETA itself returns; it is never typed from memory.

LOOKBACK_DAYS = 400


def _issued_here(branchcode):
    return TaxReceipt.objects.filter(softech_branchcode=branchcode).exclude(uuid='').exists()


def chain_lookup(branchcode, actor=None):
    """Ask ETA for the device's newest receipts. Reads only; changes nothing here."""
    config = TaxReceiptBranchConfig.objects.filter(softech_branchcode=branchcode).first()
    if config is None or not config.device_serial:
        raise TaxRuleError('أدخل سيريال جهاز الفرع أولاً')
    since = timezone.now() - dt.timedelta(days=LOOKBACK_DAYS)
    try:
        rows = eta_client.device_receipts(config, issued_from=since)
    except eta_client.EtaError as exc:
        raise TaxRuleError(str(exc)) from exc
    latest = rows[0] if rows else None
    result = {'branch': branchcode, 'device_serial': config.device_serial, 'looked_back_days': LOOKBACK_DAYS,
              'found': len(rows), 'latest': None if latest is None else {
                  'uuid': latest.get('uuid', ''), 'receipt_number': latest.get('receiptNumber', ''),
                  'issued': latest.get('dateTimeIssued', ''), 'received': latest.get('dateTimeReceived', ''),
                  'status': latest.get('status', ''), 'submitter': latest.get('submitterName', '')},
              'chain_start': config.chain_start, 'issued_here': _issued_here(branchcode)}
    audit('receipt_chain_lookup', actor=actor, entity='receipt_branch', entity_id=branchcode,
          after={'found': len(rows), 'latest_uuid': result['latest']['uuid'] if latest else ''})
    return result


def start_chain(branchcode, actor, *, mode, confirm, other_program_stopped=False, expected_uuid=''):
    """Decide the chain start once. ETA is asked again here, so the decision rests on its current answer:
    'fresh' only when ETA shows no receipt from this device; 'handover' only to the newest one it shows, which
    must be the receipt the person reviewed (expected_uuid), after they confirm the other program has stopped."""
    if confirm != branchcode:
        raise TaxRuleError('اكتب كود الفرع للتأكيد')
    if mode not in (TaxReceiptBranchConfig.CHAIN_FRESH, TaxReceiptBranchConfig.CHAIN_HANDOVER):
        raise TaxRuleError('اختر: جهاز جديد أو استلام من برنامج سابق')
    looked = chain_lookup(branchcode, actor)
    latest = looked['latest']
    with transaction.atomic():
        config = TaxReceiptBranchConfig.objects.select_for_update().get(softech_branchcode=branchcode)
        if config.chain_start or config.last_uuid or _issued_here(branchcode):
            raise TaxRuleError('بداية السلسلة محددة بالفعل لهذا الفرع')
        if mode == TaxReceiptBranchConfig.CHAIN_FRESH:
            if latest:
                raise TaxRuleError('المصلحة لديها إيصالات من هذا الجهاز؛ اختر الاستلام من البرنامج السابق')
            seed = ''
        else:
            if not latest:
                raise TaxRuleError('المصلحة لا تعرض أي إيصال من هذا الجهاز؛ لا يوجد ما يُستلم')
            if not other_program_stopped:
                raise TaxRuleError('أكد أن البرنامج السابق توقف عن الإصدار على هذا الجهاز')
            if not expected_uuid or expected_uuid != latest['uuid']:
                raise TaxRuleError('أحدث إيصال لدى المصلحة تغير منذ المراجعة؛ ابحث مرة أخرى')
            if str(latest.get('status') or '').lower() not in ('valid', ''):
                raise TaxRuleError(f'أحدث إيصال حالته {latest.get("status")}؛ راجع المصلحة قبل الاستلام')
            seed = latest['uuid']
        config.chain_start, config.chain_start_uuid, config.last_uuid = mode, seed, seed
        config.chain_start_detail = {'latest': latest, 'found': looked['found'], 'looked_back_days': LOOKBACK_DAYS,
                                     'other_program_stopped': bool(other_program_stopped)}
        config.chain_start_at, config.chain_start_by = timezone.now(), actor
        config.save()
        audit('receipt_chain_started', actor=actor, entity='receipt_branch', entity_id=branchcode,
              before={'chain_start': '', 'last_uuid': ''},
              after={'chain_start': mode, 'last_uuid': seed, 'latest': latest})
    return config


def undo_chain_start(branchcode, actor, reason):
    """Only while nothing has been issued here: after that the chain is in our receipts."""
    if not (reason or '').strip():
        raise TaxRuleError('اكتب السبب')
    with transaction.atomic():
        config = TaxReceiptBranchConfig.objects.select_for_update().filter(softech_branchcode=branchcode).first()
        if config is None:
            raise TaxRuleError('الفرع غير مُعد')
        if _issued_here(branchcode):
            raise TaxRuleError('صدرت إيصالات على هذه السلسلة؛ لا يمكن التراجع')
        before = {'chain_start': config.chain_start, 'last_uuid': config.last_uuid}
        config.chain_start, config.chain_start_uuid, config.last_uuid = '', '', ''
        config.chain_start_detail, config.chain_start_at, config.chain_start_by = None, None, None
        config.save()
        audit('receipt_chain_start_undone', actor=actor, entity='receipt_branch', entity_id=branchcode, reason=reason,
              before=before, after={'chain_start': '', 'last_uuid': ''})
    return config


def _receipt_json(receipt, config, issuer, *, uuid_value, previous, reference=None):
    N = fiscal._money
    lines = []
    tax_total = ZERO
    for l in receipt.lines.all():
        unit = fiscal.q5(l.net_ex_vat / l.quantity)
        tax_total += l.vat_amount
        lines.append({
            'internalCode': l.itemcode, 'description': l.item_name or l.itemcode, 'itemType': l.code_type,
            'itemCode': l.eta_code, 'unitType': l.unit_type, 'quantity': fiscal._qty(l.quantity), 'unitPrice': N(unit),
            'netSale': N(l.net_ex_vat), 'totalSale': N(l.net_ex_vat), 'total': N(l.total_incl_vat),
            'taxableItems': [{'taxType': issuer.vat_tax_type, 'amount': N(l.vat_amount),
                              'subType': _subtype(issuer, l.tax_treatment), 'rate': fiscal._rate(l.vat_rate)}],
        })
    header = {'dateTimeIssued': receipt.sold_at.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'receiptNumber': f'{receipt.doccode}-{receipt.docnumber}-{receipt.docdate:%Y%m%d}',
              'uuid': uuid_value, 'previousUUID': previous}
    if reference:
        header['referenceUUID'] = reference
    header['currency'] = 'EGP'
    return {
        'header': header,
        'documentType': {'receiptType': 'r' if receipt.doccode == '30' else 's', 'typeVersion': TYPE_VERSION},
        'seller': {'rin': issuer.tax_id, 'companyTradeName': issuer.name, 'branchCode': config.seller_branch_code,
                   'branchAddress': {'country': 'EG', 'governate': config.governate, 'regionCity': config.region_city,
                                     'street': config.street, 'buildingNumber': config.building_number},
                   'deviceSerialNumber': config.device_serial, 'activityCode': config.activity_code},
        'buyer': {'type': 'P'},
        'itemData': lines,
        'totalSales': N(receipt.net_amount), 'totalCommercialDiscount': N(0), 'totalItemsDiscount': N(0),
        'netAmount': N(receipt.net_amount), 'feesAmount': N(0), 'totalAmount': N(receipt.total_amount),
        'taxTotals': [{'taxType': issuer.vat_tax_type, 'amount': N(tax_total)}],
        'paymentMethod': config.payment_method, 'adjustment': N(0),
    }


def receipt_uuid(document):
    """ETA: SHA-256 of the serialized receipt, with the uuid field empty and previousUUID included."""
    return fiscal.sha256_hex(fiscal.canonical(fiscal.to_text(document)))


def issue_next(branchcode, actor, limit=200):
    """Freeze ready receipts into the branch's UUID chain, oldest sale first. Nothing is sent here."""
    issuer = TaxIssuerProfile.load()
    issued = 0
    with transaction.atomic():
        config = TaxReceiptBranchConfig.objects.select_for_update().filter(softech_branchcode=branchcode).first()
        if config is None or not config.is_enabled:
            raise TaxRuleError(f'الفرع {branchcode} غير مفعل للإيصال الإلكتروني')
        gaps = config_gaps(config, issuer)
        if gaps:
            raise TaxRuleError('بيانات ناقصة: ' + '، '.join(gaps))
        queue = TaxReceipt.objects.select_for_update().filter(softech_branchcode=branchcode, status=TaxReceipt.READY).order_by('sold_at', 'id')[:limit]
        for receipt in queue:
            reference = _original_of(receipt).uuid if receipt.doccode == '30' else None
            document = _receipt_json(receipt, config, issuer, uuid_value='', previous=config.last_uuid, reference=reference)
            value = receipt_uuid(document)
            document['header']['uuid'] = value
            receipt.uuid, receipt.previous_uuid = value, config.last_uuid
            receipt.payload_text = fiscal.to_text(document)
            receipt.status = TaxReceipt.ISSUED
            receipt.issued_at = timezone.now()
            receipt.save()
            config.last_uuid = value
            issued += 1
        config.save(update_fields=['last_uuid'])
        audit('receipts_issued', actor=actor, entity='receipt_branch', entity_id=branchcode,
              after={'issued': issued, 'last_uuid': config.last_uuid})
    return {'issued': issued}


def preview_batch(branchcode, limit=50):
    rows = list(TaxReceipt.objects.filter(softech_branchcode=branchcode, status=TaxReceipt.ISSUED).order_by('issued_at', 'id')[:limit])
    return {'dry_run': True, 'count': len(rows), 'submit_enabled': writer_allowed(FLAG),
            'receipts': [{'id': r.id, 'uuid': r.uuid, 'receipt_number': json.loads(r.payload_text)['header']['receiptNumber'],
                          'total': str(r.total_amount)} for r in rows[:10]]}


def submit_branch(branchcode, actor, confirm, limit=50):
    """Send issued receipts in chain order. An uncertain result stops the branch until reconciled."""
    if not writer_allowed(FLAG):
        raise TaxRuleError('إرسال الإيصالات مغلق (TAX_ERECEIPT_SUBMIT_ENABLED)')
    if confirm != branchcode:
        raise TaxRuleError('اكتب كود الفرع للتأكيد')
    config = TaxReceiptBranchConfig.objects.filter(softech_branchcode=branchcode, is_enabled=True).first()
    if config is None:
        raise TaxRuleError('الفرع غير مفعل')
    signer = signing.get_signer()
    try:
        signing.assert_ready_for_live(signer)
    except signing.SigningUnavailable as exc:
        raise TaxRuleError(str(exc)) from exc
    with transaction.atomic():
        if TaxReceipt.objects.filter(softech_branchcode=branchcode, status__in=[TaxReceipt.UNCERTAIN, TaxReceipt.SUBMITTING]).exists():
            raise TaxRuleError('توجد إيصالات نتيجتها غير مؤكدة في هذا الفرع؛ استعلم من المصلحة أولاً')
        batch = list(TaxReceipt.objects.select_for_update().filter(softech_branchcode=branchcode, status=TaxReceipt.ISSUED)
                     .order_by('issued_at', 'id')[:limit])
        if not batch:
            raise TaxRuleError('لا توجد إيصالات جاهزة للإرسال')
        attempt = TaxReceiptAttempt.objects.create(config=config, receipt_count=len(batch), started_by=actor)
        TaxReceipt.objects.filter(pk__in=[r.pk for r in batch]).update(status=TaxReceipt.SUBMITTING, attempt=attempt)

    texts = [r.payload_text for r in batch]
    ids = [r.pk for r in batch]
    try:
        signature = signer.sign(''.join(fiscal.canonical(t) for t in texts))
        http_status, body = eta_client.submit_receipts(config, texts, signature)
    except (signing.SigningUnavailable, eta_client.EtaNotConfigured, eta_client.EtaRefused) as exc:
        TaxReceipt.objects.filter(pk__in=ids).update(status=TaxReceipt.ISSUED, attempt=None)
        _end_attempt(attempt, TaxReceiptAttempt.FAILED, error=str(exc), http_status=getattr(exc, 'http_status', None))
        raise TaxRuleError(str(exc)) from exc
    except eta_client.EtaUncertain as exc:
        TaxReceipt.objects.filter(pk__in=ids).update(status=TaxReceipt.UNCERTAIN)
        _end_attempt(attempt, TaxReceiptAttempt.TIMEOUT, error=str(exc), http_status=exc.http_status)
        return {'status': 'uncertain', 'count': len(ids)}

    with transaction.atomic():
        attempt.submission_uuid = body.get('submissionId') or body.get('submissionUUID') or ''
        accepted = {d.get('uuid') for d in body.get('acceptedDocuments') or []}
        rejected = {d.get('uuid'): d for d in body.get('rejectedDocuments') or []}
        for receipt in batch:
            if receipt.uuid in accepted:
                receipt.status, receipt.eta_reason = TaxReceipt.SUBMITTED, ''
            elif receipt.uuid in rejected:
                receipt.status = TaxReceipt.REJECTED
                receipt.eta_reason = str(rejected[receipt.uuid].get('error') or '')[:2000]
            else:
                receipt.status = TaxReceipt.UNCERTAIN
                receipt.eta_reason = 'رد المصلحة لا يذكر هذا الإيصال'
            receipt.submission_uuid = attempt.submission_uuid
            receipt.save()
        _end_attempt(attempt, TaxReceiptAttempt.ACCEPTED, http_status=http_status)
        audit('receipts_submitted', actor=actor, entity='receipt_branch', entity_id=branchcode,
              after={'count': len(batch), 'submission': attempt.submission_uuid})
    return {'status': 'submitted', 'count': len(batch), 'submission_uuid': attempt.submission_uuid}


def _end_attempt(attempt, state, *, error='', http_status=None):
    attempt.state, attempt.error, attempt.http_status = state, error, http_status
    attempt.finished_at = timezone.now()
    attempt.save()


_ETA_STATES = {'valid': TaxReceipt.ACCEPTED, 'invalid': TaxReceipt.REJECTED, 'cancelled': TaxReceipt.REJECTED}


def reconcile_branch(branchcode, actor, limit=50):
    """Ask ETA about every uncertain or submitted receipt, by its UUID. Only a clear answer moves it."""
    config = TaxReceiptBranchConfig.objects.filter(softech_branchcode=branchcode).first()
    if config is None:
        raise TaxRuleError('الفرع غير مسجل')
    wait = dt.timedelta(minutes=int(getattr(settings, 'TAX_RECONCILE_WAIT_MINUTES', 15)))
    changed = unchanged = 0
    for receipt in TaxReceipt.objects.filter(softech_branchcode=branchcode,
                                             status__in=[TaxReceipt.UNCERTAIN, TaxReceipt.SUBMITTING, TaxReceipt.SUBMITTED]
                                             ).select_related('attempt').order_by('issued_at', 'id')[:limit]:
        try:
            row = eta_client.get_receipt_status(config, receipt.uuid, receipt.submission_uuid)
        except eta_client.EtaError as exc:
            raise TaxRuleError(f'تعذر الاستعلام من المصلحة؛ لم يتغير شيء: {exc}') from exc
        if row is None:
            started = receipt.attempt.started_at if receipt.attempt_id else None
            if receipt.status != TaxReceipt.SUBMITTED and started and timezone.now() - started >= wait:
                # ETA has no such receipt, so it may go again with the same UUID: its place in the chain holds.
                receipt.status = TaxReceipt.ISSUED
                receipt.attempt = None
                receipt.save()
                changed += 1
            else:
                unchanged += 1
            continue
        target = _ETA_STATES.get(str(row.get('status') or '').lower())
        if target is None:
            if receipt.status in (TaxReceipt.UNCERTAIN, TaxReceipt.SUBMITTING):
                receipt.status = TaxReceipt.SUBMITTED
                receipt.save()
                changed += 1
            else:
                unchanged += 1
            continue
        receipt.status = target
        receipt.eta_reason = str(row.get('errors') or '')[:2000] if target == TaxReceipt.REJECTED else ''
        receipt.save()
        changed += 1
    audit('receipts_reconciled', actor=actor, entity='receipt_branch', entity_id=branchcode,
          after={'changed': changed, 'unchanged': unchanged})
    return {'changed': changed, 'unchanged': unchanged}


def summary_by_branch():
    from django.db.models import Count, Sum
    rows = {}
    for r in TaxReceipt.objects.values('softech_branchcode', 'status').annotate(n=Count('id'), value=Sum('source_value')):
        row = rows.setdefault(r['softech_branchcode'], {'branch': r['softech_branchcode'], 'by_status': {}, 'total': 0, 'source_value': ZERO})
        row['by_status'][r['status']] = r['n']
        row['total'] += r['n']
        row['source_value'] += r['value'] or ZERO
    return [{**r, 'source_value': str(r['source_value'])} for _, r in sorted(rows.items())]
