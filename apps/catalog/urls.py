from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, ItemViewSet

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'', ItemViewSet, basename='item')

urlpatterns = router.urls
