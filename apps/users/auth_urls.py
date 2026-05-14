from django.urls import path
from .views import login_view, refresh_view, me_view, change_password_view

urlpatterns = [
    path('login/',           login_view),
    path('refresh/',         refresh_view),
    path('me/',              me_view),
    path('change-password/', change_password_view),
]
