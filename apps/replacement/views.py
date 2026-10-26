"""
apps/replacement/views.py — /api/replacement/ (doc 25 §12).
Phase 0: read + link/exception decisions. Phase 1: live case workflow (create → calculate →
submit/approve → legs → post) — every action authorised server-side in authz/workflow/legs.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Sum
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import actions as A
from . import authz
from . import legs as LG
from . import reconstruct as R
from . import workflow as W
from .models import (CaseException as X, ReconstructionRun, ReplacementCase as RC, ReplacementGrant,
                     ReplacementRule)
from .permissions import CanUseReplacement, scoped_cases
from .serializers import (CaseDetailSerializer, CaseListSerializer, ExceptionSerializer, GrantSerializer,
                          RuleSerializer, RunSerializer)
from apps.catalog.wildcard import wq


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _by_staff(qs):
    """[{name, n}] of cases per creator (full_name is a property → named in Python)."""
    from apps.users.models import StaffProfile
    rows = list(qs.values('created_by').annotate(n=Count('id')).order_by('-n'))
    staff = {s.pk: s for s in StaffProfile.objects.filter(pk__in=[r['created_by'] for r in rows if r['created_by']])}
    return [{'name': staff[r['created_by']].full_name if r['created_by'] in staff else '—', 'n': r['n']}
            for r in rows]


def _filter_cases(request, qs):
    p = request.query_params
    q = (p.get('q') or '').strip()
    if q:
        cond = (Q(number__icontains=q) | Q(softech_pic__iexact=q) | wq(q, 'patient_name')
                | Q(customer__phone__icontains=q) | Q(documents__document__docnumber=q)
                | Q(items__itemcode=q) | wq(q, 'items__item_name')
                | Q(supplier_personcode=q) | Q(contract_personcode=q))
        qs = qs.filter(cond).distinct()
    for key, field in (('branch', 'branchcode'), ('status', 'status'), ('source_type', 'source_type'),
                       ('supplier', 'supplier_personcode'), ('mode', 'settlement_mode'),
                       ('confidence', 'link_confidence'), ('severity', 'max_severity')):
        v = p.get(key)
        if v:
            qs = qs.filter(**{f'{field}__in': v.split(',')})
    if p.get('date_from'):
        qs = qs.filter(purchase_date__gte=p['date_from'])
    if p.get('date_to'):
        qs = qs.filter(purchase_date__lte=p['date_to'])
    if p.get('open_balance') == '1':
        qs = qs.filter(outstanding__gt=Decimal('0.01'))
    if p.get('has_exceptions') == '1':
        qs = qs.filter(open_exceptions__gt=0)
    if p.get('exception_type'):
        qs = qs.filter(exceptions__exception_type=p['exception_type'],
                       exceptions__status__in=[X.STATUS_OPEN, X.STATUS_ACK]).distinct()
    return qs


class ReplacementCaseViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanUseReplacement]

    def get_queryset(self):
        qs = RC.objects.select_related('branch', 'purchase_ref', 'customer')
        qs = _filter_cases(self.request, scoped_cases(self.request, qs))
        order = self.request.query_params.get('ordering') or '-purchase_date'
        allowed = {'purchase_date', 'entitlement', 'outstanding', 'open_exceptions', 'number'}
        if order.lstrip('-') in allowed:
            qs = qs.order_by(order, '-id')
        return qs

    def get_serializer_class(self):
        return CaseDetailSerializer if self.action == 'retrieve' else CaseListSerializer

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self.get_queryset().order_by()
        money = ('entitlement', 'outstanding', 'redeemed_products', 'redeemed_cash',
                 'redeemed_unclassified', 'reversed_by_return', 'absorbed')
        tot = qs.aggregate(n=Count('id'), **{m: Sum(m) for m in money})
        open_qs = qs.filter(outstanding__gt=Decimal('0.01'))
        likely = open_qs.filter(exceptions__exception_type='unlinked_voucher_likely',
                                exceptions__status__in=[X.STATUS_OPEN, X.STATUS_ACK]).distinct()
        likely_amt = RC.objects.filter(pk__in=likely.values('pk')).aggregate(s=Sum('outstanding'))['s'] or 0
        open_amt = open_qs.aggregate(s=Sum('outstanding'))['s'] or 0
        by = lambda f: list(qs.values(f).annotate(n=Count('id'), entitlement=Sum('entitlement'),
                                                  outstanding=Sum('outstanding')).order_by(f))
        exc = (X.objects.filter(case__in=qs, status__in=[X.STATUS_OPEN, X.STATUS_ACK])
               .values('exception_type', 'severity').annotate(n=Count('id'), amount=Sum('amount'))
               .order_by('-n'))
        labels = dict(X.TYPE_CHOICES)
        merged = {}
        for e in exc:                        # one chip per type, carrying its worst severity
            m = merged.setdefault(e['exception_type'], {'exception_type': e['exception_type'], 'severity': e['severity'],
                                                        'n': 0, 'amount': Decimal('0')})
            m['n'] += e['n']
            m['amount'] += e['amount'] or 0
            if X.SEVERITY_RANK[e['severity']] > X.SEVERITY_RANK[m['severity']]:
                m['severity'] = e['severity']
        exc = sorted(merged.values(), key=lambda m: (-X.SEVERITY_RANK[m['severity']], -m['n']))
        return Response({
            'totals': {k: (str(v) if v is not None else '0') for k, v in tot.items()},
            'outstanding_split': {
                'open_cases': open_qs.count(), 'open_amount': str(open_amt),
                'likely_paid_unlinked': str(likely_amt),
                'genuinely_open': str(Decimal(open_amt) - Decimal(likely_amt)),
            },
            'by_status': by('status'), 'by_supplier': by('supplier_personcode'),
            'by_branch': by('branchcode'), 'by_source': by('source_type'),
            'exceptions': [{**e, 'label': labels.get(e['exception_type'], e['exception_type']),
                            'amount': str(e['amount'] or 0)} for e in exc],
            'last_run': RunSerializer(ReconstructionRun.objects.first()).data
            if ReconstructionRun.objects.exists() else None,
            'adoption': self._adoption(qs),
        })

    @staticmethod
    def _adoption(qs):
        """Entry-first adoption per cut-over branch: purchases that came from a case entered first
        vs «شراء بدون حالة», and who posted the case-less ones (SOFTECH usercode on the purchase)."""
        from apps.purchasing.isr_fulfillment import user_label, user_names
        from . import config as C
        out = []
        for code in sorted(C.get('ENTRY_FIRST_FROM')):
            start = C.entry_first_from(code)
            base = qs.filter(branchcode=code, purchase_date__gte=start, purchase_ref__isnull=False) \
                .exclude(status=RC.STATUS_CANCELLED)
            live = base.filter(origin=RC.ORIGIN_LIVE)
            un = base.filter(status=RC.STATUS_UNCLAIMED)
            n_live, n_un = live.count(), un.count()
            by_user = list(un.values('purchase_invoice__usercode').annotate(n=Count('id'), value=Sum('entitlement'))
                           .order_by('-n'))
            names = user_names(u['purchase_invoice__usercode'] for u in by_user)
            out.append({
                'branchcode': code, 'from': start.isoformat(), 'entered_first': n_live, 'unclaimed': n_un,
                'unclaimed_value': str(un.aggregate(s=Sum('entitlement'))['s'] or 0),
                'rate': round(100 * n_live / (n_live + n_un), 1) if (n_live + n_un) else None,
                'unclaimed_by_user': [{'usercode': u['purchase_invoice__usercode'] or '',
                                       'label': user_label(u['purchase_invoice__usercode'], names),
                                       'n': u['n'], 'value': str(u['value'] or 0)} for u in by_user],
                'entered_by_staff': _by_staff(live),
            })
        return out

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'staff': _staff(self.request)}

    def _detail(self, case):
        case = RC.objects.select_related('branch', 'purchase_ref', 'customer').get(pk=case.pk)
        return Response(CaseDetailSerializer(case, context={'staff': _staff(self.request)}).data)

    def _do(self, fn):
        """Run a service call and map domain errors to HTTP (400 / 403 / 409)."""
        try:
            out = fn()
        except W.StaleVersion as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'detail': str(e) or 'غير مسموح.'}, status=status.HTTP_403_FORBIDDEN)
        except RC.DoesNotExist:
            return Response({'detail': 'الحالة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)
        return self._detail(out if isinstance(out, RC) else out.case)

    # ── Phase 0: human link / exception decisions ────────────────────────────
    @action(detail=True, methods=['post'], url_path=r'links/(?P<casedoc_id>\d+)/decide')
    def decide_link(self, request, pk=None, casedoc_id=None):
        case = self.get_object()

        def run():
            authz.require(_staff(request), 'edit', case=case)
            return A.decide_link(case, int(casedoc_id), confirm=bool(request.data.get('confirm')),
                                 user=_staff(request), note=request.data.get('note', ''), request=request)
        return self._do(run)

    @action(detail=True, methods=['post'], url_path=r'exceptions/(?P<exception_id>\d+)/decide')
    def decide_exception(self, request, pk=None, exception_id=None):
        case = self.get_object()

        def run():
            authz.require(_staff(request), 'edit', case=case)
            A.decide_exception(case, int(exception_id), status=request.data.get('status', ''),
                               user=_staff(request), note=request.data.get('note', ''), request=request)
            return case
        return self._do(run)

    @action(detail=True, methods=['post'])
    def rebuild(self, request, pk=None):
        """Re-run reconstruction for this one case (read-only vs SOFTECH)."""
        case = self.get_object()

        def run():
            authz.require(_staff(request), 'edit', case=case)
            if not case.purchase_invoice_id:
                raise ValidationError('لا توجد فاتورة شراء في المرآة بعد.')
            R.reconstruct_invoice(case.purchase_invoice, tabdeel=R.tabdeel_pics(), user=_staff(request))
            return case
        return self._do(run)

    # ── Phase 1: live workflow ───────────────────────────────────────────────
    def create(self, request):
        """POST /cases/ — new live case. Body: branch, source_type, settlement_mode, softech_pic,
        contract_personcode, items[{item_id, qty}], is_shortage_item, prescription_no, approval_no,
        notes, from_sale (customers.PurchaseHistory id, optional)."""
        from apps.branches.models import Branch
        from apps.customers.models import PurchaseHistory
        d = request.data

        def run():
            branch = Branch.objects.filter(pk=d.get('branch')).first()
            if branch is None:
                raise ValidationError('الفرع مطلوب.')
            sale = PurchaseHistory.objects.filter(pk=d['from_sale']).first() if d.get('from_sale') else None
            claim = None
            if d.get('claim_of'):
                claim = self.get_queryset().filter(pk=d['claim_of']).first()    # branch scope
                if claim is None:
                    raise ValidationError('سجل «شراء بدون حالة» غير موجود.')
            return W.create_case(user=_staff(request), branch=branch, source_type=d.get('source_type', ''),
                                 settlement_mode=d.get('settlement_mode', 'products'),
                                 softech_pic=(d.get('softech_pic') or '').strip(),
                                 contract_personcode=(d.get('contract_personcode') or '').strip(),
                                 items=d.get('items') or [], is_shortage_item=bool(d.get('is_shortage_item')),
                                 prescription_no=d.get('prescription_no', ''), approval_no=d.get('approval_no', ''),
                                 notes=d.get('notes', ''), from_sale=sale, claim_of=claim, request=request)
        resp = self._do(run)
        if resp.status_code == 200:
            resp.status_code = status.HTTP_201_CREATED
        return resp

    def _step(self, request, pk, fn, **kw):
        self.get_object()                                     # branch scope (404 outside)
        return self._do(lambda: fn(int(pk), user=_staff(request), version=request.data.get('version'),
                                   request=request, **kw))

    @action(detail=True, methods=['post'])
    def items(self, request, pk=None):
        return self._step(request, pk, W.set_items, items=request.data.get('items') or [])

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        return self._step(request, pk, W.calculate, override_pct=request.data.get('override_pct'),
                          override_reason=request.data.get('override_reason', ''))

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        return self._step(request, pk, W.submit)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._step(request, pk, W.decide, approve=True, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        return self._step(request, pk, W.decide, approve=False, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        return self._step(request, pk, W.reopen, reason=request.data.get('reason', ''))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._step(request, pk, W.cancel, reason=request.data.get('reason', ''))

    @action(detail=True, methods=['post'], url_path='link-contract')
    def link_contract(self, request, pk=None):
        from datetime import date
        d = request.data
        try:
            dd = date.fromisoformat(str(d.get('docdate')))
        except ValueError:
            return Response({'detail': 'تاريخ غير صالح.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._step(request, pk, LG.link_contract_sale, branchcode=str(d.get('branchcode', '')),
                          docnumber=str(d.get('docnumber', '')), docdate=dd)

    def _native_link(self, request, pk, fn):
        from datetime import date
        d = request.data
        try:
            dd = date.fromisoformat(str(d.get('docdate')))
        except ValueError:
            return Response({'detail': 'تاريخ غير صالح.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._step(request, pk, fn, branchcode=str(d.get('branchcode', '')),
                          docnumber=str(d.get('docnumber', '')), docdate=dd)

    @action(detail=True, methods=['post'], url_path='link-purchase')
    def link_purchase(self, request, pk=None):
        """Parallel entry: the virtual-supplier purchase posted natively in SOFTECH."""
        return self._native_link(request, pk, LG.link_native_purchase)

    @action(detail=True, methods=['post'], url_path='link-product-sale')
    def link_product_sale(self, request, pk=None):
        """Parallel entry: a cash / delivery product sale made natively at the POS."""
        return self._native_link(request, pk, LG.link_native_product_sale)

    @action(detail=True, methods=['post'], url_path='prepare-purchase')
    def prepare_purchase(self, request, pk=None):
        return self._step(request, pk, LG.prepare_purchase, expiries=request.data.get('expiries') or {})

    @action(detail=True, methods=['post'], url_path='prepare-contract-sale')
    def prepare_contract_sale(self, request, pk=None):
        return self._step(request, pk, LG.prepare_contract_sale, claim=request.data.get('claim') or {})

    @action(detail=True, methods=['post'], url_path='prepare-product-sale')
    def prepare_product_sale(self, request, pk=None):
        return self._step(request, pk, LG.prepare_product_sale, channel=request.data.get('channel', 'cash'),
                          items=request.data.get('items') or [])

    @action(detail=True, methods=['post'], url_path=r'operations/(?P<op_id>[0-9a-f-]{36})/post')
    def post_operation(self, request, pk=None, op_id=None):
        return self._step(request, pk, lambda case_id, **kw: LG.post(case_id, op_id, **kw),
                          force=bool(request.data.get('force')))

    # ── B3: cash handed to the patient ───────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='payouts')
    def request_payout(self, request, pk=None):
        from . import cash
        return self._step(request, pk, cash.request_payout, amount=request.data.get('amount'),
                          note=request.data.get('note', ''))

    @action(detail=True, methods=['post'], url_path=r'payouts/(?P<payout_id>\d+)/cancel')
    def cancel_payout(self, request, pk=None, payout_id=None):
        from . import cash
        self.get_object()                                     # branch scope (404 outside)
        return self._do(lambda: cash.cancel_payout(int(pk), int(payout_id), user=_staff(request),
                                                   version=request.data.get('version'),
                                                   reason=request.data.get('reason', ''), request=request))

    @action(detail=True, methods=['post'], url_path=r'payouts/(?P<payout_id>\d+)/confirm')
    def confirm_payout(self, request, pk=None, payout_id=None):
        from . import cash
        self.get_object()
        return self._do(lambda: cash.confirm_payout(int(pk), int(payout_id), user=_staff(request),
                                                    version=request.data.get('version'),
                                                    reference=request.data.get('reference', ''), request=request))

    # ── B4: reversals and corrections (native supplier return, approved here) ─
    @action(detail=True, methods=['post'], url_path='reversals')
    def request_reversal(self, request, pk=None):
        from . import reversal
        return self._step(request, pk, reversal.request_reversal, kind=request.data.get('kind', ''),
                          reason=request.data.get('reason', ''), amount=request.data.get('amount'))

    @action(detail=True, methods=['post'], url_path=r'reversals/(?P<rr_id>\d+)/(?P<verb>approve|reject|cancel)')
    def act_reversal(self, request, pk=None, rr_id=None, verb=None):
        from . import reversal
        self.get_object()                                     # branch scope (404 outside)
        user, version, note = _staff(request), request.data.get('version'), request.data.get('note', '')
        if verb == 'cancel':
            fn = lambda: reversal.cancel_reversal(int(pk), int(rr_id), user=user, version=version,
                                                  reason=note, request=request)
        else:
            fn = lambda: reversal.decide_reversal(int(pk), int(rr_id), user=user, version=version,
                                                  approve=verb == 'approve', note=note, request=request)
        return self._do(fn)

    @action(detail=True, methods=['post'], url_path='insurer-rejection')
    def insurer_rejection(self, request, pk=None):
        from . import reversal
        return self._step(request, pk, reversal.record_insurer_rejection, note=request.data.get('note', ''))

    # ── B2: balance in Customer 360 / POS, and funding a POS order from it ────
    def _call(self, fn, render):
        """Same error mapping as _do, for services that do not return a case."""
        try:
            return Response(render(fn()))
        except ValidationError as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'detail': str(e) or 'غير مسموح.'}, status=status.HTTP_403_FORBIDDEN)

    def _scoped_order(self, request, order_id):
        """The POS order, only inside the viewer's branches (404 outside — same rule as cases)."""
        from apps.pos_orders.models import SoftechSalesOrder
        qs = SoftechSalesOrder.objects.filter(pk=order_id)
        staff = _staff(request)
        ids = staff.accessible_branch_ids if staff and not request.user.is_superuser else None
        if staff is None and not request.user.is_superuser:
            return None
        return (qs if ids is None else qs.filter(branch_id__in=ids)).first()

    @action(detail=False, methods=['get'], url_path='patient-balance')
    def patient_balance(self, request):
        """GET ?pic=&branch= — the patient's redeemable بدل balance (live cases) + historical open, for staff."""
        from . import redemption
        out = redemption.patient_balance(request.query_params.get('pic'), staff=_staff(request),
                                         branch_id=request.query_params.get('branch') or None)
        return Response(out or {'total_available': '0', 'cases': [], 'historical': {'count': 0, 'amount': '0'}})

    @action(detail=False, methods=['get'], url_path='patient-orders')
    def patient_orders(self, request):
        """GET ?pic=&branch= — the patient's open POS cash / delivery orders that can still be funded."""
        from apps.pos_orders.models import SoftechSalesOrder
        from . import redemption
        pic = (request.query_params.get('pic') or '').strip()
        if not pic:
            return Response({'results': []})
        qs = SoftechSalesOrder.objects.filter(softech_pic__iexact=pic, channel__in=['cash', 'delivery'],
                                              status__in=redemption.FUNDABLE_ORDER_STATUSES)
        if request.query_params.get('branch'):
            qs = qs.filter(branch_id=request.query_params['branch'])
        staff = _staff(request)
        ids = staff.accessible_branch_ids if staff and not request.user.is_superuser else None
        if ids is not None:
            qs = qs.filter(branch_id__in=ids)
        rows = []
        for o in qs.order_by('-id')[:20]:
            funded = redemption.order_funding(o)
            rows.append({'id': o.pk, 'channel': o.channel, 'status': o.status, 'status_label': o.get_status_display(),
                         'created_at': o.created_at, 'total': str(redemption.order_total(o)),
                         'lines': o.lines.count(),
                         'funded_by': [{'case': op.case.number, 'case_id': op.case_id,
                                        'amount': str(op.expected_value)} for op in funded]})
        return Response({'results': rows})

    @action(detail=False, methods=['post'], url_path='fund-order')
    def fund_order(self, request):
        """POST {order, cases?:[id…]} — fund a POS order from the patient's live balance."""
        from . import redemption
        if self._scoped_order(request, request.data.get('order')) is None:
            return Response({'detail': 'الطلب غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
        return self._call(
            lambda: redemption.fund_order(int(request.data['order']), user=_staff(request),
                                          case_ids=request.data.get('cases') or None, request=request),
            lambda ops: {'funded': [{'case': op.case.number, 'case_id': op.case_id, 'amount': str(op.expected_value),
                                     'topup': op.result.get('customer_topup', '0')} for op in ops]})

    @action(detail=False, methods=['post'], url_path='unfund-order')
    def unfund_order(self, request):
        """POST {order, reason} — release the balance reserved on an unsettled POS order."""
        from . import redemption
        if self._scoped_order(request, request.data.get('order')) is None:
            return Response({'detail': 'الطلب غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
        return self._call(
            lambda: redemption.unfund_order(int(request.data['order']), user=_staff(request),
                                            reason=request.data.get('reason', ''), request=request),
            lambda n: {'released': n})

    @action(detail=False, methods=['get'], url_path='patient-sales')
    def patient_sales(self, request):
        """Recent CONTRACT sales of a patient at a branch — to start a case from the prescription.
        `pic` may be the SOFTECH PIC or a mobile number (Customer 360 identity); a mobile shared by
        several customers returns `patients` to choose from and no sales."""
        from datetime import timedelta
        from django.utils import timezone
        from apps.customers.models import Customer, PurchaseHistory
        from . import config as C
        pic = (request.query_params.get('pic') or '').strip()
        branch = request.query_params.get('branch')
        if not pic:
            return Response({'results': [], 'patients': []})
        patients = []
        digits = ''.join(ch for ch in pic if ch.isdigit())
        if digits == pic.replace(' ', '').lstrip('+') and len(digits) >= 8:       # a phone number
            tail = digits[-10:]
            found = (Customer.objects.filter(Q(phone__endswith=tail) | Q(phone_alt__endswith=tail)
                                             | Q(whatsapp_phone__endswith=tail))
                     .exclude(softech_pic='').values('softech_pic', 'name', 'phone')[:10])
            patients = [{'pic': f['softech_pic'], 'name': f['name'], 'phone': f['phone']} for f in found]
            if len(patients) != 1:
                return Response({'results': [], 'patients': patients})
            pic = patients[0]['pic']
        qs = (PurchaseHistory.objects.filter(softech_phcode__iexact=pic, doc_code='115',
                                             sales_channel__in=C.CONTRACT_CHANNELS,
                                             invoice_date__gte=timezone.now() - timedelta(days=60))
              .select_related('branch').prefetch_related('lines__item').order_by('-invoice_date')[:20])
        if branch:
            qs = [s for s in qs if str(s.branch_id) == str(branch)]
        def lines(s):
            # SOFTECH pre-splits one item over several lines (batches / reservation slices) —
            # the prescription view shows ONE row per item with the summed quantity.
            agg = {}
            for l in s.lines.all():
                if not l.item_id:
                    continue
                a = agg.setdefault(l.item.softech_id, {
                    'item_id': l.item_id, 'itemcode': l.item.softech_id, 'name': l.item.name, 'qty': Decimal('0'),
                    'public_price': str(l.list_price or l.item.pack_price or 0), 'contract_price': str(l.unit_price)})
                a['qty'] += l.quantity
            return [{**a, 'qty': str(a['qty'])} for a in agg.values()]
        return Response({'pic': pic, 'patients': patients, 'results': [{
            'id': s.pk, 'branch': s.branch_id, 'branchcode': s.branch.softech_branch_id, 'docnumber': s.docnumber,
            'date': s.invoice_date.date().isoformat() if s.invoice_date else None, 'total': str(s.total_amount),
            'contract': s.cust_branch_code, 'lines': lines(s)} for s in qs]})


class ReplacementRuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Rules are versioned: GET lists them; POST /rules/{id}/new-version/ creates version+1 (the old
    version stays for history and for every calculation that used it)."""
    permission_classes = [CanUseReplacement]
    serializer_class = RuleSerializer
    queryset = ReplacementRule.objects.all()

    @action(detail=True, methods=['post'], url_path='new-version')
    def new_version(self, request, pk=None):
        staff = _staff(request)
        if not (staff and (staff.role == 'admin' or request.user.is_superuser)):
            return Response({'detail': 'تعديل القواعد للمدير فقط.'}, status=status.HTTP_403_FORBIDDEN)
        old = self.get_object()
        latest = ReplacementRule.objects.filter(rule_key=old.rule_key).order_by('-version').first()
        fields = {f: request.data.get(f, getattr(latest, f)) for f in
                  ('name', 'deduction_pct', 'supplier_personcode', 'rounding', 'priority', 'is_active',
                   'effective_from', 'effective_until', 'contract_personcode', 'branchcode')}
        new = ReplacementRule.objects.create(
            rule_key=latest.rule_key, version=latest.version + 1, source_type=latest.source_type,
            settlement_mode=latest.settlement_mode, shortage_only=latest.shortage_only, created_by=staff, **fields)
        from apps.audit.models import AuditLog
        AuditLog.log('replacement_case_updated', user=staff, obj=new, request=request,
                     old_data=RuleSerializer(latest).data, new_data=RuleSerializer(new).data, note='rule new version')
        return Response(RuleSerializer(new).data, status=status.HTTP_201_CREATED)


class ReplacementGrantViewSet(viewsets.ModelViewSet):
    """Per-employee grants (admin only to change; supervisors may read)."""
    permission_classes = [CanUseReplacement]
    serializer_class = GrantSerializer
    queryset = ReplacementGrant.objects.select_related('staff__user')

    def _admin(self):
        s = _staff(self.request)
        return bool(s and (s.role == 'admin' or self.request.user.is_superuser))

    def create(self, request, *a, **k):
        if not self._admin():
            return Response({'detail': 'للمدير فقط.'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *a, **k)

    def update(self, request, *a, **k):
        if not self._admin():
            return Response({'detail': 'للمدير فقط.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *a, **k)

    def destroy(self, request, *a, **k):
        if not self._admin():
            return Response({'detail': 'للمدير فقط.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *a, **k)

    def perform_create(self, serializer):
        serializer.save(granted_by=_staff(self.request))

    def perform_update(self, serializer):
        serializer.save(granted_by=_staff(self.request))


class CaseExceptionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [CanUseReplacement]
    serializer_class = ExceptionSerializer

    def get_queryset(self):
        cases = scoped_cases(self.request, RC.objects.all())
        qs = X.objects.filter(case__in=cases).select_related('case', 'resolved_by')
        p = self.request.query_params
        for key, field in (('type', 'exception_type'), ('severity', 'severity'), ('status', 'status')):
            if p.get(key):
                qs = qs.filter(**{f'{field}__in': p[key].split(',')})
        if not p.get('status'):
            qs = qs.filter(status__in=[X.STATUS_OPEN, X.STATUS_ACK])
        return qs.order_by('-created_at')


class ReconstructionRunViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanUseReplacement]
    serializer_class = RunSerializer
    queryset = ReconstructionRun.objects.all()
