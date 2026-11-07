"""
apps/data_lifecycle/references.py

The reference index: every record that uses a media path, so a file used elsewhere is never moved. Checks found
607 product images and 4 OCR samples sharing a file with another row, and 299 enrichment rows holding a media URL
in a text field. A candidate path is movable only when every reference to it is one of the rule's own candidate
rows (matched on model, pk and field).

The index walks every FileField of every model, not only the classified ones, so a field added later protects
its files before anyone writes a rule for it. Reads our own database only. Company-level, no branch scoping; no
SOFTECH reads or writes.
"""
import posixpath
from dataclasses import dataclass, field
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

from django.apps import apps
from django.conf import settings
from django.db import models

# Text fields that hold a media URL rather than a file: ('app.Model', field).
TEXT_PATH_FIELDS = [('enrichment.ItemEnrichment', 'image_url'), ('enrichment.ItemEnrichment', 'image_secondary_url')]

ITERATOR_CHUNK = 2000


class Ref(NamedTuple):
    """One record using a path. Same keys as a `hold_file` row; `value` is the exact stored field value."""
    model: str
    pk: object
    field: str
    value: str

    @property
    def key(self):
        return (self.model, str(self.pk), self.field)


@dataclass
class FileCandidate:
    """A file a rule wants to move and the rows of its own that use it (the rows `hold_file` will clear)."""
    path: str
    rows: list = field(default_factory=list)
    size: int = 0


def normalise(path):
    return str(path).replace(chr(92), '/').lstrip('/')


def media_path_from_url(url):
    """The path under MEDIA_URL a URL points at, or None. Scheme, host and query are ignored."""
    if not url:
        return None
    path = unquote(urlsplit(str(url).strip()).path)
    if not path.startswith('/'):
        path = '/' + path          # a relative `media/x.jpg` still points into media
    path = posixpath.normpath(path)  # collapses `..`; a path that climbs out of media no longer matches
    prefix = '/' + settings.MEDIA_URL.strip('/') + '/'
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    if not rest:
        return None
    return rest


def build_reference_index():
    """{normalised path: set of Ref} over every FileField and every TEXT_PATH_FIELDS entry."""
    index = {}
    for model in apps.get_models():
        label = model._meta.label
        for fld in model._meta.local_fields:
            if isinstance(fld, models.FileField):
                rows = model._default_manager.exclude(**{fld.name: ''}).exclude(**{f'{fld.name}__isnull': True})
                for pk, value in rows.values_list('pk', fld.name).iterator(chunk_size=ITERATOR_CHUNK):
                    if value:
                        index.setdefault(normalise(value), set()).add(Ref(label, pk, fld.name, value))
    for label, name in TEXT_PATH_FIELDS:
        model = apps.get_model(label)
        rows = model._default_manager.exclude(**{name: ''}).exclude(**{f'{name}__isnull': True})
        for pk, value in rows.values_list('pk', name).iterator(chunk_size=ITERATOR_CHUNK):
            path = media_path_from_url(value)
            if path:
                index.setdefault(path, set()).add(Ref(label, pk, name, value))
    return index


def partition(candidates, index):
    """(movable, skipped_shared). Skipped when any reference to the path is not one of the candidate's own rows."""
    movable, skipped = [], []
    for candidate in candidates:
        own = {(r['model'], str(r['pk']), r['field']) if isinstance(r, dict) else r.key for r in candidate.rows}
        others = [ref for ref in index.get(normalise(candidate.path), ()) if ref.key not in own]
        (skipped if others else movable).append(candidate)
    return movable, skipped
