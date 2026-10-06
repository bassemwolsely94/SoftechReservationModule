from decimal import Decimal
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.catalog.models import Item
from .models import ItemPriceChangeRequest, USER_EDITABLE_FIELDS, FIELD_LABELS
from .serializers import ItemPriceChangeRequestSerializer, ReviewSerializer
from .services import execute_price_change, compute_derived_preview


def _is_admin(user):
    try:
        return user.staff_profile.role == 'admin'
    except Exception:
        return user.is_staff


def _get_approver_softech(user):
    """
    Returns (usercode, username) for the approver from their StaffProfile.
    Both fields must be set for approval to proceed.
    """
    try:
        sp = user.staff_profile
        return sp.softech_user_id.strip(), sp.softech_username.strip()
    except Exception:
        return '', ''


class IsAdminRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and _is_admin(request.user)


class RequestListCreateView(generics.ListCreateAPIView):
    serializer_class   = ItemPriceChangeRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ItemPriceChangeRequest.objects.select_related(
            'item', 'requested_by', 'reviewed_by'
        )
        s = self.request.query_params.get('status')
        if s:
            qs = qs.filter(status=s)
        item_id = self.request.query_params.get('item')
        if item_id:
            qs = qs.filter(item_id=item_id)
        if not _is_admin(self.request.user):
            qs = qs.filter(requested_by=self.request.user)
        return qs

    def perform_create(self, serializer):
        item = serializer.validated_data['item']

        # Snapshot current values of all priceable fields from Django catalog
        old_values = {}
        for django_field, _, _ in USER_EDITABLE_FIELDS:
            val = getattr(item, django_field, None)
            old_values[django_field] = str(val) if val is not None else '0'
        # Also snapshot the auto-derived fields for audit completeness
        for auto_field in ('pack_price_tax', 'unit_price'):
            val = getattr(item, auto_field, None)
            old_values[auto_field] = str(val) if val is not None else '0'

        obj = serializer.save(
            requested_by=self.request.user,
            old_values=old_values,
        )
        from .notify import notify_admins_new_request
        notify_admins_new_request(obj)


class RequestDetailView(generics.RetrieveAPIView):
    serializer_class   = ItemPriceChangeRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ItemPriceChangeRequest.objects.select_related(
            'item', 'requested_by', 'reviewed_by'
        )
        if not _is_admin(self.request.user):
            qs = qs.filter(requested_by=self.request.user)
        return qs


@api_view(['POST'])
@permission_classes([IsAdminRole])
def approve_request(request, pk):
    try:
        obj = ItemPriceChangeRequest.objects.select_related('item').get(pk=pk)
    except ItemPriceChangeRequest.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)

    if obj.status not in (
        ItemPriceChangeRequest.STATUS_PENDING,
        ItemPriceChangeRequest.STATUS_FAILED,  # allow retry on failed
    ):
        return Response(
            {'detail': f'لا يمكن اعتماد طلب بحالة: {obj.get_status_display()}'},
            status=400
        )

    # Stamp the approver's OWN real SOFTECH usercode (synced from the users
    # table), so the edit is attributable to that admin in SOFTECH exactly as if
    # they made it manually in Items Master.
    erp_usercode, erp_username = _get_approver_softech(request.user)
    if not erp_usercode:
        return Response(
            {
                'detail': (
                    'حسابك غير مرتبط بمستخدم Softech. '
                    'يرجى ربط softech_user_id (كود المستخدم في Softech) بحسابك أولاً.'
                ),
                'error_code': 'no_softech_user',
            },
            status=400
        )

    ser = ReviewSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    obj.status       = ItemPriceChangeRequest.STATUS_APPROVED
    obj.reviewed_by  = request.user
    obj.reviewed_at  = timezone.now()
    obj.review_notes = ser.validated_data.get('notes', '')
    obj.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])

    success = execute_price_change(obj, erp_usercode=erp_usercode, erp_username=erp_username)
    obj.refresh_from_db()

    if success:
        from .notify import notify_requester_decision
        notify_requester_decision(obj, 'executed')

    return Response(
        ItemPriceChangeRequestSerializer(obj).data,
        status=200 if success else 207,
    )


