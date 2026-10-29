"""
apps/invoices/pdf.py

PDF page rendering for the multi-invoice ingestion pipeline (Phase 1).

A single uploaded PDF from a main distributor is frequently a STACK of many
separate invoices (a 50-page Ramco PDF observed in prod = ~50 one-page invoices,
each with its own فاتورة number and "1 / 1" page counter). The old
ocr.extract_structured merged every page into ONE invoice — wrong. This module
renders each page to its own image so the splitter can detect invoice
boundaries and fan the bundle out into separate SupplierInvoice rows.

Renderer:  PyMuPDF (pymupdf / fitz) — pip-only, no system poppler needed.
Fallback:  pdf2image (poppler) if PyMuPDF is unavailable but poppler is present.
Both degrade to an empty list when no renderer is installed (callers treat an
empty render as "cannot process" and surface an error, never a silent success).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger('elrezeiky.invoices')

def _default_dpi() -> int:
    """Render resolution: settings.INVOICE_PDF_DPI (default 300 — Tesseract's sweet
    spot for printed Arabic), falling back to 200 if settings are unavailable."""
    try:
        from django.conf import settings
        return int(getattr(settings, 'INVOICE_PDF_DPI', 300) or 300)
    except Exception:
        return 200


DEFAULT_DPI = 200   # legacy module constant; render_pages() prefers _default_dpi()


def is_pdf(path: str) -> bool:
    return bool(path) and path.lower().endswith('.pdf')


def page_count(pdf_path: str) -> int:
    """Number of pages, or 0 if the PDF cannot be opened."""
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except ImportError:
        pass
    except Exception as e:
        logger.warning('page_count (pymupdf) failed for %s: %s', pdf_path, e)
        return 0
    # pdf2image fallback
    try:
        from pdf2image import pdfinfo_from_path
        poppler = os.environ.get('POPPLER_PATH')
        return int(pdfinfo_from_path(pdf_path, poppler_path=poppler).get('Pages', 0))
    except Exception as e:
        logger.warning('page_count (pdf2image) failed for %s: %s', pdf_path, e)
        return 0


def render_pages(pdf_path: str, out_dir: str, dpi: int | None = None,
                 pages: list[int] | None = None, prefix: str = 'page') -> list[str]:
    """
    Render PDF pages to PNG files under ``out_dir`` and return the file paths in
    page order. ``pages`` (0-based indices) renders only those pages; None = all.
    ``dpi`` None = settings.INVOICE_PDF_DPI (default 300). Returns [] when no
    renderer is available (never raises for a missing lib).
    """
    if dpi is None:
        dpi = _default_dpi()
    os.makedirs(out_dir, exist_ok=True)
    paths = _render_pymupdf(pdf_path, out_dir, dpi, pages, prefix)
    if paths is not None:
        return paths
    paths = _render_pdf2image(pdf_path, out_dir, dpi, pages, prefix)
    if paths is not None:
        return paths
    logger.warning('No PDF renderer available (install PyMuPDF) — cannot render %s', pdf_path)
    return []


def _render_pymupdf(pdf_path, out_dir, dpi, pages, prefix):
    """Returns list of paths, or None if PyMuPDF is not importable."""
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        out: list[str] = []
        with pymupdf.open(pdf_path) as doc:
            idxs = range(doc.page_count) if pages is None else pages
            for i in idxs:
                if i < 0 or i >= doc.page_count:
                    continue
                pix = doc[i].get_pixmap(dpi=dpi)
                fn = os.path.join(out_dir, f'{prefix}_{i + 1:04d}.png')
                pix.save(fn)
                out.append(fn)
        logger.info('PyMuPDF rendered %d page(s) of %s', len(out), os.path.basename(pdf_path))
        return out
    except Exception as e:
        logger.warning('PyMuPDF render failed for %s: %s', pdf_path, e)
        return None


def _render_pdf2image(pdf_path, out_dir, dpi, pages, prefix):
    """Returns list of paths, or None if pdf2image/poppler is unavailable."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        return None
    try:
        poppler = os.environ.get('POPPLER_PATH')
        # pdf2image is 1-based and inclusive; render all then keep requested pages.
        images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler)
        out: list[str] = []
        for i, img in enumerate(images):
            if pages is not None and i not in pages:
                continue
            fn = os.path.join(out_dir, f'{prefix}_{i + 1:04d}.png')
            img.save(fn, 'PNG')
            out.append(fn)
        logger.info('pdf2image rendered %d page(s) of %s', len(out), os.path.basename(pdf_path))
        return out
    except Exception as e:
        logger.warning('pdf2image render failed for %s: %s', pdf_path, e)
        return None


def renderer_available() -> bool:
    """True when at least one PDF renderer can be imported (for health checks / UI)."""
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import pdf2image  # noqa: F401
        return True
    except ImportError:
        return False
