"""
Data lifecycle Stage 4: a file follows its record into the holding folder.

When staff delete a record, or replace or clear its file, the old file used to be deleted on the spot or left
behind. Now it goes to the holding folder for 30 days (holding.HOLD_DAYS) with who and when, and is then purged.
Floors do not apply to these holds, and they are only ever retrieved as a copy, never restored into a record.

Signals on every model that owns a classified file field (register.classified_file_fields):
- post_init notes on each loaded file value the name it was loaded with (no query). post_save notes it again.
- pre_save keeps the old values of the fields this instance changed since it was loaded or last saved: one query,
  none when it changed none of them, for a new row, a raw save (fixtures), or an update_fields set that leaves
  them out. A stale instance saved in full (someone replaced the file after it was loaded) changed nothing, so
  the file it writes over is not held: holding it would send a record's live file to the hold.
- post_save schedules FILE_REPLACED for each old value that differs from the new one (a cleared field counts).
- post_delete schedules RECORD_DELETED for each non-empty value (a cascade delete sends one per child).

The hold runs in transaction.on_commit: a rolled-back delete moves nothing, and hold_file must run outside any
transaction. A path some other record still uses is never moved. The user's request never fails because of a
hold: every error is caught and logged with rule key, model, pk and the error's type, never a file name.

LIFECYCLE_FILE_RULES_ENABLED does not gate this. Company-level, no branch scoping; no SOFTECH reads or writes.
"""
import logging
from functools import partial

from django.apps import apps
from django.db import transaction
from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_init, post_save, pre_save

from . import holding, references
from .register import classified_file_fields

logger = logging.getLogger('elrezeiky.sync')

OLD_VALUES_ATTR = '_lifecycle_old_files'
# Kept on the FieldFile, not the instance: refresh_from_db copies the fresh FieldFile (and its note) across.
LOADED_NAME_ATTR = '_lifecycle_loaded_name'


def _fields_by_model():
    out = {}
    for key in classified_file_fields():
        label, field = key.rsplit('.', 1)
        out.setdefault(label, []).append(field)
    return {label: sorted(fields) for label, fields in out.items()}


FIELDS_BY_MODEL = {}


def _name(value):
    """The stored name of a FieldFile, a plain string, or None."""
    name = getattr(value, 'name', value)
    return str(name) if name else ''


def _current_user_id():
    from apps.users.middleware import get_current_user_profile
    try:
        profile = get_current_user_profile()
    except Exception:
        return None
    return getattr(profile, 'pk', None)


def _hold_after_commit(path, origin, rule_key, user_id):
    try:
        if references.references_to(path):
            return
        if not holding._inside(holding._media_root(), path).is_file():
            return
        deleted_by = None
        if user_id is not None:
            from apps.users.models import StaffProfile
            deleted_by = StaffProfile.objects.filter(pk=user_id).first()
        holding.hold_file(path, [], rule_key, origin=origin, deleted_by=deleted_by)
    except Exception as exc:
        # ids only: a file name can carry a patient's name
        logger.warning('[lifecycle] %s file of %s pk=%s was not held: %s', rule_key, origin.get('model'),
                       origin.get('pk'), type(exc).__name__)


def _schedule(sender, pk, field, path, rule_key):
    origin = {'model': sender._meta.label, 'pk': pk, 'field': field}
    transaction.on_commit(partial(_hold_after_commit, path, origin, rule_key, _current_user_id()))


def _note_loaded(sender, instance):
    """Note on each file value the name it now has. A deferred field is left alone (reading it would query)."""
    for field in FIELDS_BY_MODEL.get(sender._meta.label, ()):
        raw = instance.__dict__.get(field, False)
        if raw is False or not (raw is None or isinstance(raw, (str, FieldFile))):
            continue                                  # deferred, or a new upload assigned at construction
        value = getattr(instance, field)              # wraps a str/None in a FieldFile, no query
        if isinstance(value, FieldFile):
            value.__dict__[LOADED_NAME_ATTR] = _name(value)


def _snapshot_loaded(sender, instance, **kwargs):
    _note_loaded(sender, instance)


def _changed_here(instance, field):
    """True when this code changed the field since the instance was loaded or last saved. A value with no note
    (assigned, deferred then assigned, or unpickled) counts as changed; the pre_save query then decides."""
    value = instance.__dict__.get(field)
    if not isinstance(value, FieldFile) or LOADED_NAME_ATTR not in value.__dict__:
        return True
    return value.__dict__[LOADED_NAME_ATTR] != _name(value)


def _remember_old_files(sender, instance, raw=False, update_fields=None, **kwargs):
    instance.__dict__.pop(OLD_VALUES_ATTR, None)
    if raw or instance._state.adding or instance.pk is None:
        return
    fields = FIELDS_BY_MODEL.get(sender._meta.label, ())
    if update_fields is not None:
        fields = [f for f in fields if f in update_fields]
    fields = [f for f in fields if _changed_here(instance, f)]
    if not fields:
        return
    try:
        old = sender._default_manager.filter(pk=instance.pk).values(*fields).first()
    except Exception as exc:
        logger.warning('[lifecycle] old files of %s pk=%s not read: %s', sender._meta.label, instance.pk,
                       type(exc).__name__)
        return
    if old:
        instance.__dict__[OLD_VALUES_ATTR] = {f: _name(v) for f, v in old.items() if v}


def _hold_replaced(sender, instance, created=False, raw=False, **kwargs):
    old = instance.__dict__.pop(OLD_VALUES_ATTR, None)
    _note_loaded(sender, instance)                    # what was just saved is now the loaded value
    if raw or created or not old:
        return
    for field, before in old.items():
        if before != _name(getattr(instance, field, None)):
            _schedule(sender, instance.pk, field, before, holding.FILE_REPLACED)


def _hold_deleted(sender, instance, **kwargs):
    for field in FIELDS_BY_MODEL.get(sender._meta.label, ()):
        path = _name(getattr(instance, field, None))
        if path:
            _schedule(sender, instance.pk, field, path, holding.RECORD_DELETED)


def connect():
    FIELDS_BY_MODEL.clear()
    FIELDS_BY_MODEL.update(_fields_by_model())
    for label in FIELDS_BY_MODEL:
        model = apps.get_model(label)
        post_init.connect(_snapshot_loaded, sender=model, dispatch_uid=f'lifecycle_follow_init_{label}')
        pre_save.connect(_remember_old_files, sender=model, dispatch_uid=f'lifecycle_follow_pre_{label}')
        post_save.connect(_hold_replaced, sender=model, dispatch_uid=f'lifecycle_follow_post_{label}')
        post_delete.connect(_hold_deleted, sender=model, dispatch_uid=f'lifecycle_follow_delete_{label}')
