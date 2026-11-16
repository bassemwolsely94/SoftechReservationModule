"""ETA production item coding queue (batch S1): the owner decides per item "code" or "keep_out".

Deciding "code" also confirms the item's VAT treatment (14 = taxable, 0 = exempt under the VAT law's exemption
table) through services.confirm_treatment, unless the accountant already confirmed one, which the decision must
then match. Every decision and reopen is audited."""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from . import coding_rule, eta_codes, services
from .models import EtaCodeUsage, EtaReconUncodedItem, TaxCodingDecision, TaxItemProfile
from .services import TaxRuleError

ALREADY_DECIDED = 'للصنف قرار سابق — أعد فتحه أولاً'
RATE_MISMATCH = 'النسبة تخالف المعاملة الضريبية المعتمدة للصنف — عدّلها من شاشة الأصناف أولاً'
NEEDS_RATE_CHECK = 'النسبة تحتاج تأكيداً'
UNKNOWN_ITEM = 'صنف غير معروف'
MAX_BULK = 200

EXEMPT_REFERENCE = 'سلعة معفاة — قانون الضريبة على القيمة المضافة رقم 67 لسنة 2016، جدول الإعفاءات'
NAME_FIELDS = ('code_name', 'code_name_ar', 'description', 'description_ar')
_TREATMENT_FIELDS = ('tax_treatment', 'vat_rate', 'treatment_reference', 'treatment_confirmed_at',
                     'treatment_confirmed_by_id')


def catalog_item(profile):
    if profile.item_id:
        return profile.item
    from apps.catalog.models import Item
    return Item.objects.filter(softech_id=profile.softech_itemcode).first()


def _row(d):
    return {'decision': d.decision, 'premark': d.premark, 'premark_reason': d.premark_reason, 'vat_rate': d.vat_rate,
            'vat_flagged': d.vat_flagged, 'note': d.note, **{f: getattr(d, f) for f in NAME_FIELDS},
            'decided_by_id': d.decided_by_id, 'decided_at': d.decided_at}


def _treatment(p):
    return {f: getattr(p, f) for f in _TREATMENT_FIELDS}


def _rate(vat_rate):
    try:
        rate = Decimal(str(vat_rate))
        valid = vat_rate is not None and rate in coding_rule.STANDARD_RATES
    except (InvalidOperation, ValueError):
        rate, valid = None, False
    if not valid:
        raise TaxRuleError('اختر نسبة الضريبة: 0 أو 14')
    return rate


def decide(profile_id, actor, *, decision, vat_rate=None, names=None, note=''):
    if decision not in dict(TaxCodingDecision.DECISION_CHOICES):
        raise TaxRuleError('قرار غير معروف')
    with transaction.atomic():
        profile = TaxItemProfile.objects.select_for_update().get(pk=profile_id)
        row = TaxCodingDecision.objects.filter(profile=profile).first()
        if row is not None and row.decision:
            raise TaxRuleError(ALREADY_DECIDED)
        before = _row(row) if row is not None else None
        row = row or TaxCodingDecision(profile=profile)

        item = catalog_item(profile)
        sources = coding_rule.purchase_sources([profile.softech_itemcode]).get(profile.softech_itemcode)
        row.premark, row.premark_reason, _ = coding_rule.premark(item, sources)
        _, row.vat_flagged, _ = coding_rule.vat_prefill(item, profile)

        treatment_before = None
        if decision == TaxCodingDecision.DECISION_CODE:
            rate = _rate(vat_rate)
            if profile.treatment_confirmed_at:
                if Decimal(profile.vat_rate) != rate:
                    raise TaxRuleError(RATE_MISMATCH)
            else:
                treatment_before = _treatment(profile)
                if rate:
                    services.confirm_treatment(profile, treatment=TaxItemProfile.TREATMENT_TAXABLE, vat_rate=rate,
                                               reference='', actor=actor)
                else:
                    services.confirm_treatment(profile, treatment=TaxItemProfile.TREATMENT_EXEMPT, vat_rate=0,
                                               reference=EXEMPT_REFERENCE, actor=actor)
                profile.save()
            row.vat_rate = rate
        else:
            row.vat_rate = None

        default_name = (item.name if item is not None else '') or profile.item_name or profile.item_name_ar
        default_ar = profile.item_name_ar or default_name
        names = names or {}
        for field in NAME_FIELDS:
            limit = TaxCodingDecision._meta.get_field(field).max_length
            fallback = default_ar if field.endswith('_ar') else default_name
            row_value = str(names.get(field) or '').strip() or fallback or ''
            setattr(row, field, row_value[:limit])
        row.note = (note or '').strip()[:300]
        row.decision, row.decided_by, row.decided_at = decision, actor, timezone.now()
        row.save()

        code = profile.softech_itemcode
        services.audit('coding_decision', actor=actor, entity='item', entity_id=code, reason=row.note,
                       before=before, after=_row(row))
        if treatment_before is not None:
            services.audit('item_mapping_changed', actor=actor, entity='item', entity_id=code,
                           reason='قرار الترميز', before=treatment_before, after=_treatment(profile))
            services.revalidate_drafts_for_items({code})
    return row


