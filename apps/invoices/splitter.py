"""
apps/invoices/splitter.py

Invoice-boundary detection for multi-invoice PDF bundles (Phase 1).

A distributor PDF is a stack of pages that must be grouped into the separate
invoices it actually contains. This module is the PURE, deterministic grouping
logic: given one lightweight "probe" per page (what ocr.probe_page_header reads
from the top/bottom bands of each page), it returns the page groups, each group
being one invoice.

Grounded in the two real specimens examined (2026-10-16):

  Ramco (رامكو فارم): 50-page PDF = ~50 separate ONE-page invoices. Page 1 is
    فاتورة 1826060925 / 13-10 / net 3,571.000 / "1 / 1"; page 2 is a DIFFERENT
    invoice فاتورة 1826060870 / 12-10 / net 2,387.840 / "1 / 1". The invoice
    number changes every page and each page carries its own "x / y" counter and
    صافي الفاتورة totals block.

  PharmaOverseas (اذن استلام مسعر): doc number = barcode / رقم أمر البيع, an
    English "Page 1 of 1" counter, and lines split INTO two tax sections
    (خاضعة / غير خاضعة للضريبة) WITHIN one page — that intra-page section split
    is a line-parsing concern, never a page boundary.

Reliable signals, in priority: (1) an explicit "x of y" page counter, (2) a
change in the printed document number, (3) a fresh full header following a page
that already showed a totals block. Everything degrades gracefully: a bundle of
pages with no readable signal at all falls back to one-invoice-per-page, which
is the correct answer for the Ramco stack and a safe, reviewable default
elsewhere (the operator confirms every split in the review workbench).

NOTHING here contacts SOFTECH or decides money; it only decides which pages
belong together.
"""
from __future__ import annotations

import re


def _norm_docnum(v) -> str:
    """Normalize a printed document number for comparison (digits/letters only)."""
    if not v:
        return ''
    return re.sub(r'[^0-9A-Za-z]', '', str(v)).upper()


def _as_int(v):
    try:
        if v is None or v == '':
            return None
        return int(v)
    except (ValueError, TypeError):
        return None


def group_pages(probes: list[dict]) -> list[list[int]]:
    """
    Group page probes into invoices. Returns a list of page-index lists
    (0-based, in order), one list per detected invoice.

    Each probe is a dict (missing keys treated as unknown):
      page         int   0-based page index (defaults to position in the list)
      doc_number   str   printed invoice / sales-order / barcode number
      page_index   int   the "x" in "x of y"
      page_count   int   the "y" in "x of y"
      has_header   bool  a full supplier/customer header block was detected
      has_totals   bool  a totals / net-of-invoice block was detected
    """
    if not probes:
        return []

    groups: list[list[int]] = []
    cur: list[int] = []
    cur_docnum = None          # normalized doc number of the open segment
    cur_expected = None        # page_count "y" of the open segment, if known
    prev = None                # previous page's probe

    def close():
        nonlocal cur, cur_docnum, cur_expected
        if cur:
            groups.append(cur)
        cur, cur_docnum, cur_expected = [], None, None

    for pos, pr in enumerate(probes):
        page = pr.get('page', pos)
        docnum = _norm_docnum(pr.get('doc_number'))
        pidx = _as_int(pr.get('page_index'))
        pcount = _as_int(pr.get('page_count'))
        has_header = bool(pr.get('has_header'))
        has_totals = bool(pr.get('has_totals'))

        if not cur:
            # first page of a (possibly new) segment
            cur.append(page)
            cur_docnum = docnum or None
            cur_expected = pcount
            prev = pr
            continue

        starts_new = _is_new_invoice(
            docnum, pidx, pcount, has_header, has_totals,
            cur_docnum, cur_expected, len(cur), prev,
        )

        if starts_new:
            close()
            cur.append(page)
            cur_docnum = docnum or None
            cur_expected = pcount
        else:
            cur.append(page)
            if cur_docnum is None and docnum:
                cur_docnum = docnum
            if cur_expected is None and pcount:
                cur_expected = pcount
        prev = pr

    close()
    return groups


def _is_new_invoice(docnum, pidx, pcount, has_header, has_totals,
                    cur_docnum, cur_expected, collected, prev) -> bool:
    """Decide whether this page starts a new invoice given the open segment."""
    prev_pidx = _as_int((prev or {}).get('page_index'))
    prev_totals = bool((prev or {}).get('has_totals'))

    # 1) Explicit page counter is the strongest signal.
    if pidx is not None:
        if pidx == 1:
            # a fresh "page 1 of y" always opens a new invoice
            return True
        if prev_pidx is not None and pidx == prev_pidx + 1:
            # a clean continuation (2 follows 1, 3 follows 2 …)
            # — but only if the doc number agrees (or is unknown on either side)
            if not docnum or not cur_docnum or docnum == cur_docnum:
                return False
        if prev_pidx is not None and pidx <= prev_pidx:
            # counter reset / went backwards → new invoice
            return True

    # 2) We have already collected the whole declared page_count → next page is new.
    if cur_expected is not None and collected >= cur_expected:
        return True

    # 3) Document number changed → new invoice (only when both sides are known).
    if docnum and cur_docnum and docnum != cur_docnum:
        return True
    if docnum and cur_docnum and docnum == cur_docnum:
        # same document continuing across pages
        return False

    # 4) No counter, no comparable doc number: a fresh header right after a page
    #    that ended with a totals block = the previous invoice closed, a new one
    #    opens. This is the one-invoice-per-page fallback for scans like Ramco.
    if has_header and prev_totals:
        return True

    # 5) Ambiguous → keep it with the current invoice (operator confirms splits).
    return False


def summarize(probes: list[dict], groups: list[list[int]]) -> list[dict]:
    """
    Build a human-reviewable summary per detected invoice: its page indices, the
    doc number / type / date taken from the group's first readable probe, and a
    confidence flag so the UI can highlight low-signal splits for verification.
    """
    by_page = {pr.get('page', i): pr for i, pr in enumerate(probes)}
    out = []
    for g in groups:
        first = next((by_page[p] for p in g if by_page.get(p)), {})
        # confidence: strong when a counter or a doc number anchored this group
        anchored = any(
            _as_int(by_page.get(p, {}).get('page_index')) is not None
            or _norm_docnum(by_page.get(p, {}).get('doc_number'))
            for p in g
        )
        out.append({
            'pages': g,
            'page_numbers': [p + 1 for p in g],
            'doc_number': (first.get('doc_number') or '').strip(),
            'doc_type': (first.get('doc_type') or '').strip(),
            'date': (first.get('date') or '').strip(),
            'supplier_name': (first.get('supplier_name') or '').strip(),
            'confidence': 'high' if anchored else 'low',
        })
    return out
