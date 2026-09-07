"""
python manage.py clone_purchase --branch 130 --docnumber 11946 [--profile prod]
                                [--commit] [--keep]

No test instance → validate the writeback by CLONING a real, already-entered purchase
(stktransm/stktrans doccode 10), re-building it through our writer, and DIFFING every
column of our re-insert against the original — then (optionally) committing ONE real
document that you return manually.

Stages:
  1. READ the source purchase (header + lines) from SOFTECH (read-only).
  2. BUILD an identical SupplierInvoice draft in PG (vendor by personcode, items by
     itemcode, qty/prices/discount/expiry from the source).
  3. ROLLBACK PROBE: insert our version on the branch DB, read it back, ROLL BACK
     (zero residue) — then diff our inserted columns vs the original. Reports any
     field that differs or that we left NULL while the original had a value, plus
     whether the insert trigger bumped lastdocnumberin_supp.
  4. --commit (requires INVOICE_WRITER_ENABLED): actually insert ONE real document.
     Default WITHOUT --commit is probe-only (nothing persisted).

By default the temp SupplierInvoice is deleted afterwards (--keep to retain it, e.g.
to push later from the UI). A committed clone is always kept (it is a real ERP doc).
"""
from django.core.management.base import BaseCommand, CommandError

# Columns that legitimately differ on a re-insert (identity / timestamps / running
# balances / our idempotency + operator stamps) — excluded from the must-match diff.
_IGNORE_HEADER = {
    'docnumber', 'docdate', 'trans_time', 'table_dumped', 'docwritedate', 'docpaydue',
    'personnewbal', 'vf1', 'vf2', 'usercode', 'cashiercode', 'fatcurrentstatus', 'fatstatuscode',
}
_IGNORE_LINE = {
    'docnumber', 'docdate', 'trans_time', 'table_dumped', 'usercode', 'r_docdate',
    'vf1', 'vf2', 'vf3', 'vf4', 'promsno', 's_docdate',
}


