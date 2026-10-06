from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'', views.OfferViewSet, basename='offer')

urlpatterns = [
    path('evaluate/', views.evaluate, name='offer-evaluate'),
    path('margin-config/', views.margin_config, name='offer-margin-config'),
    path('target-fields/',  views.target_fields,  name='offer-target-fields'),
    path('field-values/',   views.field_values,   name='offer-field-values'),
    path('target-preview/', views.target_preview, name='offer-target-preview'),
    path('apply-to-order/', views.apply_to_order, name='offer-apply-to-order'),
    path('manual-matches/', views.manual_matches, name='offer-manual-matches'),
    path('detect-manual/', views.run_manual_detection, name='offer-run-detection'),
    path('', include(router.urls)),
]
