"""
benchmark_vs_softech — the literal "our OCR vs what SofTech actually stored" diff.

Run this from a machine that CAN reach the server the invoices were posted to
(e.g. the HQ main server). For each invoice in the PDF it:
  1. splits + extracts it with our free pipeline,
  2. resolves each extracted line to a catalog item (softech_id),
  3. looks up the POSTED document on the server by the printed invoice number
     (stktransm.docnumber2 = our detected doc_number), and
  4. diffs line-by-line: quantity, cost (transprice) and the three discounts,
and prints per-invoice + overall accuracy.

It is READ-ONLY on SofTech. Example:

  python manage.py benchmark_vs_softech \
      --pdf "…/رامكو.pdf" --host 192.168.1.8 --doccode 10 --limit 10

Tolerances: qty exact; cost within --cost-tol (default 1%); discount within 0.5pp.
"""
import os
import tempfile

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Diff our OCR extraction of a purchase-invoice PDF against the posted SofTech docs.'

    def add_arguments(self, parser):
        parser.add_argument('--pdf', required=True, help='Path to the invoice PDF.')
        parser.add_argument('--host', required=True, help='SofTech server the invoices were posted to.')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--db', default='SOFTECHDB9')
        parser.add_argument('--doccode', default='10', help="10=purchase, 120=return.")
        parser.add_argument('--limit', type=int, default=10, help='Max invoices to check.')
        parser.add_argument('--engine', default=None, help="OCR engine (default: auto/free).")
        parser.add_argument('--supplier', default='', help="Supplier name to resolve the "
                            "VendorProfile (enables the Tier-0 itemssuppliers code match, "
                            "as production does). e.g. رامكو. Omit → fuzzy-name matching only.")
        parser.add_argument('--cost-tol', type=float, default=0.01, help='Cost tolerance fraction.')
        parser.add_argument('--out', default='', help='Write a line-by-line diff CSV to this path.')
        parser.add_argument('--since', default='', help="Only scan docs on/after this date "
                            "(YYYY-MM-DD) — MUCH faster on HQ (docnumber2 is unindexed).")
        parser.add_argument('--timeout', type=int, default=600,
                            help='Per-scan SQL timeout seconds (big unindexed scans need this).')

    def handle(self, *args, **o):
        if not os.path.exists(o['pdf']):
            raise CommandError(f"PDF not found: {o['pdf']}")
        from apps.invoices import pdf as pdfmod, ocr, splitter, engines
        from apps.invoices import ingest as ing

        # ── 0. engine diagnostic ── (so the scorecard is never ambiguous about
        # which OCR path produced the numbers). easyocr appearing here as the free
        # engine, or 'auto' silently escalating to Gemini, both cap accuracy — the
        # tuned field-voting path is Tesseract. Force it with --engine tesseract.
        requested = (o.get('engine') or 'auto')
        tess = engines._tesseract_available()
        free = engines.best_free_engine()
        has_gem = bool(ocr._gemini_key())
        self.stdout.write(self.style.MIGRATE_HEADING('── OCR engine ──'))
        self.stdout.write(
            f"  requested={requested} | tesseract_available={tess} | "
            f"best_free={free} | gemini_key={has_gem}")
        if requested in ('auto', None) and has_gem:
            self.stdout.write(
                f"  auto mode: free={free} first, escalate to Gemini when weak "
                f"(pass --engine tesseract to pin the tuned free path)")
        elif requested in ('auto', None) and free != 'tesseract':
            self.stdout.write(self.style.WARNING(
                f"  WARNING: free engine is {free!r}, not tesseract — "
                f"field-voting path unavailable, accuracy will be lower"))

        # ── 1. split ──
        with tempfile.TemporaryDirectory() as tmp:
            paths = pdfmod.render_pages(o['pdf'], tmp)
            if not paths:
                raise CommandError('No renderable pages (PyMuPDF missing?).')
            blanks, _ = ing._preprocess_pages(paths)
            probes = []
            for i, p in enumerate(paths):
                if i in blanks:
                    continue
                pr = ing._probe_one(p, ''); pr['page'] = i
                probes.append(pr)
            groups = splitter.group_pages(probes)
            summary = splitter.summarize(probes, groups)
            self.stdout.write(f"{os.path.basename(o['pdf'])}: {len(paths)} pages → {len(groups)} invoices")

            conn = self._connect(o)
            agg = {'inv_found': 0, 'inv_missing': 0, 'line_match': 0, 'our_lines': 0,
                   'posted_lines': 0, 'qty_ok': 0, 'cost_ok': 0, 'disc_ok': 0,
                   # why unmatched lines missed (on FOUND invoices only) — tells us
                   # whether the next lever is OCR recall, catalog matching, or a
                   # wrong match, instead of guessing.
                   'miss_no_name': 0, 'miss_no_catalog': 0, 'miss_wrong_item': 0,
                   'miss_code_variant': 0, 'miss_fuzzy_wrong': 0,
                   'posted_only': 0, 'our_with_code': 0, 'tiers': {},
                   # cost-model reconciliation (posted lines only, OCR-independent):
                   # does SOFTECH transprice == base×(1−d1)(1−d2)(1−d3), or is there
                   # an extra component (the distributor margin)?
                   'recon_n': 0, 'recon_eq': 0, 'recon_resid_pct': [], 'recon_resid_abs': [],
                   # A/B: cost from OCR net vs cost from catalog-base × OCR discounts
                   # (SOFTECH's own formula; discounts OCR more robustly than net prices).
                   'cost_ok_net': 0, 'cost_ok_fromdisc': 0}
            csv_rows = []

            # The invoice numbers we detected (digits only), capped by --limit.
            segments, seg_dates = [], []
            for seg_no, (group, seg) in enumerate(zip(groups, summary)):
                if seg_no >= o['limit']:
                    break
                dn2 = ''.join(ch for ch in str(seg.get('doc_number') or '') if ch.isdigit())
                segments.append((dn2, [paths[i] for i in group]))
                seg_dates.append(seg.get('date'))

            # auto --since from the OCR'd invoice dates (so the unindexed HQ scan
            # stays small), falling back to a 90-day window when none are readable.
            if not o['since']:
                o['since'] = self._auto_since(seg_dates)
                self.stdout.write(f"auto --since = {o['since']} (from invoice dates; override with --since)")

            # ── ONE header scan (docnumber2 is UNINDEXED → never scan 43×) ──
            self.stdout.write('scanning SofTech headers (one pass)…' +
                              ('' if o['since'] else '  [tip: pass --since YYYY-MM-DD to speed this up]'))
            hdr_map = self._header_map(conn, o)          # {docnumber2:int → docnumber:int}
            if hdr_map is None:
                raise CommandError('Header scan timed out — pass --since (a recent date) and/or a bigger --timeout.')
            seg_doc = {dn2: self._resolve(hdr_map, dn2) for dn2, _ in segments}
            matched_docs = sorted({d for d in seg_doc.values() if d})
            self.stdout.write(f'  matched {len(matched_docs)}/{len(segments)} invoices to posted docs')

            # ── ONE line scan for all matched docs ──
            lines_by_doc = self._lines_map(conn, o, matched_docs) if matched_docs else {}

            vendor = self._resolve_vendor(o.get('supplier'))
            for dn2, seg_paths in segments:
                our = self._extract_lines(seg_paths, o['engine'], vendor)
                agg['our_lines'] += len(our)
                agg['our_with_code'] += sum(1 for ln in our if ln.get('code'))
                docnum = seg_doc.get(dn2)
                posted = lines_by_doc.get(docnum) if docnum else None
                if posted is None:
                    agg['inv_missing'] += 1
                    self.stdout.write(f"  inv#{dn2 or '?'}: NOT FOUND on server (our {len(our)} lines)")
                    for ln in our:
                        csv_rows.append(self._row(dn2, 'INVOICE_NOT_FOUND', ln, None, o['cost_tol']))
                    continue
                agg['inv_found'] += 1
                agg['posted_lines'] += len(posted)
                self._diff_invoice(dn2, our, posted, o['cost_tol'], agg, csv_rows)

            if conn:
                conn.close()
            self._report(agg)
            if o['out']:
                self._write_csv(o['out'], csv_rows)
                self.stdout.write(self.style.SUCCESS(f"\nline-by-line diff → {o['out']} ({len(csv_rows)} rows)"))

    # ── helpers ──
    def _auto_since(self, dates, buffer_days=7, fallback_days=90):
        """Earliest readable invoice date − buffer, else today − fallback_days.
        Returns 'YYYY-MM-DD'. Handles DD/MM/YYYY (Egyptian) and YYYY-MM-DD."""
        import datetime
        import re
        parsed = []
        for d in dates:
            s = str(d or '').strip()
            dt = None
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                try:
                    dt = datetime.datetime.strptime(s[:10], fmt).date(); break
                except ValueError:
                    continue
            if not dt:
                m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
                if m:
                    try:
                        dt = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError:
                        dt = None
                if not dt:
                    m = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', s)   # DD/MM/YYYY
                    if m:
                        try:
                            dt = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                        except ValueError:
                            dt = None
            if dt and 2000 <= dt.year <= 2100:
                parsed.append(dt)
        if parsed:
            since = min(parsed) - datetime.timedelta(days=buffer_days)
        else:
            since = datetime.date.today() - datetime.timedelta(days=fallback_days)
        return since.strftime('%Y-%m-%d')

    def _connect(self, o):
        try:
            from config.sybase import get_branch_connection
            return get_branch_connection(o['host'], o['port'], o['db'], charset='cp1256')
        except Exception as e:
            raise CommandError(f"Cannot reach SofTech {o['host']}: {e}")

    def _resolve_vendor(self, supplier):
        """Resolve the VendorProfile for --supplier (read-only) so match_candidates
        can use the authoritative Tier-0 itemssuppliers code match. None → the
        vendor-scoped tiers degrade to global lookups (fuzzy-name dominated)."""
        if not supplier:
            self.stdout.write(self.style.WARNING(
                "  no --supplier → Tier-0 itemssuppliers code match DISABLED "
                "(pass e.g. --supplier رامكو for the production matcher)"))
            return None
        from apps.invoices import suppliers as sup_mod
        from apps.invoices.models import VendorProfile
        r = sup_mod.resolve_supplier(supplier)
        if not r:
            self.stdout.write(self.style.WARNING(
                f"  supplier {supplier!r} not resolved → Tier-0 disabled"))
            return None
        vendor = VendorProfile.objects.filter(softech_personcode=r['personcode']).first()
        self.stdout.write(
            f"  supplier {supplier!r} → {r['name']} (personcode {r['personcode']}, "
            f"is_main={getattr(vendor, 'is_main', None)}, "
            f"vendor_profile={'yes' if vendor else 'MISSING'})")
        return vendor

    def _extract_lines(self, seg_paths, engine, vendor):
        """Extract this invoice's lines and match them to catalog items with the
        SAME 4-tier matcher production uses (pipeline.match_candidates) — code-first
        (itemssuppliers → learned code → learned name → fuzzy), so the benchmark
        measures the matcher we actually ship, not name-fuzzy alone."""
        from apps.invoices import ocr, pipeline
        data = ocr.extract_structured_images(seg_paths, engine=engine)
        _, cands = ocr.parse_structured(data) if data else ({}, [])
        matches = pipeline.match_candidates(cands, vendor)
        out = []
        for c, mr in zip(cands, matches):
            it = mr['item']
            out.append({
                'name': c.get('manual_name') or c.get('raw_text') or '',
                'code': (c.get('vendor_item_code') or '').strip(),
                'softech_id': (str(it.softech_id) if it and it.softech_id else None),
                'matched_name': (it.name if it else ''),
                'match_score': float(mr['score'] or 0),
                'tier': mr['tier'],
                'qty': _f(c.get('quantity')), 'cost': _f(c.get('unit_price')),
                'd1': _f(c.get('discount_pct')), 'd2': _f(c.get('extra_discount_pct')),
                'd3': _f(c.get('special_discount_pct'))})
        return out

    def _header_map(self, conn, o):
        """ONE scan: {docnumber2 → docnumber} for the doccode (optionally since a
        date). docnumber2 is UNINDEXED, so this must be a single pass, not per-row.
        Returns None on timeout."""
        cur = conn.cursor()
        where = f"doccode='{o['doccode']}'"
        if o['since']:
            where += f" AND docdate >= '{o['since']}'"
        try:
            cur.execute(f"SELECT docnumber2, docnumber FROM stktransm WHERE {where}", timeout=o['timeout'])
        except Exception as e:
            self.stderr.write(f"  header scan failed: {str(e)[:90]}")
            return None
        out = {}
        for r in cur.fetchall():
            try:
                d2 = int(r[0] or 0)
                if d2 > 0:
                    out[d2] = int(r[1])
            except (TypeError, ValueError):
                continue
        return out

    def _resolve(self, hdr_map, dn2):
        """Our detected number may carry trailing barcode digits — try the exact
        value, trimmed to 10, last digit off, and the last 10 digits."""
        if not dn2:
            return None
        for v in (dn2, dn2[:10], dn2[:-1], dn2[-10:]):
            if v and len(v) >= 6:
                try:
                    c = int(v)
                except ValueError:
                    continue
                if c in hdr_map:
                    return hdr_map[c]
        return None

    def _lines_map(self, conn, o, docnums):
        """ONE scan (chunked): posted stktrans lines grouped by docnumber."""
        cur = conn.cursor()
        out = {}
        for i in range(0, len(docnums), 200):
            inlist = ','.join(str(d) for d in docnums[i:i + 200])
            where = f"doccode='{o['doccode']}' AND docnumber IN ({inlist})"
            if o['since']:
                where += f" AND docdate >= '{o['since']}'"
            try:
                cur.execute("SELECT docnumber, itemcode, transqty, transprice, pharmacydiscp, "
                            f"additionaldiscp, specialdiscp, itemsaleprice_tax FROM stktrans WHERE {where}",
                            timeout=o['timeout'])
            except Exception as e:
                self.stderr.write(f"  line scan failed: {str(e)[:90]}")
                continue
            for r in cur.fetchall():
                out.setdefault(int(r[0]), []).append(
                    {'itemcode': str(r[1]).strip(), 'qty': _f(r[2]), 'cost': _f(r[3]),
                     'd1': _f(r[4]), 'd2': _f(r[5]), 'd3': _f(r[6]), 'base': _f(r[7])})
        # resolve posted itemcode → our catalog name (PG mirror), so the diff shows
        # the POSTED product beside ours — distinguishing a genuine wrong match from
        # the same product posted under a different SOFTECH item code.
        from apps.catalog.models import Item
        codes = {p['itemcode'] for lines in out.values() for p in lines}
        names = dict(Item.objects.filter(softech_id__in=codes)
                     .values_list('softech_id', 'name')) if codes else {}
        for lines in out.values():
            for p in lines:
                p['name'] = names.get(p['itemcode'], '')
        return out

    def _diff_invoice(self, docnum2, our, posted, cost_tol, agg, csv_rows):
        by_code = {p['itemcode']: p for p in posted}
        # ── cost-model reconciliation: SOFTECH's own transprice vs the discounted
        # base, computed ONLY from posted fields (no OCR). Reveals whether the
        # distributor margin is baked into transprice. ──
        for p in posted:
            base = p.get('base', 0)
            if base > 0 and p['cost'] > 0:
                nc = base * (1 - p['d1'] / 100) * (1 - p['d2'] / 100) * (1 - p['d3'] / 100)
                p['_net_calc'] = nc
                agg['recon_n'] += 1
                if abs(p['cost'] - nc) / p['cost'] <= 0.01:
                    agg['recon_eq'] += 1
                agg['recon_resid_abs'].append(p['cost'] - nc)
                agg['recon_resid_pct'].append((p['cost'] - nc) / p['cost'] * 100)
        used = set()
        matched = qok = cok = dok = 0
        for ln in our:
            p = by_code.get(ln['softech_id']) if ln['softech_id'] else None
            if not p:
                # categorize WHY this line didn't match a posted line
                if not (ln.get('name') or '').strip():
                    reason = 'OUR_ONLY: no name read (OCR recall)'
                    agg['miss_no_name'] += 1
                elif not ln['softech_id']:
                    reason = (f"OUR_ONLY: no catalog match (best score "
                              f"{ln.get('match_score', 0):.2f})")
                    agg['miss_no_catalog'] += 1
                else:
                    # matched to a catalog item whose code isn't on the posted
                    # invoice. Is it the SAME product under a different SOFTECH code
                    # (→ our fuzzy picked the wrong code variant), or a genuinely
                    # wrong product? Compare our match name to the posted names.
                    agg['miss_wrong_item'] += 1
                    near = self._closest_posted(ln.get('matched_name') or ln.get('name', ''),
                                                posted, used)
                    if near:
                        agg['miss_code_variant'] += 1
                        reason = (f"OUR_ONLY: likely SAME product, different code — "
                                  f"we matched '{ln.get('matched_name','')}' (code {ln['softech_id']}), "
                                  f"posted has '{near['name']}' (code {near['itemcode']})")
                    else:
                        agg['miss_fuzzy_wrong'] += 1
                        reason = (f"OUR_ONLY: matched '{ln.get('matched_name','')}' "
                                  f"(score {ln.get('match_score',0):.2f}, code {ln['softech_id']}) "
                                  f"— no similar product on this posted invoice")
                csv_rows.append(self._row(docnum2, reason, ln, None, cost_tol))
                continue
            used.add(ln['softech_id'])
            matched += 1; agg['line_match'] += 1
            t = ln.get('tier') or '?'
            agg['tiers'][t] = agg['tiers'].get(t, 0) + 1
            if abs(ln['qty'] - p['qty']) < 0.001:
                qok += 1; agg['qty_ok'] += 1
            if p['cost'] > 0 and abs(ln['cost'] - p['cost']) / p['cost'] <= cost_tol:
                cok += 1; agg['cost_ok'] += 1; agg['cost_ok_net'] += 1
            # A/B the alternative cost source: catalog base × OUR OCR discounts (how
            # SOFTECH itself computes transprice). If this beats the OCR-net cost
            # above, we should derive cost from discounts, not the net price.
            if p.get('base', 0) > 0 and p['cost'] > 0:
                cost_disc = p['base'] * (1 - ln['d1'] / 100) * (1 - ln['d2'] / 100) * (1 - ln['d3'] / 100)
                if abs(cost_disc - p['cost']) / p['cost'] <= cost_tol:
                    agg['cost_ok_fromdisc'] += 1
            # discount accuracy = EFFECTIVE discount (we post the cost, which
            # already compounds d1·d2·d3; the individual split may differ). Compare
            # 1−cost/base on the same catalog base.
            if p.get('base', 0) > 0:
                eff_p = 1 - p['cost'] / p['base']
                eff_o = 1 - ln['cost'] / p['base']
                if abs(eff_p - eff_o) <= 0.01:      # within 1 percentage-point
                    dok += 1; agg['disc_ok'] += 1
            csv_rows.append(self._row(docnum2, 'MATCHED', ln, p, cost_tol))
        missed = 0
        for p in posted:
            if p['itemcode'] not in used:
                missed += 1
                agg['posted_only'] += 1
                csv_rows.append(self._row(docnum2, 'POSTED_ONLY (we missed it)', None, p, cost_tol))

        # ── per-invoice scorecard ──
        def mk(ok, tot):
            return f"{ok}/{tot} {'✓' if tot and ok == tot else '✗' if tot else '-'}"
        extra = []
        if matched < len(posted):
            extra.append(f"missed {missed}")
        if len(our) > matched:
            extra.append(f"unmatched-ours {len(our) - matched}")
        line = (f"  inv#{docnum2}: lines {matched}/{len(posted)} "
                f"| qty {mk(qok, matched)} | cost {mk(cok, matched)} | disc {mk(dok, matched)}")
        if extra:
            line += '  (' + ', '.join(extra) + ')'
        allgood = (matched == len(posted) == len(our) and qok == cok == dok == matched and matched > 0)
        self.stdout.write(self.style.SUCCESS(line) if allgood else line)

    def _closest_posted(self, name, posted, used, threshold=0.6):
        """The unmatched posted line whose catalog name is most similar to ``name``
        (SequenceMatcher ratio ≥ threshold), or None. Used to tell 'same product,
        different SOFTECH code' from a genuinely wrong fuzzy match."""
        import difflib
        name = (name or '').strip()
        if not name:
            return None
        best, best_r = None, threshold
        for p in posted:
            if p['itemcode'] in used or not p.get('name'):
                continue
            r = difflib.SequenceMatcher(None, name, p['name']).ratio()
            if r >= best_r:
                best, best_r = p, r
        return best

    def _row(self, docnum2, status, ln, p, cost_tol):
        def ok(a, b, tol_abs=0.001, pct=None):
            if ln is None or p is None:
                return ''
            return 'Y' if (abs(a - b) <= tol_abs if pct is None else (b and abs(a - b) / b <= pct)) else 'N'
        return {
            'invoice_no': docnum2, 'status': status,
            'item_ours': (ln or {}).get('name', ''), 'item_posted': (p or {}).get('name', ''),
            'softech_id': (ln or {}).get('softech_id') or (p or {}).get('itemcode', ''),
            'qty_ours': (ln or {}).get('qty', ''), 'qty_posted': (p or {}).get('qty', ''),
            'qty_ok': ok((ln or {}).get('qty', 0), (p or {}).get('qty', 0)) if (ln and p) else '',
            'cost_ours': (ln or {}).get('cost', ''), 'cost_posted': (p or {}).get('cost', ''),
            'cost_posted_calc': round((p or {}).get('_net_calc', 0), 4) if (p and p.get('_net_calc') is not None) else '',
            'cost_residual': (round((p or {}).get('cost', 0) - (p or {}).get('_net_calc', 0), 4)
                              if (p and p.get('_net_calc') is not None) else ''),
            'cost_ok': ok((ln or {}).get('cost', 0), (p or {}).get('cost', 0), pct=cost_tol) if (ln and p) else '',
            'd1_ours': (ln or {}).get('d1', ''), 'd1_posted': (p or {}).get('d1', ''),
            'd2_ours': (ln or {}).get('d2', ''), 'd2_posted': (p or {}).get('d2', ''),
            'd3_ours': (ln or {}).get('d3', ''), 'd3_posted': (p or {}).get('d3', ''),
        }

    def _write_csv(self, path, rows):
        import csv
        cols = ['invoice_no', 'status', 'item_ours', 'item_posted', 'softech_id',
                'qty_ours', 'qty_posted', 'qty_ok',
                'cost_ours', 'cost_posted', 'cost_posted_calc', 'cost_residual', 'cost_ok',
                'd1_ours', 'd1_posted', 'd2_ours', 'd2_posted', 'd3_ours', 'd3_posted']
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def _report(self, a):
        self.stdout.write(self.style.SUCCESS('\n── ACCURACY vs SofTech ──'))
        self.stdout.write(f"invoices: found {a['inv_found']}, missing {a['inv_missing']}")
        lm = a['line_match'] or 1
        self.stdout.write(f"lines: our {a['our_lines']}, posted {a['posted_lines']}, matched {a['line_match']}")
        self.stdout.write(f"  matched-line field accuracy:")
        self.stdout.write(f"    quantity : {a['qty_ok']}/{a['line_match']} ({a['qty_ok']/lm*100:.0f}%)")
        self.stdout.write(f"    cost     : {a['cost_ok']}/{a['line_match']} ({a['cost_ok']/lm*100:.0f}%)")
        self.stdout.write(f"    discounts: {a['disc_ok']}/{a['line_match']} ({a['disc_ok']/lm*100:.0f}%)")
        self.stdout.write(f"  cost source A/B (matched lines):")
        self.stdout.write(f"    from OCR net price           : {a['cost_ok_net']}/{a['line_match']} ({a['cost_ok_net']/lm*100:.0f}%)")
        self.stdout.write(f"    from catalog base × OCR disc : {a['cost_ok_fromdisc']}/{a['line_match']} ({a['cost_ok_fromdisc']/lm*100:.0f}%)  ← SOFTECH's own formula")
        if a['tiers']:
            order = ['itemssuppliers', 'vendor_code', 'vendor_name', 'barcode', 'fuzzy', '?']
            parts = [f"{k}={a['tiers'][k]}" for k in order if a['tiers'].get(k)]
            self.stdout.write(f"  matched via: {', '.join(parts)}")

        # ── why lines didn't match (FOUND invoices only) — points the next batch ──
        our_unmatched = a['miss_no_name'] + a['miss_no_catalog'] + a['miss_wrong_item']
        self.stdout.write("  line-recall gap (found invoices):")
        self.stdout.write(f"    posted lines we missed    : {a['posted_only']}")
        self.stdout.write(f"    our lines that didn't match: {our_unmatched}")
        self.stdout.write(f"        · no name read (OCR)      : {a['miss_no_name']}")
        self.stdout.write(f"        · name, no catalog match  : {a['miss_no_catalog']}")
        self.stdout.write(f"        · matched a wrong item    : {a['miss_wrong_item']}")
        self.stdout.write(f"            – same product, diff code : {a['miss_code_variant']}")
        self.stdout.write(f"            – genuinely wrong/extra   : {a['miss_fuzzy_wrong']}")
        code_rate = (a['our_with_code'] / a['our_lines'] * 100) if a['our_lines'] else 0
        self.stdout.write(f"  OCR code recall: {a['our_with_code']}/{a['our_lines']} "
                          f"lines had a vendor item code ({code_rate:.0f}%)")
        self.stdout.write("  (see diff.csv: item_ours vs item_posted shows the matched vs posted product)")

        # ── cost-model reconciliation (OCR-independent) ──
        if a['recon_n']:
            import statistics
            eqp = a['recon_eq'] / a['recon_n'] * 100
            med_abs = statistics.median(a['recon_resid_abs']) if a['recon_resid_abs'] else 0
            med_pct = statistics.median(a['recon_resid_pct']) if a['recon_resid_pct'] else 0
            pos = sum(1 for r in a['recon_resid_pct'] if r > 1)
            self.stdout.write(self.style.SUCCESS("\n── COST MODEL RECONCILIATION (posted lines, OCR-independent) ──"))
            self.stdout.write(f"  transprice == base×(1−d1)(1−d2)(1−d3): {a['recon_eq']}/{a['recon_n']} ({eqp:.0f}%)")
            self.stdout.write(f"  residual (transprice − discounted-base): median {med_abs:+.4f} EGP "
                              f"({med_pct:+.1f}%); {pos}/{a['recon_n']} lines exceed +1%")
            if eqp >= 90:
                verdict = ("transprice IS purely the discounted base → the distributor margin is NOT "
                           "in SOFTECH's cost. The cost gap is OCR band misreading, not margin logic "
                           "→ fix the template bands, not the cost formula.")
            elif med_pct > 1:
                verdict = ("transprice EXCEEDS the discounted base by a consistent margin → SOFTECH's "
                           "stored cost DOES include an extra component (the distributor margin). "
                           "Confirmed: add it to the cost model (stop-and-confirm pricing change).")
            else:
                verdict = "mixed/small residual — inspect cost_residual per line in the CSV."
            self.stdout.write(f"  → {verdict}")


def _f(v):
    try:
        return float(str(v).replace(',', '')) if v not in (None, '') else 0.0
    except (ValueError, TypeError):
        return 0.0
