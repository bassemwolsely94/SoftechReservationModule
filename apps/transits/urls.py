from rest_framework.routers import DefaultRouter
from .views import (
    InTransitTransferViewSet,
    ItemPickOverrideViewSet,
    PickZoneRuleViewSet,
    PickZoneViewSet,
)

router = DefaultRouter()
# NOTE: specific prefixes MUST be registered before the '' catch-all so their
# routes resolve first (otherwise /pick-zones/ matches the transfer detail pk).
router.register(r'pick-zones', PickZoneViewSet, basename='pick-zone')
router.register(r'pick-rules', PickZoneRuleViewSet, basename='pick-rule')
router.register(r'item-overrides', ItemPickOverrideViewSet, basename='item-override')
router.register(r'', InTransitTransferViewSet, basename='transit-transfer')

urlpatterns = router.urls
