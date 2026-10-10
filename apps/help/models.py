"""
apps/help/models.py — in-app help (دليل الاستخدام).

The help TEXT itself lives in the repo (apps/help/content/*.py) so it ships with the
code that changed a screen and is checked by tests. The database only holds what
people add on top of it:

  HelpOverride  — a trainer's edited version of one screen's help (replaces the
                  editable fields of the repo version; removing it falls back).
  HelpRevision  — immutable history of every trainer save / revert (who, when,
                  before, after, note).
  HelpFeedback  — "was this helpful?" votes + optional comment from any user.
  HelpEvent     — one row each time someone opens a screen's help or searches it,
                  so trainers can see where users get stuck.
"""
from django.db import models


class HelpOverride(models.Model):
    screen_key = models.CharField(max_length=80, unique=True, verbose_name='الشاشة')
    data       = models.JSONField(default=dict, verbose_name='المحتوى المعدّل')
    # hash of the repo version the trainer edited — when the developers later change
    # the repo text, the hashes differ and the editor warns the trainer.
    base_hash  = models.CharField(max_length=64, blank=True, default='')
    updated_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تعديل شرح شاشة'
        verbose_name_plural = 'تعديلات شرح الشاشات'

    def __str__(self):
        return self.screen_key


class HelpRevision(models.Model):
    ACTION_SAVE   = 'save'
    ACTION_REVERT = 'revert'
    ACTION_CHOICES = [(ACTION_SAVE, 'حفظ تعديل'), (ACTION_REVERT, 'رجوع للنسخة الأصلية')]

    screen_key = models.CharField(max_length=80, db_index=True)
    action     = models.CharField(max_length=10, choices=ACTION_CHOICES)
    before     = models.JSONField(null=True, blank=True)   # effective content before
    after      = models.JSONField(null=True, blank=True)   # effective content after
    note       = models.CharField(max_length=300, blank=True, default='')
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سجل تعديل شرح'
        verbose_name_plural = 'سجل تعديلات الشرح'


class HelpFeedback(models.Model):
    screen_key = models.CharField(max_length=80, db_index=True)
    tab        = models.CharField(max_length=60, blank=True, default='')
    helpful    = models.BooleanField()
    comment    = models.CharField(max_length=500, blank=True, default='')
    lang       = models.CharField(max_length=2, default='ar')
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    role       = models.CharField(max_length=20, blank=True, default='')
    resolved   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'تقييم شرح'
        verbose_name_plural = 'تقييمات الشرح'


class HelpEvent(models.Model):
    KIND_OPEN   = 'open'
    KIND_SEARCH = 'search'
    KIND_CHOICES = [(KIND_OPEN, 'فتح الشرح'), (KIND_SEARCH, 'بحث')]

    kind       = models.CharField(max_length=10, choices=KIND_CHOICES)
    screen_key = models.CharField(max_length=80, blank=True, default='', db_index=True)
    tab        = models.CharField(max_length=60, blank=True, default='')
    query      = models.CharField(max_length=200, blank=True, default='')
    results    = models.IntegerField(null=True, blank=True)   # search hits (0 = nothing found)
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    role       = models.CharField(max_length=20, blank=True, default='')
    branch_id  = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'استخدام الشرح'
        verbose_name_plural = 'استخدام الشرح'
