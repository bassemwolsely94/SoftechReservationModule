"""
apps/data_lifecycle/rules_files.py

What the file rules of register.py select (design §5.1). Each candidates function returns FileCandidates, one per
path, with the rows of that rule that use the path. The runner then removes any file used by anything else
(references.partition), so a function here only has to say what its own rule wants.

Reads only: a candidates function changes nothing and moves nothing. The two refresh functions write the
"first seen" tables, and the runner calls them only in a daily run of a rule that is not `off`.

A row whose file is not on disk is not a candidate: nothing is moved or counted for it, and only the number of such
rows is logged. Logs carry ids and counts only, never a file name (§7).

register.py imports this module, so register and policy are imported inside functions, as in rules_rows.py.

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import datetime
import logging
import os
import re

from django.apps import apps
from django.db.models import Count, F, Max, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import holding
from .models import ObsoleteItemSeen, UnreferencedFileSeen
from .references import FileCandidate, Ref, build_reference_index, media_path_from_url, normalise

logger = logging.getLogger('elrezeiky.sync')

ITERATOR_CHUNK = 2000
BULK_BATCH = 2000
SEEN_PATH_MAX = 500     # UnreferencedFileSeen.path and HeldFile.original_path; a longer path is never tracked

# More than this share of the referenced paths missing from disk stops every file rule for the run (a bad restore
# or a wrong MEDIA_ROOT looks like this). Exactly this share still runs.
MISSING_PERCENT_LIMIT = 5

# Batch states that have finished with their pages. `pending` and `processing` never qualify.
BUNDLE_PAGES_DIR = 'invoice_bundles/pages'
BUNDLE_SETTLED_BATCH_STATUSES = ('ready', 'failed')
BUNDLE_DONE_INVOICE_STATUSES = ('finalized', 'rejected')
_BATCH_FOLDER = re.compile(r'^batch_\d+$')

# `unreferenced`: never these. Reports and bundle pages have no record by design.
UNREFERENCED_EXCLUDED = ('reports/', 'invoice_bundles/pages/')
# `unreferenced`: a prescription whose row was lost must not leave before a prescription whose row still exists
# (§2 anti-goal), and the same for a financial document. These wait for the file's own age as well.
PRESCRIPTION_FOLDERS = ('reservations/', 'pos_orders/prescriptions/', 'usage_print/prescriptions/',
                        'callcenter/prescriptions/', 'vision/ocr/')
FINANCIAL_FOLDERS = ('invoice_images/', 'invoice_bundles/', 'payments/', 'hr/receipts/')


def _cutoff(key):
    from .policy import keep_days
    return timezone.now() - datetime.timedelta(days=keep_days(key))


def _stat(path):
    """The file's os.stat_result, or None if `path` is not a regular file inside MEDIA_ROOT. Never raises."""
    try:
        full = holding._inside(holding._media_root(), path)
        return full.stat() if full.is_file() else None
    except (holding.HoldError, OSError, ValueError):
        return None


def missing_references(index):
    """(paths missing from disk, paths referenced) of a reference index."""
    return sum(1 for path in index if _stat(path) is None), len(index)


def too_many_missing(missing, total):
    return missing * 100 > total * MISSING_PERCENT_LIMIT


def _refs(queryset, field):
    """(normalised path, Ref) for each row of the queryset that has this file field filled."""
    label = queryset.model._meta.label
    rows = queryset.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}).order_by('pk')
    for pk, value in rows.values_list('pk', field).iterator(chunk_size=ITERATOR_CHUNK):
        yield normalise(value), Ref(label, pk, field, value)


def _candidates(key, refs):
    """One FileCandidate per path, so all the rows on one file move and restore together."""
    by_path = {}
    for path, ref in refs:
        by_path.setdefault(path, []).append(ref)
    out, missing_rows = [], 0
    for path, rows in by_path.items():
        stat = _stat(path)
        if stat is None:
            missing_rows += len(rows)
        else:
            out.append(FileCandidate(path, rows, stat.st_size))
    if missing_rows:
        logger.warning('[lifecycle] %s: %s row(s) point at a file that is not on disk', key, missing_rows)
    return out


def _aged_by_field(key, **only):
    """The rule's targets whose age_field is past its period. `only` narrows the rows further."""
    from .register import RULES
    rule = RULES[key]
    cutoff = _cutoff(key)
    refs = []
    for target in rule.targets:
        label, field = target.rsplit('.', 1)
        model = apps.get_model(label)
        rows = model._default_manager.filter(**{f'{rule.age_field[label]}__lte': cutoff}, **only)
        refs.extend(_refs(rows, field))
    return _candidates(key, refs)


