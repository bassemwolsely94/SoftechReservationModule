"""ETA production item coding queue (batch S1): the owner decides per item "code" or "keep_out".

Deciding "code" also confirms the item's VAT treatment (14 = taxable, 0 = exempt under the VAT law's exemption
table) through services.confirm_treatment, unless the accountant already confirmed one, which the decision must
then match. Every decision and reopen is audited.

Deciding "code" also records the item's GPC brick (batch S2): the one the person picks, else the item's suggestion
(gpc_learn's learned brick, else the stored AI proposal). Bulk "code" takes a suggestion only when it is learned or
a high-confidence AI one; anything else waits for a person (CLAUDE.md rule 10). A brick can be set later on a
"code" decision while no open or approved production code request exists for the item (`set_brick`, audited)."""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from . import coding_rule, eta_codes, gpc, services
from .models import (EtaCodeUsage, EtaReconUncodedItem, TaxBrickSuggestion, TaxCodeRequest, TaxCodingDecision,
                     TaxItemProfile)
from .services import TaxRuleError

ALREADY_DECIDED = 'للصنف قرار سابق — أعد فتحه أولاً'
RATE_MISMATCH = 'النسبة تخالف المعاملة الضريبية المعتمدة للصنف — عدّلها من شاشة الأصناف أولاً'
NEEDS_RATE_CHECK = 'النسبة تحتاج تأكيداً'
UNKNOWN_ITEM = 'صنف غير معروف'
NEEDS_BRICK_CHECK = 'الفئة تحتاج تأكيداً'
BRICK_REQUIRED = 'اختر فئة GPC للصنف'
BAD_BRICK = 'كود الفئة 8 أرقام'
UNKNOWN_BRICK = 'الفئة غير موجودة في قائمة GPC'
BRICK_NOT_CODE = 'الفئة تُسجَّل لصنف قراره «يُكوَّد» فقط'
BRICK_REQUESTED = 'طُلب كود الصنف من المصلحة بالفعل — لا تتغير الفئة'
PERSON = 'person'
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
            'vat_flagged': d.vat_flagged, 'brick': d.brick, 'brick_source': d.brick_source, 'note': d.note,
            **{f: getattr(d, f) for f in NAME_FIELDS},
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


ALREADY_CODED = 'الصنف مُكوَّد بالفعل — ليس في طابور الترميز'


def sheet_coded(profile):
    """Coded on the production sheet (approved/pending, not a preprod-only code)."""
    return (profile.coding_status in (TaxItemProfile.CODE_APPROVED, TaxItemProfile.CODE_PENDING)
            and profile.coding_env in ('', 'production'))


def _on_eta_production(codes):
    """(itemcodes with an approved/active ETA production usage, usages by itemcode)."""
    usages = {}
    for u in EtaCodeUsage.objects.filter(system='production', itemcode__in=list(codes)):
        usages.setdefault(u.itemcode, []).append(u)
    return {c for c, us in usages.items() if any(u.status.lower() in eta_codes.ACTIVE_STATUSES for u in us)}, usages


def suggestions(profiles):
    """{profile_id: {'code', 'source', 'confidence', 'reason', 'second'}}: the learned brick (gpc_learn), else the
    stored AI proposal with a brick. Learned sources carry no confidence. Constant queries."""
    from . import gpc_learn
    profiles = list(profiles)
    out = {pk: {'code': hit['code'], 'source': hit['source'], 'confidence': '', 'reason': hit.get('basis') or '',
                'second': ''} for pk, hit in gpc_learn.learned(profiles).items()}
    ai = (TaxBrickSuggestion.objects.filter(profile__in=[p.pk for p in profiles], source=TaxBrickSuggestion.SOURCE_AI)
          .exclude(brick='')) if profiles else ()
    for s in ai:
        out.setdefault(s.profile_id, {'code': s.brick, 'source': TaxBrickSuggestion.SOURCE_AI,
                                      'confidence': s.confidence, 'reason': s.reason, 'second': s.second})
    return out


