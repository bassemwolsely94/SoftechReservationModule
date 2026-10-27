"""
apps/batches/service.py

BatchService — the only place that writes to StockBatch.current_qty.

All other modules call these methods; they never touch qty directly.
"""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import StockBatch, BatchMovement, NearExpiryAlert

logger = logging.getLogger('elrezeiky.batches')


class BatchService:

    # ── FEFO query ────────────────────────────────────────────────────────────

    @classmethod
    def fefo_batches(cls, item_id: int, branch_id: int, include_quarantined=False):
        """
        Return active StockBatch queryset for (item, branch) ordered FEFO
        (oldest expiry first, then by id for determinism).

        This is the single authoritative FEFO sort used by all dispatch flows:
          transfers, delivery, manual issue, returns.
        """
        qs = StockBatch.objects.filter(
            item_id=item_id,
            branch_id=branch_id,
            current_qty__gt=0,
            is_expired=False,
        )
        if not include_quarantined:
            qs = qs.filter(is_quarantined=False)
        return qs.order_by('expiry_date', 'id')

    # ── Create from invoice ───────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def receive_from_invoice(cls, *, invoice_line, branch, received_by) -> StockBatch:
        """
        Called when a SupplierInvoice line is confirmed.
        Creates or updates StockBatch and records a RECEIVE movement.

        invoice_line: apps.invoices.models.InvoiceLine (must have item set)
        """
        if not invoice_line.item_id:
            raise ValueError('InvoiceLine must have a matched item before receiving into batch.')

        expiry = cls._parse_expiry(invoice_line.expiry_date)
        if expiry is None:
            raise ValueError(f'Cannot parse expiry date: {invoice_line.expiry_date!r}')

        qty = Decimal(str(invoice_line.quantity or 0))
        if qty <= 0:
            raise ValueError('Received quantity must be positive.')

        batch, created = StockBatch.objects.get_or_create(
            item_id=invoice_line.item_id,
            branch=branch,
            batch_number=invoice_line.batch_number or f'AUTO-{invoice_line.id}',
            defaults={
                'expiry_date':    expiry,
                'vendor':         invoice_line.invoice.vendor if invoice_line.invoice else None,
                'invoice':        invoice_line.invoice,
                'invoice_number': invoice_line.invoice.invoice_number if invoice_line.invoice else '',
                'manufacturer':   invoice_line.manufacturer,
                'purchase_price': invoice_line.unit_price or 0,
                'original_qty':   qty,
                'current_qty':    qty,
                'received_by':    received_by,
                'received_at':    timezone.now(),
            },
        )
        if not created:
            # Batch already exists (duplicate invoice confirmation guard)
            batch.current_qty  += qty
            batch.original_qty += qty
            batch.save(update_fields=['current_qty', 'original_qty', 'updated_at'])

        cls._record_movement(
            batch=batch,
            movement_type=BatchMovement.TYPE_RECEIVE,
            qty_change=qty,
            branch=branch,
            performed_by=received_by,
            reference_type='InvoiceLine',
            reference_id=invoice_line.pk,
        )
        logger.info('Batch %s received: %s units of %s at %s', batch.batch_number, qty, batch.item, branch)
        return batch

    # ── Record any movement ───────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def record_movement(
        cls,
        *,
        batch: StockBatch,
        movement_type: str,
        qty: Decimal,
        branch,
        performed_by=None,
        reference_type: str = '',
        reference_id: int = None,
        notes: str = '',
    ) -> BatchMovement:
        """
        Public API for recording any batch quantity change.
        qty must be POSITIVE for both additions and subtractions;
        the movement_type determines the sign:
          - RECEIVE, TRANSFER_IN, RETURN_IN, ADJUSTMENT(+) → adds to stock
          - TRANSFER_OUT, SALE, RETURN_OUT, QUARANTINE, DESTROY → subtracts
        """
        deduction_types = {
            BatchMovement.TYPE_TRANSFER_OUT,
            BatchMovement.TYPE_SALE,
            BatchMovement.TYPE_RETURN_OUT,
            BatchMovement.TYPE_QUARANTINE,
            BatchMovement.TYPE_DESTROY,
        }
        qty_change = -abs(qty) if movement_type in deduction_types else abs(qty)
        return cls._record_movement(
            batch=batch,
            movement_type=movement_type,
            qty_change=qty_change,
            branch=branch,
            performed_by=performed_by,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
        )

    # ── Quarantine ────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def quarantine(cls, *, batch: StockBatch, reason: str, performed_by) -> StockBatch:
        """
        Quarantine a batch.

        Role-gated:
          • admin / quality_manager → immediate effect via _apply_quarantine().
          • all other roles          → submits a batch_quarantine ApprovalRequest.
                                       Returns the batch unchanged; the ApprovalRequest
                                       outcome handler calls _apply_quarantine() on approval.
        """
        IMMEDIATE_ROLES = {'admin', 'quality_manager'}
        role = getattr(performed_by, 'role', None)

        if role in IMMEDIATE_ROLES:
            return cls._apply_quarantine(batch, reason, performed_by=performed_by)

        # Non-privileged: route through approval workflow
        from apps.approvals.service import ApprovalService
        ApprovalService.submit(
            workflow_code='batch_quarantine',
            subject_object=batch,
            title=f'طلب عزل دفعة — {batch.item.name} / {batch.batch_number}',
            requested_by=performed_by,
            body=reason,
            context_data={
                'batch_id':     batch.pk,
                'batch_number': batch.batch_number,
                'reason':       reason,
                'item_id':      batch.item_id,
                'branch_id':    batch.branch_id,
            },
        )
        logger.info(
            'Batch quarantine routed to approval for batch #%s by %s (role=%s)',
            batch.pk, performed_by.pk, role,
        )
        return batch   # unchanged until approved

    @classmethod
    @transaction.atomic
    def _apply_quarantine(cls, batch: StockBatch, reason: str, performed_by=None) -> StockBatch:
        """
        Internal: immediately quarantine a batch.
        Called directly for admin/quality_manager, or by the approval outcome handler.
        """
        if batch.is_quarantined:
            return batch   # idempotent

        batch.is_quarantined    = True
        batch.quarantine_reason = reason
        batch.save(update_fields=['is_quarantined', 'quarantine_reason', 'updated_at'])
        cls._record_movement(
            batch=batch,
            movement_type=BatchMovement.TYPE_QUARANTINE,
            qty_change=Decimal('0'),   # qty unchanged; status changes
            branch=batch.branch,
            performed_by=performed_by,
            notes=reason,
        )
        cls._notify_quarantine(batch, reason, performed_by)
        return batch

    # ── Near-expiry scan (called by management command) ───────────────────────

    @classmethod
    def scan_near_expiry(cls) -> dict:
        """
        Flag expired batches and create NearExpiryAlert rows for approaching
        thresholds.  Returns summary dict for management command output.
        """
        today      = timezone.now().date()
        thresholds = [30, 60, 90, 180]
        summary    = {'expired': 0, 'alerts_created': 0}

        # 1. Flag newly expired batches
        newly_expired = StockBatch.objects.filter(
            is_expired=False,
            expiry_date__lt=today,
            current_qty__gt=0,
        )
        for batch in newly_expired:
            batch.is_expired = True
            batch.save(update_fields=['is_expired', 'updated_at'])
            summary['expired'] += 1

        # 2. Create threshold alerts
        for days in thresholds:
            threshold_date = today + timedelta(days=days)
            candidates = StockBatch.objects.filter(
                is_expired=False,
                is_quarantined=False,
                current_qty__gt=0,
                expiry_date__lte=threshold_date,
            ).exclude(
                expiry_alerts__threshold_days=days
            ).select_related('item', 'branch', 'vendor')

            for batch in candidates:
                NearExpiryAlert.objects.get_or_create(
                    batch=batch, threshold_days=days,
                )
                cls._notify_near_expiry(batch, days)
                summary['alerts_created'] += 1

        logger.info('Near-expiry scan: %s expired, %s new alerts', summary['expired'], summary['alerts_created'])
        return summary

    # ── Near-expiry dashboard data ────────────────────────────────────────────

    @classmethod
    def near_expiry_summary(cls, branch_id=None, days=180):
        """
        Return aggregated near-expiry data for dashboard KPI widgets.
        Used by apps/batches/views.py NearExpiryView.
        """
        from django.db.models import Sum, Count, F
        today      = timezone.now().date()
        cutoff     = today + timedelta(days=days)

        qs = StockBatch.objects.filter(
            is_expired=False,
            is_quarantined=False,
            current_qty__gt=0,
            expiry_date__lte=cutoff,
        )
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        def band(d_from, d_to):
            band_qs = qs.filter(
                expiry_date__gte=today + timedelta(days=d_from),
                expiry_date__lt=today  + timedelta(days=d_to),
            )
            agg = band_qs.aggregate(
                total_qty=Sum('current_qty'),
                total_value=Sum(F('current_qty') * F('purchase_price')),
                batch_count=Count('id'),
            )
            return {
                'qty':    float(agg['total_qty'] or 0),
                'value':  float(agg['total_value'] or 0),
                'batches': agg['batch_count'],
            }

        return {
            'lt_30':   band(0,  30),
            'lt_60':   band(30, 60),
            'lt_90':   band(60, 90),
            'lt_180':  band(90, 180),
            'total_at_risk_value': float(
                qs.aggregate(v=Sum(F('current_qty') * F('purchase_price')))['v'] or 0
            ),
        }

    # ── Supplier claim data ───────────────────────────────────────────────────

    @classmethod
    def supplier_claim_lines(cls, vendor_id, branch_id=None):
        """
        Return batches eligible for supplier claim (near-expiry or expired,
        belonging to a specific vendor).  Used by claim PDF generator.
        """
        today  = timezone.now().date()
        cutoff = today + timedelta(days=90)
        qs = StockBatch.objects.filter(
            vendor_id=vendor_id,
            current_qty__gt=0,
            expiry_date__lte=cutoff,
        ).select_related('item', 'branch')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs.order_by('expiry_date')

    # ── Internal helpers ──────────────────────────────────────────────────────

    @classmethod
    def _record_movement(cls, *, batch, movement_type, qty_change, branch, performed_by=None,
                          reference_type='', reference_id=None, notes='') -> BatchMovement:
        new_qty = batch.current_qty + qty_change
        if new_qty < 0:
            raise ValueError(
                f'Movement would make batch {batch.batch_number} qty negative '
                f'({batch.current_qty} + {qty_change} = {new_qty}).'
            )
        batch.current_qty = new_qty
        batch.save(update_fields=['current_qty', 'updated_at'])

        return BatchMovement.objects.create(
            batch=batch,
            movement_type=movement_type,
            qty_change=qty_change,
            qty_after=new_qty,
            branch=branch,
            performed_by=performed_by,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
        )

    @staticmethod
    def _parse_expiry(raw: str):
        """
        Parse expiry date from raw OCR text.
        Handles: MM/YY, MM-YY, MM/YYYY, MM-YYYY, YYYY-MM-DD, DD/MM/YYYY.
        Returns date(year, month, last_day_of_month) or None.
        """
        if not raw:
            return None
        raw = raw.strip().replace(' ', '')

        formats = ['%m/%Y', '%m-%Y', '%m/%y', '%m-%y', '%Y-%m-%d', '%d/%m/%Y']
        for fmt in formats:
            try:
                parsed = datetime.strptime(raw, fmt)
                # Snap to end-of-month for MM/YY formats
                if fmt in ('%m/%Y', '%m-%Y', '%m/%y', '%m-%y'):
                    import calendar
                    last = calendar.monthrange(parsed.year, parsed.month)[1]
                    return date(parsed.year, parsed.month, last)
                return parsed.date()
            except ValueError:
                continue
        return None

    @classmethod
    def _notify_near_expiry(cls, batch: StockBatch, days: int) -> None:
        urgency = {30: '🔴', 60: '🟠', 90: '🟡', 180: '🟢'}.get(days, '⚠️')
        try:
            from apps.notifications.models import Notification
            from apps.users.models import StaffProfile
            recipients = StaffProfile.objects.filter(
                role__in=['pharmacist', 'purchasing', 'admin'],
                is_active=True,
                branch=batch.branch,
            )
            for r in recipients:
                Notification.objects.create(
                    recipient=r,
                    notification_type='system',
                    title=f'{urgency} صلاحية تنتهي خلال {days} يوم: {batch.item.name}',
                    body=(
                        f'الدفعة: {batch.batch_number}\n'
                        f'الكمية: {batch.current_qty}\n'
                        f'تاريخ الصلاحية: {batch.expiry_date}\n'
                        f'القيمة المعرضة للخطر: {batch.expiry_value:,.2f} ج.م'
                    ),
                    dedup_key=f'near_expiry_{batch.pk}_{days}',
                )
        except Exception:
            logger.exception('Failed to send near-expiry notification for batch %s', batch.pk)

    @classmethod
    def _notify_quarantine(cls, batch: StockBatch, reason: str, performed_by) -> None:
        try:
            from apps.notifications.models import Notification
            from apps.users.models import StaffProfile
            recipients = StaffProfile.objects.filter(
                role__in=['purchasing', 'admin', 'quality_manager'],
                is_active=True,
            )
            for r in recipients:
                Notification.objects.create(
                    recipient=r,
                    notification_type='system',
                    title=f'🚫 عزل دفعة: {batch.item.name} — {batch.batch_number}',
                    body=f'الفرع: {batch.branch}\nالسبب: {reason}\nبواسطة: {performed_by.full_name}',
                    dedup_key=f'quarantine_{batch.pk}',
                )
        except Exception:
            logger.exception('Failed to send quarantine notification for batch %s', batch.pk)
