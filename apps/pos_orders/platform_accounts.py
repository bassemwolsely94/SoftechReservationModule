"""
apps/pos_orders/platform_accounts.py — sales on a marketplace platform's own SOFTECH account (doc 38).

Owner 2026-11-18: every platform order posts to the platform's account (classed «عميل دائم», channel
'permanent') and is 100% آجل — the platform holds the money, so nothing enters the drawer and the whole
amount stays on the platform's balance until it pays. A «عميل دائم» sale otherwise defaults to cash, so the
writer and the validator ask this module whether the sale's account is a platform account.

The account list is MarketplaceChannel.softech_personcode (any platform, active or not). Looked up through
the app registry so pos_orders does not import the marketplace app.
"""
from django.apps import apps

from .models import CLAIM_CHANNELS

CREDIT_ONLY_MSG = 'حساب منصة بيع: طلبات المنصات تُسجَّل آجلًا بالكامل — لا يُقبل سداد نقدي أو بطاقة.'


def is_platform_account(personcode) -> bool:
    code = (personcode or '').strip()
    if not code:
        return False
    Channel = apps.get_model('marketplace', 'MarketplaceChannel')
    return Channel.objects.filter(softech_personcode=code).exists()


def is_platform_order(order) -> bool:
    """A named-account sale/return whose account belongs to a marketplace platform."""
    return order.channel in CLAIM_CHANNELS and is_platform_account(order.cust_branch_code)
