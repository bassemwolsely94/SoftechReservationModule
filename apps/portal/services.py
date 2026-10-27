"""
apps/portal/services.py

Customer lookup + magic-link delivery for the self-service portal.
"""
import logging
import urllib.parse

from django.conf import settings
from django.db.models import Q

from apps.customers.models import Customer

logger = logging.getLogger('elrezeiky.portal')


def _core_digits(phone: str) -> str:
    """
    Reduce a phone string to its national significant digits for matching.

    Strips spaces/dashes/+, the Egypt country code (20 / 0020) and a leading 0,
    returning the last 10 digits (e.g. '+20 100-123-4567' → '1001234567').
    """
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits.startswith('0020'):
        digits = digits[4:]
    elif digits.startswith('20') and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith('0'):
        digits = digits[1:]
    return digits[-10:]


def find_customer_by_phone(phone: str) -> Customer | None:
    """
    Resolve a Customer by any of its phone fields, tolerant of formatting and
    the Egypt country-code / leading-zero variations. Returns None if not found
    (callers must NOT leak this to the client).
    """
    core = _core_digits(phone)
    if len(core) < 8:
        return None
    qs = Customer.objects.filter(
        Q(phone__endswith=core)
        | Q(phone_alt__endswith=core)
        | Q(whatsapp_phone__endswith=core)
    ).exclude(softech_pic__isnull=True).exclude(softech_pic='')
    # Prefer a non-guest, fully-synced customer if several share a number.
    return qs.order_by('is_guest', 'id').first()


def send_magic_link(customer: Customer, token: str) -> bool:
    """
    Send the magic-link to the customer's WhatsApp. Returns True on success.

    Never raises to the caller — delivery failures must not change the response
    (which is always 200, regardless of whether the account exists).
    """
    base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
    link = f'{base}/portal/auth/{token}'
    wa_phone = (customer.whatsapp_phone or customer.phone or '').strip()
    if not wa_phone:
        logger.warning('portal magic-link: no phone for customer %s', customer.pk)
        return False

    body = (
        f'مرحباً {customer.name.split()[0] if customer.name else ""}،\n'
        f'رابط الدخول لحسابك في صيدليات الرزيقي (صالح ١٥ دقيقة):\n{link}\n\n'
        f'لا تشارك هذا الرابط مع أحد.'
    )
    try:
        from apps.whatsapp.sender import WhatsAppSender
        WhatsAppSender().send_text(wa_id=wa_phone, body=body, preview_url=False)
        return True
    except Exception as exc:  # noqa: BLE001 — delivery must not break the flow
        logger.warning('portal magic-link send failed for %s: %s', customer.pk, exc)
        return False


def whatsapp_share_url(phone: str, message: str) -> str | None:
    """Build a wa.me click-to-chat URL (used as a fallback in dev/non-configured envs)."""
    core = _core_digits(phone)
    if not core:
        return None
    return f'https://wa.me/20{core}?text={urllib.parse.quote(message)}'
