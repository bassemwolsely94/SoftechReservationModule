"""
customers/phone_mask.py — serializer mixins that apply the phone rules (customers/access.py) to
records outside the customers screens (Batch 5b, docs/security/PHONE_MASKING_PLAN.md).

  RecordPhoneMask    a number needed to serve a record the user can already see (D2): shown,
                     except for can_see_customer_phone = False (D3) and the viewer role (D4 / D7).
                     wa.me / tel links are dropped with the number.
  CustomerPhoneMask  a number shown because of who the customer is: the B-2 own-customer rule.

Without a request in the serializer context (internal use: exports, pushes) nothing is changed —
the callers that send data out apply the rule themselves.
"""
from . import access


def _user(serializer):
    request = serializer.context.get('request')
    return getattr(request, 'user', None)


class RecordPhoneMask:
    phone_mask_fields = ()
    phone_mask_links = ()

    def phones_visible_for(self, user, instance):
        return access.record_phones_visible(user)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = _user(self)
        if user is None:
            return data
        return access.mask_fields(data, self.phone_mask_fields,
                                  self.phones_visible_for(user, instance), self.phone_mask_links)


class CustomerPhoneMask(RecordPhoneMask):
    phone_customer_attr = 'customer'

    def phones_visible_for(self, user, instance):
        customer = getattr(instance, self.phone_customer_attr, None)
        if customer is None:
            return access.record_phones_visible(user) and access.branch_scope.branch_ids(user) is None
        return access.phones_visible(user, customer)