@api_view(['POST'])
@permission_classes([IsAdminRole])
def reject_request(request, pk):
    try:
        obj = ItemPriceChangeRequest.objects.get(pk=pk)
    except ItemPriceChangeRequest.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)

    if obj.status != ItemPriceChangeRequest.STATUS_PENDING:
        return Response(
            {'detail': f'لا يمكن رفض طلب بحالة: {obj.get_status_display()}'},
            status=400
        )

    ser = ReviewSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    obj.status       = ItemPriceChangeRequest.STATUS_REJECTED
    obj.reviewed_by  = request.user
    obj.reviewed_at  = timezone.now()
    obj.review_notes = ser.validated_data.get('notes', '')
    obj.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])

    from .notify import notify_requester_decision
    notify_requester_decision(obj, 'rejected')

    return Response(ItemPriceChangeRequestSerializer(obj).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def item_current_prices(request, softech_id):
    """
    Returns all priceable field values + pack_qty + sale_tax_pct for one item.
    Used by the create form to pre-populate current values and compute previews.
    """
    try:
        item = Item.objects.get(softech_id=softech_id)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=404)

    data = {
        'id':           item.id,
        'softech_id':   item.softech_id,
        'name':         item.name,
        'pack_qty':     item.pack_qty,
        'sale_tax_pct': str(item.sale_tax_pct or '0'),
    }
    for django_field, label, _ in USER_EDITABLE_FIELDS:
        data[django_field]             = str(getattr(item, django_field, '0') or '0')
        data[f'{django_field}_label']  = label
    # Include auto-derived fields for display
    data['pack_price_tax'] = str(item.pack_price_tax or '0')
    data['unit_price']     = str(item.unit_price or '0')

    return Response(data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def price_preview(request):
    """
    Compute auto-derived values (unit_price, pack_price_tax) for a given
    pack_price + item context. Called live from the create form.

    Query params: pack_price, pack_qty, sale_tax_pct
    """
    pack_price_str  = request.query_params.get('pack_price', '0')
    pack_qty        = int(request.query_params.get('pack_qty', 1) or 1)
    sale_tax_pct    = request.query_params.get('sale_tax_pct', '0')
    result = compute_derived_preview(pack_price_str, pack_qty, sale_tax_pct)
    return Response(result)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def approver_softech_info(request):
    """
    Returns the current user's Softech account info so the frontend
    can warn early if the admin has no linked Softech account.
    """
    erp_usercode, erp_username = _get_approver_softech(request.user)
    return Response({
        'erp_usercode': erp_usercode,
        'erp_username': erp_username,
        'is_linked':    bool(erp_usercode),
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def pending_count(request):
    count = ItemPriceChangeRequest.objects.filter(
        status=ItemPriceChangeRequest.STATUS_PENDING
    ).count()
    return Response({'count': count})


# ════════════════════════════════════════════════════════════════════════════
# Feature: per-request replication status badge (#2)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def request_replication(request, pk):
    """Live HQ↔branch replication status for the item in this request."""
    try:
        obj = ItemPriceChangeRequest.objects.select_related('item').get(pk=pk)
    except ItemPriceChangeRequest.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)
    if not _is_admin(request.user) and obj.requested_by_id != request.user.id:
        return Response({'detail': 'غير مصرح'}, status=403)
    from .replication import check_item
    return Response(check_item(obj.item.softech_id))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def request_force_replication(request, pk):
    """Force re-replication of this request's item (restamp / push / both)."""
    try:
        obj = ItemPriceChangeRequest.objects.select_related('item').get(pk=pk)
    except ItemPriceChangeRequest.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)
    # Repair preserves the item's original editor — no approver usercode needed.
    mode = request.data.get('mode', 'restamp')
    from .replication import force_replication
    out = force_replication(obj.item.softech_id, mode=mode)
    return Response(out)


# ════════════════════════════════════════════════════════════════════════════
# Feature: pending SLA dashboard (#9)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def sla_dashboard(request):
    """Pending requests aging report — count, oldest-first, age buckets."""
    from datetime import timedelta
    now = timezone.now()
    qs = ItemPriceChangeRequest.objects.filter(
        status=ItemPriceChangeRequest.STATUS_PENDING
    ).select_related('item', 'requested_by').order_by('requested_at')

    buckets = {'lt1h': 0, 'h1_4': 0, 'h4_24': 0, 'gt24h': 0}
    rows = []
    for r in qs:
        age_h = (now - r.requested_at).total_seconds() / 3600.0
        if   age_h < 1:  buckets['lt1h']  += 1
        elif age_h < 4:  buckets['h1_4']  += 1
        elif age_h < 24: buckets['h4_24'] += 1
        else:            buckets['gt24h'] += 1
        rows.append({
            'id': r.id, 'item_name': r.item.name, 'item_softech_id': r.item.softech_id,
            'requested_by': r.requested_by.get_full_name() or r.requested_by.username,
            'requested_at': r.requested_at,
            'age_hours': round(age_h, 1),
            'new_values': r.new_values,
            'reason': r.reason,
        })
    return Response({
        'total_pending': len(rows),
        'buckets': buckets,
        'oldest_age_hours': rows[0]['age_hours'] if rows else 0,
        'requests': rows,
    })


# ════════════════════════════════════════════════════════════════════════════
# Feature: rollback (#10) — create a reverse request from stored old_values
# ════════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def rollback_request(request, pk):
    """Create a NEW pending request that reverts an executed request to its old_values."""
    try:
        src = ItemPriceChangeRequest.objects.select_related('item').get(pk=pk)
    except ItemPriceChangeRequest.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)
    if src.status != ItemPriceChangeRequest.STATUS_EXECUTED:
        return Response({'detail': 'يمكن التراجع فقط عن طلب مُنفَّذ'}, status=400)

    # Reverse = restore the previous value for each field that was changed
    revert_values = {}
    for field in src.new_values.keys():
        if field in src.old_values:
            revert_values[field] = str(src.old_values[field])
    if not revert_values:
        return Response({'detail': 'لا توجد قيم سابقة للتراجع إليها'}, status=400)

    # Snapshot CURRENT values as old_values of the rollback request
    item = src.item
    old_values = {}
    for f, _, _ in USER_EDITABLE_FIELDS:
        v = getattr(item, f, None)
        old_values[f] = str(v) if v is not None else '0'
    for af in ('pack_price_tax', 'unit_price'):
        v = getattr(item, af, None)
        old_values[af] = str(v) if v is not None else '0'

    new = ItemPriceChangeRequest.objects.create(
        item=item, requested_by=request.user,
        old_values=old_values, new_values=revert_values,
        reason=f'تراجع عن الطلب #{src.id}: {src.reason}'[:500],
        status=ItemPriceChangeRequest.STATUS_PENDING,
        source='rollback', rolled_back_from=src,
    )
    from .notify import notify_admins_new_request
    notify_admins_new_request(new)
    return Response(ItemPriceChangeRequestSerializer(new).data, status=201)


