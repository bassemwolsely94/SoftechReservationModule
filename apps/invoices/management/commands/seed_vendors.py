"""
Seed the curated top-10 distributor VendorProfiles (name → SOFTECH personcode +
aliases) and optionally backfill existing SupplierInvoices:

    python manage.py seed_vendors                 # create/update the 10 profiles
    python manage.py seed_vendors --backfill      # + link unlinked invoices,
                                                  #   normalize stored line expiries

Idempotent: re-running only fills gaps.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.invoices.suppliers import TOP_SUPPLIERS, link_invoice_vendor
from apps.invoices.models import VendorProfile, SupplierInvoice, InvoiceLine
from apps.invoices.ocr import normalize_expiry


class Command(BaseCommand):
    help = 'Seed top-10 distributor VendorProfiles and (optionally) backfill invoices.'

    def add_arguments(self, parser):
        parser.add_argument('--backfill', action='store_true',
                            help='Link unlinked invoices + normalize stored expiries.')

    @transaction.atomic
    def handle(self, *args, **opts):
        # ── 1. Seed / update the curated profiles ─────────────────────────────
        created = updated = 0
        for code, (name, aliases) in TOP_SUPPLIERS.items():
            vp = VendorProfile.objects.filter(softech_personcode=code).first()
            alias_str = ','.join(aliases)
            if vp is None:
                vname, i = name, 1
                while VendorProfile.objects.filter(name=vname).exists():
                    i += 1
                    vname = f'{name} ({i})'
                # Seeded curated distributors are official → main by default.
                VendorProfile.objects.create(name=vname, softech_personcode=code,
                                             aliases=alias_str, is_main=True)
                created += 1
                self.stdout.write(self.style.SUCCESS(f'  + {code:>5}  {name}'))
            else:
                # merge any missing aliases; ensure the curated ones are flagged main
                have = {a.strip().lower() for a in (vp.aliases or '').split(',') if a.strip()}
                merged = list(have | {a.lower() for a in aliases})
                fields = []
                if len(merged) != len(have):
                    vp.aliases = ','.join(sorted(m for m in merged)); fields.append('aliases')
                if not vp.is_main:
                    vp.is_main = True; fields.append('is_main')
                if fields:
                    vp.save(update_fields=fields)
                    updated += 1
                self.stdout.write(f'    {code:>5}  {vp.name} (exists){" · set main" if "is_main" in fields else ""}')
        self.stdout.write(self.style.SUCCESS(f'Vendors: {created} created, {updated} alias-updated.'))

        if not opts['backfill']:
            return

        # ── 2. Backfill: link unlinked invoices ───────────────────────────────
        linked = 0
        for inv in SupplierInvoice.objects.filter(vendor__isnull=True):
            res = link_invoice_vendor(inv)
            if res:
                linked += 1
                self.stdout.write(f'  linked invoice {inv.pk} {inv.supplier_name!r} '
                                  f'→ {res["personcode"]} ({res["source"]})')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  invoice {inv.pk} {inv.supplier_name!r} → UNRESOLVED'))
        self.stdout.write(self.style.SUCCESS(f'Linked {linked} invoice(s).'))

        # ── 3. Backfill: normalize stored line expiries ───────────────────────
        fixed = 0
        for l in InvoiceLine.objects.exclude(expiry_date=''):
            iso = normalize_expiry(l.expiry_date)
            if iso and iso != l.expiry_date:
                l.expiry_date = iso
                l.save(update_fields=['expiry_date'])
                fixed += 1
        self.stdout.write(self.style.SUCCESS(f'Normalized {fixed} expiry value(s).'))