def check_brick(brick):
    brick = str(brick or '').strip()
    if not gpc.BRICK.match(brick):
        raise TaxRuleError(BAD_BRICK)
    if not gpc.known(brick):
        raise TaxRuleError(UNKNOWN_BRICK)
    return brick


def _brick_for(brick, suggestion, *, bulk=False):
    """(brick, source) for a decision: the person's brick ('person' unless it is the suggestion), else the
    suggestion's. In bulk only a learned or high-confidence AI suggestion is taken."""
    if str(brick or '').strip():
        brick = check_brick(brick)
        return brick, suggestion['source'] if suggestion and suggestion['code'] == brick else PERSON
    if bulk and not bulk_brick_ok(suggestion):
        raise TaxRuleError(NEEDS_BRICK_CHECK)
    if not suggestion:
        raise TaxRuleError(BRICK_REQUIRED)
    return check_brick(suggestion['code']), suggestion['source']


def bulk_brick_ok(suggestion):
    """A bulk decision may take a learned brick or a high-confidence AI one; the rest wait for a person."""
    return bool(suggestion) and (suggestion['source'] != TaxBrickSuggestion.SOURCE_AI
                                 or suggestion['confidence'] == 'high')


def decide(profile_id, actor, *, decision, vat_rate=None, names=None, note='', brick=None, bulk=False):
    """One item's decision. "code" needs a brick: `brick`, else the item's suggestion (with `bulk`, only a learned
    or high-confidence AI one, checked under the item's lock)."""
    if decision not in dict(TaxCodingDecision.DECISION_CHOICES):
        raise TaxRuleError('قرار غير معروف')
    with transaction.atomic():
        profile = TaxItemProfile.objects.select_for_update().get(pk=profile_id)
        if sheet_coded(profile) or _on_eta_production([profile.softech_itemcode])[0]:
            raise TaxRuleError(ALREADY_CODED)
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
            row.brick, row.brick_source = _brick_for(brick, suggestions([profile]).get(profile.pk), bulk=bulk)
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
            row.brick, row.brick_source = '', ''

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


def set_brick(profile_id, actor, brick):
    """Sets or changes the brick of an item decided "code" (e.g. decided before bricks were recorded), without
    reopening, while no open or approved production code request exists for it (after an ETA rejection, a failed
    or a cancelled request the brick can be fixed). Audited."""
    with transaction.atomic():
        profile = TaxItemProfile.objects.select_for_update().get(pk=profile_id)
        row = TaxCodingDecision.objects.filter(profile=profile).first()
        if row is None or row.decision != TaxCodingDecision.DECISION_CODE:
            raise TaxRuleError(BRICK_NOT_CODE)
        if (TaxCodeRequest.objects.filter(profile=profile, purpose=TaxCodeRequest.PURPOSE_NEW,
                                          environment='production',
                                          status__in=(*TaxCodeRequest.OPEN_STATES, TaxCodeRequest.APPROVED))
                .exists()):
            raise TaxRuleError(BRICK_REQUESTED)
        before = _row(row)
        row.brick, row.brick_source = _brick_for(check_brick(brick), suggestions([profile]).get(profile.pk))
        row.save(update_fields=['brick', 'brick_source'])
        services.audit('coding_brick_set', actor=actor, entity='item', entity_id=profile.softech_itemcode,
                       reason='فئة GPC', before=before, after=_row(row))
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


def candidates(*, recent_days=None):
    """The queue's items: (sold {itemcode: {'value', 'docs', 'last_day'}}, profiles, best ETA usage by itemcode) for
    items sold on ETA production receipts without a code that still have no production code. Constant queries."""
    sales = EtaReconUncodedItem.objects.filter(system='production')
    if recent_days is not None:
        sales = sales.filter(day__gte=timezone.localdate() - dt.timedelta(days=recent_days))
    sold = {r['itemcode']: r for r in sales.values('itemcode').annotate(value=Sum('value'), docs=Sum('docs'),
                                                                        last_day=Max('day'))}
    profiles = [p for p in TaxItemProfile.objects.filter(softech_itemcode__in=list(sold)) if not sheet_coded(p)]

    on_eta, usages = _on_eta_production(p.softech_itemcode for p in profiles)
    best = {code: _best_usage(us) for code, us in usages.items()}
    return sold, [p for p in profiles if p.softech_itemcode not in on_eta], best