# ════════════════════════════════════════════════════════════════════════════
# Feature: CSV/Excel batch import (#11)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def import_requests(request):
    """
    Bulk-create pending requests from an uploaded CSV/XLSX.
    Expected columns (header row, case-insensitive):
      itemcode, pack_price, pharmacy_discp, additional_discp, special_discp, pos_discp, reason
    Only itemcode + at least one priceable field required per row.
    """
    f = request.FILES.get('file')
    if not f:
        return Response({'detail': 'لم يتم رفع ملف'}, status=400)

    rows, err = _parse_import_file(f)
    if err:
        return Response({'detail': err}, status=400)

    editable = {x[0] for x in USER_EDITABLE_FIELDS}
    created, skipped = [], []
    for idx, row in enumerate(rows, start=2):  # row 1 = header
        code = str(row.get('itemcode', '')).strip()
        if not code:
            continue
        try:
            item = Item.objects.get(softech_id=code)
        except Item.DoesNotExist:
            skipped.append({'row': idx, 'itemcode': code, 'reason': 'صنف غير موجود'})
            continue
        new_values = {}
        for field in editable:
            raw = row.get(field, '')
            if raw not in ('', None):
                try:
                    val = Decimal(str(raw))
                    if val < 0:
                        raise ValueError
                    new_values[field] = str(val)
                except Exception:
                    skipped.append({'row': idx, 'itemcode': code, 'reason': f'قيمة غير صالحة: {field}={raw}'})
                    new_values = None
                    break
        if new_values is None:
            continue
        if not new_values:
            skipped.append({'row': idx, 'itemcode': code, 'reason': 'لا توجد حقول للتعديل'})
            continue

        old_values = {}
        for fl, _, _ in USER_EDITABLE_FIELDS:
            v = getattr(item, fl, None)
            old_values[fl] = str(v) if v is not None else '0'
        for af in ('pack_price_tax', 'unit_price'):
            v = getattr(item, af, None)
            old_values[af] = str(v) if v is not None else '0'

        obj = ItemPriceChangeRequest.objects.create(
            item=item, requested_by=request.user,
            old_values=old_values, new_values=new_values,
            reason=str(row.get('reason', '') or 'استيراد ملف')[:500],
            status=ItemPriceChangeRequest.STATUS_PENDING, source='import',
        )
        created.append(obj.id)

    if created:
        # Single batched notification to admins
        try:
            from apps.notifications.models import Notification
            from apps.users.models import StaffProfile
            for sp in StaffProfile.objects.filter(role='admin', is_active=True):
                Notification.send_to_user(
                    sp, 'system', '🏷️ دفعة طلبات تعديل أسعار',
                    f'{len(created)} طلب جديد عبر استيراد ملف (بواسطة {request.user.username})',
                    dedup_key=f'pricing_import_{request.user.id}_{created[0]}',
                )
        except Exception:
            pass

    return Response({'created': len(created), 'created_ids': created,
                     'skipped': skipped}, status=201 if created else 200)


