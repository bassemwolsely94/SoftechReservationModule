from django.urls import path
from apps.referral import views

urlpatterns = [
    path('my-code/', views.MyReferralCodeView.as_view(), name='referral-my-code'),
    path('customers/<int:customer_id>/code/', views.CustomerReferralCodeView.as_view(), name='referral-customer-code'),
    path('customers/<int:customer_id>/leads/', views.SubmitLeadView.as_view(), name='referral-submit-lead'),
    path('customers/<int:customer_id>/leads/list/', views.LeadListView.as_view(), name='referral-lead-list-customer'),
    path('leads/', views.LeadListView.as_view(), name='referral-lead-list'),
    path('leads/<int:pk>/', views.LeadDetailView.as_view(), name='referral-lead-detail'),
    path('leads/<int:lead_id>/events/', views.LeadEventListView.as_view(), name='referral-lead-events'),
    path('leads/<int:pk>/validate/', views.ValidateLeadView.as_view(), name='referral-validate-lead'),
    path('leads/<int:pk>/invite/', views.InviteLeadView.as_view(), name='referral-invite-lead'),
]