def rows(*, recent_days=None, premark=None, decided=None, q=''):
    """Items sold on ETA production receipts without a code that still have no production code, one dict each.
    A constant number of queries whatever the number of items. `premark` 'none' matches no suggestion; `decided`
    'yes' / 'no'. Unsorted: the view sorts and pages."""
    from apps.catalog.models import Item

    sold, profiles, best = candidates(recent_days=recent_days)
    codes = [p.softech_itemcode for p in profiles]

    items = list(Item.objects.filter(Q(pk__in=[p.item_id for p in profiles if p.item_id]) | Q(softech_id__in=codes)))
    by_pk, by_code = {i.pk: i for i in items}, {i.softech_id: i for i in items}
    sources = coding_rule.purchase_sources(codes)
    decisions = {d.profile_id: d for d in TaxCodingDecision.objects.filter(profile__in=[p.pk for p in profiles])
                 .select_related('decided_by')}
    suggested = suggestions(profiles)
    brick_names = gpc.names({s['code'] for s in suggested.values()} | {s['second'] for s in suggested.values()}
                            | {d.brick for d in decisions.values()}
                            | {p.gpc_code for p in profiles if gpc.BRICK.match(p.gpc_code or '')})

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
        s = suggested.get(p.pk) or {}
        if decision == TaxCodingDecision.DECISION_CODE and d.brick:     # the confirmed brick, not a suggestion
            brick, brick_source = d.brick, d.brick_source
            if s.get('code') != brick:
                s = {}
        else:
            brick, brick_source = s.get('code', ''), s.get('source', '')
        own = p.gpc_code if gpc.BRICK.match(p.gpc_code or '') and p.gpc_code != brick else ''
        out.append({'id': p.pk, 'itemcode': code, 'name': name, 'name_ar': p.item_name_ar,
                    'value': sale['value'] or Decimal('0'), 'docs': sale['docs'] or 0, 'last_day': sale['last_day'],
                    'premark': mark, 'premark_reason': reason, 'note': note, 'sources': dict(src or {}),
                    'vat_rate': rate, 'vat_flagged': flagged, 'vat_why': why, 'decision': decision,
                    'decided_by': _who(d.decided_by) if decision else '',
                    'decided_at': d.decided_at if decision else None,
                    'brick': brick, 'brick_name': brick_names.get(brick, ''), 'brick_source': brick_source,
                    'brick_confidence': s.get('confidence', ''), 'brick_reason': s.get('reason', ''),
                    'brick_second': s.get('second', ''), 'brick_second_name': brick_names.get(s.get('second'), ''),
                    'own_brick': own, 'own_brick_name': brick_names.get(own, ''),
                    'brick_confirmed': bool(d is not None and d.decision and d.brick),
                    'eta_last_status': best[code].status if code in best else ''})
    return out


def decide_many(itemcodes, actor, *, decision, vat_rate=None, names=None, note='', brick=None):
    """Decides each item on its own; returns (decided itemcodes, skipped [{itemcode, why}]). With more than one item
    and decision 'code', each item takes its prefilled VAT rate and its suggested brick: a flagged rate, or a brick
    that is missing or only a medium/low-confidence AI proposal, is skipped for a person to check.
    A single item takes `vat_rate`, `names` and `brick` as given, and its errors are raised, not skipped."""
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
            decide(profile.pk, actor, decision=decision, vat_rate=rate, names=None if bulk else names, note=note,
                   brick=None if bulk else brick, bulk=bulk)
        except TaxRuleError as exc:
            if not bulk:
                raise
            skipped.append({'itemcode': code, 'why': str(exc)})
            continue
        decided.append(code)
    return decided, skipped