def _parse_import_file(f):
    """Return (rows[list[dict]], error_str). Supports .csv and .xlsx."""
    name = (f.name or '').lower()
    try:
        if name.endswith('.csv'):
            import csv, io
            text = f.read().decode('utf-8-sig', errors='replace')
            reader = csv.DictReader(io.StringIO(text))
            return [{(k or '').strip().lower(): v for k, v in r.items()} for r in reader], None
        elif name.endswith('.xlsx') or name.endswith('.xlsm'):
            from openpyxl import load_workbook
            wb = load_workbook(f, read_only=True, data_only=True)
            ws = wb.active
            it = ws.iter_rows(values_only=True)
            header = [str(c).strip().lower() if c is not None else '' for c in next(it)]
            rows = []
            for r in it:
                rows.append({header[i]: r[i] for i in range(len(header)) if header[i]})
            return rows, None
        else:
            return None, 'صيغة غير مدعومة — استخدم CSV أو XLSX'
    except StopIteration:
        return [], None
    except Exception as exc:
        return None, f'تعذّر قراءة الملف: {exc}'


# ════════════════════════════════════════════════════════════════════════════
# Feature: replication audit scan + repair (#7/#8/#12) — covers DIRECT edits too
# ════════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([IsAdminRole])
def run_replication_scan(request):
    """
    Run a HQ↔branch replication audit.
    days=N (1..90) → recent-changes window; days=0 → FULL-CATALOG deep audit (#6).
    """
    from .replication import scan_recent
    from .notify import notify_admins_replication_gaps
    raw = request.data.get('days', 30)
    full = str(raw) in ('0', 'full', 'all')
    days = None if full else max(1, min(int(raw or 30), 90))
    scan = scan_recent(days=days, persist=True, triggered_by=request.user)
    notify_admins_replication_gaps(scan)
    from .serializers import ReplicationScanSerializer
    return Response(ReplicationScanSerializer(scan).data, status=201)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def replication_scans(request):
    """List recent replication scans."""
    from .models import ReplicationScan
    from .serializers import ReplicationScanSerializer
    qs = ReplicationScan.objects.all()[:30]
    return Response(ReplicationScanSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def replication_scan_detail(request, pk):
    """One scan with its gaps (optionally filtered by status/source/branch)."""
    from .models import ReplicationScan, ReplicationGap
    from .serializers import ReplicationScanSerializer, ReplicationGapSerializer
    try:
        scan = ReplicationScan.objects.get(pk=pk)
    except ReplicationScan.DoesNotExist:
        return Response({'detail': 'غير موجود'}, status=404)
    gaps = ReplicationGap.objects.filter(scan=scan)
    for p in ('status', 'source_channel', 'branch_code'):
        v = request.query_params.get(p)
        if v:
            gaps = gaps.filter(**{p: v})
    data = ReplicationScanSerializer(scan).data
    data['gaps'] = ReplicationGapSerializer(gaps, many=True).data
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def repair_gaps(request):
    """
    Force re-replication for specific gaps (or all gaps of a scan).
    Body: { gap_ids: [...] }  OR  { scan_id: N, branch_code?, status? }
          mode: 'restamp' (default) | 'push' | 'both'
    """
    from .models import ReplicationGap
    from .replication import force_replication, check_item
    # Repair preserves each item's original editor — no approver usercode needed.
    mode = request.data.get('mode', 'restamp')
    gap_ids = request.data.get('gap_ids')
    if gap_ids:
        gaps = ReplicationGap.objects.filter(id__in=gap_ids)
    elif request.data.get('scan_id'):
        gaps = ReplicationGap.objects.filter(scan_id=request.data['scan_id']).exclude(status=ReplicationGap.STATUS_REPAIRED)
        if request.data.get('branch_code'):
            gaps = gaps.filter(branch_code=request.data['branch_code'])
    else:
        return Response({'detail': 'حدد gap_ids أو scan_id'}, status=400)

    # Repair per distinct item (restamp re-pushes the whole row to all branches)
    items = sorted({g.item_softech_id for g in gaps})
    results = {}
    for code in items:
        out = force_replication(code, mode=mode)
        results[code] = out

    # Mark gaps repaired + re-verify
    repaired = 0
    for g in gaps:
        st = check_item(g.item_softech_id)
        branch = next((b for b in st.get('branches', []) if b['code'] == g.branch_code), None)
        if branch and branch['status'] == 'replicated':
            g.status = ReplicationGap.STATUS_REPAIRED
            g.repaired_at = timezone.now()
            g.repaired_by = request.user
            g.repair_note = f'mode={mode}'
            g.save(update_fields=['status', 'repaired_at', 'repaired_by', 'repair_note'])
            repaired += 1

    return Response({
        'items_repaired_attempted': len(items),
        'gaps_confirmed_repaired': repaired,
        'detail': results,
        'note': 'restamp re-queues for the native ~30-min cycle; re-run the scan after a cycle to confirm offline branches.',
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def item_replication_status(request, softech_id):
    """Ad-hoc replication check for ANY item (not tied to a request)."""
    from .replication import check_item
    return Response(check_item(softech_id))


# ════════════════════════════════════════════════════════════════════════════
# Feature #4 — Branch health board
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAdminRole])
def branch_health(request):
    """
    Per-branch replication health, derived from the latest completed scan (fast,
    no live connections): current stale items, whether the branch was down, and
    the last fully-clean scan time.
    """
    from apps.branches.models import Branch
    from .models import ReplicationScan, ReplicationGap

    latest = ReplicationScan.objects.filter(status=ReplicationScan.STATUS_DONE).first()
    branches = Branch.objects.filter(
        is_operational=True, db_host__isnull=False
    ).exclude(softech_branch_id='100').exclude(db_host='')

    rows = []
    for b in branches:
        code = b.softech_branch_id
        stale = unreachable = 0
        was_down = False
        if latest:
            gaps = ReplicationGap.objects.filter(scan=latest, branch_code=code).exclude(status='repaired')
            stale = gaps.filter(status='stale').count()
            unreachable = gaps.filter(status='unreachable').count()
            was_down = code in (latest.branches_down or [])
        last_clean = (
            ReplicationScan.objects.filter(status=ReplicationScan.STATUS_DONE)
            .exclude(gaps__branch_code=code)
            .order_by('-started_at').values_list('started_at', flat=True).first()
        )
        total_gaps = stale + unreachable
        rows.append({
            'branch_code': code, 'branch_name': b.name, 'db_host': b.db_host,
            'stale_items': stale, 'unreachable_items': unreachable,
            'total_gaps': total_gaps, 'was_down': was_down,
            'health': 'down' if was_down else ('lagging' if total_gaps else 'healthy'),
            'last_clean_scan_at': last_clean,
        })
    rows.sort(key=lambda r: (-r['total_gaps'], r['branch_code']))
    return Response({
        'latest_scan_id': latest.id if latest else None,
        'latest_scan_at': latest.started_at if latest else None,
        'branches': rows,
        'branches_down': latest.branches_down if latest else [],
    })


# ════════════════════════════════════════════════════════════════════════════
# Feature #8 — Per-item price history timeline (system of record)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def price_history(request, softech_id):
    """Every recorded change for an item — old to new, who, when, reason, source."""
    try:
        item = Item.objects.get(softech_id=softech_id)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=404)

    qs = (ItemPriceChangeRequest.objects
          .filter(item=item)
          .select_related('requested_by', 'reviewed_by')
          .order_by('-requested_at'))

    events = []
    for r in qs:
        events.append({
            'id': r.id,
            'status': r.status, 'status_display': r.get_status_display(),
            'source': r.source,
            'requested_by': r.requested_by.get_full_name() or r.requested_by.username,
            'requested_at': r.requested_at,
            'reviewed_by': (r.reviewed_by.get_full_name() or r.reviewed_by.username) if r.reviewed_by else None,
            'reviewed_at': r.reviewed_at,
            'erp_executed_at': r.erp_executed_at,
            'erp_username': r.erp_username,
            'old_values': r.old_values, 'new_values': r.new_values,
            'executed_values': {k: v for k, v in (r.executed_values or {}).items() if not k.startswith('_')},
            'reason': r.reason, 'review_notes': r.review_notes,
            'rolled_back_from': r.rolled_back_from_id,
        })
    return Response({
        'item': {'softech_id': item.softech_id, 'name': item.name},
        'count': len(events),
        'events': events,
    })


