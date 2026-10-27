from rest_framework.routers import DefaultRouter
from .views import (
    LeaveTypeViewSet, LeaveBalanceViewSet, LeaveRequestViewSet,
    OvertimeRequestViewSet, SalaryAdvanceViewSet, ExpenseClaimViewSet,
    ShiftTemplateViewSet, ShiftAssignmentViewSet, AttendanceViewSet,
    PermitViewSet,
)

router = DefaultRouter()
router.register(r'leave-types',        LeaveTypeViewSet,        basename='leave-type')
router.register(r'leave-balances',     LeaveBalanceViewSet,     basename='leave-balance')
router.register(r'leave-requests',     LeaveRequestViewSet,     basename='leave-request')
router.register(r'overtime',           OvertimeRequestViewSet,  basename='overtime')
router.register(r'salary-advances',    SalaryAdvanceViewSet,    basename='salary-advance')
router.register(r'expense-claims',     ExpenseClaimViewSet,     basename='expense-claim')
router.register(r'permits',            PermitViewSet,           basename='permit')
router.register(r'shifts',             ShiftTemplateViewSet,    basename='shift')
router.register(r'shift-assignments',  ShiftAssignmentViewSet,  basename='shift-assignment')
router.register(r'attendance',         AttendanceViewSet,       basename='attendance')

urlpatterns = router.urls
