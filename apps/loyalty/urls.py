from django.urls import path
from apps.loyalty import views

urlpatterns = [
    path('tiers/', views.TierListView.as_view(), name='loyalty-tiers'),
    path('rewards/', views.RewardCatalogView.as_view(), name='loyalty-rewards'),
    path('customers/<int:customer_id>/account/', views.AccountDetailView.as_view(), name='loyalty-account'),
    path('customers/<int:customer_id>/transactions/', views.TransactionListView.as_view(), name='loyalty-transactions'),
    path('customers/<int:customer_id>/adjust/', views.AdjustPointsView.as_view(), name='loyalty-adjust'),
    path('customers/<int:customer_id>/redeem/', views.RedeemRewardView.as_view(), name='loyalty-redeem'),
    path('customers/<int:customer_id>/redemptions/', views.RedemptionListView.as_view(), name='loyalty-redemptions'),
    path('redemptions/<int:pk>/approve/', views.ApproveRedemptionView.as_view(), name='loyalty-approve-redemption'),
    # SOFTECH points bridge
    path('customers/<int:customer_id>/softech-balance/', views.SoftechBalanceView.as_view(), name='loyalty-softech-balance'),
    path('customers/<int:customer_id>/softech-log/', views.SoftechLogView.as_view(), name='loyalty-softech-log'),
]
