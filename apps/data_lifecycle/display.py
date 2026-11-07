"""Tell a screen that retention removed a file, so it shows a calm note instead of a broken image.

`RetentionNoteMixin` adds `retention_removed: {field: 'YYYY-MM-DD'}` to a serializer. The key is present only when
at least one of `retention_fields` is empty AND a held file (not restored) says retention moved it; otherwise it is
left out (frontends treat missing and empty alike). A field that never had a file reports nothing.

A list serializer (many=True) makes ONE lookup for the whole page, and only when some row has an empty field.
"""
from django.db.models import Manager
from django.utils import timezone

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
                .order_by('moved_at').values_list('primary_pk', 'primary_field', 'moved_at'))
        for pk, field, moved_at in rows:       # oldest first, so the newest overwrites
            out[(label, pk, field)] = timezone.localtime(moved_at).date().isoformat()
    return out


class RetentionNoteMixin:
    retention_fields = ()

    @classmethod
    def many_init(cls, *args, **kwargs):
        listing = super().many_init(*args, **kwargs)
        child, plain = listing.child, listing.to_representation

        def to_representation(data):
            items = list(data.all() if isinstance(data, Manager) else data)
            child._retention_cache = removed_dates(items, child.retention_fields)
            try:
                return plain(items)
            finally:
                child._retention_cache = None
        listing.to_representation = to_representation
        return listing

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
