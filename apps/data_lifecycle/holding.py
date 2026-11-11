"""
apps/data_lifecycle/holding.py

The holding folder: a file leaves media together with its database references, waits 30 days where no URL
can reach it, and is then purged. Until then an admin can restore it. Who may call restore is the caller's
check (server-side, admin only; design §7).

A failure must never lose a document, so:
- The file moves first and the database follows in one transaction; if any of that fails the file goes back.
- A move never overwrites anything. If the file cannot go back, it stays in the holding folder, and
  FileStranded plus a critical log line say where.
- Nothing is recorded as purged unless the file really was deleted, or an admin said it is lost (mark_lost).

hold_file and restore refuse to run inside a caller's transaction (durable=True): a later rollback would revert
the rows and the HeldFile but could not move the file back.

Logs and error messages carry ids only, never filenames (§7). An OSError or a database error can quote a
path, so every failure leaves here as a HoldError naming only the error's type.

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import datetime
import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog

from .models import HeldFile

logger = logging.getLogger('elrezeiky.sync')

HOLD_DAYS = 30
AUDIT_ACTION = 'lifecycle_file_restored'
AUDIT_ACTION_LOST = 'lifecycle_file_marked_lost'
HASH_CHUNK = 1024 * 1024


class HoldError(Exception):
    """Refused or failed, with the file safe where it was. The message is Arabic, names no file, safe to show."""


class FileStranded(HoldError):
    """The database step failed and the file could not go back. It is intact; the critical log says where."""


def _media_root():
    return Path(settings.MEDIA_ROOT).resolve()


def _hold_root():
    """The configured folder, or a refusal. Whole resolved paths are compared: `media_hold` starts with the
    text `media` but is not inside it. An empty LIFECYCLE_HOLD_ROOT= in .env arrives as Path('.')."""
    root = Path(settings.LIFECYCLE_HOLD_ROOT).resolve()
    media = _media_root()
    if root == media or media in root.parents or root == Path.cwd().resolve():
        raise HoldError('مجلد الحجز LIFECYCLE_HOLD_ROOT يجب أن يكون خارج مجلد الملفات، فلم يُنقل أو يُحذف شيء.')
    return root


def _inside(base, relative):
    """The full path, or a refusal if it would be `base` itself or anywhere outside it."""
    full = (base / relative).resolve()
    if base not in full.parents:
        raise HoldError('مسار الملف خارج المجلد المسموح به.')
    return full


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while chunk := stream.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _move(source, target):
    """Move without ever overwriting. Creating `target` exclusively claims the name, so this fails if anything
    is there, and an upload arriving now picks another name. On failure, while `source` is still whole, our
    claim or partial copy is removed (a move across disks copies first and deletes the source last)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    open(target, 'xb').close()
    try:
        shutil.move(str(source), str(target))
    except BaseException:
        if source.exists():
            target.unlink(missing_ok=True)
        raise


def _after_failure(exc, moved, ref):
    """Inside an `except`: put a moved file back, then raise. `moved` is (where it is now, where it belongs).
    `ref` says where a file that cannot go back really is and what it belongs to: ids and hashes, no filename."""
    if moved:
        try:
            _move(*moved)
        except Exception as back_exc:
            logger.critical('[lifecycle] a file could not go back: %s (%s)', ref, type(back_exc).__name__)
            raise FileStranded(f'تعذر إرجاع الملف إلى مكانه، وهو سليم ({ref}). راجع السجل فورًا.') from None
    if isinstance(exc, HoldError) or not isinstance(exc, Exception):
        raise exc
    raise HoldError(f'لم تكتمل العملية ({type(exc).__name__})، وبقي الملف في مكانه.') from None


def _clear_row(row):
    """0 rows means the row changed or went away after it was read. That fails the whole hold."""
    model = apps.get_model(row['model'])
    field = row['field']
    if not model.objects.filter(pk=row['pk'], **{field: row['value']}).update(**{field: ''}):
        raise HoldError('تغيّر السجل أثناء النقل، فلم يُنقل الملف.')


def _write_back_row(row):
    model = apps.get_model(row['model'])
    field = row['field']
    if not model.objects.filter(pk=row['pk'], **{field: ''}).update(**{field: row['value']}):
        raise HoldError('السجل به ملف جديد أو لم يعد موجودًا، فلا يمكن استرجاع الملف إليه.')


def _check_row(row):
    apps.get_model(row['model'])._meta.get_field(row['field'])
    if row['pk'] is None or not row['value']:
        raise HoldError('بيانات السجل غير مكتملة، فلم يُنقل الملف.')


