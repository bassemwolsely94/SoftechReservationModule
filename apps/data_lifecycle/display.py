"""Tell a screen that retention removed a file, so it shows a calm note instead of a broken image.

`RetentionNoteMixin` adds `retention_removed: {field: 'YYYY-MM-DD'}` to a serializer. The key is present only when
at least one of `retention_fields` is empty AND a held file (not restored) says retention moved it; otherwise it is
left out (frontends treat missing and empty alike). A field that never had a file reports nothing.

A file staff deleted or replaced (holding.STAFF_RULE_KEYS) is not retention's doing, so it shows no note.

A list serializer (many=True) makes ONE lookup for the whole page, and only when some row has an empty field. That
lives on a ListSerializer subclass, not a patched instance: DRF re-creates a nested `many=True` field for each parent
serializer from its class and arguments, so a patch on the instance would be lost and every row would query.
"""
from django.db.models.manager import BaseManager
from django.utils import timezone
from rest_framework.serializers import LIST_SERIALIZER_KWARGS, LIST_SERIALIZER_KWARGS_REMOVE, ListSerializer

from .holding import STAFF_RULE_KEYS
from .models import HeldFile


def removed_dates(instances, fields):
    """{(pk string, field): 'YYYY-MM-DD'} for the empty `fields` of `instances` that retention removed.
    One query, none when nothing is empty. The newest unrestored held file wins."""
    wanted = {}
    for obj in instances:
        empty = [f for f in fields if not getattr(obj, f, None)]
        if empty:
            wanted.setdefault(obj._meta.label, {}).setdefault('pks', set()).add(str(obj.pk))
            wanted[obj._meta.label].setdefault('fields', set()).update(empty)
    out = {}
    for label, w in wanted.items():
        rows = (HeldFile.objects.filter(primary_model=label, primary_pk__in=w['pks'],
                                        primary_field__in=w['fields'], restored_at__isnull=True)
                .exclude(rule_key__in=STAFF_RULE_KEYS)
                .order_by('moved_at').values_list('primary_pk', 'primary_field', 'moved_at'))
        for pk, field, moved_at in rows:       # oldest first, so the newest overwrites
            out[(label, pk, field)] = timezone.localtime(moved_at).date().isoformat()
    return out


class RetentionListSerializer(ListSerializer):
    """The page's removed dates in one lookup, handed to the child for the length of this call."""

    def to_representation(self, data):
        items = list(data.all() if isinstance(data, BaseManager) else data)
        self.child._retention_cache = removed_dates(items, self.child.retention_fields)
        try:
            return super().to_representation(items)
        finally:
            self.child._retention_cache = None


class RetentionNoteMixin:
    retention_fields = ()

    @classmethod
    def many_init(cls, *args, **kwargs):
        """DRF's many_init with RetentionListSerializer as the list class. DRF re-creates a nested list from its
        class and arguments, so the one-lookup behaviour survives where an instance patch would not."""
        list_kwargs = {}
        for key in LIST_SERIALIZER_KWARGS_REMOVE:
            value = kwargs.pop(key, None)
            if value is not None:
                list_kwargs[key] = value
        list_kwargs['child'] = cls(*args, **kwargs)
        list_kwargs.update({key: value for key, value in kwargs.items() if key in LIST_SERIALIZER_KWARGS})
        return RetentionListSerializer(*args, **list_kwargs)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        cache = getattr(self, '_retention_cache', None)
        if cache is None:       # a single object, or a nested one outside a list
            cache = removed_dates([instance], self.retention_fields)
        label, pk = instance._meta.label, str(instance.pk)
        removed = {f: cache[(label, pk, f)] for f in self.retention_fields if (label, pk, f) in cache}
        if removed:
            data['retention_removed'] = removed
        return data
