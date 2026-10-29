from rest_framework.routers import SimpleRouter

from .views import (CaseExceptionViewSet, ReconstructionRunViewSet, ReplacementCaseViewSet,
                    ReplacementGrantViewSet, ReplacementRuleViewSet)

router = SimpleRouter()     # no API-root index page (Z-9c)
router.register(r'cases', ReplacementCaseViewSet, basename='replacement-case')
router.register(r'exceptions', CaseExceptionViewSet, basename='replacement-exception')
router.register(r'runs', ReconstructionRunViewSet, basename='replacement-run')
router.register(r'rules', ReplacementRuleViewSet, basename='replacement-rule')
router.register(r'grants', ReplacementGrantViewSet, basename='replacement-grant')

urlpatterns = router.urls