def hold_file(path, rows, rule_key):
    """Move a file (`path` relative to MEDIA_ROOT) to the holding folder and clear every reference to it.
    `rows` is a list of {model: 'app.Model', pk, field, value}, value being the field's exact current content.
    A file no record uses has rows=[]. Returns the HeldFile. Raises HoldError; the file is then back in place,
    unless it is FileStranded."""
    moved, ref = None, ''
    try:
        root, media = _hold_root(), _media_root()
        source = _inside(media, path)
        if not source.is_file():
            raise HoldError('الملف غير موجود.')
        for row in rows:
            _check_row(row)
        hold_name = uuid.uuid4().hex + source.suffix
        target = root / hold_name
        size, sha256 = source.stat().st_size, _sha256(source)
        first = rows[0] if rows else {}
        # The HeldFile insert rolls back in the case this is for, so this line is all that says what the file is.
        ref = (f'it is in the holding folder as {hold_name}; rule_key={rule_key} '
               f'primary_model={first.get("model", "")} primary_pk={first.get("pk", "")} '
               f'primary_field={first.get("field", "")} sha256={sha256}')
        _move(source, target)
        moved = (target, source)
        with transaction.atomic(durable=True):
            for row in rows:
                _clear_row(row)
            now = timezone.now()
            return HeldFile.objects.create(
                original_path=source.relative_to(media).as_posix(), hold_path=hold_name, rule_key=rule_key,
                size=size, sha256=sha256, moved_at=now, purge_after=now + datetime.timedelta(days=HOLD_DAYS),
                primary_model=first.get('model', ''), primary_pk=str(first.get('pk', '')),
                primary_field=first.get('field', ''), rows=rows)
    except BaseException as exc:
        _after_failure(exc, moved, ref)


def restore(held_id, user):
    """Put a held file back at its original path and write each row's value back, with AuditLog. Refused when
    the path is occupied, a row is gone or no longer empty, or the bytes are not the ones held. The row lock
    keeps a second restore and the purge out meanwhile."""
    moved = None
    try:
        if user is None:
            raise HoldError('يجب تحديد المستخدم الذي يسترجع الملف.')
        root, media = _hold_root(), _media_root()
        with transaction.atomic(durable=True):
            held = HeldFile.objects.select_for_update().filter(pk=held_id).first()
            if held is None:
                raise HoldError('الملف المحجوز غير موجود.')
            if held.restored_at or held.purged_at:
                raise HoldError('تم استرجاع هذا الملف أو حذفه نهائيًا من قبل.')
            source, home = _inside(root, held.hold_path), _inside(media, held.original_path)
            if os.path.lexists(home):
                raise HoldError('يوجد ملف آخر في المسار الأصلي، فلم يُسترجع الملف.')
            if not source.is_file() or _sha256(source) != held.sha256:
                raise HoldError('الملف المحجوز مفقود أو تغيّر محتواه، فلم يُسترجع.')
            _move(source, home)
            moved = (home, source)
            for row in held.rows:
                _write_back_row(row)
            held.restored_at, held.restored_by = timezone.now(), user
            held.save(update_fields=['restored_at', 'restored_by'])
            # AuditLog.log returns None instead of raising; rule 8 says no unaudited change may stick.
            if AuditLog.log(AUDIT_ACTION, user=user, obj=held, old_data={'restored_at': None},
                            new_data={'restored_at': held.restored_at.isoformat()},
                            extra={'rule_key': held.rule_key, 'primary_model': held.primary_model,
                                   'primary_pk': held.primary_pk, 'primary_field': held.primary_field}) is None:
                raise HoldError('تعذر تسجيل الاسترجاع في سجل المراجعة، فلم يُسترجع الملف.')
    except BaseException as exc:
        _after_failure(exc, moved, f'held {held_id}: it is at the original_path of that record, not in the holding '
                                   f'folder, and the record still says held')
    return held


def _is_missing(path):
    """True only when nothing at all is at `path`. A permission or disk error raises instead of looking missing."""
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


def _existing_hold_root():
    root = _hold_root()
    if not root.is_dir():
        raise HoldError('مجلد الحجز LIFECYCLE_HOLD_ROOT غير موجود، فلم يُحذف أي ملف. راجع الإعداد.')
    return root


def _find_missing(root, rows):
    """The ids of due held files that are not on disk. A row whose path cannot be checked is left out here and
    fails in the purge loop instead."""
    missing = set()
    for held_id, hold_path in rows:
        try:
            if _is_missing(_inside(root, hold_path)):
                missing.add(held_id)
        except Exception:
            continue
    return missing


