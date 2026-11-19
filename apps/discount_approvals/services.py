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
from config.writers import writer_allowed
from django.utils import timezone

from .models import ItemPriceChangeRequest, FIELD_LABELS, FIELD_TO_SOFTECH

logger = logging.getLogger('elrezeiky.discount_approvals')


def _round4(val: Decimal) -> Decimal:
    return val.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


# D-09 compare-and-set (owner approved 2026-11-19; audit S-11 / BE-14).
# Two values "match" when they agree to within half a unit of the mirror's 3rd decimal: the
# approved-against snapshot (old_values) comes from our mirror at 3 dp, SOFTECH keeps 4.
MATCH_TOL = Decimal('0.0005')
# The SQL guard on pack size / VAT re-checks the very values just read, so it can be tight.
_LIVE_TOL = Decimal('0.00005')


def _dec(v) -> Decimal:
    """SOFTECH NULL and our '0' placeholder both mean 0 (old_values stores None as '0')."""
    if v is None or v == '':
        return Decimal('0')
    return Decimal(str(v))


def _same(a, b, tol=MATCH_TOL) -> bool:
    return abs(_dec(a) - _dec(b)) <= tol


def _derive(requested: dict, pack_qty, tax_pct) -> dict:
    """
    The field set to write: the requested fields plus the auto-derived dependents whenever
    pack_price changes. The formula is unchanged (D-09 only changes WHERE pack/VAT come from):
        unit_price     = round(pack_price / packqty, 4)
        pack_price_tax = round(pack_price * (1 + sale_tax_pct/100), 4)
    """
    values = dict(requested)
    if 'pack_price' in values:
        new_pack = values['pack_price']
        pack_qty = _dec(pack_qty or 1)
        tax_pct  = _dec(tax_pct or 0)
        values['unit_price']     = _round4(new_pack / pack_qty) if pack_qty > 0 else new_pack
        values['pack_price_tax'] = _round4(new_pack * (1 + tax_pct / 100))
    return values


def _requested(request: ItemPriceChangeRequest) -> dict:
    return {k: Decimal(str(v)) for k, v in (request.new_values or {}).items() if k in FIELD_TO_SOFTECH}


def _build_values(request: ItemPriceChangeRequest) -> dict:
    """Mirror-based field set (preview only). The HQ write never uses this: it derives from the
    LIVE SOFTECH row inside its own transaction (_cas_write)."""
    item = request.item
    values = {k: Decimal(str(v)) for k, v in request.new_values.items()}
    return _derive(values, item.pack_qty, item.sale_tax_pct)


def _update_count(cur):
    """Rows the last UPDATE touched. config.sybase.CursorWrapper has no DB-API rowcount, so ask
    the JDBC statement; None when it cannot be told (treated as NOT written)."""
    rc = getattr(cur, 'rowcount', None)
    if isinstance(rc, int) and rc >= 0:
        return rc
    try:
        return int(cur._stmt.getUpdateCount())
    except Exception:
        return None