def reopen(profile_id, actor, reason):
    reason = (reason or '').strip()
    if not reason:
        raise TaxRuleError('اذكر سبب إعادة الفتح')
    with transaction.atomic():
        profile = TaxItemProfile.objects.select_for_update().get(pk=profile_id)
        row = TaxCodingDecision.objects.filter(profile=profile).first()
        if row is None or not row.decision:
            raise TaxRuleError('لا يوجد قرار لإعادة فتحه')
        before = _row(row)
        row.decision, row.decided_by, row.decided_at = '', None, None
        row.reopened_by, row.reopened_at, row.reopen_reason = actor, timezone.now(), reason[:300]
        row.save()
        services.audit('coding_decision_reopened', actor=actor, entity='item', entity_id=profile.softech_itemcode,
                       reason=reason, before=before, after=_row(row))
    return row


# ── the queue: which items to decide, and deciding many at once ──────────────────────────────────

def _best_usage(usages):
    """The usage row eta_codes keeps for an item: approved/active, then submitted/pending, then the rest;
    a tie goes to the newer request."""
    return max(usages, key=lambda u: (eta_codes._rank(u.status), u.active_from or dt.date.min))


def _who(user):
    return (user.get_full_name() or user.username) if user is not None else ''


def rows(*, recent_days=None, premark=None, decided=None, q=''):
    """Items sold on ETA production receipts without a code that still have no production code, one dict each.
    A constant number of queries whatever the number of items. `premark` 'none' matches no suggestion; `decided`
    'yes' / 'no'. Unsorted: the view sorts and pages."""
    from apps.catalog.models import Item

    sales = EtaReconUncodedItem.objects.filter(system='production')
    if recent_days is not None:
        sales = sales.filter(day__gte=timezone.localdate() - dt.timedelta(days=recent_days))
    sold = {r['itemcode']: r for r in sales.values('itemcode').annotate(value=Sum('value'), docs=Sum('docs'),
                                                                        last_day=Max('day'))}
    profiles = list(TaxItemProfile.objects.filter(softech_itemcode__in=list(sold)).exclude(
        coding_status__in=(TaxItemProfile.CODE_APPROVED, TaxItemProfile.CODE_PENDING),
        coding_env__in=('', 'production')))

    usages = {}
    for u in EtaCodeUsage.objects.filter(system='production', itemcode__in=[p.softech_itemcode for p in profiles]):
        usages.setdefault(u.itemcode, []).append(u)
    best = {code: _best_usage(us) for code, us in usages.items()}
    on_eta = {code for code, us in usages.items() if any(u.status.lower() in eta_codes.ACTIVE_STATUSES for u in us)}
    profiles = [p for p in profiles if p.softech_itemcode not in on_eta]
    codes = [p.softech_itemcode for p in profiles]

    items = list(Item.objects.filter(Q(pk__in=[p.item_id for p in profiles if p.item_id]) | Q(softech_id__in=codes)))
    by_pk, by_code = {i.pk: i for i in items}, {i.softech_id: i for i in items}
    sources = coding_rule.purchase_sources(codes)
    decisions = {d.profile_id: d for d in TaxCodingDecision.objects.filter(profile__in=[p.pk for p in profiles])
                 .select_related('decided_by')}

    q = (q or '').strip().lower()
    out = []
    for p in profiles:
        code = p.softech_itemcode
        item = by_pk.get(p.item_id) if p.item_id else by_code.get(code)
        name = (item.name if item is not None else '') or p.item_name or p.item_name_ar
        if q and q not in code.lower() and q not in name.lower() and q not in p.item_name_ar.lower():
            continue
        src = sources.get(code)
        mark, reason, note = coding_rule.premark(item, src)
        if premark is not None and mark != ('' if premark == 'none' else premark):
            continue
        d = decisions.get(p.pk)
        decision = (d.decision if d is not None else '') or None
        if (decided == 'yes' and decision is None) or (decided == 'no' and decision is not None):
            continue
        rate, flagged, why = coding_rule.vat_prefill(item, p)
        sale = sold[code]
        out.append({'id': p.pk, 'itemcode': code, 'name': name, 'name_ar': p.item_name_ar,
                    'value': sale['value'] or Decimal('0'), 'docs': sale['docs'] or 0, 'last_day': sale['last_day'],
                    'premark': mark, 'premark_reason': reason, 'note': note, 'sources': dict(src or {}),
                    'vat_rate': rate, 'vat_flagged': flagged, 'vat_why': why, 'decision': decision,
                    'decided_by': _who(d.decided_by) if decision else '',
                    'decided_at': d.decided_at if decision else None,
                    'eta_last_status': best[code].status if code in best else ''})
    return out


