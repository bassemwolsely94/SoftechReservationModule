from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    SeasonalityIndexViewSet, ForecastRunViewSet, ForecastAccuracyViewSet, KpiBoardView,
    KpiSheetExportView, KpiRefreshView, ForecastScenarioViewSet, BacktestViewSet, GrowthView,
    ProfitExclusionViewSet, ForecastReferenceView,
)

router = DefaultRouter()
router.register(r'seasonality',  SeasonalityIndexViewSet, basename='seasonality')
router.register(r'runs',         ForecastRunViewSet,       basename='forecast-run')
router.register(r'accuracy',     ForecastAccuracyViewSet,  basename='forecast-accuracy')
router.register(r'scenarios',    ForecastScenarioViewSet,  basename='forecast-scenario')
router.register(r'backtest',     BacktestViewSet,          basename='forecast-backtest')
router.register(r'profit-exclusions', ProfitExclusionViewSet, basename='profit-exclusion')

urlpatterns = router.urls + [
    path('kpi-board/',        KpiBoardView.as_view(),       name='kpi-board'),
    path('kpi-board/export/',  KpiSheetExportView.as_view(), name='kpi-board-export'),
    path('kpi-board/refresh/', KpiRefreshView.as_view(),     name='kpi-board-refresh'),
    path('growth/',           GrowthView.as_view(),         name='kpi-growth'),
    path('references/',       ForecastReferenceView.as_view(), name='forecast-references'),
]
