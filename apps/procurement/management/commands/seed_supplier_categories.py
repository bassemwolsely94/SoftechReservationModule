"""
python manage.py seed_supplier_categories

Idempotently seeds the admin-managed SupplierCategory master and the
(ptcode, ptclassifcode) → category SupplierClassificationRule mapping from the
real SOFTECH person taxonomy (see apps.sync SoftechPersonType / PersonClassif).

Safe to re-run: categories are matched by `code`, rules by (ptcode, ptclassifcode).
Existing manual edits to names/colours are preserved unless --force-names.
"""
from django.core.management.base import BaseCommand
from apps.procurement.models import SupplierCategory, SupplierClassificationRule


# (code, name_ar, name_en, color, sort, is_fallback)
CATEGORIES = [
    ('OFFICIAL_DISTRIBUTOR', 'موزع رسمي',        'Official Distributor',   'blue',   10, False),
    ('MANUFACTURER',         'مصنع / شركة أدوية', 'Manufacturer',           'green',  20, False),
    ('GENERAL_SUPPLIER',     'مورد عام',          'General Supplier',       'sky',    30, False),
    ('DRUG_WAREHOUSE',       'مخازن أدوية',       'Drug Warehouse',         'amber',  40, False),
    ('INDIVIDUAL_SUPPLIER',  'مورد أفراد',        'Individual Supplier',    'purple', 50, False),
    ('CLEARING',             'مقاصات',            'Clearing / Settlement',  'teal',   60, False),
    ('SERVICE_VENDOR',       'مورد خدمات',        'Service Vendor',         'pink',   70, False),
    ('EXTERNAL_TRANSFER',    'تحويل خارجي',       'External Transfer',      'slate',  80, False),
    ('CUSTOMER_REPURCHASE',  'شراء من عميل / مريض','Customer / Patient',    'violet', 90, False),
    ('INTERNAL_TRANSFER',    'تحويل داخلي',       'Internal Branch',        'gray',  100, False),
    ('SISTER_COMPANY',       'شركة شقيقة',        'Sister Company',         'indigo',110, False),
    ('FIXED_ASSET_SUPPLIER', 'مورد أصول ثابتة',   'Fixed-Asset Supplier',   'orange',120, False),
    ('UNKNOWN',              'غير مصنف',          'Unknown',                'gray',  999, True),
]

# (ptcode, ptclassifcode, category_code, priority)  — '' classif = ptcode-only catch
RULES = [
    # pt20 (Supplier) sub-classifications — exact
    ('20', '20', 'OFFICIAL_DISTRIBUTOR', 10),   # موزع
    ('20', '60', 'OFFICIAL_DISTRIBUTOR', 10),   # شركات توزيع
    ('20', '70', 'MANUFACTURER',         10),   # شركات منتجة
    ('20', '50', 'DRUG_WAREHOUSE',       10),   # مخازن ادوية
    ('20', '30', 'INDIVIDUAL_SUPPLIER',  10),   # اشخاص
    ('20', '80', 'INDIVIDUAL_SUPPLIER',  10),   # مورد أفراد
    ('20', '40', 'CLEARING',             10),   # مقاصات
    ('20', '96', 'SERVICE_VENDOR',       10),   # خدمات
    ('20', '97', 'EXTERNAL_TRANSFER',    10),   # جهات تحويل خارجية
    # pt20 default for any other supplier classif (classif 10 مورد + unmapped)
    ('20', '',   'GENERAL_SUPPLIER',     50),
    # Other person types acting as purchase sources — ptcode-only
    ('10', '',   'CUSTOMER_REPURCHASE',  50),   # Corporate customer (تعاقدات/آجل, تبرعات…)
    ('11', '',   'CUSTOMER_REPURCHASE',  50),   # Individual customer
    ('00', '',   'INTERNAL_TRANSFER',    50),   # Branch
    ('80', '',   'SISTER_COMPANY',       50),   # Sister company
    ('70', '',   'FIXED_ASSET_SUPPLIER', 50),   # Fixed-asset supplier
]


class Command(BaseCommand):
    help = 'Seed admin-managed supplier categories + classification rules from the SOFTECH taxonomy'

    def add_arguments(self, parser):
        parser.add_argument('--force-names', action='store_true',
                            help='Overwrite existing name_ar/name_en/color/sort with the seed values')

    def handle(self, *args, **opts):
        force = opts['force_names']
        cat_by_code = {}
        created_c = updated_c = 0
        for code, ar, en, color, sort, fb in CATEGORIES:
            obj, created = SupplierCategory.objects.get_or_create(
                code=code,
                defaults=dict(name_ar=ar, name_en=en, color=color,
                              sort_order=sort, is_fallback=fb, is_active=True),
            )
            if created:
                created_c += 1
            elif force:
                obj.name_ar, obj.name_en, obj.color = ar, en, color
                obj.sort_order, obj.is_fallback = sort, fb
                obj.save()
                updated_c += 1
            cat_by_code[code] = obj

        created_r = 0
        for ptcode, classif, cat_code, prio in RULES:
            _, created = SupplierClassificationRule.objects.update_or_create(
                ptcode=ptcode, ptclassifcode=classif,
                defaults=dict(category=cat_by_code[cat_code], priority=prio, is_active=True),
            )
            created_r += 1 if created else 0

        self.stdout.write(self.style.SUCCESS(
            f'Categories: {created_c} created, {updated_c} updated, '
            f'{SupplierCategory.objects.count()} total. '
            f'Rules: {SupplierClassificationRule.objects.count()} total ({created_r} new).'
        ))
