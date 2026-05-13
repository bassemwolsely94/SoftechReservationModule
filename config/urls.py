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
    path('api/chronic/', include('apps.chronic.urls')),
    path('api/followups/', include('apps.followups.urls')),
    path('api/callcenter/', include('apps.callcenter.urls')),
    path('api/config/',      include('apps.config.urls')),
    path('api/stockcount/',  include('apps.stockcount.urls')),
    path('api/shortage/',    include('apps.shortage.urls')),
    path('api/vouchers/',    include('apps.vouchers.urls')),
    path('api/invoices/',    include('apps.invoices.urls')),
    path('api/incentives/', include('apps.incentives.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)