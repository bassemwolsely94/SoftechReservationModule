from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    SeasonalityIndexViewSet, ForecastRunViewSet, ForecastAccuracyViewSet, KpiBoardView,
    ForecastScenarioViewSet, BacktestViewSet, GrowthView,
)

router = DefaultRouter()
router.register(r'seasonality',  SeasonalityIndexViewSet, basename='seasonality')
router.register(r'runs',         ForecastRunViewSet,       basename='forecast-run')
router.register(r'accuracy',     ForecastAccuracyViewSet,  basename='forecast-accuracy')
router.register(r'scenarios',    ForecastScenarioViewSet,  basename='forecast-scenario')
router.register(r'backtest',     BacktestViewSet,          basename='forecast-backtest')

urlpatterns = router.urls + [
    path('kpi-board/', KpiBoardView.as_view(), name='kpi-board'),
    path('growth/',    GrowthView.as_view(),   name='kpi-growth'),
]