# ════════════════════════════════════════════════════════════════════════════
# Feature #11 — Who-changed-what (module vs direct SOFTECH edits per operator)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAdminRole])
def who_changed_what(request):
    """
    Over the last N days, how much pricing changed via the module vs directly in
    SOFTECH, broken down by operator — to see how much bypasses the approval flow.
    """
    from datetime import timedelta
    from config.sybase import get_sybase_connection
    from .replication import _usercode_name_map

    days = max(1, min(int(request.query_params.get('days', 30) or 30), 90))
    cutoff = timezone.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    by_user = []
    total_direct = 0
    try:
        conn = get_sybase_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT usercode, COUNT(*) FROM SOFTECHDB9.dbo.items "
            f"WHERE itemlastupdate >= convert(datetime, '{cutoff_str}') "
            "GROUP BY usercode"
        )
        raw = cur.fetchall()
        conn.close()
        codes = [str(r[0] or '').strip() for r in raw]
        names = _usercode_name_map(codes)
        for r in raw:
            uc = str(r[0] or '').strip()
            n = int(r[1] or 0)
            total_direct += n
            by_user.append({'usercode': uc, 'name': names.get(uc, '') or uc, 'edits': n})
        by_user.sort(key=lambda x: -x['edits'])
    except Exception as exc:
        return Response({'detail': f'تعذّر قراءة Softech: {exc}'}, status=502)

    from django.db.models import Count
    mod = (ItemPriceChangeRequest.objects
           .filter(status=ItemPriceChangeRequest.STATUS_EXECUTED, erp_executed_at__gte=cutoff)
           .values('erp_username', 'reviewed_by__username')
           .annotate(n=Count('id')))
    module_total = sum(m['n'] for m in mod)
    by_approver = [{
        'approver': (m['reviewed_by__username'] or m['erp_username'] or '—'),
        'erp_username': m['erp_username'], 'executed': m['n'],
    } for m in sorted(mod, key=lambda x: -x['n'])]

    return Response({
        'days': days,
        'total_hq_edits': total_direct,
        'module_executed': module_total,
        'module_share_pct': round(100.0 * module_total / total_direct, 1) if total_direct else 0,
        'by_user_softech': by_user,
        'by_approver_module': by_approver,
    })


