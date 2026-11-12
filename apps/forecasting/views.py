"""
Forecasting ViewSets
====================
SeasonalityIndexViewSet  — CRUD for seasonal indices
ForecastRunViewSet       — trigger runs, browse history
ForecastAccuracyViewSet  — browse back-test results
"""
import logging
from datetime import date

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    SeasonalityIndex, ForecastRun, ForecastAccuracy, KpiActualRollup,
    ForecastScenario, ForecastFactor, ForecastResult, BacktestRun, ProfitExclusion,
)
from .serializers import (
    SeasonalityIndexSerializer, ForecastRunSerializer, ForecastAccuracySerializer,
    ForecastScenarioSerializer, ForecastFactorSerializer, ForecastResultSerializer,
    BacktestRunSerializer, ProfitExclusionSerializer,
)
from .service import ForecastService
from .engine import ForecastEngine
from .backtest import BacktestService
from core.threads import start_thread
from core.export_safety import neutralise_formulas
from django.db.models import Value
from django.db.models.functions import Coalesce, Concat, NullIf, Trim
from core.sort_ordering import NullsLastOrderingFilter as NullsLastOrdering


logger = logging.getLogger('elrezeiky')

ANALYST_ROLES = {'admin', 'supervisor', 'purchasing'}


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _is_analyst(request):
    sp = _staff(request)
    return sp and sp.role in ANALYST_ROLES


class CanUseForecasting(BasePermission):
    """Forecasting is the `analytics` module (owner decision 2026-10-28, Batch 4 Z-7b): reads
    need analytics view; every write also needs an analyst role (ANALYST_ROLES) — the inner
    _guard / _is_analyst checks stay. Was: any logged-in user, and the seasonality / accuracy
    viewsets let anyone create, edit or delete records."""
    message = 'ليس لديك صلاحية على هذه الوحدة'

    def has_permission(self, request, view):
        from core.permissions import matrix_allows
        if view is not None and not hasattr(view, request.method.lower()):
            return True                                  # no handler for the method: DRF answers 405
        sp = _staff(request)
        if not matrix_allows(sp, 'analytics', 'view'):
            return False
        return request.method in SAFE_METHODS or bool(sp and sp.role in ANALYST_ROLES)


