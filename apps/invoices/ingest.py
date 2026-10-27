"""
apps/invoices/ingest.py

Multi-invoice bundle ingestion (Phase 1).

Fans a single uploaded PDF (an InvoiceBatch) out into the separate invoices it
contains, then runs each through the EXISTING per-invoice pipeline:

    render pages (pdf.render_pages, PyMuPDF)
      → probe each page's identity header (ocr.probe_page_header)
      → group pages into invoices (splitter.group_pages)        ← pure, tested
      → for each group: create a SupplierInvoice, OCR just those pages
        (ocr.extract_structured_images), parse, match (pipeline.build_lines)

Runs in a background thread (the module's established async pattern; a durable
task queue is a noted future hardening). It never contacts SOFTECH — only the
child invoices do, later, through the existing approval-gated writer.

A PDF that yields no renderable pages (no renderer installed) fails the batch
with a clear error rather than silently producing nothing.
"""
from __future__ import annotations

import logging
import os
import threading

from django.conf import settings

logger = logging.getLogger('elrezeiky.invoices')


def start_async(batch):
    """Kick bundle processing onto a daemon thread; returns immediately."""
    t = threading.Thread(target=process_bundle, args=(batch.pk,),
                         daemon=True, name=f'invoice-batch-{batch.pk}')
    t.start()


def _preprocess_pages(page_paths):
    """Skip blank/not-uploaded pages and auto-rotate crooked scans in place.
    Returns (blank_page_indices set, rotated_count)."""
    from PIL import Image
    from . import preprocess
    blank, rotated = set(), 0
    for i, p in enumerate(page_paths):
        try:
            with Image.open(p) as img:
                if preprocess.is_blank_page(img):
                    blank.add(i)
                    continue
                up, deg = preprocess.correct_orientation(img)
                if deg:
                    up.save(p)
                    rotated += 1
        except Exception as e:
            logger.warning('preprocess page %d failed: %s', i, e)
    return blank, rotated


def _probe_one(path, hints):
    from PIL import Image
    from . import ocr
    pr = None
    try:
        with Image.open(path) as im:
            pr = ocr.probe_page_header(im, hints)
    except Exception as e:
        logger.warning('probe failed for %s: %s', path, e)
    return pr or {'has_header': True, 'has_totals': True}


def _work_dir(batch) -> str:
    base = getattr(settings, 'MEDIA_ROOT', '.')
    d = os.path.join(base, 'invoice_bundles', 'pages', f'batch_{batch.pk}')
    os.makedirs(d, exist_ok=True)
    return d


def process_bundle(batch_pk: int):
    """Render → probe → split → fan out. Safe to call directly (also used by tests)."""
    from .models import InvoiceBatch, SupplierInvoice
    from . import pdf as pdfmod, splitter, ocr, pipeline

    try:
        batch = InvoiceBatch.objects.select_related('branch', 'vendor').get(pk=batch_pk)
    except InvoiceBatch.DoesNotExist:
        logger.warning('invoice batch %s vanished before processing', batch_pk)
        return

    batch.status = 'processing'
    batch.error = ''
    batch.save(update_fields=['status', 'error'])

    try:
        src = batch.source_file.path
        hints = ''
        if batch.vendor_id and batch.vendor and batch.vendor.ocr_profile:
            try:
                hints = ocr.vendor_prompt_hints(batch.vendor.ocr_profile)
            except Exception:
                hints = ''

        out_dir = _work_dir(batch)
        if pdfmod.is_pdf(src):
            page_paths = pdfmod.render_pages(src, out_dir)
        else:
            page_paths = [src]

        if not page_paths:
            batch.status = 'failed'
            batch.error = ('تعذّر تحويل ملف PDF إلى صور — تأكد من تثبيت محرك PyMuPDF '
                           '(PyMuPDF) على الخادم.')
            batch.save(update_fields=['status', 'error'])
            logger.warning('batch %s: no renderable pages (renderer missing?)', batch_pk)
            return

        # ── robustness pass: skip blank/not-uploaded pages, auto-rotate crooked
        #    scans, then probe only the real content pages for boundaries ──
        blank_pages, rotated_pages = _preprocess_pages(page_paths)
        probes = []
        for i, p in enumerate(page_paths):
            if i in blank_pages:
                continue
            pr = _probe_one(p, hints)
            pr['page'] = i
            probes.append(pr)

        groups = splitter.group_pages(probes) if probes else []
        summary = splitter.summarize(probes, groups)

        batch_flags = []
        if blank_pages:
            batch_flags.append('blank_pages')
        if rotated_pages:
            batch_flags.append('rotated_pages')

        batch.page_count = len(page_paths)
        batch.detected_count = len(groups)
        batch.split_summary = summary
        batch.flags = batch_flags
        batch.save(update_fields=['page_count', 'detected_count', 'split_summary', 'flags'])

        for seg_no, (group, seg) in enumerate(zip(groups, summary)):
            _build_segment_invoice(batch, seg_no, group, seg, page_paths, hints)
            # progress: lets the workbench show a live bar for big bundles
            batch.processed_count = seg_no + 1
            batch.save(update_fields=['processed_count'])

        batch.status = 'ready'
        batch.save(update_fields=['status'])
        logger.info('batch %s: %d page(s) → %d invoice(s)',
                    batch_pk, batch.page_count, batch.detected_count)

    except Exception as e:
        logger.exception('batch %s processing failed', batch_pk)
        try:
            batch.status = 'failed'
            batch.error = str(e)[:2000]
            batch.save(update_fields=['status', 'error'])
        except Exception:
            pass


