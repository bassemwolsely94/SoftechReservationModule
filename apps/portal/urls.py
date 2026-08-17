from django.urls import path

from apps.portal import views

urlpatterns = [
    # Public entry points (no session)
    path('request-link/', views.request_link, name='portal-request-link'),
    path('auth/',         views.auth_exchange, name='portal-auth'),

    # Session-scoped (customer-only) endpoints
    path('me/',       views.me,       name='portal-me'),
    path('orders/',   views.orders,   name='portal-orders'),
    path('loyalty/',  views.loyalty,  name='portal-loyalty'),
    path('refills/',  views.refills,  name='portal-refills'),
    path('reorder/',  views.reorder,  name='portal-reorder'),
]
