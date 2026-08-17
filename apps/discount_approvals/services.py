r"""
Softech write service for approved discount/price changes.

════════════════════════════════════════════════════════════════
REPLICATION — how a price/discount change reaches all branches
════════════════════════════════════════════════════════════════

Confirmed by full investigation of the live system:

  • The ERP "Items Master -> Save" performs a single  UPDATE SOFTECHDB9.dbo.items.
  • Trigger  tr_items  (readable) fires on every HQ items update and stamps
        items.itemlastupdate = GETDATE()
  • The SOFTECH Smart Business 9 service bus  (D:\SSB9\ssb9_service_bus.exe,
    launched at boot by the "SofTech Start" scheduled task) polls items changed
    since its last run (via the itemlastupdate column) and pushes the FULL item
    row — every column, INCLUDING posdiscp — to each branch's items table.
  • Cycle interval: ~30 minutes.

Why this is the right design:
  • posdiscp exists ONLY in items (no britems/queue column carries it), yet it
    replicates in daily ERP use — proving the service bus reads items directly.
  • Doing exactly the ERP's single UPDATE makes our change indistinguishable
    from a manual admin edit: same trigger chain, same service-bus replication,
    same audit (usercode), same ~30-min propagation to all branches.
  • No britems writes and no direct per-branch writes — those bypass the native
    flow and proved fragile against the intermittent HQ link.

So: write HQ items (all changed fields + derived dependents + approver usercode).
SOFTECH's own trigger + service bus carry it to every branch.
════════════════════════════════════════════════════════════════
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.utils import timezone

from .models import ItemPriceChangeRequest, FIELD_TO_SOFTECH

logger = logging.getLogger('elrezeiky.discount_approvals')


def _round4(val: Decimal) -> Decimal:
    return val.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def _build_values(request: ItemPriceChangeRequest) -> dict:
    """
    Build the field set to write to HQ items.

    Includes the requested fields plus auto-derived dependents whenever
    pack_price changes:
        unit_price     = round(pack_price / packqty, 4)
        pack_price_tax = round(pack_price * (1 + sale_tax_pct/100), 4)
    """
    item   = request.item
    values = {k: Decimal(str(v)) for k, v in request.new_values.items()}

    if 'pack_price' in values:
        new_pack = values['pack_price']
        pack_qty = Decimal(str(item.pack_qty or 1))
        tax_pct  = Decimal(str(item.sale_tax_pct or 0))
        values['unit_price']     = _round4(new_pack / pack_qty) if pack_qty > 0 else new_pack
        values['pack_price_tax'] = _round4(new_pack * (1 + tax_pct / 100))

    return values


def execute_price_change(
    request: ItemPriceChangeRequest,
    erp_usercode: str,
    erp_username: str = '',
) -> bool:
    """
    Apply an approved pricing change exactly as the ERP does: one UPDATE to
    HQ SOFTECHDB9.dbo.items. SOFTECH's tr_items trigger + SSB9 service bus then
    replicate the full row (incl. posdiscp) to all branches within ~30 minutes.

    Returns True on success (HQ write committed + verified).
    """
    from config.sybase import get_sybase_connection

    softech_id = request.item.softech_id
    values     = _build_values(request)

    if not values:
        _fail(request, erp_usercode, erp_username, 'لا توجد حقول للتحديث')
        return False

    # Build the single items UPDATE (mirrors the ERP Save)
    set_parts, params = [], []
    for django_field, val in values.items():
        col = FIELD_TO_SOFTECH.get(django_field)
        if col:
            set_parts.append(f"{col} = ?")
            params.append(float(val))
    set_parts.append("usercode = ?")          # approver attribution (audit)
    # CRITICAL — stamp itemlastupdate exactly like the ERP "Items Master -> Save".
    # The SSB replication engine (ssbsb9_replicate.exe / sgnl4000.pbd) polls
    #   items WHERE itemlastupdate > <last_run>
    # and pushes the FULL row (incl. posdiscp) to every branch each ~30-min cycle.
    # The tr_items trigger does NOT stamp this on external JDBC writes, so we must
    # set it ourselves — otherwise the poller never sees our change and branches
    # never receive it. (Confirmed: branches mirror HQ rows keyed by this column.)
    set_parts.append("itemlastupdate = GETDATE()")   # literal SQL, no param
    params.extend([erp_usercode, softech_id])
    sql = f"UPDATE SOFTECHDB9.dbo.items SET {', '.join(set_parts)} WHERE itemcode = ?"

    logger.info(
        f"[pricing_approvals] request={request.id} item={softech_id} "
        f"fields={list(values.keys())} erp_user={erp_usercode}({erp_username})"
    )

    try:
        conn = get_sybase_connection()
        cur  = conn.cursor()
        cur.execute(sql, params)

        # Readback verify the HQ write committed
        verify_cols = [FIELD_TO_SOFTECH[f] for f in values if f in FIELD_TO_SOFTECH]
        if verify_cols:
            cur.execute(
                f"SELECT {', '.join(verify_cols)} FROM SOFTECHDB9.dbo.items WHERE itemcode = ?",
                [softech_id]
            )
            row = cur.fetchone()
            expected = [float(values[f]) for f in values if f in FIELD_TO_SOFTECH]
            actual   = [float(x or 0) for x in row] if row else []
            mismatch = [
                (verify_cols[i], expected[i], actual[i])
                for i in range(min(len(expected), len(actual)))
                if abs(expected[i] - actual[i]) > 0.01
            ]
            if mismatch:
                conn.close()
                raise RuntimeError(f'HQ readback mismatch: {mismatch}')
        conn.close()
    except Exception as exc:
        logger.error(f"[pricing_approvals] HQ write failed: {exc}")
        _fail(request, erp_usercode, erp_username, f'فشل الكتابة على HQ: {exc}')
        return False

    # Mirror to Django so the UI reflects it immediately
    _mirror_to_django(request, values)

    request.status          = ItemPriceChangeRequest.STATUS_EXECUTED
    request.erp_executed_at = timezone.now()
    request.erp_usercode    = erp_usercode
    request.erp_username    = erp_username
    request.erp_error       = ''
    request.executed_values = {
        **{k: str(v) for k, v in values.items()},
        '_hq':          'ok',
        '_itemlastupdate': 'stamped',
        '_replication': 'SSB replicate polls itemlastupdate -> pushes full row (incl posdiscp) to all branches (~30 min)',
    }
    request.save(update_fields=[
        'status', 'erp_executed_at', 'erp_usercode', 'erp_username',
        'erp_error', 'executed_values',
    ])
    logger.info(f"[pricing_approvals] request={request.id} HQ committed; "
                f"branches replicate via SSB9 service bus (~30 min)")
    return True


def _fail(request, erp_usercode, erp_username, error_msg):
    request.status          = ItemPriceChangeRequest.STATUS_FAILED
    request.erp_error       = error_msg
    request.erp_executed_at = timezone.now()
    request.erp_usercode    = erp_usercode
    request.erp_username    = erp_username
    request.save(update_fields=[
        'status', 'erp_error', 'erp_executed_at', 'erp_usercode', 'erp_username',
    ])


def _mirror_to_django(request: ItemPriceChangeRequest, values: dict):
    """Immediately update the Django Item row (don't wait for the next sync)."""
    item, fields = request.item, []
    for f, v in values.items():
        if hasattr(item, f):
            setattr(item, f, v)
            fields.append(f)
    if fields:
        item.save(update_fields=fields)


def compute_derived_preview(pack_price_str: str, pack_qty: int, sale_tax_pct_str: str) -> dict:
    """unit_price + pack_price_tax preview for the create form."""
    try:
        pp = Decimal(str(pack_price_str))
        pq = Decimal(str(max(pack_qty, 1)))
        tx = Decimal(str(sale_tax_pct_str or 0))
        return {
            'unit_price':     str(_round4(pp / pq)),
            'pack_price_tax': str(_round4(pp * (1 + tx / 100))),
        }
    except Exception:
        return {}
