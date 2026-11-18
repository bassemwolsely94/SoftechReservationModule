from django.urls import path

from . import views

urlpatterns = [
    path('channels/', views.ChannelListCreate.as_view(), name='marketplace-channels'),
    path('channels/<int:pk>/', views.ChannelDetail.as_view(), name='marketplace-channel'),
    path('channels/<int:pk>/push-stock/', views.ChannelPushStock.as_view(), name='marketplace-push-stock'),
    path('stores/', views.StoreListCreate.as_view(), name='marketplace-stores'),
    path('stores/<int:pk>/', views.StoreDetail.as_view(), name='marketplace-store'),
    path('listings/', views.ListingListCreate.as_view(), name='marketplace-listings'),
    path('listings/<int:pk>/approve/', views.ListingApprove.as_view(), name='marketplace-listing-approve'),
    path('listings/<int:pk>/unapprove/', views.ListingUnapprove.as_view(), name='marketplace-listing-unapprove'),
    path('orders/', views.OrderList.as_view(), name='marketplace-orders'),
    path('orders/manual/', views.OrderManual.as_view(), name='marketplace-order-manual'),
    path('orders/<int:pk>/', views.OrderDetail.as_view(), name='marketplace-order'),
    path('orders/<int:pk>/accept/', views.OrderAccept.as_view(), name='marketplace-order-accept'),
    path('orders/<int:pk>/reject/', views.OrderReject.as_view(), name='marketplace-order-reject'),
    path('orders/<int:pk>/status/', views.OrderStatus.as_view(), name='marketplace-order-status'),
    path('settlements/', views.SettlementListCreate.as_view(), name='marketplace-settlements'),
    path('settlements/<int:pk>/', views.SettlementDetail.as_view(), name='marketplace-settlement'),
    path('push-log/', views.PushLogList.as_view(), name='marketplace-push-log'),
    path('webhooks/<slug:channel_code>/', views.WebhookView.as_view(), name='marketplace-webhook'),
]