def decide_many(itemcodes, actor, *, decision, vat_rate=None, names=None, note=''):
    """Decides each item on its own; returns (decided itemcodes, skipped [{itemcode, why}]). With more than one item
    and decision 'code', each item takes its prefilled VAT rate and a flagged rate is skipped for a person to check.
    A single item takes `vat_rate` and `names` as given, and its errors are raised, not skipped."""
    codes = list(dict.fromkeys(str(c).strip() for c in itemcodes or () if str(c).strip()))
    if not codes:
        raise TaxRuleError('اختر الأصناف')
    if len(codes) > MAX_BULK:
        raise TaxRuleError(f'{MAX_BULK} صنف على الأكثر في المرة')
    if decision not in dict(TaxCodingDecision.DECISION_CHOICES):
        raise TaxRuleError('قرار غير معروف')
    bulk = len(codes) > 1
    profiles = {p.softech_itemcode: p for p in TaxItemProfile.objects.filter(softech_itemcode__in=codes)}
    decided, skipped = [], []
    for code in codes:
        profile = profiles.get(code)
        if profile is None:
            if not bulk:
                raise TaxItemProfile.DoesNotExist(UNKNOWN_ITEM)
            skipped.append({'itemcode': code, 'why': UNKNOWN_ITEM})
            continue
        rate = vat_rate
        if bulk and decision == TaxCodingDecision.DECISION_CODE:
            rate, flagged, _ = coding_rule.vat_prefill(catalog_item(profile), profile)
            if flagged:
                skipped.append({'itemcode': code, 'why': NEEDS_RATE_CHECK})
                continue
        try:
            decide(profile.pk, actor, decision=decision, vat_rate=rate, names=None if bulk else names, note=note)
        except TaxRuleError as exc:
            if not bulk:
                raise
            skipped.append({'itemcode': code, 'why': str(exc)})
            continue
        decided.append(code)
    return decided, skipped
