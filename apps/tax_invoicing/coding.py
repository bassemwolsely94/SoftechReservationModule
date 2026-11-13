"""
apps/tax_invoicing/coding.py — asking ETA for item codes (EGS) and following each request. Doc 36 §coding.

An item without an approved ETA code blocks every document it is on. For such an item we ask ETA to
register our own internal code, EG-<tax id>-<SOFTECH item code>, under a GPC brick, then follow the
request until ETA's staff approve or reject it. ETA's answer is the only thing that moves the item's
coding fields: pending once ETA holds the request, approved or rejected on ETA's decision.

Gates for sending, in order: flag TAX_ETA_CODING_ENABLED (writer instance only) · production also
needs TAX_ETA_PRODUCTION_ALLOWED (eta_client) · `finalize` permission in the view · a typed count.
"""
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from config.writers import writer_allowed

from . import environment, eta_client, gpc
from .models import TaxCodeRequest, TaxIssuerProfile, TaxItemProfile
from .services import TaxRuleError, audit

FLAG = 'TAX_ETA_CODING_ENABLED'
MAX_PER_ACTION = 200
GPC_BRICK = re.compile(r'^\d{8}$')
_ETA_STATUS = {'submitted': TaxCodeRequest.SUBMITTED, 'approved': TaxCodeRequest.APPROVED,
               'rejected': TaxCodeRequest.REJECTED}


def item_code_for(tax_id, softech_itemcode):
    return f'EG-{tax_id}-{softech_itemcode}'


def _issuer_tax_id():
    issuer = TaxIssuerProfile.objects.first()
    tax_id = re.sub(r'\D', '', (issuer.tax_id if issuer else '') or '')
    if not tax_id:
        raise TaxRuleError('أدخل رقم التسجيل الضريبي للشركة في إعدادات المُصدر أولاً')
    return tax_id


def candidates(limit=500):
    """Items that need a code: none yet, or ETA rejected the last one; and none already open."""
    open_ids = TaxCodeRequest.objects.filter(status__in=TaxCodeRequest.OPEN_STATES).values('profile_id')
    return (TaxItemProfile.objects
            .filter(coding_status__in=[TaxItemProfile.CODE_MISSING, TaxItemProfile.CODE_REJECTED])
            .exclude(pk__in=open_ids).order_by('softech_itemcode')[:limit])


def _catalog_without_profile():
    from apps.catalog.models import Item
    return Item.objects.filter(is_active=True).exclude(
        softech_id__in=TaxItemProfile.objects.values('softech_itemcode'))


def add_from_catalog(actor):
    """Active catalog items with no tax profile yet (new since the owner's workbook) become uncoded profiles,
    so they can be offered for a code. Sets nothing else: tax treatment stays for the accountant."""
    rows = [TaxItemProfile(softech_itemcode=i.softech_id, item=i, item_name=i.name[:200],
                           coding_status=TaxItemProfile.CODE_MISSING)
            for i in _catalog_without_profile().order_by('softech_id')]
    TaxItemProfile.objects.bulk_create(rows, batch_size=2000, ignore_conflicts=True)
    audit('items_added_from_catalog', actor=actor, entity='item_import', entity_id='catalog',
          after={'added': len(rows), 'first': [r.softech_itemcode for r in rows[:20]]})
    return {'added': len(rows)}


def _check_fields(parent_code, code_name, code_name_ar):
    problems = []
    if not GPC_BRICK.match(parent_code or ''):
        problems.append('كود GPC (المستوى الرابع) يجب أن يكون 8 أرقام')
    elif not gpc.known(parent_code):
        problems.append(f'كود GPC {parent_code} ليس في قائمة فئات GPC')
    if not (code_name or '').strip():
        problems.append('الاسم الإنجليزي مطلوب')
    if not (code_name_ar or '').strip():
        problems.append('الاسم العربي مطلوب')
    return problems


