from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import QATemplateListView, QAInspectionViewSet

router = DefaultRouter()
router.register(r'inspections', QAInspectionViewSet, basename='qa-inspection')

urlpatterns = [
    path('templates/', QATemplateListView.as_view(), name='qa-templates'),
] + router.urls