def _alert_missing(held_id, now):
    """One admin alert a day per held id. The message names the id only, never the file."""
    from apps.sync.maintenance import _alert_admins
    try:
        _alert_admins('🟠 ملف محجوز مفقود',
                      f'الملف المحجوز رقم {held_id} غير موجود في مجلد الحجز في موعد حذفه، فتم تخطيه ولم يُسجَّل '
                      f'كمحذوف. لو تأكدت أنه فُقد: manage.py lifecycle mark-lost {held_id} --user <admin> '
                      f'--reason "..."',
                      f'lifecycle_held_missing_{held_id}_{timezone.localtime(now).date().isoformat()}')
    except Exception as exc:
        logger.error('[lifecycle] alert for missing held %s failed: %s', held_id, type(exc).__name__)


def purge_expired(now=None):
    """Delete every held file past its date that was not restored. The row stays, so the removal date stays
    known. One failure does not stop the others, but the step then raises so the retention run shows it.

    A held file already missing from disk is not recorded as purged. One such file is skipped with a daily admin
    alert (an admin closes it with mark_lost), so it cannot fail the step every day. But a missing hold root, or
    more than half of the due files missing (two or more), likely means a wrong LIFECYCLE_HOLD_ROOT: then the
    step raises before deleting anything. With nothing due, the hold root is not read at all.
    Returns how many were purged."""
    now = now or timezone.now()
    due = HeldFile.objects.filter(purge_after__lte=now, restored_at__isnull=True, purged_at__isnull=True)
    rows = list(due.order_by('pk').values_list('pk', 'hold_path'))
    if not rows:
        return 0
    root = _existing_hold_root()
    missing = _find_missing(root, rows)
    if len(missing) >= 2 and len(missing) * 2 > len(rows):
        logger.error('[lifecycle] purge stopped: %s of %s due held files are missing', len(missing), len(rows))
        raise HoldError(f'{len(missing)} من {len(rows)} ملف محجوز غير موجود في مجلد الحجز، وقد يكون المجلد خطأ. '
                        f'لم يُحذف أي ملف.')
    purged, failed = 0, 0
    for held_id, _ in rows:
        if held_id in missing:
            logger.warning('[lifecycle] held %s is missing from the hold folder; skipped', held_id)
            _alert_missing(held_id, now)
            continue
        try:
            with transaction.atomic():
                held = due.select_for_update().filter(pk=held_id).first()
                if held is None:        # restored since the list was read
                    continue
                path = _inside(root, held.hold_path)
                if not path.is_file():
                    raise FileNotFoundError
                held.purged_at = now
                held.save(update_fields=['purged_at'])
                path.unlink()           # last, so a failure here rolls back the date just written
            purged += 1
        except Exception as exc:
            failed += 1
            logger.error('[lifecycle] held %s was not purged: %s', held_id, type(exc).__name__)
    if failed:
        raise HoldError(f'تعذر حذف {failed} ملف محجوز، وتم حذف {purged}. راجع السجل.')
    return purged


def mark_lost(held_id, user, reason):
    """Close a held file that is really gone from the hold folder: sets purged_at, with AuditLog. Refused while
    anything is at its path, when the hold root itself is missing, or when the record is already closed. Who
    may call it is the caller's check (admin only)."""
    reason = (reason or '').strip()
    if user is None or not reason:
        raise HoldError('يجب تحديد المستخدم وسبب اعتبار الملف مفقودًا.')
    try:
        root = _existing_hold_root()
        with transaction.atomic(durable=True):
            held = HeldFile.objects.select_for_update().filter(pk=held_id).first()
            if held is None:
                raise HoldError('الملف المحجوز غير موجود.')
            if held.restored_at or held.purged_at:
                raise HoldError('تم استرجاع هذا الملف أو حذفه نهائيًا من قبل.')
            if not _is_missing(_inside(root, held.hold_path)):
                raise HoldError('الملف ما زال موجودًا في مجلد الحجز، فلا يُعتبر مفقودًا.')
            held.purged_at = timezone.now()
            held.save(update_fields=['purged_at'])
            # AuditLog.log returns None instead of raising; rule 8 says no unaudited change may stick.
            if AuditLog.log(AUDIT_ACTION_LOST, user=user, obj=held, old_data={'purged_at': None},
                            new_data={'purged_at': held.purged_at.isoformat()},
                            extra={'reason': reason, 'rule_key': held.rule_key, 'primary_model': held.primary_model,
                                   'primary_pk': held.primary_pk, 'primary_field': held.primary_field}) is None:
                raise HoldError('تعذر التسجيل في سجل المراجعة، فلم يتغير شيء.')
    except HoldError:
        raise
    except Exception as exc:
        raise HoldError(f'لم تكتمل العملية ({type(exc).__name__}).') from None
    return held