def prepare(profile_ids, actor, *, parent_code='', active_from=None, reason='', use_suggested=False):
    """Draft one request per item. Sends nothing. Returns {'created': [...], 'skipped': [{itemcode, why}]}.
    The brick: the one typed for the batch, else the item's own, else (only when asked) the suggested one,
    which the person saw beside the item before preparing."""
    tax_id = _issuer_tax_id()
    ids = list(profile_ids)[:MAX_PER_ACTION]
    created, skipped = [], []
    profiles = list(TaxItemProfile.objects.filter(pk__in=ids).select_related('item__category').order_by('softech_itemcode'))
    suggested = gpc.suggest(profiles) if use_suggested and not parent_code else {}
    for profile in profiles:
        if profile.coding_status not in (TaxItemProfile.CODE_MISSING, TaxItemProfile.CODE_REJECTED):
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'للصنف كود معتمد أو قيد الاعتماد'})
            continue
        own = '' if (profile.gpc_code or '').strip() == '0' else (profile.gpc_code or '').strip()
        brick = (parent_code or own or suggested.get(profile.id, {}).get('code') or '').strip()
        name_en = (profile.item_name or '').strip()
        name_ar = (profile.item_name_ar or '').strip() or name_en
        problems = _check_fields(brick, name_en, name_ar)
        if problems:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': '؛ '.join(problems)})
            continue
        try:
            with transaction.atomic():
                row = TaxCodeRequest.objects.create(
                    profile=profile, item_code=item_code_for(tax_id, profile.softech_itemcode), parent_code=brick,
                    code_name=name_en[:200], code_name_ar=name_ar[:200], active_from=active_from or timezone.localdate(),
                    request_reason=(reason or 'صنف صيدلي يُباع للعملاء')[:300], prepared_by=actor)
        except IntegrityError:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'يوجد طلب مفتوح لهذا الصنف'})
            continue
        audit('code_request_prepared', actor=actor, entity='code_request', entity_id=row.pk,
              after={'item_code': row.item_code, 'parent_code': brick, 'itemcode': profile.softech_itemcode,
                     'brick_from': 'batch' if parent_code else 'item' if own else 'suggested'})
        created.append(row.pk)
    return {'created': created, 'skipped': skipped}


def edit(request_id, actor, fields):
    """Correct a request before it goes out. Only a prepared request can change."""
    allowed = {'parent_code', 'code_name', 'code_name_ar', 'description', 'description_ar', 'request_reason'}
    with transaction.atomic():
        row = TaxCodeRequest.objects.select_for_update().get(pk=request_id)
        if row.status != TaxCodeRequest.PREPARED:
            raise TaxRuleError('يُعدَّل الطلب قبل إرساله فقط')
        before = {k: getattr(row, k) for k in allowed}
        for key, value in fields.items():
            if key in allowed:
                setattr(row, key, str(value or '').strip()[:300])
        problems = [] if row.purpose == TaxCodeRequest.PURPOSE_GS1 else _check_fields(row.parent_code, row.code_name, row.code_name_ar)
        if problems:
            raise TaxRuleError('؛ '.join(problems))
        row.save()
        audit('code_request_edited', actor=actor, entity='code_request', entity_id=row.pk,
              before=before, after={k: getattr(row, k) for k in allowed})
    return row


def cancel(request_id, actor, reason):
    with transaction.atomic():
        row = TaxCodeRequest.objects.select_for_update().get(pk=request_id)
        if row.status not in (TaxCodeRequest.PREPARED, TaxCodeRequest.FAILED):
            raise TaxRuleError('يُلغى الطلب قبل وصوله للمصلحة فقط')
        if not (reason or '').strip():
            raise TaxRuleError('اكتب سبب الإلغاء')
        old, row.status = row.status, TaxCodeRequest.CANCELLED
        row.save()
        audit('code_request_cancelled', actor=actor, entity='code_request', entity_id=row.pk, reason=reason,
              before={'status': old}, after={'status': row.status})
    return row


def _payload(row):
    item = {'codeType': 'EGS', 'parentCode': row.parent_code, 'itemCode': row.item_code,
            'codeName': row.code_name, 'codeNameAr': row.code_name_ar,
            'activeFrom': row.active_from.strftime('%Y-%m-%dT00:00:00Z')}
    for key, field in (('description', 'description'), ('descriptionAr', 'description_ar'),
                       ('requestReason', 'request_reason')):
        if getattr(row, field):
            item[key] = getattr(row, field)
    return item


def _mark_profile_pending(row, actor):
    if row.purpose == TaxCodeRequest.PURPOSE_MIRROR:
        return     # a test-system copy of a real code: the item's real coding stays as it is
    profile = row.profile
    before = {'coding_status': profile.coding_status, 'eta_code': profile.eta_code, 'code_type': profile.code_type}
    profile.coding_status, profile.eta_code, profile.code_type = TaxItemProfile.CODE_PENDING, row.item_code, _code_type(row)
    profile.coding_env = row.environment
    if row.parent_code and profile.gpc_code in ('', '0'):
        profile.gpc_code = row.parent_code
    profile.save()
    audit('item_coding_from_eta', actor=actor, entity='item', entity_id=profile.pk, reason=f'طلب كود {row.item_code}',
          before=before, after={'coding_status': profile.coding_status, 'eta_code': profile.eta_code,
                                'code_type': profile.code_type})