# ════════════════════════════════════════════════════════════════════════════
# Feature #5 — Auto-repair policy (read/update the scheduled-job config)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def replication_policy(request):
    from .models import ReplicationPolicy
    pol = ReplicationPolicy.get()
    if request.method == 'POST':
        for f in ('auto_repair_enabled', 'weekly_full_audit'):
            if f in request.data:
                setattr(pol, f, bool(request.data[f]))
        for f in ('max_items_per_run', 'daily_window_days'):
            if f in request.data:
                try:
                    setattr(pol, f, max(1, int(request.data[f])))
                except Exception:
                    pass
        pol.updated_by = request.user
        pol.save()
    return Response({
        'auto_repair_enabled': pol.auto_repair_enabled,
        'max_items_per_run': pol.max_items_per_run,
        'daily_window_days': pol.daily_window_days,
        'weekly_full_audit': pol.weekly_full_audit,
        'updated_at': pol.updated_at,
        'updated_by': pol.updated_by.username if pol.updated_by else None,
    })


# ════════════════════════════════════════════════════════════════════════════
# Feature #10 — Discount-impact report (sales lift after a discount change)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAdminRole])
def discount_impact(request):
    """
    For each EXECUTED price/discount change, compare item sales in the `window`
    days BEFORE vs AFTER the change, using SalesTransactionLine. Uses daily
    averages so a partial after-window is still comparable.

    Query params: window (days, default 30), branch (optional softech branch),
                  min_after_days (skip changes too recent to judge, default 7).
    """
    from datetime import timedelta
    from django.db.models import Sum
    from apps.purchasing.models import SalesTransactionLine

    window = max(7, min(int(request.query_params.get('window', 30) or 30), 120))
    min_after = max(1, int(request.query_params.get('min_after_days', 7) or 7))
    branch = (request.query_params.get('branch') or '').strip()
    today = timezone.now().date()

    DISCOUNT_FIELDS = {'pos_discp', 'pharmacy_discp', 'additional_discp', 'special_discp'}

    reqs = (ItemPriceChangeRequest.objects
            .filter(status=ItemPriceChangeRequest.STATUS_EXECUTED, erp_executed_at__isnull=False)
            .select_related('item')
            .order_by('-erp_executed_at'))

    def agg(item, d0, d1):
        qs = SalesTransactionLine.objects.filter(item=item, doc_date__gte=d0, doc_date__lt=d1)
        if branch:
            qs = qs.filter(softech_branchcode=branch)
        r = qs.aggregate(q=Sum('net_qty'), rev=Sum('net_revenue'))
        return float(r['q'] or 0), float(r['rev'] or 0)

    changes = []
    lifts = []
    for req in reqs:
        d = req.erp_executed_at.date()
        after_end = min(d + timedelta(days=window), today)
        after_days = (after_end - d).days
        if after_days < min_after:
            maturity = 'too_recent'
        else:
            maturity = 'mature'

        before_q, before_rev = agg(req.item, d - timedelta(days=window), d)
        after_q,  after_rev  = agg(req.item, d, after_end)

        before_days = window
        b_qd = before_q / before_days if before_days else 0
        a_qd = after_q / after_days if after_days else 0
        b_rd = before_rev / before_days if before_days else 0
        a_rd = after_rev / after_days if after_days else 0

        qty_lift = round(100 * (a_qd - b_qd) / b_qd, 1) if b_qd else None
        rev_lift = round(100 * (a_rd - b_rd) / b_rd, 1) if b_rd else None
        if b_qd == 0 and a_qd > 0:
            qty_lift = None  # no baseline
            maturity = 'no_baseline' if maturity == 'mature' else maturity

        changed = {}
        for f, newv in (req.new_values or {}).items():
            changed[f] = {'old': (req.old_values or {}).get(f), 'new': newv,
                          'is_discount': f in DISCOUNT_FIELDS}

        if maturity == 'mature' and qty_lift is not None:
            lifts.append(qty_lift)

        changes.append({
            'request_id': req.id,
            'item_softech_id': req.item.softech_id, 'item_name': req.item.name,
            'executed_at': req.erp_executed_at, 'days_since': (today - d).days,
            'changed': changed,
            'before': {'qty': round(before_q, 1), 'revenue': round(before_rev, 2), 'days': before_days},
            'after':  {'qty': round(after_q, 1),  'revenue': round(after_rev, 2),  'days': after_days},
            'qty_lift_pct': qty_lift, 'revenue_lift_pct': rev_lift,
            'maturity': maturity,
        })

    pos = sum(1 for x in lifts if x > 0)
    neg = sum(1 for x in lifts if x < 0)
    return Response({
        'window_days': window, 'branch': branch or 'all',
        'summary': {
            'total_changes': len(changes),
            'evaluated': len(lifts),
            'avg_qty_lift_pct': round(sum(lifts) / len(lifts), 1) if lifts else None,
            'positive_count': pos, 'negative_count': neg,
        },
        'changes': changes,
    })


