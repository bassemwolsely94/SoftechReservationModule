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
