"""
python manage.py price_change_probe --request <pk>                       (plan only, no connection)
python manage.py price_change_probe --request <pk> --run                 (ROLLBACK probe on HQ)
python manage.py price_change_probe --item <softech_id> --set pack_price=100 [--set pos_discp=7] --run

ROLLBACK PROBE for the D-09 compare-and-set price writer (apps/discount_approvals/services.py
_cas_write), following the POS writer "golden template" loop: run the REAL statements against HQ
inside BEGIN TRAN ... ROLLBACK TRAN, read the whole items row back inside the transaction, diff
every column against the row before, then confirm after the rollback that the row is exactly as it
was (itemlastupdate included). Nothing of ours persists.

What it answers before the writer is switched on for real:
  * does jConnect report the UPDATE's row count as 1 (tr_items fires on items; the trigger's own
    count must not be what getUpdateCount() returns)?
  * does the WHERE compare-and-set (ABS(ISNULL(col,0) - ?) <= tol) match the live row?
  * which columns the UPDATE + tr_items change (expected: the price columns, usercode,
    itemlastupdate, plus whatever the trigger stamps).

SAFETY
  * Without --run nothing connects: it prints the request and the plan.
  * --run never commits: _cas_write(commit=False) always ends in ROLLBACK TRAN, and the request
    row in our database is never modified (an --item probe is an unsaved in-memory request).
  * It holds an exclusive lock on ONE items row for the length of the probe (milliseconds) — run
    it off-peak on the writer instance, ONLY after the owner says go. Not run as of 2026-11-19.
"""
import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Item
from apps.discount_approvals.models import AUTO_DERIVED, FIELD_TO_SOFTECH, ItemPriceChangeRequest
from apps.discount_approvals.services import _cas_write


def _row_dict(cur, softech_id):
    """The whole HQ items row as {column: str(value)} (read-only)."""
    cur.execute("SELECT * FROM SOFTECHDB9.dbo.items WHERE itemcode = ?", [softech_id])
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0].lower() for d in cur.description]
    return {c: (None if v is None else str(v)) for c, v in zip(cols, row)}


def _diff(a, b):
    return {c: {'before': a.get(c), 'after': b.get(c)}
            for c in sorted(set(a) | set(b)) if a.get(c) != b.get(c)}


class Command(BaseCommand):
    help = 'Rollback probe of the D-09 compare-and-set price writer (always ROLLBACK, zero persistence)'

    def add_arguments(self, parser):
        parser.add_argument('--request', type=int, help='existing ItemPriceChangeRequest id (never modified)')
        parser.add_argument('--item', help='softech itemcode for an in-memory request (with --set)')
        parser.add_argument('--set', action='append', default=[], metavar='FIELD=VALUE',
                            help='requested field for --item, e.g. pack_price=100 (repeatable)')
        parser.add_argument('--usercode', default='', help='SOFTECH usercode to stamp in the probe')
        parser.add_argument('--run', action='store_true',
                            help='connect to HQ and run the probe (ROLLBACK). Without it: plan only.')

    def handle(self, *args, **o):
        req = self._request(o)
        usercode = o['usercode'] or req.erp_usercode or 'PROBE'
        plan = {
            'request': req.pk, 'item': req.item.softech_id, 'item_name': req.item.name,
            'new_values': req.new_values,
            'approved_against': {f: req.old_values.get(f) for f in req.new_values},
            'mirror_pack_qty': req.item.pack_qty, 'mirror_sale_tax_pct': str(req.item.sale_tax_pct),
            'usercode': usercode,
        }
        self.stdout.write(json.dumps({'plan': plan}, ensure_ascii=False, indent=2, default=str))
        if not o['run']:
            self.stdout.write('Plan only (no --run): nothing connected, nothing written.')
            return

        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        try:
            cur = conn.cursor()
            before = _row_dict(cur, req.item.softech_id)
            if before is None:
                raise CommandError(f'item {req.item.softech_id} not found at HQ')
            res = _cas_write(cur, req, usercode, commit=False,
                             inspect=lambda c: _row_dict(c, req.item.softech_id))
            after = _row_dict(cur, req.item.softech_id)
        finally:
            conn.close()

        inside = res.pop('inspect', None)
        report = {
            'outcome': res['outcome'],
            'committed': res['committed'],                     # must be False
            'rowcount_reported': res.get('rowcount'),          # must be 1 on 'written'
            'live_read': res.get('live'),
            'values_derived_from_live': res.get('values'),
            'conflicts': res.get('conflicts'),
            'readback_in_tran': res.get('readback'),
            'columns_changed_in_tran': _diff(before, inside) if inside else None,
            'row_restored_after_rollback': after == before,
            'diff_after_rollback': _diff(before, after),       # must be {}
        }
        self.stdout.write(json.dumps({'probe': report}, ensure_ascii=False, indent=2, default=str))
        if res['committed'] or after != before:
            raise CommandError('PROBE FAILED: HQ row differs after rollback — stop and investigate')
        self.stdout.write(self.style.SUCCESS('Probe done: rolled back, HQ row unchanged.'))

    def _request(self, o):
        if o.get('request'):
            try:
                return ItemPriceChangeRequest.objects.select_related('item').get(pk=o['request'])
            except ItemPriceChangeRequest.DoesNotExist:
                raise CommandError(f'request {o["request"]} not found')
        if not o.get('item') or not o['set']:
            raise CommandError('Provide --request <pk>, or --item <softech_id> with --set FIELD=VALUE')
        item = Item.objects.filter(softech_id=o['item']).first()
        if item is None:
            raise CommandError(f'item {o["item"]} not in our catalog')
        new = {}
        for pair in o['set']:
            field, _, value = pair.partition('=')
            if field not in FIELD_TO_SOFTECH or field in AUTO_DERIVED:
                raise CommandError(f'{field}: not a user-editable price field')
            try:
                new[field] = str(Decimal(value))
            except InvalidOperation:
                raise CommandError(f'{field}: {value!r} is not a number')
        # approved-against snapshot exactly as the create view takes it (our mirror)
        old = {f: (str(getattr(item, f)) if getattr(item, f, None) is not None else '0')
               for f in FIELD_TO_SOFTECH}
        return ItemPriceChangeRequest(item=item, old_values=old, new_values=new)   # never saved