def _cas_write(cur, request: ItemPriceChangeRequest, erp_usercode: str, *, commit: bool,
               inspect=None) -> dict:
    """
    One HQ items UPDATE as a compare-and-set, all inside ONE explicit transaction on `cur`:

      BEGIN TRAN
        1. read the live row (HOLDLOCK): packqty, itemsalestaxp and every price column
        2. recompute the derived prices from the LIVE pack size / VAT (never from our mirror)
        3. already at the target -> nothing to write (a retry after a lost reply)    'already_applied'
           a requested field no longer equals what was approved (old_values)         'conflict'
        4. UPDATE ... WHERE itemcode = ? AND <each requested column> ~ <approved old>
                                    AND packqty ~ <live> AND itemsalestaxp ~ <live>
           the row count must be exactly 1, else                                     'rowcount'
        5. read back inside the transaction, else                                    'readback_mismatch'
      COMMIT TRAN only when `commit` and step 5 passed; every other path ROLLBACK TRAN.

    Explicit BEGIN/COMMIT in the connection's default autocommit (UNCHAINED) mode, as the native
    client does; jConnect chained mode trips SOFTECH triggers (see invoices/writer.py).
    commit=False is the rollback probe (manage.py price_change_probe): the same statements,
    always rolled back. `inspect(cur)` (probe only) runs after a verified write, still inside the
    transaction, to read the whole row. Returns a plain dict and never touches our database.
    """
    softech_id = request.item.softech_id
    requested  = _requested(request)
    old        = request.old_values or {}
    fields     = list(FIELD_TO_SOFTECH)                       # every priceable column, fixed order
    cols       = [FIELD_TO_SOFTECH[f] for f in fields]
    res = {'outcome': None, 'softech_id': softech_id, 'committed': False}

    cur.execute('BEGIN TRAN')
    try:
        cur.execute(
            f"SELECT packqty, itemsalestaxp, {', '.join(cols)} "
            "FROM SOFTECHDB9.dbo.items HOLDLOCK WHERE itemcode = ?", [softech_id])
        row = cur.fetchone()
        if not row:
            res['outcome'] = 'not_found'
            return res
        live = {'pack_qty': row[0], 'sale_tax_pct': row[1]}
        live.update({f: row[2 + i] for i, f in enumerate(fields)})
        res['live'] = {k: str(_dec(v)) for k, v in live.items()}

        values = _derive(requested, live['pack_qty'], live['sale_tax_pct'])
        res['values'] = {k: str(v) for k, v in values.items()}

        if all(_same(live[f], v) for f, v in values.items()):
            res['outcome'] = 'already_applied'
            return res

        conflicts = {f: {'approved': str(old.get(f, '0')), 'softech': str(_dec(live[f]))}
                     for f in requested if not _same(live[f], old.get(f, '0'))}
        if conflicts:
            res['outcome'], res['conflicts'] = 'conflict', conflicts
            return res

        set_parts, params = [], []
        for f, val in values.items():
            set_parts.append(f"{FIELD_TO_SOFTECH[f]} = ?")
            params.append(float(val))
        set_parts.append("usercode = ?")          # approver attribution (audit)
        # CRITICAL: stamp itemlastupdate exactly like the ERP "Items Master -> Save".
        # The SSB replication engine (ssbsb9_replicate.exe / sgnl4000.pbd) polls
        #   items WHERE itemlastupdate > <last_run>
        # and pushes the FULL row (incl. posdiscp) to every branch each ~30-min cycle.
        # The tr_items trigger does NOT stamp this on external JDBC writes, so we must
        # set it ourselves, otherwise the poller never sees our change and branches
        # never receive it. (Confirmed: branches mirror HQ rows keyed by this column.)
        set_parts.append("itemlastupdate = GETDATE()")   # literal SQL, no param
        params.append(erp_usercode)
        where, wparams = ["itemcode = ?"], [softech_id]
        for f in requested:                       # compare-and-set on what was approved
            where.append(f"ABS(ISNULL({FIELD_TO_SOFTECH[f]}, 0) - ?) <= {MATCH_TOL}")
            wparams.append(float(_dec(old.get(f, '0'))))
        if 'pack_price' in requested:             # derivation inputs unchanged since step 1
            where.append(f"ABS(ISNULL(packqty, 0) - ?) <= {_LIVE_TOL}")
            where.append(f"ABS(ISNULL(itemsalestaxp, 0) - ?) <= {_LIVE_TOL}")
            wparams += [float(_dec(live['pack_qty'])), float(_dec(live['sale_tax_pct']))]
        cur.execute(
            f"UPDATE SOFTECHDB9.dbo.items SET {', '.join(set_parts)} WHERE {' AND '.join(where)}",
            params + wparams)
        rc = _update_count(cur)
        res['rowcount'] = rc
        if rc != 1:
            res['outcome'] = 'rowcount'
            return res

        verify = list(values)
        cur.execute(
            f"SELECT {', '.join(FIELD_TO_SOFTECH[f] for f in verify)} "
            "FROM SOFTECHDB9.dbo.items WHERE itemcode = ?", [softech_id])
        back = cur.fetchone()
        res['readback'] = {f: str(_dec(back[i])) for i, f in enumerate(verify)} if back else {}
        if not back or not all(_same(back[i], values[f], Decimal('0.01')) for i, f in enumerate(verify)):
            res['outcome'] = 'readback_mismatch'
            return res
        if inspect is not None:              # before 'written', so a failing inspect never commits
            res['inspect'] = inspect(cur)
        res['outcome'] = 'written'
        return res
    finally:
        if commit and res['outcome'] == 'written':
            cur.execute('COMMIT TRAN')
            res['committed'] = True
        else:
            try:
                cur.execute('ROLLBACK TRAN')
            except Exception as exc:          # the open tran dies with the connection anyway
                logger.warning('[pricing_approvals] rollback failed: %s', exc)


_OUTCOME_ERRORS = {
    'not_found':         'الصنف غير موجود في SOFTECH الرئيسي',
    'rowcount':          'لم يُحدَّث أي صف في SOFTECH (تغيّر الصنف أثناء الكتابة) — لم يُكتب شيء',
    'readback_mismatch': 'القيم المقروءة بعد الكتابة لا تطابق المطلوب — تم التراجع ولم يُكتب شيء',
}


