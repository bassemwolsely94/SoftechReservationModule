"""
core/sort_rank.py — annotation helpers so a sortable header orders by what the column SHOWS.

  choice_rank(field, choices)  — position of a choice in the model's STATUS_CHOICES-style list
      (lifecycle order, not the alphabetical order of the stored code). Unknown values sort after all.
  text_or(*fields)             — first non-empty text among the fields (e.g. customer name, else contact name);
      NULL when all are empty, so the nulls-last ordering puts blanks at the end.

Used with core.sort_ordering.NullsLastOrderingFilter (annotate in get_queryset, list the annotation in
`ordering_fields`).
"""
from django.db.models import Case, CharField, F, IntegerField, Value, When
from django.db.models.functions import Coalesce, NullIf


def choice_rank(field, choices):
    keys = [c[0] if isinstance(c, (list, tuple)) else c for c in choices]
    return Case(*[When(**{field: k}, then=Value(i)) for i, k in enumerate(keys)],
                default=Value(len(keys)), output_field=IntegerField())


def text_or(*fields):
    return Coalesce(*[NullIf(F(f), Value('')) for f in fields], output_field=CharField())


def branch_label(prefix=''):
    """Branch shown name: name_ar, else name — for the branch FK at `prefix` (e.g. 'requesting_branch')."""
    p = f'{prefix}__' if prefix else ''
    return text_or(f'{p}name_ar', f'{p}name')


def label_sort(field, choices):
    """The choice's display label (what the column shows) as sortable text."""
    return Case(*[When(**{field: k}, then=Value(str(lbl))) for k, lbl in choices],
                default=F(field), output_field=CharField())