def _code_type(row):
    return 'GS1' if row.purpose == TaxCodeRequest.PURPOSE_GS1 else 'EGS'


def _send_one(row):
    if row.purpose == TaxCodeRequest.PURPOSE_GS1:
        return eta_client.request_code_reuse([{'codetype': 'GS1', 'itemCode': row.item_code,
                                               'comment': (row.request_reason or 'باركود المصنع لصنف نبيعه')[:200]}])
    return eta_client.create_egs_codes([_payload(row)])


def send(request_ids, actor, confirm):
    """Send prepared requests one by one, so each item's outcome is its own. The typed confirmation
    is the number of requests being sent."""
    if not writer_allowed(FLAG):
        raise TaxRuleError('طلب الأكواد من المصلحة مغلق (TAX_ETA_CODING_ENABLED)')
    ids = list(request_ids)[:MAX_PER_ACTION]
    rows = list(TaxCodeRequest.objects.filter(pk__in=ids, status__in=[TaxCodeRequest.PREPARED, TaxCodeRequest.FAILED])
                .select_related('profile').order_by('id'))
    if not rows:
        raise TaxRuleError('لا توجد طلبات جاهزة للإرسال')
    if str(confirm).strip() != str(len(rows)):
        raise TaxRuleError(f'اكتب عدد الطلبات ({len(rows)}) للتأكيد')
    env = environment.current() or 'custom'
    results = {'submitted': 0, 'failed': 0, 'uncertain': 0, 'stopped': ''}
    for row in rows:
        with transaction.atomic():
            claimed = TaxCodeRequest.objects.filter(pk=row.pk, status__in=[TaxCodeRequest.PREPARED, TaxCodeRequest.FAILED]) \
                .update(status=TaxCodeRequest.SENDING, sent_by=actor, sent_at=timezone.now(), environment=env, error='')
        if not claimed:
            continue
        try:
            http_status, body = _send_one(row)
        except eta_client.EtaNotConfigured as exc:
            TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.FAILED, error=str(exc))
            results['stopped'] = str(exc)
            break
        except eta_client.EtaRefused as exc:
            TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.FAILED, error=str(exc)[:2000],
                                                            eta_response=exc.body or {})
            audit('code_request_refused', actor=actor, entity='code_request', entity_id=row.pk, reason=str(exc)[:500])
            results['failed'] += 1
            continue
        except eta_client.EtaUncertain as exc:
            TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.UNCERTAIN, error=str(exc)[:2000],
                                                            eta_response=exc.body or {})
            audit('code_request_uncertain', actor=actor, entity='code_request', entity_id=row.pk, reason=str(exc)[:500])
            results['uncertain'] += 1
            results['stopped'] = 'توقف الإرسال بعد نتيجة غير مؤكدة؛ حدّث الحالة من المصلحة أولاً'
            break
        with transaction.atomic():
            row.refresh_from_db()
            row.status, row.eta_response = TaxCodeRequest.SUBMITTED, body if isinstance(body, dict) else {'body': body}
            row.save()
            _mark_profile_pending(row, actor)
            audit('code_request_sent', actor=actor, entity='code_request', entity_id=row.pk,
                  after={'item_code': row.item_code, 'http_status': http_status, 'environment': env})
        results['submitted'] += 1
    return results