class Command(BaseCommand):
    help = 'Clone a real entered purchase, diff our re-insert vs the original, optionally commit one.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', required=True, help='SOFTECH branchcode of the source doc')
        parser.add_argument('--docnumber', required=True, type=int, help='source purchase docnumber (doccode 10)')
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--commit', action='store_true',
                            help='actually insert ONE real document (needs INVOICE_WRITER_ENABLED)')
        parser.add_argument('--keep', action='store_true', help='keep the temp SupplierInvoice')
        parser.add_argument('--invoice-number', default='',
                            help='override the supplier invoice no (docnumber2) — use a UNIQUE value '
                                 'for a real --commit test so the dup-guard does not adopt the source doc')
        parser.add_argument('--as-return', action='store_true',
                            help='build a RETURN-to-supplier (doccode 120) of the source purchase '
                                 '(return_of_docnumber = --docnumber), cloning its lines')

    def handle(self, *args, **o):
        from django.db import transaction
        from config.sybase import SoftechConnector
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile
        from apps.invoices import writer

        branchcode = str(o['branch']).strip()
        docnumber = o['docnumber']

        # ── 1. READ the source doc (read-only) ─────────────────────────────────
        self.stdout.write(f'Reading source purchase {branchcode}/10/{docnumber} (profile={o["profile"]})…')
        conn = SoftechConnector(profile=o['profile']).connect()
        try:
            src_hdr = self._one(conn, "SELECT * FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                                [branchcode, docnumber])
            if not src_hdr:
                raise CommandError('Source purchase header not found.')
            src_lines = self._all(conn, "SELECT * FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=? "
                                        "ORDER BY itemcode", [branchcode, docnumber])
            personcode = str(src_hdr.get('cust_branch_code') or '').strip()
            supp = self._one(conn, "SELECT personname FROM personsdata WHERE personcode=? AND ptcode='20'",
                             [personcode])
            supp_name = (supp.get('personname') if supp else None) or f'SOFTECH {personcode}'
        finally:
            conn.close()
        self.stdout.write(f'  supplier={personcode} "{supp_name}" | lines={len(src_lines)} | docvalue={src_hdr.get("docvalue")}')

        # ── 2. BUILD the clone draft in PG ─────────────────────────────────────
        branch = Branch.objects.filter(softech_branch_id=branchcode).first()
        if not branch:
            raise CommandError(f'No PG Branch with softech_branch_id={branchcode}.')
        vendor, _ = VendorProfile.objects.get_or_create(
            softech_personcode=personcode,
            defaults={'name': supp_name[:200]})
        if not vendor.softech_personcode:
            vendor.softech_personcode = personcode
            vendor.save(update_fields=['softech_personcode'])

        created_invoice = None
        committed = False
        try:
            with transaction.atomic():
                inv_no = o['invoice_number'] or str(src_hdr.get('docnumber2') or '')
                is_ret = o['as_return']
                inv = SupplierInvoice.objects.create(
                    branch=branch, vendor=vendor,
                    doc_kind=('return' if is_ret else 'purchase'),
                    return_of_docnumber=(docnumber if is_ret else None),
                    supplier_name=supp_name[:200], invoice_number=inv_no,
                    status='confirmed',
                    notes=f'[{"return of" if is_ret else "clone of"} {branchcode}/10/{docnumber}]')
                created_invoice = inv
                missing = []
                for sl in src_lines:
                    code = str(sl.get('itemcode') or '').strip()
                    item = Item.objects.filter(softech_id=code).first()
                    if not item:
                        missing.append(code)
                        continue
                    InvoiceLine.objects.create(
                        invoice=inv, item=item, manual_name=item.name,
                        quantity=sl.get('transqty') or 0,
                        public_price=sl.get('itemsaleprice') or 0,
                        unit_price=sl.get('transprice') or 0,
                        discount_pct=sl.get('pharmacydiscp') or 0,
                        extra_discount_pct=sl.get('additionaldiscp') or 0,
                        vat_pct=sl.get('origintaxp') or 0,
                        expiry_date=str(sl.get('itemexpirydate') or '')[:10],
                        is_confirmed=True,
                    )
                if missing:
                    self.stdout.write(self.style.WARNING(
                        f'  ⚠ {len(missing)} itemcode(s) not in catalog mirror, skipped: {missing}'))
                if not inv.lines.exists():
                    raise CommandError('No lines could be matched to catalog items — aborting.')

                # ── 3. ROLLBACK PROBE + diff ───────────────────────────────────
                self.stdout.write('Running rollback probe (real insert → readback → ROLLBACK)…')
                res = writer.probe_invoice(inv, confirm=True)
                if res.get('error'):
                    raise CommandError(f'Probe error: {res["error"]}')
                rb = res.get('readback') or {}
                self._report(rb, src_hdr, src_lines)
                self.stdout.write(
                    f'\nProbe: ok={res.get("ok")} allocated_docnumber={res.get("allocated_docnumber")} '
                    f'trigger_bumped_counter={rb.get("trigger_bumped_counter")} '
                    f'counter {rb.get("counter_before")}→{rb.get("counter_after")}')

                # ── 4. optional REAL commit ────────────────────────────────────
                if o['commit']:
                    if not writer.writer_enabled():
                        raise CommandError('--commit needs INVOICE_WRITER_ENABLED=True in the environment.')
                    self.stdout.write(self.style.WARNING('COMMITTING one real document…'))
                    cres = writer.push_final(inv, dry_run=False)
                    committed = bool(cres.get('wrote_to_softech'))
                    self.stdout.write(self.style.SUCCESS(
                        f'  committed={committed} softech_docnumber={cres.get("docnumber")}'))

                # keep the invoice only if committed or --keep; else roll back PG creation
                if not committed and not o['keep']:
                    raise _Rollback()
        except _Rollback:
            created_invoice = None  # PG creation rolled back by design
            self.stdout.write('Temp invoice rolled back (use --keep to retain it).')

        if committed:
            self.stdout.write(self.style.SUCCESS(
                f'\n✅ Real document created. Verify in SOFTECH, then RETURN it manually (doccode 120).'))
        elif created_invoice and o['keep']:
            self.stdout.write(self.style.SUCCESS(
                f'\nKept SupplierInvoice id={created_invoice.pk} (status=confirmed) — push from UI when ready.'))

    # ── diff reporting ─────────────────────────────────────────────────────────
    def _report(self, readback, src_hdr, src_lines):
        our_hdr = (readback or {}).get('full_header')
        our_lines = (readback or {}).get('full_lines') or []
        if not our_hdr:
            self.stdout.write(self.style.ERROR('  No inserted header captured — cannot diff.'))
            return
        self.stdout.write('\n── HEADER diff (our re-insert vs original) ──')
        self._diff_row(our_hdr, src_hdr, _IGNORE_HEADER)

        self.stdout.write('\n── LINE diffs ──')
        src_by_item = {}
        for sl in src_lines:
            src_by_item.setdefault(str(sl.get('itemcode')).strip(), sl)
        for ol in our_lines:
            code = str(ol.get('itemcode')).strip()
            sl = src_by_item.get(code)
            self.stdout.write(f'  item {code}:')
            if not sl:
                self.stdout.write(self.style.WARNING('    (no matching original line)'))
                continue
            self._diff_row(ol, sl, _IGNORE_LINE, indent='    ')

    def _diff_row(self, ours, orig, ignore, indent='  '):
        cols = list(orig.keys())
        diffs = 0
        ours_null = 0
        for c in cols:
            if c in ignore:
                continue
            ov, sv = ours.get(c), orig.get(c)
            if self._eq(ov, sv):
                continue
            if ov is None and sv is not None:
                ours_null += 1
                self.stdout.write(self.style.WARNING(f'{indent}OURS-NULL {c}: original={sv!r} (we leave NULL)'))
            else:
                diffs += 1
                self.stdout.write(self.style.ERROR(f'{indent}DIFF     {c}: ours={ov!r} original={sv!r}'))
        if diffs == 0 and ours_null == 0:
            self.stdout.write(self.style.SUCCESS(f'{indent}✓ all compared columns match'))
        else:
            self.stdout.write(f'{indent}→ {diffs} diff(s), {ours_null} ours-null (review whether they matter)')

    @staticmethod
    def _eq(a, b):
        if a is None and b is None:
            return True
        try:
            fa, fb = float(a), float(b)
            return abs(fa - fb) < 0.01
        except (TypeError, ValueError):
            return str(a).strip() == str(b).strip()

    # ── read helpers (dict rows) ───────────────────────────────────────────────
    @staticmethod
    def _one(conn, sql, params):
        conn._cursor().execute('SET ROWCOUNT 1')
        try:
            cur = conn._cursor(); cur.execute(sql, params)
            cols = [d[0] for d in cur.description]; r = cur.fetchone()
            return dict(zip(cols, r)) if r else None
        finally:
            conn._cursor().execute('SET ROWCOUNT 0')

    @staticmethod
    def _all(conn, sql, params):
        cur = conn._cursor(); cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


class _Rollback(Exception):
    """Internal signal to roll back the temp PG creation."""
