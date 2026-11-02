"""
customers/access.py — who may find, read, edit a customer and see their phone numbers
(owner decision B-2, 2026-10-30; security Batch 5).

A customer can buy at any branch, so serving one must never depend on where they registered —
but the customer base must not leak out of a branch:

  • find   — a branch user browses and name-searches their OWN branches' customers (home branch =
             `preferred_branch`, set by the SOFTECH sync; a branch-less record they created counts
             as theirs). Any other customer is found only by their FULL phone number
             (MIN_PHONE_DIGITS+ digits). `can_see_all_customers` widens name search to every branch.
  • read   — a found customer opens (POS summary, repeat order, receipt …) whatever their branch.
  • phones — another branch's customer's numbers are masked (last 3 digits) — so a list, a
             print or a screenshot holds no usable numbers. `can_see_customer_phone = False`
             masks every number for that user.
  • edit   — own branches only; the all-branch roles (call center, supervisor, HQ) edit anyone.

All-branch users (core.branch_scope) are unrestricted, apart from a restricted branch.
"""
import re

from django.db.models import Q

from core import branch_scope

MIN_PHONE_DIGITS = 10          # Egyptian mobile = 11 digits, landline with area code = 10
PHONE_FIELDS = ('phone', 'phone_alt', 'whatsapp_phone')
_NON_DIGIT = re.compile(r'\D+')


def digits(s):
    return _NON_DIGIT.sub('', s or '')


def _profile(user):
    return getattr(user, 'staff_profile', None)


def own_q(user):
    """None = every customer; otherwise the Q of the user's own customers."""
    ids = branch_scope.branch_ids(user)
    if ids is None:
        return None
    q = Q(preferred_branch_id__in=ids)
    profile = _profile(user)
    if profile is not None:
        q |= Q(preferred_branch__isnull=True, created_by=profile)
    return q


def full_phone_q(raw):
    d = digits(raw)
    if len(d) < MIN_PHONE_DIGITS:
        return None
    return Q(phone__icontains=d) | Q(phone_alt__icontains=d) | Q(whatsapp_phone__icontains=d)


def findable_q(user, raw=''):
    """What a lookup for `raw` may return: own customers, any customer whose full phone was typed,
    and — with can_see_all_customers and a search term — every customer. None = no limit."""
    own = own_q(user)
    if own is None:
        return None
    profile = _profile(user)
    if raw and profile is not None and profile.can_see_all_customers:
        return None
    phone = full_phone_q(raw)
    return own | phone if phone is not None else own


def is_own(user, customer):
    ids = branch_scope.branch_ids(user)
    if ids is None:
        return True
    if customer.preferred_branch_id is not None:
        return customer.preferred_branch_id in ids
    profile = _profile(user)
    return profile is not None and customer.created_by_id == profile.pk


def can_edit(user, customer):
    return is_own(user, customer)


def phones_visible(user, customer):
    profile = _profile(user)
    if profile is not None and not profile.can_see_customer_phone:
        return False
    return is_own(user, customer)


def mask(value):
    d = digits(value)
    if not d:
        return value
    return '•' * max(len(d) - 3, 3) + d[-3:]


def mask_dict(user, customer, data):
    """Mask the phone fields of one serialized customer row in place (when the user may not see them)."""
    if not phones_visible(user, customer):
        for f in PHONE_FIELDS:
            if data.get(f):
                data[f] = mask(data[f])
    return data


# ── Batch 5b: numbers outside the customers screens (docs/security/PHONE_MASKING_PLAN.md) ──────

def record_phones_visible(user):
    """A number needed to SERVE a record the user can already see (their branch's reservation,
    delivery order, follow-up, call…) — owner decision D2: shown, whatever the customer's home
    branch. Masked for `can_see_customer_phone = False` (D3) and for the read-only viewer role
    (D4 / D7)."""
    profile = _profile(user)
    if profile is None:
        return bool(getattr(user, 'is_superuser', False))
    return bool(profile.can_see_customer_phone and profile.role != 'viewer')


def record_phone(user, value):
    return value if record_phones_visible(user) else mask(value)


def customer_phone(user, customer, value):
    """A number shown because of WHO the customer is (lookups, profiles, analytics lists): the
    B-2 rule — own customers only, masked otherwise."""
    if customer is None:
        return value if branch_scope.branch_ids(user) is None and record_phones_visible(user) else mask(value)
    return value if phones_visible(user, customer) else mask(value)


def mask_fields(data, fields, visible, links=()):
    """Mask `fields` of a dict in place when not `visible`; drop wa.me / tel links (D3) — they
    carry the number."""
    if visible:
        return data
    for f in fields:
        if data.get(f):
            data[f] = mask(data[f])
    for f in links:
        if f in data:
            data[f] = None
    return data


PAYLOAD_PHONE_KEYS = frozenset({'phone', 'phone_alt', 'whatsapp_phone', 'customer_phone',
                                'customer_phone_alt', 'contact_phone', 'delivery_phone',
                                'lead_phone', 'phone_number', 'caller_number', 'mobileno'})
PAYLOAD_LINK_KEYS = frozenset({'whatsapp_url', 'whatsapp_url_with_message', 'whatsapp_url_plain',
                               'tel_url'})


def mask_payload(data, visible):
    """Function views that build nested dicts: mask every known phone key, drop wa.me / tel
    links. Returns `data` (changed in place)."""
    if visible:
        return data
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if k in PAYLOAD_PHONE_KEYS and isinstance(v, str) and v:
                data[k] = mask(v)
            elif k in PAYLOAD_LINK_KEYS:
                data[k] = None
            else:
                mask_payload(v, visible)
    elif isinstance(data, list):
        for v in data:
            mask_payload(v, visible)
    return data
