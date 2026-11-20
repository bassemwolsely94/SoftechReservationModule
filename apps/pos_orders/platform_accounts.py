"""
apps/pos_orders/platform_accounts.py — sales on a marketplace platform's own SOFTECH account (doc 38).

Owner 2026-11-18: every platform order posts to the platform's account (classed «عميل دائم», channel
'permanent') and is 100% آجل — the platform holds the money, so nothing enters the drawer and the whole
amount stays on the platform's balance until it pays. A «عميل دائم» sale otherwise defaults to cash, so the
writer and the validator ask this module whether the sale's account is a platform account.

The account list is MarketplaceChannel.softech_personcode (any platform, active or not). Looked up through
the app registry so pos_orders does not import the marketplace app.
"""
import re

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist

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


_SAFE_NUMBER = re.compile(r'[^A-Za-z0-9._/-]')
_PRINTABLE = re.compile(r'[^\w .#()/-]')   # letters (Arabic too), digits, spaces, a few marks
COMMENT_MAX = 100   # stktransm5.comments / stktransm.comments are varchar(100) (checked branch 130, 2026-11-20)


def platform_comment(order):
    """«<platform> #<platform order no.>» for the SOFTECH header `comments`, so accounts can match the sale to
    the platform's statement (owner OK 2026-11-20). None for any order that did not come from a platform —
    those keep native's empty comments. Only the platform's own order number: no customer name or phone."""
    try:
        ext = order.marketplace_order
    except (ObjectDoesNotExist, AttributeError):
        return None
    if ext is None or not is_platform_order(order):
        return None
    # the order number comes from the platform (untrusted): keep plain characters only. The writer also
    # quote-escapes every literal; this keeps control characters / odd symbols out of SOFTECH's column.
    number = _SAFE_NUMBER.sub('', str(ext.external_id or ''))[:40]
    name = ' '.join(_PRINTABLE.sub(' ', str(ext.channel.name or '')).split())[:40]
    if not number:
        return None
    return f'{name} #{number}'.strip()[:COMMENT_MAX]