def _apply_eta_answer(row, eta_row, actor):
    status = _ETA_STATUS.get(str(eta_row.get('status') or '').strip().lower())
    row.eta_status = str(eta_row.get('status') or '')[:20]
    row.eta_request_id = str(eta_row.get('codeUsageRequestID') or row.eta_request_id or '')[:30]
    row.checked_at = timezone.now()
    if status is None:
        row.save()
        return
    old = row.status
    row.status = status
    if status in (TaxCodeRequest.APPROVED, TaxCodeRequest.REJECTED):
        row.decided_at = row.decided_at or timezone.now()
    row.save()
    if status == TaxCodeRequest.SUBMITTED and old == TaxCodeRequest.UNCERTAIN:
        _mark_profile_pending(row, actor)
    if status in (TaxCodeRequest.APPROVED, TaxCodeRequest.REJECTED) and row.purpose == TaxCodeRequest.PURPOSE_MIRROR:
        if status == TaxCodeRequest.APPROVED:
            profile = row.profile
            profile.eta_check_env, profile.eta_check_status = row.environment, TaxItemProfile.CHECK_FOUND
            profile.eta_checked_at = timezone.now()
            profile.save()
    elif status in (TaxCodeRequest.APPROVED, TaxCodeRequest.REJECTED):
        profile = row.profile
        before = {'coding_status': profile.coding_status, 'eta_code': profile.eta_code}
        profile.coding_status = TaxItemProfile.CODE_APPROVED if status == TaxCodeRequest.APPROVED else TaxItemProfile.CODE_REJECTED
        profile.eta_code, profile.code_type = row.item_code, _code_type(row)
        profile.coding_env = row.environment
        if status == TaxCodeRequest.APPROVED:
            profile.eta_check_env, profile.eta_check_status = row.environment, TaxItemProfile.CHECK_FOUND
            profile.eta_checked_at = timezone.now()
        if status == TaxCodeRequest.APPROVED and eta_row.get('activeFrom'):
            profile.active_from = str(eta_row['activeFrom'])[:10]
        profile.save()
        audit('item_coding_from_eta', actor=actor, entity='item', entity_id=profile.pk,
              reason=f'قرار المصلحة على {row.item_code}: {row.eta_status}', before=before,
              after={'coding_status': profile.coding_status, 'eta_code': profile.eta_code})
    if old != row.status:
        audit('code_request_status', actor=actor, entity='code_request', entity_id=row.pk,
              before={'status': old}, after={'status': row.status, 'eta_status': row.eta_status})


def refresh(actor=None, request_ids=None, limit=100):
    """Ask ETA about requests it holds (or may hold). Reading never needs the sending switches.
    "Could not ask" changes nothing; an uncertain request ETA has no trace of becomes failed (safe to resend)."""
    states = [TaxCodeRequest.SUBMITTED, TaxCodeRequest.UNCERTAIN]
    if request_ids:
        # Asked about by name: a refused request too ("code already exists" may mean ETA already has ours).
        states.append(TaxCodeRequest.FAILED)
    qs = TaxCodeRequest.objects.filter(status__in=states).select_related('profile')
    if request_ids:
        qs = qs.filter(pk__in=request_ids)
    done = {'checked': 0, 'approved': 0, 'rejected': 0, 'error': ''}
    for row in qs.order_by('checked_at', 'id')[:limit]:
        try:
            found = eta_client.my_code_requests(row.item_code)
        except (eta_client.EtaUncertain, eta_client.EtaRefused, eta_client.EtaNotConfigured) as exc:
            done['error'] = str(exc)
            break
        with transaction.atomic():
            row = TaxCodeRequest.objects.select_for_update().select_related('profile').get(pk=row.pk)
            if found:
                _apply_eta_answer(row, found[0], actor)
            elif row.status == TaxCodeRequest.UNCERTAIN:
                row.status, row.checked_at = TaxCodeRequest.FAILED, timezone.now()
                row.error = 'المصلحة لا تعرض هذا الطلب؛ يمكن إرساله مرة أخرى'
                row.save()
                audit('code_request_status', actor=actor, entity='code_request', entity_id=row.pk,
                      before={'status': TaxCodeRequest.UNCERTAIN}, after={'status': row.status})
            else:
                row.checked_at = timezone.now()
                row.save()
        done['checked'] += 1
        if row.status == TaxCodeRequest.APPROVED:
            done['approved'] += 1
        elif row.status == TaxCodeRequest.REJECTED:
            done['rejected'] += 1
    return done


def summary():
    from django.db.models import Count
    counts = dict(TaxCodeRequest.objects.values_list('status').annotate(n=Count('id')))
    here = environment.current()
    checks = dict(TaxItemProfile.objects.exclude(eta_code='').filter(eta_check_env=here)
                  .values_list('eta_check_status').annotate(n=Count('id')))
    return {'by_status': counts, 'candidates': candidates(limit=100000).count(),
            'catalog_without_profile': _catalog_without_profile().count(),
            'mirror_candidates': mirror_candidates(limit=100000).count() if here not in ('', 'production') else 0,
            'checks': {'found': checks.get(TaxItemProfile.CHECK_FOUND, 0),
                       'inactive': checks.get(TaxItemProfile.CHECK_INACTIVE, 0),
                       'not_found': checks.get(TaxItemProfile.CHECK_NOT_FOUND, 0),
                       'unchecked': TaxItemProfile.objects.exclude(eta_code='').exclude(eta_check_env=here).count()},
            'send_enabled': writer_allowed(FLAG), 'environment': environment.describe()}



