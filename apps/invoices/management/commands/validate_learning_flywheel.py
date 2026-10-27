"""
Validate the per-vendor LEARNING FLYWHEEL, quota-free.

The invoice matcher is deliberately cold-start-weak: the first invoice from a
distributor matches mostly by fuzzy name, but on confirm every matched line is
remembered as a VendorItemMapping (vendor + normalized name → item, with the
supplier code). The NEXT invoice then matches those repeat products INSTANTLY via
the learned code/name tiers instead of fuzzy. The one-shot benchmark can't see
this (it always tests a stone-cold cache); this command does.

It renders the bundle, splits it into invoices, and processes them IN ORDER on the
FREE OCR engine (Tesseract — no Gemini, no quota). For each invoice it (1) matches
against the mappings learned from the invoices BEFORE it, records the tier mix,
then (2) "confirms" the confident matches — writing the same VendorItemMapping rows
production would on a real confirm — so later invoices benefit. If the share of
lines matched via the LEARNED tiers (vendor_code / vendor_name) climbs across the
bundle, the flywheel works.

EVERYTHING runs inside one transaction that is ROLLED BACK at the end, so no
mappings persist — this is a measurement, not a data change. Tier 0 (SOFTECH
itemssuppliers) is skipped by default so the run is fully offline and the flywheel
is isolated from that (constant, non-learning) tier.

Usage:
  python manage.py validate_learning_flywheel \
      --pdf "…/رامكو.pdf" --supplier رامكو --limit 50
"""
from __future__ import annotations

