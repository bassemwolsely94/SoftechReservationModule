"""
apps/crews/models.py

Crews (الأطقم) — dated cross-branch groupings of people (spec 2026-11-13 §6). Crew = who,
branch = where. Membership = (people matching an active rule ∪ manual includes) − manual
excludes, evaluated per day by apps/crews/membership.py. Rule and manual rows are end-dated
(valid_to) or voided, never edited in place, so a past month always resolves the same way.
All valid_from / valid_to are inclusive; valid_to NULL = open.
"""
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class Crew(models.Model):
    TYPE_CHOICES = [('call_center', 'كول سنتر'), ('job', 'وظيفي'), ('custom', 'مخصص')]

    name        = models.CharField(max_length=120, verbose_name='اسم الطاقم')
    type        = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='النوع')
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_by  = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    updated_by  = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'طاقم'
        verbose_name_plural = 'الأطقم'
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_archived=False),
                                    name='uniq_live_crew_name'),
        ]

    def __str__(self):
        return self.name

    def has_history(self) -> bool:
        """True once any live (not voided) rule or manual row reaches before today — the crew
        then has past membership and must be archived, not deleted."""
        today = timezone.localdate()
        return (self.rules.filter(voided_at__isnull=True, valid_from__lt=today).exists()
                or self.manual_members.filter(voided_at__isnull=True, valid_from__lt=today).exists())


class DatedRow(models.Model):
    """Shared dating for rule and manual rows. Ending = set valid_to (+ ended_by/at); voiding =
    a row entered by mistake, ignored everywhere (+ voided_by/at)."""
    valid_from = models.DateField()
    valid_to   = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    ended_by   = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    ended_at   = models.DateTimeField(null=True, blank=True)
    voided_at  = models.DateTimeField(null=True, blank=True)
    voided_by  = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=models.F('valid_from')),
                name='%(app_label)s_%(class)s_valid_range'),
        ]


class CrewRule(DatedRow):
    """Matches people by their assignment on a day. Every NON-EMPTY set must match; an empty set
    is "any"; a rule with every set empty matches nobody."""
    crew        = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name='rules')
    job_titles  = models.JSONField(default=list, blank=True)
    branches    = models.ManyToManyField('branches.Branch', related_name='+', blank=True)
    departments = models.JSONField(default=list, blank=True)
    sections    = models.JSONField(default=list, blank=True)
    note        = models.CharField(max_length=255, blank=True)

    class Meta(DatedRow.Meta):
        ordering = ['crew_id', 'valid_from', 'id']


class CrewManualMember(DatedRow):
    """A person added to or removed from a crew by hand. Off-payroll people (no Employee row) are
    held by a bare SOFTECH user code or PBX extension, flagged «خارج كشف الرواتب»."""
    MODE_CHOICES = [('include', 'إضافة'), ('exclude', 'استبعاد')]

    crew            = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name='manual_members')
    mode            = models.CharField(max_length=10, choices=MODE_CHOICES)
    employee        = models.ForeignKey('hr.Employee', null=True, blank=True, on_delete=models.PROTECT,
                                        related_name='+')
    softech_usercode = models.CharField(max_length=20, blank=True)
    pbx_extension   = models.CharField(max_length=10, blank=True)
    label           = models.CharField(max_length=120, blank=True)
    reason          = models.CharField(max_length=255)

    class Meta(DatedRow.Meta):
        ordering = ['crew_id', 'valid_from', 'id']
        constraints = DatedRow.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(employee__isnull=False) | ~Q(softech_usercode='') | ~Q(pbx_extension=''),
                name='crew_manual_member_has_identity'),
        ]