# ── Does ETA hold the code? (per ETA system) ───────────────────────────────────────────────────

CHECK_PER_ACTION = 100


def check_codes(actor=None, profile_ids=None, limit=CHECK_PER_ACTION):
    """Ask ETA, code by code, whether it holds each item's code in the system in use, and record the answer
    beside the system's name. Reads only. Unchecked-here items go first. "Could not ask" stops and changes
    nothing for the item it was on."""
    here = environment.current()
    if not here:
        raise TaxRuleError('منظومة المصلحة غير محددة (TAX_ETA_ENVIRONMENT)')
    qs = TaxItemProfile.objects.exclude(eta_code='').exclude(code_type='')
    if profile_ids:
        qs = qs.filter(pk__in=list(profile_ids)[:limit])
    else:
        from django.db.models import Case, IntegerField, Value, When
        qs = qs.annotate(seen=Case(When(eta_check_env=here, then=Value(1)), default=Value(0),
                                   output_field=IntegerField())).order_by('seen', 'eta_checked_at', 'id')
    done = {'checked': 0, 'found': 0, 'inactive': 0, 'not_found': 0, 'error': '', 'environment': here}
    for profile in qs[:limit]:
        try:
            details = eta_client.code_details(profile.code_type.upper(), profile.eta_code)
        except (eta_client.EtaUncertain, eta_client.EtaRefused, eta_client.EtaNotConfigured) as exc:
            done['error'] = str(exc)
            break
        if details is None:
            result = TaxItemProfile.CHECK_NOT_FOUND
        elif details.get('active') is False:
            result = TaxItemProfile.CHECK_INACTIVE
        else:
            result = TaxItemProfile.CHECK_FOUND
        profile.eta_check_env, profile.eta_check_status, profile.eta_checked_at = here, result, timezone.now()
        profile.eta_check_detail = None if details is None else {
            k: details.get(k) for k in ('codeID', 'codeName', 'codeNameAr', 'activeFrom', 'activeTo', 'active',
                                        'parentItemCode', 'parentCodeName')}
        profile.save(update_fields=['eta_check_env', 'eta_check_status', 'eta_checked_at', 'eta_check_detail', 'updated_at'])
        done['checked'] += 1
        done[result] += 1
    audit('item_codes_checked', actor=actor, entity='item', reason=f'فحص الأكواد في {here}', after=done)
    return done


def mirror_candidates(limit=500):
    """Items whose real code (EGS, ours) the test system in use does not hold, with no open request."""
    here = environment.current()
    if here in ('', 'production'):
        return TaxItemProfile.objects.none()
    open_ids = TaxCodeRequest.objects.filter(status__in=TaxCodeRequest.OPEN_STATES).values('profile_id')
    return (TaxItemProfile.objects.filter(coding_status=TaxItemProfile.CODE_APPROVED, code_type__iexact='EGS',
                                          eta_check_env=here, eta_check_status=TaxItemProfile.CHECK_NOT_FOUND)
            .exclude(pk__in=open_ids).order_by('softech_itemcode')[:limit])


def prepare_mirror(profile_ids, actor, *, reason=''):
    """Register the items' existing real codes in the test system in use, so test documents can carry them.
    Never in production: there a missing code is a finding for the accountant, not something to re-register."""
    here = environment.current()
    if here in ('', 'production'):
        raise TaxRuleError('تسجيل الأكواد الحالية متاح في المنظومة التجريبية فقط')
    tax_id = _issuer_tax_id()
    allowed = set(mirror_candidates(limit=100000).values_list('pk', flat=True))
    created, skipped = [], []
    for profile in TaxItemProfile.objects.filter(pk__in=list(profile_ids)[:MAX_PER_ACTION]).order_by('softech_itemcode'):
        if profile.pk not in allowed:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'افحص الكود أولاً: يُسجل فقط كود غير موجود في هذه المنظومة'})
            continue
        if not profile.eta_code.upper().startswith(f'EG-{tax_id}-'):
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'الكود ليس كوداً داخلياً لهذه الشركة'})
            continue
        problems = _check_fields(profile.gpc_code, profile.item_name, profile.item_name_ar or profile.item_name)
        if problems:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': '؛ '.join(problems)})
            continue
        try:
            with transaction.atomic():
                row = TaxCodeRequest.objects.create(
                    profile=profile, purpose=TaxCodeRequest.PURPOSE_MIRROR, item_code=profile.eta_code,
                    parent_code=profile.gpc_code, code_name=profile.item_name[:200],
                    code_name_ar=(profile.item_name_ar or profile.item_name)[:200], active_from=timezone.localdate(),
                    request_reason=(reason or 'تسجيل كود قائم للاختبار')[:300], prepared_by=actor)
        except IntegrityError:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'يوجد طلب مفتوح لهذا الصنف'})
            continue
        audit('code_request_prepared', actor=actor, entity='code_request', entity_id=row.pk,
              after={'item_code': row.item_code, 'purpose': 'mirror', 'environment': here})
        created.append(row.pk)
    return {'created': created, 'skipped': skipped}


