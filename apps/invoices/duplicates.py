"""
Same-file upload notice: has this exact file been uploaded before?

The invoices module is company-level (its viewsets do not branch-scope), so this lookup has no
branch filter either: a file uploaded for any branch counts. Matching is by SHA-256 of the bytes.
"""
from __future__ import annotations

from .models import InvoiceBatch, SupplierInvoice
from .serializers import SupplierInvoiceListSerializer


def _label(kind, obj) -> str:
    if kind == 'invoice':
        return f'فاتورة {obj.supplier_name or "؟"} — {obj.invoice_number or obj.id}'
    return f'حزمة #{obj.id}'


def find_duplicate(sha: str) -> dict | None:
    """Newest earlier upload with this hash: invoices first, then batches. None when new."""
    if not sha:
        return None
    inv = SupplierInvoice.objects.filter(source_sha256=sha).order_by('-created_at', '-id').first()
    if inv:
        return {'kind': 'invoice', 'id': inv.id, 'label': _label('invoice', inv),
                'status_label': SupplierInvoiceListSerializer.STATUS_LABELS.get(inv.status, inv.status),
                'created_at': inv.created_at.isoformat()}
    batch = InvoiceBatch.objects.filter(source_sha256=sha).order_by('-created_at', '-id').first()
    if batch:
        return {'kind': 'batch', 'id': batch.id, 'label': _label('batch', batch),
                'status_label': dict(InvoiceBatch.STATUS).get(batch.status, batch.status),
                'created_at': batch.created_at.isoformat()}
    return None
