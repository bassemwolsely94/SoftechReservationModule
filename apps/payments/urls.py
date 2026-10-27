from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .audit_views import BankStatementImportViewSet, BankStatementLineViewSet, PaymentExceptionViewSet

_audit_router = DefaultRouter()
_audit_router.register(r'statements',  BankStatementImportViewSet, basename='statement-import')
_audit_router.register(r'stmt-lines',  BankStatementLineViewSet,   basename='statement-line')
_audit_router.register(r'exceptions',  PaymentExceptionViewSet,    basename='payment-exception')

urlpatterns = [
    path('audit/', include(_audit_router.urls)),

    path('', views.ExternalPaymentListView.as_view()),
    path('summary/', views.payment_summary),
    path('<int:pk>/', views.ExternalPaymentDetailView.as_view()),
    path('<int:pk>/confirm/', views.payment_confirm),
    path('<int:pk>/reconcile/', views.payment_reconcile),
    path('<int:pk>/dispute/', views.payment_dispute),
    path('<int:pk>/screenshot/', views.payment_upload_screenshot),
]
