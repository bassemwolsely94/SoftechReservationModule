"""
core/stable_ordering.py — unique tiebreak for paged DRF lists that accept `?ordering=`.

Sorting a paged list by a low-cardinality column (status, level, category...) leaves ties in an undefined
order, so rows can repeat or vanish between pages. Both helpers append the primary key after whatever
ordering was requested (or the queryset / model default).

  StableOrderingFilter  — drop-in for rest_framework.filters.OrderingFilter in `filter_backends`
  StableOrderingMixin   — for views that keep the default filter backends (OrderingFilter is a default backend)
"""
from rest_framework import filters


def _with_pk(qs):
    order = list(qs.query.order_by) or list(qs.model._meta.ordering)
    if any(str(o).lstrip('-') in ('pk', 'id') for o in order):
        return qs
    return qs.order_by(*order, 'pk')


class StableOrderingFilter(filters.OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        return _with_pk(super().filter_queryset(request, queryset, view))


class StableOrderingMixin:
    def filter_queryset(self, queryset):
        return _with_pk(super().filter_queryset(queryset))