def prescriptions_candidates():
    return _aged_by_field('prescriptions')


def ocr_pos_rx_candidates():
    """Only module pos_rx. The readings are other columns of the row, so they stay."""
    return _aged_by_field('ocr_pos_rx', module='pos_rx')


def conversations_candidates():
    return _aged_by_field('conversations')


def financial_docs_candidates():
    return _aged_by_field('financial_docs')


def delivery_proof_candidates():
    return _aged_by_field('delivery_proof')


def staff_messages_candidates():
    return _aged_by_field('staff_messages')


# ── Item images ──────────────────────────────────────────────────────────────

def images_rejected_candidates():
    """Ages from the rejection, so a candidate found long ago and rejected today waits its full period."""
    from apps.images.models import ImageCandidate
    from .register import IMAGE_REJECTED_STATUSES
    rows = (ImageCandidate.objects.filter(status__in=IMAGE_REJECTED_STATUSES)
            .annotate(aged_from=Coalesce('reviewed_at', 'created_at'))
            .filter(aged_from__lte=_cutoff('images_rejected')))
    return _candidates('images_rejected', _refs(rows, 'local_file'))


def images_unreviewed_candidates():
    from apps.images.models import ImageCandidate
    from .register import IMAGE_UNREVIEWED_STATUSES
    rows = ImageCandidate.objects.filter(status__in=IMAGE_UNREVIEWED_STATUSES,
                                         created_at__lte=_cutoff('images_unreviewed'))
    return _candidates('images_unreviewed', _refs(rows, 'local_file'))


def _obsolete_items():
    from apps.catalog.models import Item
    return Item.objects.filter(Q(no_more_use=True) | Q(item_archive=True) | Q(is_active=False))


def refresh_obsolete_seen(now=None):
    """Bring the clocks up to date with the items, never changing an item. A new obsolete item starts a clock, an
    item back in use clears it, and an item obsolete again starts over. Returns how many rows changed."""
    now = now or timezone.now()
    seen = ObsoleteItemSeen.objects
    obsolete = _obsolete_items().values('pk')
    changed = seen.filter(cleared_at__isnull=True).exclude(item__in=obsolete).update(cleared_at=now)
    changed += seen.filter(cleared_at__isnull=False, item__in=obsolete).update(first_seen_at=now, cleared_at=None)
    new_ids = _obsolete_items().exclude(pk__in=seen.values('item_id')).values_list('pk', flat=True)
    new_rows = [ObsoleteItemSeen(item_id=pk, first_seen_at=now) for pk in new_ids]
    seen.bulk_create(new_rows, batch_size=BULK_BATCH, ignore_conflicts=True)
    return changed + len(new_rows)


def images_obsolete_candidates():
    """Whatever the status, on items that are obsolete right now and have been seen so for the full period. The
    item's state is read here as well as in the refresh, so an item that just came back is never selected.
    ItemEnrichment.image_url joins a group only when it points at one of these paths."""
    from apps.enrichment.models import ItemEnrichment
    from apps.images.models import ImageCandidate
    from apps.product_experience.models import ProductMedia
    clocks = ObsoleteItemSeen.objects.filter(cleared_at__isnull=True, first_seen_at__lte=_cutoff('images_obsolete'))
    items = _obsolete_items().filter(pk__in=clocks.values('item_id')).values('pk')
    refs = [*_refs(ImageCandidate.objects.filter(item__in=items), 'local_file'),
            *_refs(ProductMedia.objects.filter(item__in=items), 'file'),
            *_refs(ProductMedia.objects.filter(item__in=items), 'thumbnail')]
    paths = {path for path, _ in refs}
    urls = ItemEnrichment.objects.filter(item__in=items).exclude(image_url='').order_by('pk')
    for pk, url in urls.values_list('pk', 'image_url').iterator(chunk_size=ITERATOR_CHUNK):
        path = media_path_from_url(url)
        if path in paths:
            refs.append((path, Ref('enrichment.ItemEnrichment', pk, 'image_url', url)))
    return _candidates('images_obsolete', refs)


# ── Invoice bundle pages ─────────────────────────────────────────────────────

def _utc(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)


def _page_files(folder):
    with os.scandir(folder) as entries:
        return sorted((entry.name, entry.stat()) for entry in entries if entry.is_file(follow_symlinks=False))


