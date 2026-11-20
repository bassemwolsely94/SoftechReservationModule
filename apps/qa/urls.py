from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import FridgeReadingViewSet, FridgeUnitViewSet, QATemplateListView, QAInspectionViewSet

router = DefaultRouter()
router.register(r'inspections', QAInspectionViewSet, basename='qa-inspection')
router.register(r'fridges', FridgeUnitViewSet, basename='qa-fridge')                  # C31
router.register(r'fridge-readings', FridgeReadingViewSet, basename='qa-fridge-reading')  # C31

urlpatterns = [
    path('templates/', QATemplateListView.as_view(), name='qa-templates'),
] + router.urls
