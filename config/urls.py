from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.auth_urls')),
    path('api/reservations/', include('apps.reservations.urls')),
    path('api/customers/', include('apps.customers.urls')),
    path('api/items/', include('apps.catalog.urls')),
    path('api/branches/', include('apps.branches.urls')),
    path('api/sync/', include('apps.sync.urls')),
    path('api/dashboard/', include('apps.dashboard.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/transfers/', include('apps.transfers.urls')),
    path('api/demand/', include('apps.demand.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)