# ── GS1: the manufacturer's barcode, asked for our use ─────────────────────────────────────────

def gtin_ok(code):
    """A GS1 GTIN-8/12/13/14 with a correct check digit."""
    code = (code or '').strip()
    if not re.fullmatch(r'\d{8}|\d{12,14}', code):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def gtin_for(item):
    """The item's GS1 barcode: the main one if valid, else the first valid active one from SOFTECH's
    itembarcodes (where the catalog keeps them). '' when it has none."""
    if item is None:
        return ''
    if gtin_ok(item.barcode):
        return item.barcode.strip()
    codes = sorted(b.barcode.strip() for b in item.barcodes.all() if b.is_active and gtin_ok(b.barcode))
    return codes[0] if codes else ''


def gs1_candidates(limit=500):
    """Uncoded items with a valid GTIN barcode: ETA may already hold it from GS1 Egypt.
    Each comes back with `.gtin` set."""
    from django.db.models import Prefetch
    from apps.catalog.models import ItemBarcode
    open_ids = TaxCodeRequest.objects.filter(status__in=TaxCodeRequest.OPEN_STATES).values('profile_id')
    qs = (TaxItemProfile.objects
          .filter(coding_status__in=[TaxItemProfile.CODE_MISSING, TaxItemProfile.CODE_REJECTED], item__isnull=False)
          .exclude(pk__in=open_ids).select_related('item').order_by('softech_itemcode')
          .prefetch_related(Prefetch('item__barcodes', queryset=ItemBarcode.objects.filter(is_active=True))))
    out = []
    for p in qs:
        p.gtin = gtin_for(p.item)
        if p.gtin:
            out.append(p)
            if len(out) >= limit:
                break
    return out


def prepare_gs1(profile_ids, actor, *, reason=''):
    """Draft a "use this GS1 code" request per item, from its catalog barcode. Sends nothing.
    Real or test system alike: an approved GS1 code is the item's code in that system."""
    ids = list(profile_ids)[:MAX_PER_ACTION]
    created, skipped = [], []
    for profile in TaxItemProfile.objects.filter(pk__in=ids).select_related('item').prefetch_related('item__barcodes').order_by('softech_itemcode'):
        barcode = gtin_for(profile.item)
        if profile.coding_status not in (TaxItemProfile.CODE_MISSING, TaxItemProfile.CODE_REJECTED):
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'للصنف كود معتمد أو قيد الاعتماد'})
            continue
        if not gtin_ok(barcode):
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'لا يوجد للصنف باركود GS1 صحيح'})
            continue
        try:
            with transaction.atomic():
                row = TaxCodeRequest.objects.create(
                    profile=profile, purpose=TaxCodeRequest.PURPOSE_GS1, item_code=barcode, parent_code='',
                    code_name=(profile.item_name or barcode)[:200],
                    code_name_ar=(profile.item_name_ar or profile.item_name or barcode)[:200],
                    active_from=timezone.localdate(), request_reason=(reason or 'باركود المصنع لصنف نبيعه')[:300],
                    prepared_by=actor)
        except IntegrityError:
            skipped.append({'itemcode': profile.softech_itemcode, 'why': 'يوجد طلب مفتوح لهذا الصنف'})
            continue
        audit('code_request_prepared', actor=actor, entity='code_request', entity_id=row.pk,
              after={'item_code': barcode, 'purpose': 'gs1', 'itemcode': profile.softech_itemcode})
        created.append(row.pk)
    return {'created': created, 'skipped': skipped}