# ════════════════════════════════════════════════════════════════════════════
# DISCOUNT-ALIGNMENT AUDIT  (compare item discount vs classification tier %)
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def alignment_scan(request):
    """
    Scan catalog items and flag those whose actual basic discount
    (pharmacy_discp) diverges from their classification tier % and/or the master
    SupplierDiscountPolicy. Read-only.

    Query params:
      only_misaligned=0|1   (default 1)  — return only flagged rows
      supplier_code=<csv>   — filter by supplier
      origin_code=<csv>     — filter by origin
      flag=<name>           — keep only rows carrying this flag
      search=<text>         — itemname / code contains
      include_inactive=1    — include is_active=False (discontinued) items
      limit=<int>           — cap rows (default 2000)
    """
    from .alignment import scan_alignment

    qs = Item.objects.all()
    if request.query_params.get('include_inactive') != '1':
        qs = qs.filter(is_active=True)

    def _csv(key):
        raw = request.query_params.get(key)
        return [v.strip() for v in raw.split(',') if v.strip()] if raw else None

    supp = _csv('supplier_code')
    if supp:
        qs = qs.filter(supplier_code__in=supp)
    origin = _csv('origin_code')
    if origin:
        qs = qs.filter(origin_code__in=origin)
    search = request.query_params.get('search')
    if search:
        qs = qs.filter(name__icontains=search)

    only_mis = request.query_params.get('only_misaligned', '1') != '0'
    try:
        limit = min(int(request.query_params.get('limit', 2000)), 20000)
    except (ValueError, TypeError):
        limit = 2000

    qs = qs.only(
        'id', 'softech_id', 'name', 'supplier_code', 'supplier_name',
        'origin_code', 'origin_name', 'origin_name_ar',
        'store_classif', 'store_classif_name',
        'pack_price', 'cost_price', 'pharmacy_discp', 'additional_discp',
        'special_discp', 'pos_discp', 'is_active', 'no_more_use',
    )
    rows, stats = scan_alignment(qs, only_misaligned=only_mis, limit=limit)

    flag = request.query_params.get('flag')
    if flag:
        rows = [r for r in rows if flag in r['flags']]

    return Response({'rows': rows, 'stats': stats})


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def alignment_policies(request):
    """GET → list master discount policies. POST (admin) → upsert one."""
    from .models import SupplierDiscountPolicy

    if request.method == 'GET':
        data = [{
            'id': p.id, 'scope': p.scope, 'code': p.code, 'label': p.label,
            'expected_discount': str(p.expected_discount),
            'expected_pos_discount': str(p.expected_pos_discount) if p.expected_pos_discount is not None else None,
            'is_active': p.is_active, 'note': p.note,
            'updated_at': p.updated_at,
        } for p in SupplierDiscountPolicy.objects.all()]
        return Response(data)

    if not _is_admin(request.user):
        return Response({'detail': 'غير مصرح — للمدير فقط'}, status=403)

    d = request.data
    scope = d.get('scope', 'supplier')
    code  = str(d.get('code', '')).strip()
    if scope not in ('supplier', 'origin') or not code:
        return Response({'detail': 'نطاق أو كود غير صالح'}, status=400)
    try:
        expected = Decimal(str(d.get('expected_discount')))
    except Exception:
        return Response({'detail': 'الخصم المتوقع غير صالح'}, status=400)
    pos = d.get('expected_pos_discount')
    try:
        pos_val = Decimal(str(pos)) if pos not in (None, '') else None
    except Exception:
        pos_val = None

    obj, _ = SupplierDiscountPolicy.objects.update_or_create(
        scope=scope, code=code,
        defaults={
            'label': d.get('label', ''),
            'expected_discount': expected,
            'expected_pos_discount': pos_val,
            'is_active': bool(d.get('is_active', True)),
            'note': d.get('note', ''),
            'updated_by': request.user,
        },
    )
    return Response({'id': obj.id, 'scope': obj.scope, 'code': obj.code,
                     'expected_discount': str(obj.expected_discount)}, status=200)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def alignment_tiers(request):
    """Distinct origin / contract-discount tiers (code, name, pct) for fix pickers."""
    from .alignment import list_tiers
    return Response(list_tiers())


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def alignment_apply(request):
    """
    Master-policy direction: fix stale classification LABELS to match the real
    discount. Bulk-writes itemorigincode / itemstoreclassif to SOFTECH for the
    selected items. Admin-only; uses the approver's own SOFTECH usercode.

    Body: { item_ids: [int], origin_code?: str, store_classif?: str }
    """
    if not _is_admin(request.user):
        return Response({'detail': 'غير مصرح — للمدير فقط'}, status=403)

    usercode, username = _get_approver_softech(request.user)
    if not usercode:
        return Response({'detail': 'لا يوجد كود SOFTECH مرتبط بحسابك — يلزم لتنفيذ التغيير'}, status=400)

    # Two modes:
    #   uniform   → {item_ids:[...], origin_code, store_classif}  (same target for all)
    #   per-row   → {changes:[{item_id, origin_code?, store_classif?}, ...]}  (each its own)
    changes = request.data.get('changes')
    if changes:
        plan = [{'item_id': c.get('item_id'),
                 'origin_code': c.get('origin_code'),
                 'store_classif': c.get('store_classif')} for c in changes]
    else:
        item_ids = request.data.get('item_ids') or []
        origin_code = request.data.get('origin_code')
        store_classif = request.data.get('store_classif')
        plan = [{'item_id': iid, 'origin_code': origin_code, 'store_classif': store_classif}
                for iid in item_ids]

    if not plan:
        return Response({'detail': 'لم تُحدَّد أصناف'}, status=400)
    if len(plan) > 1000:
        return Response({'detail': 'الحد الأقصى 1000 صنف في المرة'}, status=400)

    from .alignment import apply_classification_changes
    err, results = apply_classification_changes(plan, usercode)
    if err:
        return Response({'detail': err}, status=400)

    ok = sum(1 for r in results if r['ok'])
    return Response({
        'applied': ok, 'failed': len(results) - ok, 'total': len(results),
        'usercode': usercode, 'results': results,
        'note': 'كُتب على HQ + itemlastupdate — تنتشر للفروع عبر SSB9 خلال ~30 دقيقة',
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def alignment_tier_preview(request):
    """READ-ONLY preview of a new lookup tier before creating it (Phase 3)."""
    from .alignment import preview_new_tier
    kind  = request.query_params.get('kind', 'store')
    label = request.query_params.get('label', '')
    code  = request.query_params.get('code') or None
    if not label:
        return Response({'detail': 'الاسم مطلوب'}, status=400)
    return Response(preview_new_tier(kind, label, code))


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def alignment_tier_create(request):
    """Create a new classification tier in a SOFTECH lookup table (admin only)."""
    if not _is_admin(request.user):
        return Response({'detail': 'غير مصرح — للمدير فقط'}, status=403)
    usercode, _username = _get_approver_softech(request.user)
    if not usercode:
        return Response({'detail': 'لا يوجد كود SOFTECH مرتبط بحسابك'}, status=400)

    from .alignment import create_new_tier
    kind  = request.data.get('kind', 'store')
    label = request.data.get('label', '')
    code  = request.data.get('code') or None
    err, result = create_new_tier(kind, label, usercode, code)
    if err:
        return Response({'detail': err}, status=400)
    return Response(result)
