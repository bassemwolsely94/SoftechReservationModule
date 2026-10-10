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
  HelpLearned   — onboarding checklist: «فهمت هذه الشاشة» per staff + screen.
  HelpQuizAttempt — server-graded module quiz attempts.
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
    KIND_ASK    = 'ask'
    KIND_CHOICES = [(KIND_OPEN, 'فتح الشرح'), (KIND_SEARCH, 'بحث'), (KIND_ASK, 'اسأل النظام')]

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


class HelpLearned(models.Model):
    """A staff member ticked «فهمت هذه الشاشة» on one screen's help (onboarding
    checklist). `version` is the help's `updated` date at that moment — when the
    text changes later, the item shows «اتغيّر الشرح — راجعه تاني»."""
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='+')
    screen_key = models.CharField(max_length=80)
    version    = models.CharField(max_length=10, blank=True, default='')
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['staff', 'screen_key'], name='help_learned_once')]
        verbose_name = 'شاشة تم فهمها'
        verbose_name_plural = 'مسار التدريب — الشاشات المفهومة'


class HelpQuizAttempt(models.Model):
    """One submitted module quiz. Graded on the server (onboarding.QUIZZES); the
    answers chosen are kept so a trainer can see which question trips people up."""
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='+')
    module_key = models.CharField(max_length=40, db_index=True)
    score      = models.PositiveSmallIntegerField()
    total      = models.PositiveSmallIntegerField()
    passed     = models.BooleanField()
    answers    = models.JSONField(default=list)   # chosen option index per question (None = skipped)
    # hash of the questions answered (training.quiz_version) — a pass counts only
    # while the quiz is unchanged; after a trainer/developer edit it must be retaken
    version    = models.CharField(max_length=16, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'محاولة اختبار'
        verbose_name_plural = 'محاولات الاختبارات'


class HelpTrainingOverride(models.Model):
    """A trainer's version of a role's training path or a module's quiz, replacing the
    repo one (content/onboarding.py) until reverted. History → HelpRevision with
    screen_key 'path:<role>' / 'quiz:<module>'."""
    KIND_PATH = 'path'
    KIND_QUIZ = 'quiz'
    KIND_CHOICES = [(KIND_PATH, 'مسار تدريبي لدور'), (KIND_QUIZ, 'اختبار موديول')]

    kind       = models.CharField(max_length=10, choices=KIND_CHOICES)
    key        = models.CharField(max_length=40)          # role or module key
    data       = models.JSONField(default=dict)           # {'screens': [...]} or {'questions': [...]}
    base_hash  = models.CharField(max_length=64, blank=True, default='')
    updated_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'key'], name='help_training_override_once')]
        verbose_name = 'تعديل مسار/اختبار تدريبي'
        verbose_name_plural = 'تعديلات المسارات والاختبارات'