class SeasonalityIndexViewSet(viewsets.ModelViewSet):
    serializer_class   = SeasonalityIndexSerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    # sortable grid: the page is cut at 50, so the headers sort on the server (explicit whitelist)
    filter_backends    = [NullsLastOrdering]
    ordering_fields    = ['item__name', 'category__name', 'month', 'index_value', 'computed_at']

    def get_queryset(self):
        qs    = SeasonalityIndex.objects.select_related('item', 'category')
        item  = self.request.query_params.get('item')
        cat   = self.request.query_params.get('category')
        month = self.request.query_params.get('month')
        if item:
            qs = qs.filter(item_id=item)
        if cat:
            qs = qs.filter(category_id=cat)
        if month:
            qs = qs.filter(month=month)
        return qs

    @action(detail=False, methods=['post'], url_path='compute')
    def compute(self, request):
        """Compute and store seasonality indices from historical sales for an item."""
        if not _is_analyst(request):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        item_id = request.data.get('item_id')
        years   = int(request.data.get('years', 2))

        if not item_id:
            return Response({'detail': 'item_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            results = ForecastService.compute_seasonality_indices(int(item_id), years=years)
            return Response({'months': [{'month': m, 'index': float(v)} for m, v in results]})
        except Exception:
            logger.exception('seasonality compute failed for item=%s', item_id)
            return Response({'detail': 'فشل حساب المؤشرات الموسمية'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ForecastRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = ForecastRunSerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    # «بواسطة» sorts by the name the grid shows (triggered_by_name = StaffProfile.full_name)
    queryset           = (ForecastRun.objects.select_related('triggered_by__user').annotate(
        triggered_by_sort=Coalesce(
            NullIf(Trim(Concat('triggered_by__user__first_name', Value(' '), 'triggered_by__user__last_name')), Value('')),
            NullIf(Trim('triggered_by__softech_username'), Value('')),
            'triggered_by__user__username'))
        .order_by('-started_at'))
    filter_backends    = [NullsLastOrdering]
    ordering_fields    = ['started_at', 'completed_at', 'items_processed', 'status', 'triggered_by_sort']

    @action(detail=False, methods=['post'], url_path='trigger')
    def trigger(self, request):
        """Manually trigger a full forecast run (async-friendly but runs synchronously here)."""
        if not _is_analyst(request):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        branch_ids = request.data.get('branch_ids')
        item_ids   = request.data.get('item_ids')

        try:
            result = ForecastService.run_forecast(
                triggered_by = _staff(request),
                branch_ids   = branch_ids,
                item_ids     = item_ids,
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except Exception:
            logger.exception('Manual forecast trigger failed')
            return Response({'detail': 'فشل تشغيل التنبؤ'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ForecastAccuracyViewSet(viewsets.ModelViewSet):
    serializer_class   = ForecastAccuracySerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    filter_backends    = [NullsLastOrdering]
    ordering_fields    = ['item__name', 'branch__name', 'forecast_date', 'forecast_30d',
                          'actual_30d', 'mape', 'mae']

    def get_queryset(self):
        qs     = ForecastAccuracy.objects.select_related('item', 'branch')
        item   = self.request.query_params.get('item')
        branch = self.request.query_params.get('branch')
        if item:
            qs = qs.filter(item_id=item)
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs

    @action(detail=True, methods=['post'], url_path='update-actual')
    def update_actual(self, request, pk=None):
        """Record the actual 30-day demand and recalculate accuracy metrics."""
        record     = self.get_object()
        actual_30d = request.data.get('actual_30d')
        if actual_30d is None:
            return Response({'detail': 'actual_30d مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        from decimal import Decimal
        actual = Decimal(str(actual_30d))
        record.actual_30d = actual

        # MAPE = |forecast - actual| / actual * 100
        if actual:
            record.mape = abs(record.forecast_30d - actual) / actual * Decimal('100')
            record.mae  = abs(record.forecast_30d - actual)

        record.save(update_fields=['actual_30d', 'mape', 'mae'])
        return Response(ForecastAccuracySerializer(record).data)


# ════════════════════════════════════════════════════════════════════════════
# KPI Board (doc 16, Phase 2) — Excel-style branch × metric matrix for a month:
# actuals from KpiActualRollup + matched SalesTargets + attainment/pace.
# ════════════════════════════════════════════════════════════════════════════

from .kpi_board import BOARD_METRICS  # noqa: E402  (board maths live in kpi_board)


class KpiBoardView(APIView):
    """GET /api/forecasting/kpi-board/?year=&month= — branch KPI grid + chain totals.
    Targets come from the editable SalesTargets; % is achievement vs the target PRO-RATED
    to the latest complete data day (owner convention, == legacy sheet H/I)."""
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        from apps.branches.models import Branch
        from apps.incentives.models import SalesTarget
        from apps.forecasting import kpi_board

        today = date.today()
        year  = int(request.query_params.get('year',  today.year))
        month = int(request.query_params.get('month', today.month))

        m_start, m_end, data_through, total, elapsed, frac = kpi_board.month_pacing(year, month)

        # actuals from rollups (rebuilt daily) → {(branch_id, metric): value}
        rollups = KpiActualRollup.objects.filter(
            year=year, month=month, metric__in=BOARD_METRICS,
        ).values('branch_id', 'metric', 'value')
        actual = {(r['branch_id'], r['metric']): float(r['value']) for r in rollups}
        branch_ids_with_data = {r['branch_id'] for r in rollups}

        # editable targets overlapping the month (branch + chain scope) → value + id
        tqs = kpi_board.month_targets(m_start, m_end, BOARD_METRICS,
                                      [SalesTarget.SCOPE_BRANCH, SalesTarget.SCOPE_CHAIN])
        branch_target = {}
        chain_target  = {}
        for t in tqs:
            tv = float(t['target_value'] or 0)
            if t['scope_type'] == SalesTarget.SCOPE_BRANCH and t['branch_id']:
                branch_target[(t['branch_id'], t['metric'])] = (tv, t['id'])
            elif t['scope_type'] == SalesTarget.SCOPE_CHAIN:
                chain_target[t['metric']] = (tv, t['id'])

        from apps.forecasting.kpi import analytics_branches
        branches = (analytics_branches().filter(id__in=branch_ids_with_data)
                    .order_by('code', 'softech_branch_id')) if branch_ids_with_data else []

        def cell(a, t, tid=None):
            return kpi_board.make_cell(a, t, tid, data_through, m_end, frac)

        rows = []
        totals_actual = {m: 0.0 for m in BOARD_METRICS}
        totals_target = {m: 0.0 for m in BOARD_METRICS}
        for b in branches:
            cells = {}
            for m in BOARD_METRICS:
                a = actual.get((b.id, m), 0.0)
                t, tid = branch_target.get((b.id, m), (0.0, None))
                cells[m] = cell(a, t, tid)
                totals_actual[m] += a
                totals_target[m] += t
            rows.append({
                'branch_id': b.id, 'code': b.code or b.softech_branch_id,
                'name': getattr(b, 'name_ar', '') or b.name, 'cells': cells,
            })

        totals = {}
        for m in BOARD_METRICS:
            ct = chain_target.get(m)
            t = ct[0] if ct else totals_target[m]
            totals[m] = cell(totals_actual[m], t, ct[1] if ct else None)

        call_center = self._call_center_block(year, month, cell, m_start, m_end)

        return Response({
            'year': year, 'month': month,
            'has_data': bool(branch_ids_with_data),
            'data_through': data_through.isoformat() if data_through else None,
            'days_elapsed': elapsed, 'days_total': total,
            'metrics': [{'key': m, 'label': KpiActualRollup.METRIC_LABELS.get(m, m),
                         'is_count': m == KpiActualRollup.M_CUSTOMERS} for m in BOARD_METRICS],
            'branches': rows,
            'totals': totals,
            'call_center': call_center,
        })

    # Call-center KPI set (sales / profit / beauty / orders / calls).
    CC_METRICS = [
        KpiActualRollup.M_CASH_DELIVERY, KpiActualRollup.M_GROSS_PROFIT,
        KpiActualRollup.M_BEAUTY, KpiActualRollup.M_CUSTOMERS,
        KpiActualRollup.M_PIC_COUNT, KpiActualRollup.M_CALL_COUNT,
    ]

    def _call_center_block(self, year, month, cell, m_start, m_end):
        from apps.branches.models import Branch
        from apps.incentives.models import SalesTarget
        cc = Branch.objects.filter(softech_branch_id='CC').first()
        if not cc:
            return None
        actual = {r['metric']: float(r['value']) for r in KpiActualRollup.objects.filter(
            branch=cc, year=year, month=month, metric__in=self.CC_METRICS).values('metric', 'value')}
        if not actual:
            return None
        tgt = {t['metric']: (float(t['target_value'] or 0), t['id']) for t in SalesTarget.objects.filter(
            scope_type=SalesTarget.SCOPE_BRANCH, branch=cc, metric__in=self.CC_METRICS,
            period_start__lte=m_end, period_end__gte=m_start).values('id', 'metric', 'target_value')}
        # CC labels: M_CUSTOMERS = order count; M_PIC_COUNT = distinct customers (PIC).
        cc_labels = dict(KpiActualRollup.METRIC_LABELS)
        cc_labels[KpiActualRollup.M_CUSTOMERS] = 'عدد الطلبات'
        cc_labels[KpiActualRollup.M_PIC_COUNT] = 'عدد العملاء'
        count_metrics = (KpiActualRollup.M_CUSTOMERS, KpiActualRollup.M_PIC_COUNT, KpiActualRollup.M_CALL_COUNT)
        return {
            'branch_id': cc.id,
            'metrics': [{'key': m, 'label': cc_labels.get(m, m), 'is_count': m in count_metrics}
                        for m in self.CC_METRICS],
            'cells': {m: cell(actual.get(m, 0.0), *tgt.get(m, (0.0, None))) for m in self.CC_METRICS},
        }


class KpiRefreshView(APIView):
    """GET — rollup freshness for the current + previous months (computed_at vs last sales
    sync, stale flag). POST — rebuild in the background every stale month plus the current
    month, so a just-closed month picks up its late sales too (rollup_refresh)."""
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        from apps.forecasting import rollup_refresh
        return Response(rollup_refresh.status())

    def post(self, request):
        from core.permissions import deny_unless
        denied = deny_unless(request, 'purchasing', 'edit', 'create')   # /api/forecasting/ = purchasing (Z-2)
        if denied:
            return denied
        from apps.forecasting import rollup_refresh
        if rollup_refresh.status()['running']:
            return Response({'started': False, 'running': True})

        def _job():
            from django.db import connections
            connections.close_all()
            try:
                rollup_refresh.refresh(force_current=True)
            except Exception:
                logger.exception('KPI rollup refresh job failed')
            finally:
                connections.close_all()

        start_thread(_job)
        return Response({'started': True})


class KpiSheetExportView(APIView):
    """
    GET /api/forecasting/kpi-board/export/?year=&month=&models=a,b,avg
        &threshold=&benchmark=&days_elapsed=
    Streams the legacy-format KPI target workbook (one sheet per model) built from
    the forecast engine (targets) + KpiActualRollup (achieved). Read-only.
    """
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        import io
        from decimal import Decimal, InvalidOperation
        from django.http import HttpResponse
        from apps.forecasting.kpi_export import build_target_workbook

        today = date.today()
        try:
            year = int(request.query_params.get('year', today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            return Response({'detail': 'سنة/شهر غير صالحين'}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= month <= 12):
            return Response({'detail': 'الشهر يجب أن يكون 1–12'}, status=status.HTTP_400_BAD_REQUEST)

        raw = (request.query_params.get('models') or 'a,b,avg')
        models = tuple(m.strip() for m in raw.split(',') if m.strip() in ('a', 'b', 'avg'))
        if not models:
            return Response({'detail': 'نماذج غير صالحة (a,b,avg)'}, status=status.HTTP_400_BAD_REQUEST)

        def _dec(key, default):
            v = request.query_params.get(key)
            if v in (None, ''):
                return Decimal(default)
            try:
                return Decimal(str(v))
            except (InvalidOperation, ValueError):
                return Decimal(default)

        days_elapsed = request.query_params.get('days_elapsed')
        days_elapsed = int(days_elapsed) if (days_elapsed or '').isdigit() else None

        try:
            wb = build_target_workbook(
                year, month, models=models, days_elapsed=days_elapsed,
                incentive_threshold=_dec('threshold', '0.90'),
                benchmark_growth=_dec('benchmark', '0.30'))
            buf = io.BytesIO()
            neutralise_formulas(wb, keep_safe_formulas=True).save(buf)
            buf.seek(0)
        except Exception:
            logger.exception('KPI sheet export failed for %s-%s', year, month)
            return Response({'detail': 'فشل إنشاء ملف الإكسل'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        fname = f'kpi_target_{year}_{month:02d}.xlsx'
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp


# ════════════════════════════════════════════════════════════════════════════
# Forecast scenarios (doc 16, Phase 3) — factor-driven target generation.
# ════════════════════════════════════════════════════════════════════════════

class ForecastScenarioViewSet(viewsets.ModelViewSet):
    """CRUD + generate + commit for forecast scenarios (analyst roles only to mutate)."""
    serializer_class   = ForecastScenarioSerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    queryset = (ForecastScenario.objects
                .select_related('created_by')
                .prefetch_related('factors')
                .order_by('-year', '-month', '-created_at'))

    def _staff(self):
        return getattr(self.request.user, 'staff_profile', None)

    def _guard(self):
        sp = self._staff()
        if not (sp and sp.role in ANALYST_ROLES):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('لا تملك صلاحية إدارة سيناريوهات التنبؤ')
        return sp

    def perform_create(self, serializer):
        scenario = serializer.save(created_by=self._guard())
        ForecastEngine.ensure_factors(scenario)

    def perform_update(self, serializer):
        self._guard()
        serializer.save()

    def perform_destroy(self, instance):
        self._guard()
        instance.delete()

    @action(detail=True, methods=['patch'], url_path='factors')
    def update_factors(self, request, pk=None):
        """Bulk-update this scenario's per-metric factors. Body: [{metric, growth_goal, w_lm,...}]"""
        self._guard()
        scenario = self.get_object()
        ForecastEngine.ensure_factors(scenario)
        by_metric = {f.metric: f for f in scenario.factors.all()}
        for row in request.data if isinstance(request.data, list) else request.data.get('factors', []):
            f = by_metric.get(row.get('metric'))
            if not f:
                continue
            for field in ['growth_goal', 'w_lm', 'w_pm', 'w_yoy', 'seasonality_index']:
                if field in row and row[field] is not None:
                    setattr(f, field, row[field])
            if 'benchmark' in row:          # nullable → allow clearing back to the global default
                f.benchmark = row['benchmark'] if row['benchmark'] not in ('', None) else None
            f.save()
        return Response(ForecastScenarioSerializer(scenario).data)

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        self._guard()
        scenario = self.get_object()
        try:
            summary = ForecastEngine().generate(scenario)
        except Exception:
            logger.exception('Forecast generate failed for scenario=%s', scenario.pk)
            return Response({'detail': 'فشل احتساب التنبؤ'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({**summary, 'scenario': ForecastScenarioSerializer(scenario).data})

    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        scenario = self.get_object()
        qs = ForecastResult.objects.filter(scenario=scenario).select_related('branch')
        # Branch rows follow the caller's branches (owner decisions 3 / B-1: branch roles keep their
        # own-branch analytics; round 2 R4 detail canary). Chain-level rows (no branch) stay.
        from django.db.models import Q
        from core.branch_scope import branch_ids
        ids = branch_ids(request.user)
        if ids is not None:
            qs = qs.filter(Q(branch__isnull=True) | Q(branch_id__in=ids))
        metric = request.query_params.get('metric')
        if metric:
            qs = qs.filter(metric=metric)
        return Response(ForecastResultSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='apply-references')
    def apply_references(self, request, pk=None):
        """Manually apply the stored grounded references (seasonality/benchmark/growth/
        inflation) to this scenario's factors. Does NOT generate — call generate next."""
        self._guard()
        scenario = self.get_object()
        from apps.forecasting import references as R
        try:
            res = R.apply_to_scenario(scenario)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**res, 'scenario': ForecastScenarioSerializer(scenario).data})

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        """Stream an Excel of the full scenario forecast (per-KPI branch rows + totals + factors)."""
        scenario = self.get_object()
        if scenario.status == ForecastScenario.STATUS_DRAFT:
            return Response({'detail': 'احسب السيناريو أولاً قبل التصدير'},
                            status=status.HTTP_400_BAD_REQUEST)
        import io
        from django.http import HttpResponse
        from .kpi_export import build_scenario_workbook
        try:
            wb = build_scenario_workbook(scenario)
            buf = io.BytesIO(); neutralise_formulas(wb, keep_safe_formulas=True).save(buf); buf.seek(0)
        except Exception:
            logger.exception('Scenario export failed for %s', scenario.pk)
            return Response({'detail': 'فشل تصدير الملف'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        fname = f'forecast_{scenario.year}_{scenario.month:02d}_{scenario.pk}.xlsx'
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp

    @action(detail=True, methods=['post'])
    def commit(self, request, pk=None):
        sp = self._guard()
        scenario = self.get_object()
        if scenario.status == ForecastScenario.STATUS_DRAFT:
            return Response({'detail': 'احسب السيناريو أولاً قبل الاعتماد'},
                            status=status.HTTP_400_BAD_REQUEST)
        summary = ForecastEngine().commit(scenario, created_by=sp)
        return Response({**summary, 'scenario': ForecastScenarioSerializer(scenario).data})

    @action(detail=True, methods=['post'], url_path='commit-cell')
    def commit_cell(self, request, pk=None):
        """Set ONE target (branch/salesperson/category × metric) from this scenario's forecast
        — the per-cell «اعتمد من النموذج» on the KPI board. Body: {metric, branch_id|scope_key}."""
        sp = self._guard()
        scenario = self.get_object()
        metric = request.data.get('metric')
        if not metric:
            return Response({'detail': 'حدّد المؤشر'}, status=status.HTTP_400_BAD_REQUEST)
        branch_id = request.data.get('branch_id')
        scope_key = request.data.get('scope_key')
        # Branch roles may only pull cells for branches they can see (round-2 R4).
        if branch_id is not None:
            from core.branch_scope import branch_ids
            ids = branch_ids(request.user)
            if ids is not None and int(branch_id) not in ids:
                return Response({'detail': 'ليس لديك صلاحية على هذا الفرع'},
                                status=status.HTTP_403_FORBIDDEN)
        try:
            res = ForecastEngine().commit_cell(
                scenario, metric, branch_id=int(branch_id) if branch_id is not None else None,
                scope_key=scope_key, created_by=sp)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(res)


class ForecastReferenceView(APIView):
    """GET grounded reference values; POST (analyst) recomputes them / sets fresh inflation.
    Body: {real_growth?, inflation?, inflation_source?}."""
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        from apps.forecasting import references as R
        from apps.forecasting.engine import seasonality_mode
        return Response({**(R.get() or {}), 'engine_seasonality_mode': seasonality_mode()})

    def post(self, request):
        sp = getattr(request.user, 'staff_profile', None)
        if not (sp and sp.role in ANALYST_ROLES):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
        from apps.forecasting import references as R
        d = request.data or {}
        if 'seasonality_mode' in d:
            return _set_seasonality_mode(request, sp, d.get('seasonality_mode'))
        prev = R.get() or {}
        rg = d.get('real_growth')
        rg = float(rg) if rg not in (None, '') else float(prev.get('real_growth', 0.15))
        infl = d.get('inflation')
        infl = float(infl) if infl not in (None, '') else None
        try:
            refs = R.compute(real_growth=rg, inflation_annual=infl,
                             inflation_source=d.get('inflation_source', ''))
        except Exception:
            logger.exception('reference compute failed')
            return Response({'detail': 'فشل حساب القيم المرجعية'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(refs)


class ForecastPlanView(APIView):
    """GET /api/forecasting/plan/?horizon=6 — rolling outlook: the running month (estimate)
    + the next N months, per branch + chain, with same-month-last-year YoY. Read-only:
    computed on the fly from the rollups, nothing stored; targets still need a scenario."""
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        from apps.forecasting.engine import ForecastEngine, PLAN_HORIZON
        try:
            horizon = int(request.query_params.get('horizon', PLAN_HORIZON))
        except (TypeError, ValueError):
            horizon = PLAN_HORIZON
        horizon = max(1, min(horizon, PLAN_HORIZON))
        try:
            return Response(ForecastEngine().plan(horizon=horizon))
        except Exception:
            logger.exception('forecast plan failed')
            return Response({'detail': 'تعذّر حساب الخطة'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _set_seasonality_mode(request, sp, mode):
    """Switch how the engine applies seasonality (none | chain | branch) — audited."""
    from apps.config.models import SystemSetting
    from apps.audit.models import AuditLog
    from apps.forecasting.engine import SEASONALITY_MODES, seasonality_mode
    mode = str(mode or '').strip().lower()
    if mode not in SEASONALITY_MODES:
        return Response({'detail': 'وضع غير صالح'}, status=status.HTTP_400_BAD_REQUEST)
    old = seasonality_mode()
    SystemSetting.objects.update_or_create(key='forecast_seasonality_mode', defaults={
        'value': mode, 'label': 'وضع الموسمية في محرك التنبؤ', 'category': 'general'})
    if old != mode:
        AuditLog.log('forecast_seasonality_mode', user=sp, changes={'mode': [old, mode]},
                     note=f'وضع الموسمية في محرك التنبؤ: {old} → {mode}')
    from apps.forecasting import references as R
    return Response({**(R.get() or {}), 'engine_seasonality_mode': mode})


class GrowthView(APIView):
    """GET /api/forecasting/growth/?metric=&year=&period=&period_type=&comparison=&branch=&salesperson=&category="""
    permission_classes = [IsAuthenticated, CanUseForecasting]

    def get(self, request):
        from apps.forecasting.growth import GrowthService
        q = request.query_params
        metric = q.get('metric', 'net_revenue')
        try:
            year = int(q.get('year')); period = int(q.get('period'))
        except (TypeError, ValueError):
            return Response({'detail': 'year & period required'}, status=status.HTTP_400_BAD_REQUEST)
        scope = {}
        if q.get('branch'):
            scope['branch_ids'] = [int(q['branch'])]
        if q.get('salesperson'):
            scope['softech_user'] = q['salesperson']
        if q.get('category'):
            scope['category_id'] = int(q['category'])
        try:
            data = GrowthService().compare(
                metric, year=year, period=period,
                period_type=q.get('period_type', 'month'),
                comparison=q.get('comparison', 'yoy'), **scope)
        except Exception:
            logger.exception('growth compare failed')
            return Response({'detail': 'فشل حساب النمو'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(data)


class BacktestViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse backtest runs; POST run/ to execute a new one (analyst roles)."""
    serializer_class   = BacktestRunSerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    queryset = BacktestRun.objects.prefetch_related('results').order_by('-created_at')

    def _guard(self):
        sp = getattr(self.request.user, 'staff_profile', None)
        if not (sp and sp.role in ANALYST_ROLES):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('لا تملك صلاحية تشغيل الاختبار الرجعي')
        return sp

    @action(detail=False, methods=['post'])
    def run(self, request):
        sp = self._guard()
        scenario = None
        sid = request.data.get('scenario_id')
        if sid:
            scenario = ForecastScenario.objects.filter(pk=sid).first()
        months_back = int(request.data.get('months_back', 12))
        try:
            run = BacktestService().run(
                months_back=months_back, scenario=scenario, created_by=sp,
                benchmark_growth=request.data.get('benchmark_growth'),
                incentive_threshold=request.data.get('incentive_threshold'),
                inflation=request.data.get('inflation'),
                promotion_lift=request.data.get('promotion_lift'),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception('Backtest run failed')
            return Response({'detail': 'فشل تشغيل الاختبار الرجعي'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(BacktestRunSerializer(run).data, status=status.HTTP_201_CREATED)


class ProfitExclusionViewSet(viewsets.ModelViewSet):
    """
    CRUD for items excluded from معامل الربحية (e.g. DLV delivery fee). Analyst roles
    mutate; everyone authenticated can read. Create by `code` (SOFTECH itemcode).
    NOTE: changes take effect for on-demand resolves immediately, and for the KPI
    board / engine after the next rollup rebuild (build_kpi_rollups).
    """
    serializer_class   = ProfitExclusionSerializer
    permission_classes = [IsAuthenticated, CanUseForecasting]
    queryset = ProfitExclusion.objects.select_related('item').order_by('item__softech_id')

    def _guard(self):
        sp = getattr(self.request.user, 'staff_profile', None)
        if not (sp and sp.role in ANALYST_ROLES):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('لا تملك صلاحية تعديل استثناءات الربحية')
        return sp

    def perform_create(self, serializer):
        self._guard(); serializer.save()

    def perform_update(self, serializer):
        self._guard(); serializer.save()

    def perform_destroy(self, instance):
        self._guard(); instance.delete()
