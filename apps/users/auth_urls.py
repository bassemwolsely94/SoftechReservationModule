from django.urls import path
from .views import login_view, refresh_view, me_view, change_password_view
from .mfa import (
    verify_2fa_view, setup_2fa_view, enable_2fa_view, disable_2fa_view, status_2fa_view,
)

urlpatterns = [
    path('login/',           login_view),
    path('refresh/',         refresh_view),
    path('me/',              me_view),
    path('change-password/', change_password_view),

    # Two-factor authentication (TOTP)
    path('2fa/verify/',      verify_2fa_view),
    path('2fa/setup/',       setup_2fa_view),
    path('2fa/enable/',      enable_2fa_view),
    path('2fa/disable/',     disable_2fa_view),
    path('2fa/status/',      status_2fa_view),
]