def execute_price_change(
    request: ItemPriceChangeRequest,
    erp_usercode: str,
    erp_username: str = '',
) -> bool:
    """
    Apply an approved pricing change exactly as the ERP does: one UPDATE to
    HQ SOFTECHDB9.dbo.items. SOFTECH's tr_items trigger + SSB9 service bus then
    replicate the full row (incl. posdiscp) to all branches within ~30 minutes.

    D-09: the UPDATE is a compare-and-set derived from the LIVE row (_cas_write). A request whose
    field changed in SOFTECH since it was filed is written nowhere and marked softech_changed;
    a retry of a change that already landed writes nothing and is marked executed.

    Returns True on success (HQ write committed + verified, or already in place).
    """
    from config.sybase import get_sybase_connection
    from core.softech_audit import audit_softech_write

    if not writer_allowed('PRICING_SOFTECH_WRITE_ENABLED'):
        _fail(request, erp_usercode, erp_username,
              'كتابة الأسعار إلى SOFTECH معطّلة (PRICING_SOFTECH_WRITE_ENABLED=False)')
        return False

    if not _requested(request):
        _fail(request, erp_usercode, erp_username, 'لا توجد حقول للتحديث')
        return False

    softech_id = request.item.softech_id
    logger.info(
        f"[pricing_approvals] request={request.id} item={softech_id} "
        f"fields={list(_requested(request))} erp_user={erp_usercode}({erp_username})"
    )

    conn = None
    try:
        conn = get_sybase_connection()
        res = _cas_write(conn.cursor(), request, erp_usercode, commit=True)
    except Exception as exc:
        logger.error(f"[pricing_approvals] HQ write failed: {exc}")
        # The outcome may be unknown (link dropped around COMMIT). Retrying is safe: the next
        # run reads SOFTECH first and finds the change either already in place or not.
        _fail(request, erp_usercode, erp_username,
              f'فشل الكتابة على HQ: {exc} — إعادة الاعتماد آمنة (تقرأ SOFTECH أولاً)')
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    outcome = res['outcome']
    if outcome == 'conflict':
        _softech_changed(request, erp_usercode, erp_username, res)
        audit_softech_write('softech_price_change_conflict', actor=request.reviewed_by, obj=request,
                            before=res['conflicts'], after=None, softech_id=softech_id,
                            live=res.get('live'), note='D-09: nothing written')
        return False
    if outcome not in ('written', 'already_applied'):
        _fail(request, erp_usercode, erp_username, _OUTCOME_ERRORS.get(outcome, str(outcome)))
        audit_softech_write('softech_price_change_refused', actor=request.reviewed_by, obj=request,
                            before=res.get('live'), after=res.get('values'), softech_id=softech_id,
                            outcome=outcome, rowcount=res.get('rowcount'), note='D-09: rolled back')
        return False

    values = {k: Decimal(v) for k, v in res['values'].items()}
    live = res['live']
    # Mirror to Django so the UI reflects it immediately (the live pack size / VAT too)
    _mirror_to_django(request, {**values, 'pack_qty': int(_dec(live['pack_qty'])),
                                'sale_tax_pct': _dec(live['sale_tax_pct'])})

    request.status          = ItemPriceChangeRequest.STATUS_EXECUTED
    request.erp_executed_at = timezone.now()
    request.erp_usercode    = erp_usercode
    request.erp_username    = erp_username
    request.erp_error       = ''
    request.executed_values = {
        **{k: str(v) for k, v in values.items()},
        '_hq':          'ok' if outcome == 'written' else 'already_applied',
        '_live_pack_qty':     live['pack_qty'],
        '_live_sale_tax_pct': live['sale_tax_pct'],
        '_itemlastupdate': 'stamped' if outcome == 'written' else 'unchanged',
        '_replication': 'SSB replicate polls itemlastupdate -> pushes full row (incl posdiscp) to all branches (~30 min)',
    }
    request.save(update_fields=[
        'status', 'erp_executed_at', 'erp_usercode', 'erp_username',
        'erp_error', 'executed_values',
    ])
    if outcome == 'written':
        audit_softech_write('softech_price_change_written', actor=request.reviewed_by, obj=request,
                            before={f: live[f] for f in values}, after=res['values'],
                            softech_id=softech_id, usercode=erp_usercode)
    logger.info(f"[pricing_approvals] request={request.id} HQ {outcome}; "
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


def _softech_changed(request, erp_usercode, erp_username, res):
    """D-09: SOFTECH no longer holds what the request was approved against; nothing written."""
    labels = '، '.join(
        f"{FIELD_LABELS.get(f, f)}: المعتمد {c['approved']} / SOFTECH الآن {c['softech']}"
        for f, c in res['conflicts'].items())
    now = timezone.now()
    request.status           = ItemPriceChangeRequest.STATUS_SOFTECH_CHANGED
    request.softech_conflict = {
        'fields': res['conflicts'],
        'live_pack_qty': res['live']['pack_qty'],
        'live_sale_tax_pct': res['live']['sale_tax_pct'],
        'detected_at': now.isoformat(),
    }
    request.erp_error       = f'تغيّر في SOFTECH بعد تقديم الطلب — لم يُكتب شيء. {labels}'
    request.erp_executed_at = now
    request.erp_usercode    = erp_usercode
    request.erp_username    = erp_username
    request.save(update_fields=[
        'status', 'softech_conflict', 'erp_error', 'erp_executed_at', 'erp_usercode', 'erp_username',
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
