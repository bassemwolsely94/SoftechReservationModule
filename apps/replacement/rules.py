"""
apps/replacement/rules.py — rule resolution + the authoritative entitlement calculation
(doc 25 §9/§12). Pure-ish: reads rules and catalog prices, never SOFTECH. React only shows the
result of `calculate`; it never computes money.

    eligible public value = Σ public_price × qty
    entitlement           = eligible × (1 − deduction %)  → rounded DOWN by the rule's rounding
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import ReplacementCalculation as Calc, ReplacementCase as RC, ReplacementRule as Rule

CENT = Decimal('0.01')
ROUND_STEP = {Rule.ROUND_NONE: None, Rule.ROUND_1: Decimal('1'), Rule.ROUND_5: Decimal('5'),
              Rule.ROUND_10: Decimal('10'), Rule.ROUND_50: Decimal('50')}


def resolve_rule(case: RC, mode: str, on_date=None) -> Rule:
    """Most specific active rule for (source, mode, shortage flag, contract, branch, date).
    Specificity: shortage-only > contract-specific > branch-specific > generic; then priority;
    then the latest version of that rule_key."""
    on_date = on_date or timezone.localdate()
    mode = 'products' if mode in ('products', 'mixed') else 'cash'      # D9: mixed = one purchase at product rule
    qs = (Rule.objects.filter(is_active=True, source_type=case.source_type, settlement_mode=mode,
                              effective_from__lte=on_date)
          .filter(Q(effective_until__isnull=True) | Q(effective_until__gte=on_date))
          .filter(Q(contract_personcode='') | Q(contract_personcode=case.contract_personcode or ''))
          .filter(Q(branchcode='') | Q(branchcode=case.branchcode or '')))
    if not case.is_shortage_item:
        qs = qs.filter(shortage_only=False)
    rules = list(qs)
    if not rules:
        raise ValidationError('لا توجد قاعدة خصم سارية لهذا النوع / طريقة الصرف — راجع إعدادات القواعد.')

    def key(r):
        return (0 if r.shortage_only and case.is_shortage_item else 1,
                0 if r.contract_personcode else 1, 0 if r.branchcode else 1, r.priority, -r.version)
    return sorted(rules, key=key)[0]


def _round(v: Decimal, rounding: str) -> Decimal:
    step = ROUND_STEP.get(rounding)
    v = v.quantize(CENT, rounding=ROUND_DOWN)
    if not step:
        return v
    return (v / step).to_integral_value(rounding=ROUND_DOWN) * step


MIL = Decimal('0.001')


def compute(lines: list[dict], deduction_pct: Decimal, rounding: str) -> dict:
    """lines: [{itemcode, name, qty, public_price}] → per-line + totals (pure, deterministic).

    Built PER UNIT so the result is exactly postable: the purchase writer posts
    unit_price (3 dp) × qty, so unit_net = ⌊public × (1 − pct)⌋₃dp and line = round(unit × qty, 2).
    The rule's rounding (always DOWN, in the pharmacy's favour) is absorbed by lowering the
    largest line's unit price; the returned entitlement is what the purchase will carry."""
    pct = Decimal(str(deduction_pct))
    out, pub_total = [], Decimal('0')
    for l in lines:
        qty, price = Decimal(str(l['qty'])), Decimal(str(l['public_price']))
        unit = (price * (Decimal('1') - pct / 100)).quantize(MIL, rounding=ROUND_DOWN)
        eligible = (price * qty).quantize(CENT)
        pub_total += eligible
        out.append({**{k: str(v) for k, v in l.items()}, 'eligible': eligible, 'deduction_pct': pct,
                    'unit_net': unit, 'entitlement': (unit * qty).quantize(CENT)})
    raw = sum((l['entitlement'] for l in out), Decimal('0'))
    target = _round(raw, rounding)
    if out and target < raw:
        big = max(out, key=lambda l: l['entitlement'])
        qty = Decimal(str(big['qty']))
        big['unit_net'] = ((big['entitlement'] - (raw - target)) / qty).quantize(MIL, rounding=ROUND_DOWN)
        big['entitlement'] = (big['unit_net'] * qty).quantize(CENT)
    ent = sum((l['entitlement'] for l in out), Decimal('0'))
    for l in out:
        for k in ('eligible', 'deduction_pct', 'unit_net', 'entitlement'):
            l[k] = str(l[k])
    return {'lines': out, 'public_value': pub_total, 'entitlement_raw': raw,
            'rounding_adj': ent - raw, 'entitlement': ent}


def fingerprint(case: RC, rule: Rule, applied_pct, lines) -> str:
    payload = json.dumps({'case': case.pk, 'rule': [rule.rule_key, rule.version], 'pct': str(applied_pct),
                          'mode': case.settlement_mode, 'lines': lines}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def calculate(case: RC, *, user, override_pct=None, override_reason='') -> Calc:
    """Create a new immutable calculation snapshot for the case's current items."""
    items = list(case.items.filter(disposition__in=['selected_for_replacement', 'partially_replaced']))
    if not items:
        raise ValidationError('اختر صنفاً واحداً على الأقل للاستبدال.')
    rule = resolve_rule(case, case.settlement_mode)
    applied = Decimal(str(rule.deduction_pct))
    if override_pct is not None and Decimal(str(override_pct)) != applied:
        applied = Decimal(str(override_pct))
        if not (Decimal('0') <= applied < Decimal('100')):
            raise ValidationError('نسبة خصم غير صالحة.')
        if not (override_reason or '').strip():
            raise ValidationError('تغيير نسبة الخصم يتطلب سبباً.')
        lowered = Decimal(str(rule.deduction_pct)) - applied            # >0 ⇒ patient-favourable
        if lowered > 0:
            from .authz import max_override_pp
            allowed = max_override_pp(user)
            if lowered > allowed:
                raise ValidationError(f'غير مسموح لك بتخفيض الخصم أكثر من {allowed} نقطة.')
    lines = [{'itemcode': i.itemcode, 'name': i.item_name, 'qty': i.qty_replaced,
              'public_price': i.public_unit_price} for i in items]
    res = compute(lines, applied, rule.rounding)
    seq = (case.calculations.order_by('-seq').values_list('seq', flat=True).first() or 0) + 1
    return Calc.objects.create(
        case=case, seq=seq, rule=rule, rule_deduction_pct=rule.deduction_pct, applied_deduction_pct=applied,
        override_reason=(override_reason or '')[:300], lines=res['lines'], public_value=res['public_value'],
        entitlement_raw=res['entitlement_raw'], rounding_adj=res['rounding_adj'],
        entitlement=res['entitlement'], fingerprint=fingerprint(case, rule, applied, res['lines']),
        created_by=user)
