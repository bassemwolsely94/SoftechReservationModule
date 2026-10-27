"""Insights API (doc 18) — browse reports, generate on demand, tune rules."""
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import InsightRun, InsightRule, InsightFinding
from .serializers import (InsightRunSerializer, InsightRunListSerializer, InsightRuleSerializer,
                          InsightFindingSerializer)
from .engine import InsightEngine

logger = logging.getLogger('elrezeiky')
ANALYST_ROLES = {'admin', 'supervisor', 'purchasing', 'quality_manager'}


class InsightRunViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = InsightRun.objects.prefetch_related('findings').order_by('-period_start', '-created_at')

    def get_serializer_class(self):
        return InsightRunSerializer if self.action == 'retrieve' else InsightRunListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params.get('period')
        if p:
            qs = qs.filter(period_type=p)
        d = self.request.query_params.get('domain')
        if d:
            qs = qs.filter(domain=d)
        return qs

    @action(detail=False, methods=['get'])
    def freshness(self, request):
        """Live mirror freshness — data_through per source (sales/purchasing) + last sync — so the
        UI can confirm SOFTECH data is fully collected up to a period end BEFORE generating a
        report. GET /api/insights/reports/freshness/?domain=sales|purchasing&end=YYYY-MM-DD
        (end defaults to yesterday, the default report ref date)."""
        from datetime import date, datetime, timedelta
        from apps.insights.rules import data_freshness
        domain = request.query_params.get('domain', 'sales')
        end_s = request.query_params.get('end'); start_s = request.query_params.get('start')
        try:
            end = datetime.strptime(end_s, '%Y-%m-%d').date() if end_s else (date.today() - timedelta(days=1))
            start = datetime.strptime(start_s, '%Y-%m-%d').date() if start_s else end
        except ValueError:
            return Response({'detail': 'bad date'}, status=status.HTTP_400_BAD_REQUEST)
        fr = data_freshness(start, end, domain)
        iso = lambda d: d.isoformat() if d else None
        return Response({
            'domain': domain, 'start': iso(start), 'end': iso(end),
            'sales_through': iso(fr['sales_through']), 'purch_through': iso(fr['purch_through']),
            'src_through': iso(fr['src_through']),
            'last_sync_at': fr['last_sync_at'].isoformat() if fr['last_sync_at'] else None,
            'last_sync_failed': fr['last_sync_failed'],
            'gap_days': fr['gap_days'], 'covered': fr['covered'], 'complete': fr['complete'],
            'empty_days': fr['empty_days'], 'low_days': fr['low_days'],
        })

    @action(detail=False, methods=['post'])
    def backfill(self, request):
        """Re-sync SOFTECH data for the report period to FILL detected gaps — a background job
        that surfaces on the sync status poll (GET /api/sync/status/), exactly like the sync page.
        SALES  → backfill_sales_history --start --end (month-by-month idempotent upsert + rollup
                 rebuild; fills empty/partial days).
        PURCHASING → run_procurement_engine --days N (covers the period), wrapped in a SyncRun so
                 it polls the same way. Admin/supervisor only. Returns 202 immediately."""
        sp = getattr(request.user, 'staff_profile', None)
        if not (sp and sp.role in {'admin', 'supervisor'}):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
        import threading
        from datetime import datetime, date, timedelta
        from django.core.management import call_command
        from django.db import connections
        from django.utils import timezone
        from apps.sync.models import SyncRun
        domain = request.data.get('domain', 'sales')
        parse = lambda s: datetime.strptime(s, '%Y-%m-%d').date() if s else None
        try:
            start = parse(request.data.get('start')); end = parse(request.data.get('end'))
        except ValueError:
            return Response({'detail': 'تاريخ غير صالح'}, status=status.HTTP_400_BAD_REQUEST)
        if not start or not end:
            return Response({'detail': 'حدد فترة صالحة'}, status=status.HTTP_400_BAD_REQUEST)
        if end < start:
            start, end = end, start
        # don't stack a second heavy run on one already in flight (stale >30 min ignored)
        cutoff = timezone.now() - timedelta(minutes=30)
        if SyncRun.objects.filter(status='running', started_at__gte=cutoff).exists():
            return Response({'status': 'running', 'detail': 'مزامنة جارية بالفعل'},
                            status=status.HTTP_202_ACCEPTED)
        ym_start, ym_end = start.strftime('%Y-%m'), end.strftime('%Y-%m')

        def _worker():
            run = None
            try:
                if domain == 'purchasing':
                    run = SyncRun.objects.create(status='running')
                    call_command('run_procurement_engine', days=max((date.today() - start).days + 1, 1))
                    run.status = 'success'; run.completed_at = timezone.now(); run.save()
                else:
                    call_command('backfill_sales_history', start=ym_start, end=ym_end)  # owns its SyncRun
            except Exception:
                logger.exception('[insights backfill] failed')
                if run:
                    run.status = 'failed'; run.completed_at = timezone.now(); run.save()
            finally:
                connections.close_all()

        threading.Thread(target=_worker, name='insights-backfill', daemon=True).start()
        return Response({'status': 'running', 'domain': domain, 'months': sorted({ym_start, ym_end}),
                         'detail': 'بدأت إعادة المزامنة/التعبئة'}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def scopes(self, request, pk=None):
        """Branches + salespeople that have findings in this run (for the scope dropdowns).
        Each salesperson is tagged with their PRIMARY branch in the period (where they sold
        most) so the same rep name across branch logins can be told apart and aligned."""
        run = self.get_object()
        from django.db.models import Count
        from apps.branches.models import Branch
        from apps.users.models import ERPUser
        from apps.customers.models import PurchaseHistory
        # set() (not .distinct()) — InsightFinding has default Meta.ordering, which makes
        # .values_list(...).distinct() add hidden ORDER BY columns and return duplicates.
        bcodes = set(run.findings.filter(scope_type='branch').exclude(scope_key='')
                     .values_list('scope_key', flat=True))
        ucodes = set(run.findings.filter(scope_type='salesperson').exclude(scope_key='')
                     .values_list('scope_key', flat=True))
        branches = Branch.objects.all()
        bname = {b.code or b.softech_branch_id: (b.name_ar or b.name) for b in branches}
        bcode_by_id = {b.id: (b.code or b.softech_branch_id) for b in branches}
        bname_by_id = {b.id: (b.name_ar or b.name) for b in branches}
        uname = {str(c): (n or '').strip() for c, n in
                 ERPUser.objects.exclude(user_id='').values_list('username', 'user_id')}
        # primary branch per usercode = branch with most invoices in the run period
        primary = {}
        for r in (PurchaseHistory.objects.filter(
                    invoice_date__date__gte=run.period_start, invoice_date__date__lte=run.period_end,
                    doc_code='115', softech_user__in=ucodes)
                  .values('softech_user', 'branch_id').annotate(c=Count('id'))):
            u = r['softech_user']
            if u not in primary or r['c'] > primary[u][1]:
                primary[u] = (r['branch_id'], r['c'])
        sps = []
        for c in ucodes:
            bid = primary.get(c, (None, 0))[0]
            sps.append({'key': c, 'name': uname.get(c, c),
                        'branch_code': bcode_by_id.get(bid, ''), 'branch_name': bname_by_id.get(bid, '')})
        sps.sort(key=lambda x: (x['branch_name'], x['name']))
        return Response({
            'branches': sorted(({'key': c, 'name': bname.get(c, c)} for c in bcodes), key=lambda x: x['name']),
            'salespeople': sps,
        })

    @action(detail=True, methods=['get'])
    def scoped(self, request, pk=None):
        """Rendered narrative (AR+EN) + findings for a scope: chain | branch | salesperson.
        Chain drops per-branch/per-rep info detail so the chain view stays uncluttered."""
        run = self.get_object()
        stype = request.query_params.get('type', 'chain')
        key = (request.query_params.get('key') or '').strip()
        if stype == 'branch' and key:
            from apps.branches.models import Branch
            b = Branch.objects.filter(code=key).first() or Branch.objects.filter(softech_branch_id=key).first()
            nar_ar = InsightEngine.render_for_branch(run, b.id, 'ar') if b else None
            nar_en = InsightEngine.render_for_branch(run, b.id, 'en') if b else None
            fs = run.findings.filter(scope_key=key)
        elif stype == 'salesperson' and key:
            nar_ar = InsightEngine.render_for_salesperson(run, key, 'ar')
            nar_en = InsightEngine.render_for_salesperson(run, key, 'en')
            fs = run.findings.filter(scope_type='salesperson', scope_key=key)
        else:
            stype = 'chain'
            nar_ar, nar_en = run.narrative_ar, run.narrative_en
            fs = run.findings.exclude(severity='info', scope_type__in=['branch', 'salesperson'])
        return Response({
            'scope_type': stype, 'scope_key': key,
            'narrative_ar': nar_ar or '', 'narrative_en': nar_en or '',
            'findings': InsightFindingSerializer(fs.order_by('severity', 'rule_code'), many=True).data,
        })

    def _guard(self):
        sp = getattr(self.request.user, 'staff_profile', None)
        if not (sp and sp.role in ANALYST_ROLES):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('غير مصرح')

    @action(detail=False, methods=['post'])
    def generate(self, request):
        self._guard()
        from datetime import datetime
        period = request.data.get('period', 'day')
        domain = request.data.get('domain', 'sales')
        if domain not in ('sales', 'purchasing'):
            domain = 'sales'
        parse = lambda s: datetime.strptime(s, '%Y-%m-%d').date() if s else None
        ref_date = parse(request.data.get('date'))
        start = parse(request.data.get('start'))
        end = parse(request.data.get('end'))

        # Validate an explicit custom range per period type.
        if start and end:
            if end < start:
                start, end = end, start
            span = (end - start).days + 1
            if period == 'day' and span != 1:
                return Response({'detail': 'التقرير اليومي يوم واحد فقط'}, status=status.HTTP_400_BAD_REQUEST)
            if period == 'week' and span != 7:
                return Response({'detail': 'التقرير الأسبوعي يجب أن يكون 7 أيام بالضبط'}, status=status.HTTP_400_BAD_REQUEST)
            if period == 'month' and span > 31:
                return Response({'detail': 'التقرير الشهري لا يتجاوز 31 يوماً'}, status=status.HTTP_400_BAD_REQUEST)
            if period == 'mtd' and (start.day != 1 or start.month != end.month or start.year != end.year):
                return Response({'detail': 'تقرير الشهر حتى تاريخه يبدأ من أول الشهر حتى يوم داخل نفس الشهر'},
                                status=status.HTTP_400_BAD_REQUEST)
        try:
            run = InsightEngine.run(period_type=period, ref_date=ref_date, start=start, end=end, domain=domain)
        except Exception:
            logger.exception('insight generate failed')
            return Response({'detail': 'فشل توليد التقرير'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(InsightRunSerializer(run).data, status=status.HTTP_201_CREATED)


class InsightRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = InsightRuleSerializer

    def get_queryset(self):
        InsightEngine.ensure_rules()
        return InsightRule.objects.all()

    def _guard(self):
        sp = getattr(self.request.user, 'staff_profile', None)
        if not (sp and sp.role in {'admin', 'supervisor'}):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('غير مصرح')

    def perform_update(self, serializer):
        self._guard(); serializer.save()

    def create(self, request, *a, **k):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed('POST')   # rules are seeded, not user-created
