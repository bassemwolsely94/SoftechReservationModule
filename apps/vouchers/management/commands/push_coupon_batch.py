"""
python manage.py push_coupon_batch BATCH_ID            # dry-run: show both SOFTECH document plans
python manage.py push_coupon_batch BATCH_ID --probe    # rollback rehearsal on HQ + diff vs docs 63944/63945
python manage.py push_coupon_batch BATCH_ID --commit   # REAL write (needs INVOICE_WRITER_ENABLED=True)
python manage.py push_coupon_batch BATCH_ID --verify   # read-only: docs present + HQ stock after a commit

Stocks a coupon batch in SOFTECH as two supplier-1268 purchase documents (points 102230 /
served 118639), through apps/invoices/writer.py. --probe inserts the full documents, reads
them back and ALWAYS rolls back (zero residue) — run it off-peak; it briefly locks the HQ
purchase counter. Re-running --commit after a partial failure resumes the missing leg; a
pushed leg is never pushed twice. Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md
"""
from django.core.management.base import BaseCommand, CommandError

from apps.vouchers import coupon_push
from apps.vouchers.models import CouponBatch


class Command(BaseCommand):
    help = 'Stock a gift-coupon batch in SOFTECH (dry-run / --probe / --commit)'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--probe', action='store_true', help='rollback rehearsal + column diff')
        mode.add_argument('--commit', action='store_true', help='REAL write to SOFTECH')
        mode.add_argument('--verify', action='store_true', help='read-only check of a stocked batch')
        parser.add_argument('--force', action='store_true', help='push despite validation WARNINGS')

    def handle(self, *args, **o):
        try:
            batch = CouponBatch.objects.get(pk=o['batch_id'])
        except CouponBatch.DoesNotExist:
            raise CommandError(f'batch {o["batch_id"]} not found')
        if o['verify']:
            return self._verify(batch)
        if batch.status == 'stocked' and not o['probe']:
            raise CommandError(f'batch #{batch.pk} is already stocked in SOFTECH')
        try:
            if o['probe']:
                self._probe(batch)
            else:
                self._push(batch, commit=o['commit'], force=o['force'])
        except ValueError as e:
            raise CommandError(str(e))

    def _probe(self, batch):
        self.stdout.write(f'Rollback rehearsal of batch #{batch.pk} ({batch.serial_from}–{batch.serial_to}) …')
        for leg, r in coupon_push.probe_batch(batch).items():
            self.stdout.write(f'\n── {leg} leg vs reference doc {r["reference_doc"]} ──')
            if r['error']:
                self.stdout.write(self.style.ERROR(f'  ERROR: {r["error"]}'))
                continue
            style = self.style.SUCCESS if r['ok'] else self.style.ERROR
            self.stdout.write(style(f'  insert ok={r["ok"]} lines {r["lines_found"]}/{r["lines_expected"]} '
                                    f'rolled_back={r["rolled_back"]} serials_in_order={r["serials_ok"]}'))
            for label, diffs in (('header', r['header_diff']), ('line 1', r['line_diff'])):
                if not diffs:
                    self.stdout.write(self.style.SUCCESS(f'  {label}: all compared columns match'))
                for col, ours, ref in diffs:
                    self.stdout.write(self.style.WARNING(f'  {label} DIFF {col}: ours={ours!r} reference={ref!r}'))

    def _verify(self, batch):
        r = coupon_push.verify_batch(batch)
        n = batch.size
        for leg, x in r['legs'].items():
            ok = x.get('present') and x.get('lines') == n
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f'{leg} leg: doc {x.get("docnumber")} present={x.get("present")} '
                                    f'lines={x.get("lines")}/{n} docvalue={x.get("docvalue")}'))
        for code, qty in r['stock'].items():
            rows = r['serial_rows'].get(code, {})
            self.stdout.write(f'item {code}: HQ stock now {qty:g} | this batch\'s serial rows at HQ: '
                              f'{rows.get("rows")} (qty {rows.get("qty", 0):g})')

    def _push(self, batch, *, commit, force):
        results = coupon_push.push_batch(batch, commit=commit, force=force)
        for leg, r in results.items():
            mode = r.get('mode')
            if mode == 'dry_run':
                plan = r['plan']
                first = plan['lines'][0]
                self.stdout.write(f'\n── {leg} leg (DRY-RUN — nothing written) ──')
                self.stdout.write(f'  supplier {plan["supplier_code"]} → branch {plan["branchcode"]}, '
                                  f'{len(plan["lines"])} lines, docvalue {plan["doc_value"]}, '
                                  f'usercode {plan["header"]["usercode"]}')
                self.stdout.write(f'  line 1: item {first["itemcode"]} serial {first.get("item_partno")} '
                                  f'expiry {first["itemexpirydate"]} price {first["itemsaleprice"]}')
            elif r.get('wrote_to_softech'):
                self.stdout.write(self.style.SUCCESS(f'{leg} leg → SOFTECH 100/10/{r["docnumber"]}'))
            elif mode in ('idempotent', 'already_finalized'):
                self.stdout.write(f'{leg} leg already in SOFTECH (doc {r.get("docnumber")}) — not pushed again')
            else:
                self.stdout.write(self.style.ERROR(f'{leg} leg NOT written: {r}'))
        batch.refresh_from_db()
        self.stdout.write(f'\nBatch #{batch.pk} status: {batch.status}')