def _build_segment_invoice(batch, seg_no, group, seg, page_paths, hints):
    """Create one SupplierInvoice from a detected page group and run matching."""
    import json
    from .models import SupplierInvoice
    from . import ocr, pipeline

    seg_paths = [page_paths[i] for i in group if 0 <= i < len(page_paths)]
    invoice = SupplierInvoice.objects.create(
        branch       = batch.branch,
        vendor       = batch.vendor,
        doc_kind     = batch.doc_kind,
        created_by   = batch.created_by,
        batch        = batch,
        source_pages = [i + 1 for i in group],
        status       = 'processing',
        supplier_name  = seg.get('supplier_name', '') or (batch.vendor.name if batch.vendor else ''),
        invoice_number = seg.get('doc_number', '') or '',
    )
    # Attach the segment's first rendered page as the invoice image so the review
    # workbench shows the scan beside the SofTech grid (reuses source_image_url).
    if seg_paths:
        try:
            from django.core.files import File
            with open(seg_paths[0], 'rb') as fh:
                invoice.source_image.save(
                    f'batch{batch.pk}_inv{invoice.pk}_p{group[0] + 1}.png',
                    File(fh), save=True)
        except Exception as e:
            logger.warning('batch %s: could not attach page image to invoice %s: %s',
                           batch.pk, invoice.pk, e)

    try:
        structured = ocr.extract_structured_images(
            seg_paths, hints, engine=(batch.ocr_engine or None), vendor=batch.vendor)
        if structured and structured.get('lines'):
            header, candidates = ocr.parse_structured(structured)
            invoice.raw_ocr_text = json.dumps(structured, ensure_ascii=False)[:20000]
            pipeline.apply_ocr_header(invoice, header)
        else:
            # text fallback on the first page of the segment
            raw = ocr.extract_text(seg_paths[0]) if seg_paths else ''
            invoice.raw_ocr_text = raw
            candidates = ocr.parse_lines(raw)

        # review flags: incomplete / low-recall / paper-cut / low-confidence
        try:
            from . import preprocess
            flags = preprocess.page_quality(structured).get('flags', [])
            if not seg.get('has_totals', True):
                flags.append('no_totals')
            invoice.ocr_flags = flags
        except Exception:
            invoice.ocr_flags = []

        invoice.status = 'review'
        invoice.save()
        pipeline.build_lines(invoice, candidates)
        # cache a thorough duplicate scan so the list flags re-entries (best-effort)
        try:
            from . import writer
            writer.scan_invoice_duplicates(invoice)
        except Exception as e:
            logger.warning('dup scan failed for invoice %s: %s', invoice.pk, e)
    except Exception as e:
        invoice.status = 'review'
        invoice.notes = (invoice.notes + f'\n[OCR error: {e}]')[:2000]
        invoice.save(update_fields=['status', 'notes'])
        logger.warning('batch %s segment %s OCR failed: %s', batch.pk, seg_no, e)

    return invoice