import tempfile

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Measure how invoice→item matching improves as the per-vendor flywheel learns."

    def add_arguments(self, parser):
        parser.add_argument('--pdf', required=True)
        parser.add_argument('--supplier', default='', help='Vendor name (رامكو) for the learned mappings.')
        parser.add_argument('--engine', default='tesseract', help='FREE OCR engine (default tesseract — no quota).')
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--confirm-threshold', type=float, default=0.70,
                            help='Only learn matches at/above this score (simulates an operator '
                                 'accepting confident matches and correcting the rest).')
        parser.add_argument('--with-itemssuppliers', action='store_true',
                            help='Also let Tier-0 SOFTECH itemssuppliers fire (hits SOFTECH; off by default).')

    def handle(self, *args, **o):
        import os
        if not os.path.exists(o['pdf']):
            raise CommandError(f"PDF not found: {o['pdf']}")
        from apps.invoices import pdf as pdfmod, ocr, splitter, pipeline
        from apps.invoices import ingest as ing
        from apps.invoices.models import VendorProfile, VendorItemMapping
        from apps.shortage.matching import _normalize

        vendor = None
        if o['supplier']:
            from apps.invoices import suppliers as sup_mod
            r = sup_mod.resolve_supplier(o['supplier'])
            if r:
                vendor = VendorProfile.objects.filter(softech_personcode=r['personcode']).first()
        if vendor is None:
            raise CommandError("Need a resolvable --supplier with a VendorProfile (learned "
                               "mappings are vendor-scoped).")
        if not o['with_itemssuppliers']:
            vendor.is_main = False   # in-memory only; isolates the flywheel, stays offline

        self.stdout.write(f"supplier → {vendor.name} (personcode {vendor.softech_personcode}); "
                          f"engine={o['engine']}; confirm≥{o['confirm_threshold']}; "
                          f"Tier-0 itemssuppliers {'ON' if o['with_itemssuppliers'] else 'OFF'}")

        # ── split ──
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
            groups = splitter.group_pages(probes)[:o['limit']]
            self.stdout.write(f"{os.path.basename(o['pdf'])}: {len(paths)} pages → {len(groups)} invoices "
                              f"(processing {len(groups)} in order)\n")

            rows = []   # per-invoice stats
            learned_items = set()   # item ids with a learned mapping from earlier invoices
            rep = {'total': 0, 'converted': 0, 'leaked': 0, 'missed': 0}
            LEARNED = ('vendor_code', 'vendor_name')

            # one transaction, rolled back at the end → nothing persists
            with transaction.atomic():
                for idx, group in enumerate(groups, 1):
                    seg_paths = [paths[i] for i in group]
                    data = ocr.extract_structured_images(seg_paths, engine=o['engine'])
                    _, cands = ocr.parse_structured(data) if data else ({}, [])
                    cands = [c for c in cands if (c.get('manual_name') or c.get('raw_text'))]
                    matches = pipeline.match_candidates(cands, vendor)

                    n = len(cands)
                    tiers = {}
                    for mr in matches:
                        t = mr['tier'] or 'none'
                        tiers[t] = tiers.get(t, 0) + 1
                    matched = sum(1 for mr in matches if mr['item'])
                    learned = sum(tiers.get(t, 0) for t in LEARNED)
                    rows.append({'inv': idx, 'n': n, 'matched': matched,
                                 'learned': learned, 'tiers': tiers})

                    # ── repeat conversion: of lines whose item was ALREADY learned on
                    # an earlier invoice, how many re-matched via a learned tier vs
                    # leaked back to fuzzy (OCR name/code varied) or missed entirely?
                    # This separates "repeats don't recur" from "OCR too noisy to learn".
                    for mr in matches:
                        iid = mr['item'].id if mr['item'] else None
                        if iid and iid in learned_items:
                            rep['total'] += 1
                            if mr['tier'] in LEARNED:
                                rep['converted'] += 1
                            elif mr['tier'] == 'fuzzy':
                                rep['leaked'] += 1
                            else:
                                rep['missed'] += 1

                    # ── "confirm" the confident matches → learn (same as production) ──
                    for cand, mr in zip(cands, matches):
                        if not mr['item'] or (mr['score'] or 0) < o['confirm_threshold']:
                            continue
                        learned_items.add(mr['item'].id)
                        name = cand.get('manual_name') or cand.get('raw_text') or ''
                        norm = _normalize(name)
                        if not norm:
                            continue
                        code = (cand.get('vendor_item_code') or '').strip()
                        m, created = VendorItemMapping.objects.get_or_create(
                            vendor=vendor, raw_name_normalized=norm,
                            defaults={'item': mr['item'], 'vendor_item_code': code, 'use_count': 1})
                        if not created:
                            m.item = mr['item']; m.use_count += 1
                            if code:
                                m.vendor_item_code = code
                            m.save(update_fields=['item', 'vendor_item_code', 'use_count', 'updated_at'])

                transaction.set_rollback(True)   # discard every learned row

        self._report(rows, rep)

    def _report(self, rows, rep):
        if not rows:
            self.stdout.write('no invoices processed.'); return
        self.stdout.write("inv │ lines │ matched │ via-learned │ learned% │ tiers")
        self.stdout.write("────┼───────┼─────────┼─────────────┼──────────┼──────────────────────")
        for r in rows:
            lp = (r['learned'] / r['n'] * 100) if r['n'] else 0
            tiers = ', '.join(f"{k}={v}" for k, v in sorted(r['tiers'].items()))
            self.stdout.write(f"{r['inv']:>3} │ {r['n']:>5} │ {r['matched']:>7} │ "
                              f"{r['learned']:>11} │ {lp:>7.0f}% │ {tiers}")

        # convergence: first third vs last third
        k = max(1, len(rows) // 3)
        first, last = rows[:k], rows[-k:]

        def share(group):
            tot = sum(r['n'] for r in group) or 1
            return (sum(r['matched'] for r in group) / tot * 100,
                    sum(r['learned'] for r in group) / tot * 100)

        fm, fl = share(first)
        lm, ll = share(last)
        self.stdout.write(self.style.SUCCESS("\n── FLYWHEEL CONVERGENCE ──"))
        self.stdout.write(f"  first {k} invoices:  matched {fm:.0f}%  |  via learned tiers {fl:.0f}%")
        self.stdout.write(f"  last  {k} invoices:  matched {lm:.0f}%  |  via learned tiers {ll:.0f}%")
        delta = ll - fl
        verdict = ("FLYWHEEL WORKS — repeat products increasingly match via learned "
                   "code/name tiers" if delta >= 10 else
                   "weak/no climb — repeats may not recur, or OCR name/code reads vary "
                   "too much to learn (see per-invoice tiers)")
        self.stdout.write(f"  learned-tier share climbed {fl:.0f}% → {ll:.0f}%  (Δ {delta:+.0f} pts) → {verdict}")

        # ── the decisive split: of REPEATS (item already learned earlier), did the
        # learned tier re-fire, or did the read vary too much and leak to fuzzy? ──
        t = rep['total']
        self.stdout.write(self.style.SUCCESS("\n── REPEAT CONVERSION (already-learned items seen again) ──"))
        if not t:
            self.stdout.write("  no repeats — within this bundle, products essentially don't recur, "
                              "so the flywheel has nothing to convert here (needs more invoices over time).")
            return
        conv = rep['converted'] / t * 100
        leak = rep['leaked'] / t * 100
        miss = rep['missed'] / t * 100
        self.stdout.write(f"  repeat sightings: {t}")
        self.stdout.write(f"    re-matched via learned tier : {rep['converted']:>3} ({conv:.0f}%)")
        self.stdout.write(f"    leaked back to fuzzy         : {rep['leaked']:>3} ({leak:.0f}%)  ← OCR name/code varied")
        self.stdout.write(f"    missed entirely              : {rep['missed']:>3} ({miss:.0f}%)")
        if leak + miss >= conv:
            self.stdout.write("  → repeats DO recur, but the OCR read varies too much for the learned "
                              "key to re-fire. The flywheel is throttled by OCR CONSISTENCY, not by "
                              "lack of repeats → better/steadier OCR (or an OCR-robust learning key) "
                              "is the lever, and it compounds with the flywheel.")
        else:
            self.stdout.write("  → most repeats convert via the learned tier: the flywheel is working; "
                              "accuracy will climb with volume as more products get confirmed once.")
