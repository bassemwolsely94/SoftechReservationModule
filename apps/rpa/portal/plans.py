"""Server-built step plans for the portal robot. The robot does what the plan says, nothing else.

A plan holds only: ids, supplier SKUs, quantities, the account label, and the mode. Never a
password, cookie, a URL from the database, or an instruction to press Submit.
"""
from __future__ import annotations

import re

from apps.rpa.models import PortalLine

MAX_STEPDOWN_TRIES = 6

_PACK_WORDS = {'tab', 'tabs', 'tablet', 'tablets', 'cap', 'caps', 'capsule', 'capsules', 'strip',
               'strips', 'pack', 'packs', 'box', 'amp', 'amps', 'vial', 'vials', 'sachet',
               'sachets', 'supp', 'pcs', 'pc', 'x'}


class PlanError(ValueError):
    pass


def discovery_term(name: str) -> str:
    """The portal search term for an item: its English name with trailing pack words and bare
    counts dropped ('PANADOL EXTRA 24 TAB' -> 'PANADOL EXTRA'). Strengths such as '1GM' or
    '50 MG' stay. If trimming would leave nothing, the name is used as it is."""
    words = re.sub(r'\s+', ' ', str(name or '')).strip().split(' ')
    kept = list(words)
    while kept and (kept[-1].lower().strip('.') in _PACK_WORDS or kept[-1].isdigit()):
        kept.pop()
    return ' '.join(kept) if kept else ' '.join(words).strip()


def _account(job) -> dict:
    return {'identity_text': job.account.identity_text}


def discovery_plan(job) -> dict:
    """One search per keyless buy line still pending; not_found lines are never searched again."""
    lines = (PortalLine.objects.filter(basket__job=job, supplier_key='', status='pending')
             .select_related('item').order_by('basket__seq', 'id'))
    searches, seen = [], set()
    for ln in lines:
        if ln.buyline_id in seen:
            continue
        seen.add(ln.buyline_id)
        searches.append({'buyline_id': ln.buyline_id, 'term': discovery_term(ln.item.name)})
    return {'kind': 'discovery', 'portal': job.portal.key, 'account': _account(job),
            'searches': searches}


def fill_plan(basket) -> dict:
    if basket.status != 'ready':
        raise PlanError('السلة غير جاهزة')
    job = basket.job
    lines = [{'line_id': ln.pk, 'sku_padded': ln.supplier_key_padded, 'sku': ln.supplier_key,
              'qty': ln.wanted_qty}
             for ln in basket.lines.exclude(supplier_key='').order_by('id')]
    live = bool(job.portal.live and not job.dry_run)
    return {'kind': 'fill', 'basket_id': basket.pk, 'portal': job.portal.key,
            'mode': 'live' if live else 'dry_run', 'account': _account(job), 'lines': lines,
            'expect_lines': len(lines), 'max_stepdown_tries': MAX_STEPDOWN_TRIES}


def history_plan(basket) -> dict:
    return {'kind': 'history', 'basket_id': basket.pk,
            'since': basket.filled_at.isoformat() if basket.filled_at else None,
            'order_ref': basket.portal_ref or ''}
