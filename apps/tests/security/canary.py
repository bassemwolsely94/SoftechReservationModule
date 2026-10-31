"""
apps/tests/security/canary.py — plant one marked record per branch-linked model (Batch 5).

For every model with a path to a branch — a ForeignKey to branches.Branch, or a SOFTECH branch-code
char field (branch_code / softech_branchcode / branchcode) — one row is created in the given branch.
Every free-text field on that row carries MARKER, so a list response that contains MARKER is showing
that branch's record. Required relations to other models are filled with neutral rows (no marker),
so shared master data (items, suppliers…) never trips the sweep on its own.

Best effort by design: a model whose row can't be built generically is reported in `skipped`
(the sweep test lists them), never silently dropped.
"""
import datetime
from decimal import Decimal

from django.apps import apps
from django.db import IntegrityError, models, transaction

MARKER = 'CNRYA'
CODE_FIELDS = ('branch_code', 'softech_branchcode', 'branchcode', 'softech_branch_code')
SKIP_APPS = {'admin', 'auth', 'contenttypes', 'sessions', 'token_blacklist', 'django_celery_beat',
             'django_celery_results', 'branches'}


def _branch_model():
    return apps.get_model('branches', 'Branch')


def branch_linked_models():
    Branch = _branch_model()
    out = []
    for m in apps.get_models():
        if m._meta.app_label in SKIP_APPS or m._meta.proxy or not m._meta.managed:
            continue
        fks = [f for f in m._meta.concrete_fields if f.is_relation and f.related_model is Branch]
        codes = [f for f in m._meta.concrete_fields
                 if f.name in CODE_FIELDS and isinstance(f, models.CharField)]
        if fks or codes:
            out.append((m, fks, codes))
    return out


PHONE_KEYS = ('phone', 'mobile', 'wa_id', 'caller_number', 'caller_id')


class Planter:
    def __init__(self, branch, user, profile, phone=None):
        self.branch, self.user, self.profile = branch, user, profile
        self.phone = phone           # phone sweep: every phone-like field gets this number
        self.neutral = {}            # model → a neutral instance reused as a dependency
        self.planted = {}            # model label → pk
        self.skipped = {}            # model label → reason
        self._depth = 0

    # ── values ────────────────────────────────────────────────────────────────
    def _text(self, f, marked):
        if f.choices:
            return f.choices[0][0]
        max_len = getattr(f, 'max_length', None) or 200
        if self.phone and any(k in f.name for k in PHONE_KEYS):
            return self.phone[:max_len]
        if f.name in CODE_FIELDS:
            return self.branch.softech_branch_id[:max_len]
        if not marked:
            return 'x'[:max_len]
        return MARKER if max_len >= len(MARKER) else 'x'[:max_len]

    def _value(self, f, marked):
        if isinstance(f, (models.CharField, models.TextField)):
            if isinstance(f, (models.EmailField,)):
                return 'cnrya@example.test' if marked else 'x@example.test'
            if isinstance(f, (models.URLField,)):
                return 'https://example.test/'
            if isinstance(f, models.GenericIPAddressField):
                return '127.0.0.1'
            return self._text(f, marked)
        if f.choices:
            return f.choices[0][0]
        if isinstance(f, models.BooleanField):
            return False
        if isinstance(f, (models.DecimalField,)):
            return Decimal('1')
        if isinstance(f, (models.IntegerField, models.FloatField)):
            return 1
        if isinstance(f, models.DateTimeField):
            from django.utils import timezone
            return timezone.now()
        if isinstance(f, models.DateField):
            return datetime.date.today()
        if isinstance(f, models.TimeField):
            return datetime.time(9, 0)
        if isinstance(f, models.DurationField):
            return datetime.timedelta(minutes=1)
        if isinstance(f, models.UUIDField):
            import uuid
            return uuid.uuid4()
        if isinstance(f, models.JSONField):
            return {}
        if isinstance(f, (models.BinaryField,)):
            return b''
        if isinstance(f, models.FileField):
            return ''
        return None

    def _related(self, f):
        rel = f.related_model
        Branch = _branch_model()
        if rel is Branch:
            return self.branch
        if rel is self.user.__class__:
            return self.user
        if rel is self.profile.__class__:
            return self.profile
        if rel in self.neutral:
            return self.neutral[rel]
        obj = self.build(rel, marked=False)
        if obj is not None:
            self.neutral[rel] = obj
        return obj

    # ── rows ──────────────────────────────────────────────────────────────────
    def build(self, model, marked):
        if self._depth > 4:
            return None
        self._depth += 1
        try:
            kwargs = {}
            for f in model._meta.concrete_fields:
                if f.primary_key or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
                    continue
                if f.is_relation:
                    if f.related_model is _branch_model():
                        kwargs[f.name] = self.branch            # every branch FK → this branch
                    elif not f.null:
                        val = self._related(f)
                        if val is None:
                            return None
                        kwargs[f.name] = val
                    continue
                needed = not f.null and not f.has_default() and not f.blank
                text = isinstance(f, (models.CharField, models.TextField)) and not f.choices
                phone = text and self.phone and any(k in f.name for k in PHONE_KEYS)
                if f.name in CODE_FIELDS or needed or (marked and text) or phone:
                    val = self._value(f, marked)
                    if val is None and needed:
                        return None
                    if val is not None:
                        kwargs[f.name] = val
            try:
                with transaction.atomic():
                    return model._default_manager.create(**kwargs)
            except (IntegrityError, ValueError, TypeError, Exception):   # noqa: BLE001 — best effort
                return None
        finally:
            self._depth -= 1

    def plant_phones(self):
        """Phone sweep: this branch's customer first (every phone field = self.phone), then every
        model with a phone-like field or a branch link, attached to that customer."""
        Customer = apps.get_model('customers', 'Customer')
        cust = self.build(Customer, marked=True)
        self.customer = cust
        if cust is not None:
            self.neutral[Customer] = cust
        linked = {m for m, _, _ in branch_linked_models()}
        phoney = {m for m in apps.get_models()
                  if m._meta.app_label not in SKIP_APPS and not m._meta.proxy and m._meta.managed
                  and any(isinstance(f, (models.CharField, models.TextField))
                          and any(k in f.name for k in PHONE_KEYS) for f in m._meta.concrete_fields)}
        for model in sorted(linked | phoney, key=lambda m: m._meta.label):
            if model is Customer:
                continue
            obj = self.build(model, marked=True)
            (self.planted if obj is not None else self.skipped)[model._meta.label] = getattr(obj, 'pk', 'skip')
        return self

    def plant_all(self):
        for model, _, _ in branch_linked_models():
            label = model._meta.label
            try:
                obj = self.build(model, marked=True)
            except Exception as exc:      # noqa: BLE001
                obj, why = None, f'{type(exc).__name__}'
            else:
                why = 'could not build generically'
            if obj is None:
                self.skipped[label] = why
            else:
                self.planted[label] = obj.pk
        return self
