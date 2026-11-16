"""ETA production item coding queue (batch S1): the owner decides per item "code" or "keep_out".

Deciding "code" also confirms the item's VAT treatment (14 = taxable, 0 = exempt under the VAT law's exemption
table) through services.confirm_treatment, unless the accountant already confirmed one, which the decision must
then match. Every decision and reopen is audited."""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import coding_rule, services
from .models import TaxCodingDecision, TaxItemProfile
from .services import TaxRuleError

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
            raise TaxRuleError('للصنف قرار سابق — أعد فتحه أولاً')
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
                    raise TaxRuleError('النسبة تخالف المعاملة المعتمدة من المحاسب')
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
        names = names or {}
        for field in NAME_FIELDS:
            limit = TaxCodingDecision._meta.get_field(field).max_length
            row_value = (names.get(field) or '').strip() or default_name or ''
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
