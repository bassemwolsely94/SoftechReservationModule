"""
apps/invoices/table_reconstruct.py

Pure table reconstruction from OCR word boxes — the core of the FREE structured
extractor (Phase 2b). Takes the boxes any engine produces (easyocr detail=1,
RapidOCR, PaddleOCR …) and rebuilds the invoice's row/column grid WITHOUT calling
any paid API.

Everything here is deterministic and unit-tested on synthetic boxes; it decides
layout only, never financial values. A box is a dict:
    {'cx','cy','w','h','text','conf'}   (cx/cy = centre, pixel or normalized)

Pipeline:
    group_rows(boxes)        → rows clustered by y-centre
    cluster_columns(boxes)   → column centres from an x-centre histogram
    assemble_grid(...)       → 2D grid of merged cell strings (rows × columns)
    reconstruct_table(boxes) → {'columns': [...], 'rows': [[cell,…], …]}

Column→field meaning is applied downstream from a per-distributor template, so
this module stays generic and safe (no guessing which column is a price).
"""
from __future__ import annotations

import statistics


def _span(boxes, key):
    vals = [b[key] for b in boxes]
    return (min(vals), max(vals)) if vals else (0.0, 0.0)


def group_rows(boxes: list[dict], y_tol: float | None = None) -> list[list[dict]]:
    """
    Cluster boxes into table rows by vertical centre. ``y_tol`` is the max gap (in
    the same units as cy) that still counts as the same row; when None it is
    derived from the median box height (half a line), which adapts to DPI.
    Returns rows top→bottom, each a list of boxes.
    """
    if not boxes:
        return []
    if y_tol is None:
        heights = [b.get('h', 0) for b in boxes if b.get('h')]
        med_h = statistics.median(heights) if heights else 0
        y_tol = (med_h * 0.6) if med_h else 0.01

    rows: list[list[dict]] = []
    for b in sorted(boxes, key=lambda x: x['cy']):
        if rows and abs(b['cy'] - _row_cy(rows[-1])) <= y_tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def _row_cy(row: list[dict]) -> float:
    return sum(b['cy'] for b in row) / len(row)


def cluster_columns(boxes: list[dict], min_count: int = 2,
                    merge_gap: float | None = None) -> list[float]:
    """
    Find column centres from the histogram of box centre-x. A column is a peak
    with at least ``min_count`` boxes; peaks closer than ``merge_gap`` are merged.
    ``merge_gap`` defaults to ~3% of the x-span. Returns centres left→right.
    """
    if not boxes:
        return []
    xs = sorted(b['cx'] for b in boxes)
    lo, hi = xs[0], xs[-1]
    width = (hi - lo) or 1.0
    if merge_gap is None:
        merge_gap = width * 0.03

    # agglomerate sorted x's into clusters separated by > merge_gap
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and (x - clusters[-1][-1]) <= merge_gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    centres = [sum(c) / len(c) for c in clusters if len(c) >= min_count]
    return centres


def assemble_grid(boxes: list[dict], col_centres: list[float],
                  rows: list[list[dict]] | None = None) -> list[list[str]]:
    """
    Build a rows×columns grid of cell strings. Each box is assigned to the nearest
    column centre; boxes landing in the same (row, column) are joined in reading
    order (left→right by cx). Empty cells are ''. Column order is left→right (the
    caller reverses for RTL when applying a template).
    """
    if rows is None:
        rows = group_rows(boxes)
    if not col_centres:
        # single-column fallback: one cell per row with all text joined
        return [[' '.join(b['text'] for b in sorted(r, key=lambda x: x['cx']))]
                for r in rows]

    grid: list[list[str]] = []
    for row in rows:
        cells: list[list[dict]] = [[] for _ in col_centres]
        for b in row:
            ci = min(range(len(col_centres)), key=lambda i: abs(b['cx'] - col_centres[i]))
            cells[ci].append(b)
        grid.append([
            ' '.join(bb['text'] for bb in sorted(cell, key=lambda x: x['cx'])).strip()
            for cell in cells
        ])
    return grid


def reconstruct_table(boxes: list[dict], y_tol: float | None = None,
                      min_col_count: int = 2) -> dict:
    """Full reconstruction: {'columns': [centres], 'rows': [[cell,…],…]}."""
    rows = group_rows(boxes, y_tol=y_tol)
    cols = cluster_columns(boxes, min_count=min_col_count)
    grid = assemble_grid(boxes, cols, rows)
    return {'columns': cols, 'rows': grid}
