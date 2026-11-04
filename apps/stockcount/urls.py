from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import StockCountSessionViewSet
from .daily import views as daily

router = SimpleRouter()     # no API-root index page (Z-9c)
router.register('sessions', StockCountSessionViewSet, basename='stockcount-session')

urlpatterns = [
    path('', include(router.urls)),
    # Small daily counts (Project 2) — 404 while DAILY_COUNT_ENABLED is off.
    path('daily/my/',                    daily.my_list,       name='daily-count-my'),
    path('daily/my/count/',              daily.my_count,      name='daily-count-count'),
    path('daily/board/',                 daily.board,         name='daily-count-board'),
    path('daily/staff/',                 daily.branch_staff,  name='daily-count-staff'),
    path('daily/report/',                daily.report,        name='daily-count-report'),
    path('daily/generate/',              daily.generate_now,  name='daily-count-generate'),
    path('daily/settings/',              daily.settings_view, name='daily-count-settings'),
    path('daily/picks/<int:pk>/recount/', daily.pick_recount,  name='daily-count-recount'),
    path('daily/picks/<int:pk>/accept/',  daily.pick_accept,   name='daily-count-accept'),
    path('daily/picks/<int:pk>/escalate/', daily.pick_escalate, name='daily-count-escalate'),
]