def bundle_pages_candidates():
    """The page images of a batch whose every invoice is finalized or rejected, or a failed batch with none open.

    Nothing reads these pages after ingest (apps/invoices/ingest.py), and a reprocess renders them again from
    source_file, which is outside this folder and stays. A `ready` batch with no invoices is left alone.

    The period runs from the latest of: the last invoice change, the batch's updated_at and the newest page. The
    newest page is there because ingest saves the batch status with update_fields, which leaves updated_at behind,
    so a failed batch has no date of its own and its pages are rewritten by a reprocess."""
    from apps.invoices.models import InvoiceBatch
    cutoff = _cutoff('bundle_pages')
    root = holding._media_root() / BUNDLE_PAGES_DIR
    if not root.is_dir():
        return []
    with os.scandir(root) as entries:
        folders = {int(entry.name[len('batch_'):]): entry.name for entry in entries
                   if _BATCH_FOLDER.match(entry.name) and entry.is_dir(follow_symlinks=False)}
    batches = (InvoiceBatch.objects.filter(pk__in=folders, status__in=BUNDLE_SETTLED_BATCH_STATUSES)
               .annotate(invoice_total=Count('invoices'),
                         invoice_open=Count('invoices', filter=~Q(invoices__status__in=BUNDLE_DONE_INVOICE_STATUSES)),
                         last_invoice_at=Max('invoices__updated_at'))
               .order_by('pk'))
    out = []
    for batch in batches:
        if batch.invoice_open or (batch.status == 'ready' and not batch.invoice_total):
            continue
        folder = f'{BUNDLE_PAGES_DIR}/{folders[batch.pk]}'
        files = _page_files(holding._media_root() / folder)
        dates = [batch.updated_at, *[_utc(stat.st_mtime) for _, stat in files]]
        if batch.last_invoice_at:
            dates.append(batch.last_invoice_at)
        if max(dates) <= cutoff:
            out.extend(FileCandidate(f'{folder}/{name}', [], stat.st_size) for name, stat in files)
    return out


# ── Files no record uses ─────────────────────────────────────────────────────

def _is_excluded(path):
    return path.startswith(UNREFERENCED_EXCLUDED) or len(path) > SEEN_PATH_MAX


def _files_on_disk():
    media = holding._media_root()
    for folder, _, names in os.walk(media):
        for name in names:
            full = os.path.join(folder, name)
            if not os.path.islink(full):
                yield os.path.relpath(full, media).replace(os.sep, '/')


def refresh_unreferenced_seen(index=None, now=None):
    """One scan of media. A file no record uses gets a first date, or a new last date if it has one. A file that
    now has a record or is gone loses its row, so its count starts over. Returns how many files are on the list."""
    now = now or timezone.now()
    index = build_reference_index() if index is None else index
    found = {path for path in _files_on_disk() if path not in index and not _is_excluded(path)}
    rows = UnreferencedFileSeen.objects
    known = set(rows.values_list('path', flat=True))
    rows.filter(path__in=known - found).delete()
    rows.filter(path__in=known & found).update(last_seen_at=now)
    rows.bulk_create([UnreferencedFileSeen(path=path, first_seen_at=now, last_seen_at=now) for path in found - known],
                     batch_size=BULK_BATCH, ignore_conflicts=True)
    return len(found)


def _orphan_minimum_days(path):
    from .policy import keep_days
    if path.startswith(PRESCRIPTION_FOLDERS):
        return keep_days('prescriptions')
    if path.startswith(FINANCIAL_FOLDERS):
        return keep_days('financial_docs')
    return 0


def unreferenced_candidates():
    """Files found on two scans at least the rule's period apart. rows=[]: partition drops any that has a record
    by now, because it looks at a fresher index than the last scan."""
    from .policy import keep_days
    now = timezone.now()
    apart = datetime.timedelta(days=keep_days('unreferenced'))
    rows = UnreferencedFileSeen.objects.filter(last_seen_at__gte=F('first_seen_at') + apart).order_by('pk')
    out, missing = [], 0
    for path in rows.values_list('path', flat=True).iterator(chunk_size=ITERATOR_CHUNK):
        if _is_excluded(path):
            continue
        stat = _stat(path)
        if stat is None:
            missing += 1
        elif _utc(stat.st_mtime) <= now - datetime.timedelta(days=_orphan_minimum_days(path)):
            out.append(FileCandidate(path, [], stat.st_size))
    if missing:
        logger.warning('[lifecycle] unreferenced: %s listed file(s) are no longer on disk', missing)
    return out
