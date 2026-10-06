from rest_framework.routers import DefaultRouter

from .views import (CaseExceptionViewSet, ReconstructionRunViewSet, ReplacementCaseViewSet,
                    ReplacementGrantViewSet, ReplacementRuleViewSet)

router = DefaultRouter()
router.register(r'cases', ReplacementCaseViewSet, basename='replacement-case')
router.register(r'exceptions', CaseExceptionViewSet, basename='replacement-exception')
router.register(r'runs', ReconstructionRunViewSet, basename='replacement-run')
router.register(r'rules', ReplacementRuleViewSet, basename='replacement-rule')
router.register(r'grants', ReplacementGrantViewSet, basename='replacement-grant')

urlpatterns = router.urls
