"""
core/sort_ordering.py — server ordering for sortable grid headers on PAGED lists.

  NullsLastOrderingFilter — drop-in for rest_framework.filters.OrderingFilter in `filter_backends`:
      * only the fields in the view's `ordering_fields` are honoured (DRF ignores the rest);
      * when the user asked for an ordering, empty (NULL) values sort last in both directions;
      * a unique `pk` tiebreak is appended, so rows never repeat/vanish between pages.
    The view's default `ordering` (no `?ordering=`) is left exactly as it was.

  explicit_order_by(raw, allowed, default) — for views that build their own queryset order:
      `allowed` maps the public key to a model field; raises ValidationError (HTTP 400) on an unknown key.
"""
from django.db.models import F
from rest_framework import filters
from rest_framework.exceptions import ValidationError

from core.stable_ordering import _with_pk


def _expr(field, desc):
    f = F(field)
    return f.desc(nulls_last=True) if desc else f.asc(nulls_last=True)


class NullsLastOrderingFilter(filters.OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        asked = request.query_params.get(self.ordering_param)
        ordering = self.get_ordering(request, queryset, view)
        if asked and ordering:
            queryset = queryset.order_by(*[
                _expr(o.lstrip('-'), o.startswith('-')) for o in ordering])
            return queryset.order_by(*queryset.query.order_by, 'pk')
        return _with_pk(super().filter_queryset(request, queryset, view))


def staff_name_key(prefix):
    """Annotation expression mirroring StaffProfile.full_name (real name, else SOFTECH username, else login)
    for the staff FK at `prefix` (e.g. 'handled_by'), so a «المندوب» column sorts by what it shows."""
    from django.db.models import CharField, Value
    from django.db.models.functions import Coalesce, Concat, NullIf, Trim
    return Coalesce(
        NullIf(Trim(Concat(F(f'{prefix}__user__first_name'), Value(' '), F(f'{prefix}__user__last_name'),
                           output_field=CharField())), Value('')),
        NullIf(F(f'{prefix}__softech_username'), Value('')),
        F(f'{prefix}__user__username'),
        output_field=CharField())


def explicit_order_by(raw, allowed, default):
    """-> tuple of order_by() args. `raw` is the `?ordering=` value ('' = the default)."""
    raw = (raw or '').strip()
    if not raw:
        return tuple(default)
    desc = raw.startswith('-')
    key = raw.lstrip('-')
    if key not in allowed:
        raise ValidationError({'detail': 'ترتيب غير مدعوم.'})
    return (_expr(allowed[key], desc), 'pk')
