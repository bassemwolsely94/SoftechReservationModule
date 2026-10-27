"""
python manage.py backfill_item_names

Populates supplier_name, family_name, medicine_type_name, medicine_type_name_ar
on all catalog.Item rows by querying SOFTECH personsdata, itemssuppliers,
itemsfamily, and basic_data.

Safe to re-run — uses bulk_update so only touches changed rows.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Backfill supplier/producer/medicine-type display names on Item from SOFTECH'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print statistics without writing to the database',
        )
        parser.add_argument(
            '--batch', type=int, default=500,
            help='Batch size for bulk_update (default: 500)',
        )

    def handle(self, *args, **options):
        dry_run    = options['dry_run']
        batch_size = options['batch']

        self.stdout.write('Connecting to SOFTECH...')
        try:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'SOFTECH connection failed: {exc}'))
            return

        cursor = conn.cursor()

        # ── 1. Load personsdata (fallback for supplier/producer names) ────────
        self.stdout.write('Loading personsdata...')
        person_names: dict[str, str] = {}
        try:
            cursor.execute(
                'SELECT personcode, personname FROM SOFTECHDB9.dbo.personsdata'
                ' WHERE personname IS NOT NULL'
            )
            for r in cursor.fetchall():
                code = str(r[0] or '').strip()
                if code:
                    person_names[code] = str(r[1] or '').strip()
            self.stdout.write(f'  {len(person_names)} person records loaded')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  personsdata query failed: {exc}'))

        # ── 2. Load itemssuppliers: itemcode → primary suppcode ───────────────
        # main_supp = 'Y' marks the canonical supplier for each item.
        self.stdout.write('Loading itemssuppliers...')
        item_supplier_map: dict[str, str] = {}
        try:
            cursor.execute(
                'SELECT itemcode, suppcode FROM SOFTECHDB9.dbo.itemssuppliers'
                " WHERE main_supp = '1'"
            )
            for r in cursor.fetchall():
                icode = str(r[0] or '').strip()
                scode = str(r[1] or '').strip()
                if icode and scode:
                    item_supplier_map[icode] = scode
            self.stdout.write(f'  {len(item_supplier_map)} item-supplier links loaded')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  itemssuppliers query failed: {exc}'))

        # ── 3. Load itemsfamily: familycode → (familyname, familynamearabic) ──
        self.stdout.write('Loading itemsfamily...')
        family_names: dict[str, tuple[str, str]] = {}
        try:
            cursor.execute(
                'SELECT familycode, familyname, familynamearabic'
                ' FROM SOFTECHDB9.dbo.itemsfamily'
                " WHERE familyname IS NOT NULL AND familyname != ''"
            )
            for r in cursor.fetchall():
                code = str(r[0] or '').strip()
                if code and code not in family_names:
                    family_names[code] = (
                        str(r[1] or '').strip(),
                        str(r[2] or '').strip(),
                    )
            self.stdout.write(f'  {len(family_names)} family/producer codes loaded')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  itemsfamily query failed: {exc}'))

        # ── 4. Load itemstree: cdlcode → (cdldescr, cdldescrar) ──────────────
        # itemstree is the authoritative lookup for items.itemmedicine codes.
        # It contains exactly the 8 pharmacy medicine-type rows shown in the
        # SOFTECH item-card configuration screen (00=N A, 10=Medicine,
        # 20=Others, 30=Body Building, 40=Veterinary, 50=Cosmetics,
        # 60=هدايا عملاء, 70=Services خدمات).
        self.stdout.write('Loading itemstree (medicine types)...')
        medicine_names: dict[str, tuple[str, str]] = {}
        try:
            cursor.execute(
                'SELECT cdlcode, cdldescr, cdldescrar'
                ' FROM SOFTECHDB9.dbo.itemstree'
                " WHERE cdldescr IS NOT NULL AND cdldescr != ''"
            )
            for r in cursor.fetchall():
                code = str(r[0] or '').strip()
                if code:
                    medicine_names[code] = (
                        str(r[1] or '').strip(),
                        str(r[2] or '').strip(),
                    )
            self.stdout.write(f'  {len(medicine_names)} medicine type codes loaded')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  itemstree query failed: {exc}'))

        conn.close()

        # ── 5. Update Item rows ───────────────────────────────────────────────
        from apps.catalog.models import Item

        items        = list(Item.objects.only(
            'id', 'softech_id',
            'supplier_code', 'supplier_name',
            'family_code', 'family_name', 'family_name_ar',
            'medicine_type', 'medicine_type_name', 'medicine_type_name_ar',
        ))
        to_update    = []
        unchanged    = 0

        for item in items:
            changed = False
            item_code = str(item.softech_id or '').strip()

            # ── Supplier ─────────────────────────────────────────────────────
            # Source: itemssuppliers (main_supp='1') → suppcode → personsdata name.
            # Falls back to the code already on the Item when no itemssuppliers row exists.
            supp_code = item_supplier_map.get(item_code, item.supplier_code or '')
            new_supp  = person_names.get(supp_code, '') if supp_code else ''

            # Update supplier_code when itemssuppliers gives us the canonical code
            if supp_code and item.supplier_code != supp_code:
                item.supplier_code = supp_code
                changed = True
            if new_supp and item.supplier_name != new_supp:
                item.supplier_name = new_supp
                changed = True

            # ── Family / Producer ─────────────────────────────────────────────
            # Source: itemsfamily only — familycode → familyname / familynamearabic.
            # Does NOT fall back to personsdata; family codes are a separate
            # classification namespace from person/company codes.
            fam_code = item.family_code or ''
            fam_name_en, fam_name_ar = family_names.get(fam_code, ('', '')) if fam_code else ('', '')
            if fam_name_en and item.family_name != fam_name_en:
                item.family_name = fam_name_en
                changed = True
            if fam_name_ar and item.family_name_ar != fam_name_ar:
                item.family_name_ar = fam_name_ar
                changed = True

            # Medicine type names (correct pharmacy-specific entry via DESC order)
            med_en, med_ar = medicine_names.get(item.medicine_type, ('', '')) if item.medicine_type else ('', '')
            if med_en and item.medicine_type_name != med_en:
                item.medicine_type_name = med_en
                changed = True
            if med_ar and item.medicine_type_name_ar != med_ar:
                item.medicine_type_name_ar = med_ar
                changed = True

            if changed:
                to_update.append(item)
            else:
                unchanged += 1

        self.stdout.write(
            f'\n{len(items)} items scanned — '
            f'{len(to_update)} need update, {unchanged} already correct'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: no changes written'))
            # Show a sample of what would change
            for item in to_update[:5]:
                self.stdout.write(
                    f'  [{item.softech_id}] supp=[{item.supplier_code}] {item.supplier_name}  '
                    f'fam=[{item.family_code}] {item.family_name}  '
                    f'med=[{item.medicine_type}] {item.medicine_type_name}'
                )
            return

        if not to_update:
            self.stdout.write(self.style.SUCCESS('Nothing to update — all names already populated.'))
            return

        Item.objects.bulk_update(
            to_update,
            fields=[
                'supplier_code', 'supplier_name',
                'family_name', 'family_name_ar',
                'medicine_type_name', 'medicine_type_name_ar',
            ],
            batch_size=batch_size,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(to_update)} items updated.'
        ))

        # Print a few examples
        self.stdout.write('\nSample updates:')
        for item in to_update[:8]:
            self.stdout.write(
                f'  [{item.softech_id:>6}] supp=[{item.supplier_code:>8}] {item.supplier_name[:28]:<28}  '
                f'fam=[{item.family_code:>5}] {item.family_name[:22]:<22}  '
                f'med=[{item.medicine_type}] {item.medicine_type_name}'
            )
