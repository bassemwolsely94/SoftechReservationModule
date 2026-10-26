"""
Calibrate a per-vendor column template by SEEING the real column geometry.

For one rendered page (or, with --scan, the page that most looks like a product
grid) it prints every OCR box grouped into x-fraction bands, plus the template the
page auto-selects and its current bands. Use it to place/fix a vendor's column
bands — e.g. add the missing هامش ثابت للصيدلى / للموزع columns on the far left —
instead of guessing.

  python manage.py ocr_dump_columns --pdf "…/فارما اوفر.pdf" --page 4
  python manage.py ocr_dump_columns --pdf "…/فارما اوفر.pdf" --scan      # auto-find a grid page
"""
from __future__ import annotations

import re
import tempfile

from django.core.management.base import BaseCommand, CommandError

_PRICE = re.compile(r'\d{1,6}[.,]\d{2,3}')   # invoice money tokens (have decimals)


class Command(BaseCommand):
    help = "Dump a page's OCR boxes by x-position to calibrate a column template."

    def add_arguments(self, parser):
        parser.add_argument('--pdf', required=True)
        parser.add_argument('--page', type=int, default=1, help='1-based page number.')
        parser.add_argument('--scan', action='store_true',
                            help='Render all pages and dump the one that most looks like a '
                                 'product grid (most money-valued boxes).')
        parser.add_argument('--bins', type=int, default=20, help='x-fraction buckets.')

    def handle(self, *args, **o):
        import os
        if not os.path.exists(o['pdf']):
            raise CommandError(f"PDF not found: {o['pdf']}")
        from PIL import Image
        from apps.invoices import pdf as pdfmod, engines, preprocess

        def boxes_of(img):
            try:
                from django.conf import settings
                if getattr(settings, 'INVOICE_OCR_ENHANCE', True):
                    img = preprocess.enhance_for_ocr(img)
            except Exception:
                pass
            import pytesseract
            engines._tesseract_available()
            data = pytesseract.image_to_data(img, lang='ara+eng', config='--psm 6 --oem 1',
                                             output_type=pytesseract.Output.DICT)
            return engines._boxes_from_tesseract(data), float(getattr(img, 'width', 0) or 1)

        with tempfile.TemporaryDirectory() as tmp:
            if o['scan']:
                paths = pdfmod.render_pages(o['pdf'], tmp)
                if not paths:
                    raise CommandError('could not render pages.')
                best_i, best_n, best = 0, -1, None
                self.stdout.write(f"scanning {len(paths)} pages for the best product-grid page…")
                for i, p in enumerate(paths):
                    try:
                        bx, w = boxes_of(Image.open(p))
                    except Exception as e:
                        raise CommandError(f"tesseract read failed on page {i + 1}: {e}")
                    nmoney = sum(1 for b in bx if _PRICE.search(b['text']))
                    if nmoney > best_n:
                        best_i, best_n, best = i, nmoney, (bx, w)
                self.stdout.write(f"  → page {best_i + 1} has the most money-valued boxes ({best_n}); dumping it.\n")
                page_no = best_i + 1
                boxes, width = best
            else:
                idx = max(0, o['page'] - 1)
                paths = pdfmod.render_pages(o['pdf'], tmp, pages=[idx])
                if not paths:
                    raise CommandError('could not render that page.')
                try:
                    boxes, width = boxes_of(Image.open(paths[0]))
                except Exception as e:
                    raise CommandError(f"tesseract read failed: {e}")
                page_no = o['page']

        self._dump(page_no, boxes, width, o['bins'], engines)

    def _dump(self, page_no, boxes, width, bins, engines):
        self.stdout.write(f"page {page_no}: width={int(width)}px, {len(boxes)} boxes\n")
        alltext = engines._norm_ar(' '.join(b['text'] for b in boxes).lower())
        tpl = None
        for name, t in engines._BUILTIN_TEMPLATES.items():
            if any(engines._norm_ar(k) in alltext for k in t['keywords']):
                tpl = (name, t); break
        if tpl:
            self.stdout.write(self.style.MIGRATE_HEADING(f"auto-selected template: {tpl[0]}"))
            for b in tpl[1].get('bands', []):
                self.stdout.write(f"    {b['field']:<20} x {b['x0']:.3f}–{b['x1']:.3f}")
        else:
            self.stdout.write(self.style.WARNING("no built-in template matched this page's keywords"))

        # ── isolate the GRID BAND: the y-range where the money columns live, so the
        # page header (which spans every x) can't swamp the real table columns. ──
        price_ys = sorted(b['cy'] for b in boxes if _PRICE.search(b['text']))
        grid = boxes
        if len(price_ys) >= 5:
            lo_y, hi_y = price_ys[0], price_ys[-1]
            pad = 0.01 * max(1.0, max(b['cy'] for b in boxes))
            grid = [b for b in boxes if (lo_y - pad) <= b['cy'] <= (hi_y + pad)]
            h = max(b['cy'] for b in boxes) or 1
            self.stdout.write(f"\ngrid band: y {lo_y / h:.2f}–{hi_y / h:.2f} of page "
                              f"({len(grid)} of {len(boxes)} boxes; header excluded)")
        else:
            self.stdout.write(self.style.WARNING(
                "\n<5 price tokens on this page — showing all boxes (try --scan for a grid page)"))

        bins = max(4, bins)
        buckets: dict[int, list] = {}
        for b in grid:
            xf = b['cx'] / width
            buckets.setdefault(min(bins - 1, int(xf * bins)), []).append(b)
        self.stdout.write("\nx-fraction buckets within the grid band (RTL — item name is right/high-x):")
        self.stdout.write(f"  {'x0–x1':<12} {'n':>3} {'$':>3}  sample texts")
        for bi in range(bins - 1, -1, -1):
            items = buckets.get(bi, [])
            if not items:
                continue
            lo, hi = bi / bins, (bi + 1) / bins
            nmoney = sum(1 for b in items if _PRICE.search(b['text']))
            sample = ' | '.join(b['text'] for b in items[:8] if b['text'].strip())[:90]
            self.stdout.write(f"  {lo:.2f}–{hi:.2f}   {len(items):>3} {nmoney:>3}  {sample}")
        self.stdout.write("\nTip: the '$' column counts money tokens per band — the price/margin "
                          "columns are the ones with high $. Read off their x0–x1 and set the bands.")
