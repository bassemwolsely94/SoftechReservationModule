"""
apps/rider_payouts/rule.py — the rider payout rule (C22 / P-48). Deterministic, Decimal, no guessing.

    ride amount   = flat fee × deliveries on the ride
                  + per-km fee × ride distance (km)        — only when the distance is known
    day top-up    = max(0, daily minimum − the rider's ride amounts that day)
                    — only for the vehicle types in the minimum list, only on days with a ride
    period total  = Σ ride amounts + Σ day top-ups + Σ adjustments (extras / deductions, each with a reason)

Every number comes from a SystemSetting (/settings → التوصيل):

    delivery_driver_fee_base          flat fee per delivery (ج.م)        — the existing setting
    delivery_driver_fee_per_km        per-km fee (ج.م)                    — the existing setting
    delivery_payout_daily_minimum     daily minimum (ج.م), 0 = off        — new (C22)
    delivery_payout_minimum_vehicles  vehicle types the minimum covers    — new (C22), comma list

A missing, blank, negative or unreadable value falls back to the safe default below — a flat fee of
10 per delivery, nothing per km, no minimum — and `fallbacks` names the keys that fell back, so the
screen can say so. Unknown input (no distance) pays the plain flat fee. Money is rounded to the
piaster, half up, once per ride and once per day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal('0.01')
ZERO = Decimal('0.00')

FLAT_KEY = 'delivery_driver_fee_base'
PER_KM_KEY = 'delivery_driver_fee_per_km'
MINIMUM_KEY = 'delivery_payout_daily_minimum'
MINIMUM_VEHICLES_KEY = 'delivery_payout_minimum_vehicles'

DEFAULT_FLAT = Decimal('10.00')       # owner, P-48 Batch 4: 10 EGP per fee unit
DEFAULT_PER_KM = ZERO                 # unknown until the owner confirms (owner question)
DEFAULT_MINIMUM = ZERO                # off until the owner confirms the 50 EGP/day (owner question)
DEFAULT_MINIMUM_VEHICLES = ('motorcycle',)


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PayoutRule:
    flat_fee: Decimal = DEFAULT_FLAT
    per_km: Decimal = DEFAULT_PER_KM
    daily_minimum: Decimal = DEFAULT_MINIMUM
    minimum_vehicles: tuple = DEFAULT_MINIMUM_VEHICLES
    fallbacks: tuple = field(default=())

    def snapshot(self) -> dict:
        """What a period stores: the numbers it was calculated with."""
        return {'flat_fee': str(self.flat_fee), 'per_km': str(self.per_km),
                'daily_minimum': str(self.daily_minimum), 'minimum_vehicles': list(self.minimum_vehicles),
                'fallbacks': list(self.fallbacks)}

    # ── the rule ─────────────────────────────────────────────────────────────
    def ride_amounts(self, deliveries: int, distance_km) -> tuple[Decimal, Decimal, Decimal]:
        """(flat part, distance part, ride amount) for one ride."""
        n = max(int(deliveries or 0), 0)
        flat = money(self.flat_fee * n)
        if distance_km is None or self.per_km <= 0:
            km = ZERO
        else:
            km = money(self.per_km * Decimal(str(distance_km)))
        return flat, km, flat + km

    def day_topup(self, vehicle_type: str, day_total: Decimal) -> Decimal:
        """The top-up that lifts one rider-day to the daily minimum (0 when not covered)."""
        if self.daily_minimum <= 0 or (vehicle_type or '') not in self.minimum_vehicles:
            return ZERO
        return max(ZERO, money(self.daily_minimum - day_total))


def _decimal_setting(raw, default: Decimal) -> tuple[Decimal, bool]:
    """(value, fell_back)."""
    text = str(raw if raw is not None else '').strip()
    if not text:
        return default, True
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return default, True
    if not value.is_finite() or value < 0:
        return default, True
    return money(value), False


def current_rule() -> PayoutRule:
    """The rule as the settings say right now."""
    from apps.config.services import get_setting

    fallbacks = []
    flat, fb = _decimal_setting(get_setting(FLAT_KEY, default=''), DEFAULT_FLAT)
    if fb:
        fallbacks.append(FLAT_KEY)
    per_km, fb = _decimal_setting(get_setting(PER_KM_KEY, default=''), DEFAULT_PER_KM)
    if fb:
        fallbacks.append(PER_KM_KEY)
    minimum, fb = _decimal_setting(get_setting(MINIMUM_KEY, default=''), DEFAULT_MINIMUM)
    if fb:
        fallbacks.append(MINIMUM_KEY)
    raw = str(get_setting(MINIMUM_VEHICLES_KEY, default='') or '').strip()
    if raw:
        vehicles = tuple(v.strip() for v in raw.split(',') if v.strip())
    else:
        vehicles = DEFAULT_MINIMUM_VEHICLES
        fallbacks.append(MINIMUM_VEHICLES_KEY)
    return PayoutRule(flat_fee=flat, per_km=per_km, daily_minimum=minimum, minimum_vehicles=vehicles,
                      fallbacks=tuple(fallbacks))
