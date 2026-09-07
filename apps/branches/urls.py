from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BranchViewSet, branch_settings

router = DefaultRouter()
router.register(r'', BranchViewSet, basename='branch')

urlpatterns = [
    path('<int:branch_id>/settings/', branch_settings, name='branch-settings'),
    path('', include(router.urls)),
]
