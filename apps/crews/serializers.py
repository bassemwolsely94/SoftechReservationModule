"""
apps/crews/serializers.py

Input validation for the /api/crews/ writes and the JSON shapes the screen reads. Business rules
(month lock, end / void, name uniqueness) live in services.py, not here.
"""
from django.utils import timezone
from rest_framework import serializers

from apps.hr.models import Employee

from .models import Crew, CrewManualMember
from .unattributed import branch_label

def _text_list():
    return serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=True),
                                 required=False, default=list)


class CrewInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    type = serializers.ChoiceField(choices=Crew.TYPE_CHOICES)
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_name(self, v):
        v = v.strip()
        if not v:
            raise serializers.ValidationError('الاسم مطلوب.')
        return v


class RuleInput(serializers.Serializer):
    job_titles = _text_list()
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    departments = _text_list()
    sections = _text_list()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    valid_to = serializers.DateField(required=False, allow_null=True, default=None)


class PreviewRule(serializers.Serializer):
    job_titles = _text_list()
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    departments = _text_list()
    sections = _text_list()


class PreviewInput(serializers.Serializer):
    rules = PreviewRule(many=True)
    date = serializers.DateField(required=False, allow_null=True, default=None)
    crew_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class ManualInput(serializers.Serializer):
    mode = serializers.ChoiceField(choices=CrewManualMember.MODE_CHOICES)
    employee_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    softech_usercode = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    pbx_extension = serializers.CharField(max_length=10, required=False, allow_blank=True, default='')
    label = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    reason = serializers.CharField(max_length=255)
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    valid_to = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        emp_id = attrs.pop('employee_id', None)
        attrs['employee'] = None
        if emp_id is not None:
            attrs['employee'] = Employee.objects.filter(pk=emp_id).first()
            if attrs['employee'] is None:
                raise serializers.ValidationError({'employee_id': 'موظف غير موجود.'})
        return attrs


class EndInput(serializers.Serializer):
    on = serializers.DateField()


class GenericRuleInput(serializers.Serializer):
    groups = serializers.ListField(child=serializers.CharField(max_length=50), required=False, default=list)
    usercodes = serializers.ListField(child=serializers.CharField(max_length=20), required=False, default=list)


# ── output ───────────────────────────────────────────────────────────────────

def _name(profile):
    return profile.full_name if profile else ''


def row_status(row, today=None) -> str:
    today = today or timezone.localdate()
    if row.voided_at is not None:
        return 'voided'
    if row.valid_from > today:
        return 'future'
    if row.valid_to is not None and row.valid_to < today:
        return 'ended'
    return 'active'


def _dated(row, today) -> dict:
    return {'id': row.id, 'valid_from': row.valid_from, 'valid_to': row.valid_to,
            'status': row_status(row, today),
            'created_by_name': _name(row.created_by), 'created_at': row.created_at,
            'ended_by_name': _name(row.ended_by), 'ended_at': row.ended_at,
            'voided_by_name': _name(row.voided_by), 'voided_at': row.voided_at}


def rule_out(rule, today=None) -> dict:
    branches = sorted(rule.branches.all(), key=lambda b: branch_label(b))
    return {**_dated(rule, today), 'job_titles': rule.job_titles, 'departments': rule.departments,
            'sections': rule.sections, 'note': rule.note,
            'branch_ids': [b.id for b in branches], 'branch_labels': [branch_label(b) for b in branches]}


def manual_out(row, today=None) -> dict:
    e = row.employee
    return {**_dated(row, today), 'mode': row.mode, 'mode_label': row.get_mode_display(),
            'employee_id': row.employee_id, 'employee_name': e.name_ar if e else '',
            'hr_number': e.hr_number if e else '', 'softech_usercode': row.softech_usercode,
            'pbx_extension': row.pbx_extension, 'label': row.label, 'reason': row.reason,
            'off_payroll': row.employee_id is None}


def member_key(key) -> str:
    return f'{key[0]}:{key[1]}'


def member_out(m, labels: dict) -> dict:
    return {'key': member_key(m.key), 'employee_id': m.employee_id, 'name': m.name, 'hr_number': m.hr_number,
            'job_title': m.job_title, 'branch_id': m.branch_id, 'branch_label': labels.get(m.branch_id, ''),
            'softech_usercodes': list(m.softech_usercodes), 'extensions': list(m.extensions),
            'staff_id': m.staff_id, 'off_payroll': m.off_payroll, 'source': m.source}
