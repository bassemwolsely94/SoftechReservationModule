from django.urls import path
from rest_framework.routers import DefaultRouter
from . import merge_views
from .views import CustomerViewSet

router = DefaultRouter()
router.register(r'', CustomerViewSet, basename='customer')

# Explicit paths first — the router's detail route would otherwise capture 'merge-candidates/'.
urlpatterns = [
    path('merge-candidates/', merge_views.candidates, name='merge-candidates'),
    path('merge-candidates/bulk/', merge_views.bulk, name='merge-candidates-bulk'),
    path('merge-candidates/<int:pk>/<str:action>/', merge_views.act, name='merge-candidates-act'),
] + router.urls
