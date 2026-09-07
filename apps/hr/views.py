"""
apps/hr/views.py

REST API for the HR module.

URL layout (all under /api/hr/):
  leave-types/                   — list leave types
  leave-balances/                — my balances (or all for admin/supervisor)
  leave-requests/                — CRUD + submit/cancel actions
  overtime/                      — overtime requests
  salary-advances/               — salary advance requests
  expense-claims/                — expense + mamoriya claims
  shifts/                        — shift templates (admin only)
  shift-assignments/             — assign shifts to staff
"""
import math
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    LeaveType, LeaveBalance, LeaveRequest,
    ShiftTemplate, ShiftAssignment,
    OvertimeRequest, SalaryAdvance, ExpenseClaim,
    AttendanceRecord, Permit,
)
from .serializers import (
    LeaveTypeSerializer, LeaveBalanceSerializer,
    LeaveRequestSerializer, SubmitLeaveSerializer,
    ShiftTemplateSerializer, ShiftAssignmentSerializer,
    OvertimeRequestSerializer, SubmitOvertimeSerializer,
    SalaryAdvanceSerializer, SubmitAdvanceSerializer,
    ExpenseClaimSerializer, SubmitExpenseClaimSerializer,
    PermitSerializer, SubmitPermitSerializer,
)
from .service import HrService, HrError


# ── Helpers ────────────────────────────────────────────────────────────────────

def _profile(request):
    return request.user.staff_profile

def _is_manager(profile):
    return profile.role in ('admin', 'supervisor', 'purchasing')


def _subject_kwargs(request, d):
    """Resolve the on-behalf-of subject + nominated approvers from validated data.

    subject_staff: explicit pk → that profile; else if employee_* given → non-login
    subject (None); else → self-service (the caller). Returns kwargs for HrService.
    """
    from apps.users.models import StaffProfile
    profile = _profile(request)
    sid = d.get('subject_staff')
    if sid:
        subject_staff = StaffProfile.objects.filter(pk=sid).first()
    elif d.get('employee_hr_code') or d.get('employee_name'):
        subject_staff = None            # non-login employee (office boy)
    else:
        subject_staff = profile         # self-service
    approvers = list(StaffProfile.objects.filter(pk__in=d.get('approver_ids') or [], is_active=True))
    return {
        'submitted_by':     profile,
        'subject_staff':    subject_staff,
        'employee_hr_code': d.get('employee_hr_code', ''),
        'employee_name':    d.get('employee_name', ''),
        'softech_code':     d.get('softech_code', ''),
        'nominated_approvers': approvers,
    }


# ── Leave types ────────────────────────────────────────────────────────────────

class LeaveTypeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       viewsets.GenericViewSet):
    """GET /api/hr/leave-types/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = LeaveTypeSerializer
    queryset           = LeaveType.objects.filter(is_active=True)


# ── Leave balances ─────────────────────────────────────────────────────────────

class LeaveBalanceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    GET /api/hr/leave-balances/          — my balances
    GET /api/hr/leave-balances/?staff=X  — admin/supervisor: another employee
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = LeaveBalanceSerializer

    def get_queryset(self):
        profile    = _profile(self.request)
        target_id  = self.request.query_params.get('staff')
        if target_id and _is_manager(profile):
            return LeaveBalance.objects.filter(staff_id=target_id).select_related('leave_type')
        return LeaveBalance.objects.filter(staff=profile).select_related('leave_type')


# ── Leave requests ─────────────────────────────────────────────────────────────

class LeaveRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """
    GET  /api/hr/leave-requests/              — list (own or all for manager)
    GET  /api/hr/leave-requests/{id}/         — detail
    POST /api/hr/leave-requests/submit/       — create + submit
    POST /api/hr/leave-requests/{id}/cancel/  — cancel
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = LeaveRequestSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = LeaveRequest.objects.select_related('staff', 'leave_type', 'approval_request', 'submitted_by')
        if _is_manager(profile):
            if self.request.query_params.get('staff'):
                qs = qs.filter(staff_id=self.request.query_params['staff'])
        else:
            qs = qs.filter(Q(staff=profile) | Q(submitted_by=profile))

        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])

        return qs.order_by('-created_at')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        profile    = _profile(request)
        serializer = SubmitLeaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            leave = HrService.submit_leave(
                leave_type_code=d['leave_type_code'],
                start_date=d['start_date'],
                end_date=d['end_date'],
                days=d['days_requested'],
                reason=d.get('reason', ''),
                return_to_work_date=d.get('return_to_work_date'),
                **_subject_kwargs(request, d),
            )
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeaveRequestSerializer(leave).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        leave = self.get_object()
        try:
            HrService.cancel_leave(leave=leave, cancelled_by=_profile(request))
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'تم الإلغاء.'})


# ── Overtime ───────────────────────────────────────────────────────────────────

class OvertimeRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                              viewsets.GenericViewSet):
    """
    GET  /api/hr/overtime/
    GET  /api/hr/overtime/{id}/
    POST /api/hr/overtime/submit/
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = OvertimeRequestSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = OvertimeRequest.objects.select_related('staff', 'branch', 'submitted_by')
        if not _is_manager(profile):
            qs = qs.filter(Q(staff=profile) | Q(submitted_by=profile))
        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])
        return qs.order_by('-date', '-created_at')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        profile    = _profile(request)
        serializer = SubmitOvertimeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            ot = HrService.submit_overtime(
                branch=profile.branch,
                date=d['date'],
                hours=d['hours'],
                reason=d['reason'],
                **_subject_kwargs(request, d),
            )
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OvertimeRequestSerializer(ot).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            HrService.cancel_request(obj=self.get_object(), cancelled_by=_profile(request))
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'تم الإلغاء.'})


# ── Salary advance ─────────────────────────────────────────────────────────────

class SalaryAdvanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            viewsets.GenericViewSet):
    """
    GET  /api/hr/salary-advances/
    GET  /api/hr/salary-advances/{id}/
    POST /api/hr/salary-advances/submit/
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = SalaryAdvanceSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = SalaryAdvance.objects.select_related('staff', 'submitted_by')
        if not _is_manager(profile):
            qs = qs.filter(Q(staff=profile) | Q(submitted_by=profile))
        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])
        return qs.order_by('-created_at')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        profile    = _profile(request)
        serializer = SubmitAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            advance = HrService.submit_salary_advance(
                amount=d['amount'],
                repayment_date=d['repayment_date'],
                reason=d['reason'],
                **_subject_kwargs(request, d),
            )
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SalaryAdvanceSerializer(advance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            HrService.cancel_request(obj=self.get_object(), cancelled_by=_profile(request))
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'تم الإلغاء.'})


# ── Expense claims ─────────────────────────────────────────────────────────────

class ExpenseClaimViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """
    GET  /api/hr/expense-claims/
    GET  /api/hr/expense-claims/{id}/
    POST /api/hr/expense-claims/submit/
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ExpenseClaimSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = ExpenseClaim.objects.select_related('staff', 'branch', 'submitted_by')
        if not _is_manager(profile):
            qs = qs.filter(Q(staff=profile) | Q(submitted_by=profile))
        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])
        if self.request.query_params.get('category'):
            qs = qs.filter(category=self.request.query_params['category'])
        return qs.order_by('-created_at')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        profile    = _profile(request)
        serializer = SubmitExpenseClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        trip_fields = [
            'trip_destination', 'trip_purpose', 'trip_start', 'trip_end',
            'distance_km', 'transport_type', 'allowance_amount',
        ]
        trip_data = {k: d[k] for k in trip_fields if d.get(k) not in (None, '', 0)}

        try:
            claim = HrService.submit_expense_claim(
                branch=profile.branch,
                category=d['category'],
                expense_date=d['expense_date'],
                amount=d['amount'],
                description=d['description'],
                trip_data=trip_data,
                **_subject_kwargs(request, d),
            )
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseClaimSerializer(claim).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            HrService.cancel_request(obj=self.get_object(), cancelled_by=_profile(request))
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'تم الإلغاء.'})


# ── Permits (اذن مأمورية / اذن تعديل شيفت) ──────────────────────────────────────

class PermitViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                    viewsets.GenericViewSet):
    """
    GET  /api/hr/permits/
    GET  /api/hr/permits/{id}/
    POST /api/hr/permits/submit/
    POST /api/hr/permits/{id}/cancel/
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = PermitSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = Permit.objects.select_related('staff', 'branch', 'submitted_by')
        if not _is_manager(profile):
            qs = qs.filter(Q(staff=profile) | Q(submitted_by=profile))
        elif self.request.query_params.get('staff'):
            qs = qs.filter(staff_id=self.request.query_params['staff'])
        if self.request.query_params.get('permit_type'):
            qs = qs.filter(permit_type=self.request.query_params['permit_type'])
        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])
        return qs.order_by('-date', '-created_at')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        profile    = _profile(request)
        serializer = SubmitPermitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            permit = HrService.submit_permit(
                branch=profile.branch,
                permit_type=d['permit_type'],
                date=d['date'],
                time_from=d['time_from'],
                time_to=d.get('time_to'),
                destination=d.get('destination', ''),
                reason=d.get('reason', ''),
                **_subject_kwargs(request, d),
            )
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PermitSerializer(permit).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            HrService.cancel_request(obj=self.get_object(), cancelled_by=_profile(request))
        except HrError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'تم الإلغاء.'})


# ── Shift templates (admin/supervisor) ─────────────────────────────────────────

class ShiftTemplateViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            mixins.CreateModelMixin, mixins.UpdateModelMixin,
                            viewsets.GenericViewSet):
    """GET/POST/PATCH /api/hr/shifts/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = ShiftTemplateSerializer

    def get_queryset(self):
        qs = ShiftTemplate.objects.select_related('branch')
        if self.request.query_params.get('branch'):
            qs = qs.filter(branch_id=self.request.query_params['branch'])
        return qs.filter(is_active=True)

    def perform_create(self, serializer):
        profile = _profile(self.request)
        if not _is_manager(profile):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('يمكن للمديرين فقط إنشاء نماذج الشيفت.')
        serializer.save()


# ── Shift assignments ──────────────────────────────────────────────────────────

class ShiftAssignmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                              mixins.CreateModelMixin,
                              viewsets.GenericViewSet):
    """GET/POST /api/hr/shift-assignments/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = ShiftAssignmentSerializer

    def get_queryset(self):
        profile = _profile(self.request)
        qs = ShiftAssignment.objects.select_related('staff', 'shift')
        if not _is_manager(profile):
            qs = qs.filter(staff=profile)
        elif self.request.query_params.get('staff'):
            qs = qs.filter(staff_id=self.request.query_params['staff'])
        return qs.order_by('-valid_from')

    def perform_create(self, serializer):
        serializer.save(assigned_by=_profile(self.request))


# ── Attendance (geofenced clock in/out) ──────────────────────────────────────

GEOFENCE_RADIUS_M = 200   # max metres from the branch to count as "on site"


def _haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two lat/lng points."""
    r = 6371000.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlmb = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _attendance_dict(rec):
    return {
        'id': rec.id, 'work_date': rec.work_date,
        'staff_name': rec.staff.full_name if rec.staff_id else None,
        'branch_name': (rec.branch.name_ar or rec.branch.name) if rec.branch_id else None,
        'check_in_at': rec.check_in_at, 'check_in_distance_m': rec.check_in_distance_m, 'check_in_ok': rec.check_in_ok,
        'check_out_at': rec.check_out_at, 'check_out_distance_m': rec.check_out_distance_m, 'check_out_ok': rec.check_out_ok,
        'is_open': rec.check_out_at is None,
    }


class AttendanceViewSet(viewsets.ViewSet):
    """GET /api/hr/attendance/ (list), /status/, POST /check-in/, /check-out/."""
    permission_classes = [IsAuthenticated]

    def _geofence(self, branch, lat, lng):
        """Return (distance_m, ok). ok is None when branch coords are unknown."""
        if branch and branch.latitude is not None and branch.longitude is not None and lat and lng:
            d = int(round(_haversine_m(branch.latitude, branch.longitude, lat, lng)))
            return d, (d <= GEOFENCE_RADIUS_M)
        return None, None

    def list(self, request):
        profile = _profile(request)
        qs = AttendanceRecord.objects.select_related('staff__user', 'branch')
        if not _is_manager(profile):
            qs = qs.filter(staff=profile)
        else:
            if request.query_params.get('staff'):
                qs = qs.filter(staff_id=request.query_params['staff'])
            if request.query_params.get('branch'):
                qs = qs.filter(branch_id=request.query_params['branch'])
        if request.query_params.get('date'):
            qs = qs.filter(work_date=request.query_params['date'])
        return Response([_attendance_dict(r) for r in qs[:100]])

    @action(detail=False, methods=['get'])
    def status(self, request):
        """Today's record for the current user (open/closed), or null."""
        profile = _profile(request)
        rec = AttendanceRecord.objects.filter(
            staff=profile, work_date=timezone.localdate()
        ).order_by('-check_in_at').first()
        return Response(_attendance_dict(rec) if rec else {'none': True})

    @action(detail=False, methods=['post'], url_path='check-in')
    def check_in(self, request):
        profile = _profile(request)
        today = timezone.localdate()
        open_rec = AttendanceRecord.objects.filter(
            staff=profile, work_date=today, check_out_at__isnull=True
        ).first()
        if open_rec:
            return Response({'detail': 'لديك حضور مفتوح بالفعل اليوم — سجّل الانصراف أولاً'},
                            status=status.HTTP_400_BAD_REQUEST)
        lat = request.data.get('lat'); lng = request.data.get('lng')
        branch = profile.branch
        dist, ok = self._geofence(branch, lat, lng)
        rec = AttendanceRecord.objects.create(
            staff=profile, branch=branch, work_date=today,
            check_in_lat=lat or None, check_in_lng=lng or None,
            check_in_distance_m=dist, check_in_ok=ok,
        )
        return Response(_attendance_dict(rec), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='check-out')
    def check_out(self, request):
        profile = _profile(request)
        rec = AttendanceRecord.objects.filter(
            staff=profile, work_date=timezone.localdate(), check_out_at__isnull=True
        ).order_by('-check_in_at').first()
        if not rec:
            return Response({'detail': 'لا يوجد حضور مفتوح لتسجيل الانصراف'},
                            status=status.HTTP_400_BAD_REQUEST)
        lat = request.data.get('lat'); lng = request.data.get('lng')
        dist, ok = self._geofence(rec.branch, lat, lng)
        rec.check_out_at = timezone.now()
        rec.check_out_lat = lat or None
        rec.check_out_lng = lng or None
        rec.check_out_distance_m = dist
        rec.check_out_ok = ok
        rec.save(update_fields=['check_out_at', 'check_out_lat', 'check_out_lng',
                                'check_out_distance_m', 'check_out_ok'])
        return Response(_attendance_dict(rec))
