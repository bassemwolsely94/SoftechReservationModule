"""
apps/incentives/management/commands/test_near_expiry_engine.py

Unit-tests for the Near-Expiry Incentive engine logic.
Tests are pure Python — no Sybase connection required.
Covers all requirement test cases from the MASTER PROMPT.

Run with:
    python manage.py test_near_expiry_engine
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from django.core.management.base import BaseCommand


# ── Stub rule builder ──────────────────────────────────────────────────────────

def make_rule(
    item_code='1001',
    expiry_within_days=None,
    is_imported_filter='any',
    origin_codes=None,
    margin_min=None,
    margin_max=None,
    pack_price_min=None,
    pack_price_max=None,
    min_qty=Decimal('0'),
    branch_filter='',
    person_code_filter='',
    time_window_start=None,
    time_window_end=None,
    min_total_qty_in_period=None,
    incentive_type='percent',
    incentive_value=Decimal('5'),
    category_code='',
):
    return SimpleNamespace(
        id=1,
        item_code=item_code,
        category_code=category_code,
        rule_items=[],
        expiry_within_days=expiry_within_days,
        is_imported_filter=is_imported_filter,
        origin_codes=origin_codes,
        margin_min=margin_min,
        margin_max=margin_max,
        pack_price_min=pack_price_min,
        pack_price_max=pack_price_max,
        min_qty=min_qty,
        branch_filter=branch_filter,
        person_code_filter=person_code_filter,
        time_window_start=time_window_start,
        time_window_end=time_window_end,
        min_total_qty_in_period=min_total_qty_in_period,
        incentive_type=incentive_type,
        incentive_value=incentive_value,
        slab_config=None,
    )


class Command(BaseCommand):
    help = 'Test near-expiry incentive engine logic'

    def handle(self, *args, **options):
        from apps.incentives.engine import _find_matching_rule

        passed = 0
        failed = 0
        today = date.today()

        def run(name, expected_match, rule, item_code, expiry_date=None,
                item_attrs=None, person_code='EMP1', branch_code='100',
                qty=Decimal('5'), erp_dt=None, total_period_qty=Decimal('5')):
            nonlocal passed, failed
            rule_item_sets = {rule.id: frozenset([rule.item_code]) if rule.item_code else frozenset()}
            if erp_dt is None:
                erp_dt = datetime.combine(today, datetime.min.time())

            result = _find_matching_rule(
                [rule], rule_item_sets, item_code, person_code, branch_code,
                qty, erp_dt, total_period_qty,
                item_expiry_date=expiry_date,
                item_attr_map=item_attrs or {},
            )
            matched = result is not None
            ok = matched == expected_match
            status = 'PASS' if ok else 'FAIL'
            if ok:
                passed += 1
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(
                    f'  [{status}] {name} — expected match={expected_match}, got match={matched}'
                ))
                return
            self.stdout.write(self.style.SUCCESS(f'  [{status}] {name}'))

        self.stdout.write('=' * 60)
        self.stdout.write('Near-Expiry Incentive Engine Tests')
        self.stdout.write('=' * 60)

        # ── 1. Basic near-expiry: item within threshold ──────────────────────
        self.stdout.write('\n1. Near-expiry threshold tests')
        rule = make_rule(item_code='1001', expiry_within_days=90)
        run('Local item, 89 days remaining (qualifies)',
            True, rule, '1001',
            expiry_date=today + timedelta(days=89))
        run('Local item, 90 days remaining (qualifies — boundary)',
            True, rule, '1001',
            expiry_date=today + timedelta(days=90))
        run('Local item, 91 days remaining (does NOT qualify)',
            False, rule, '1001',
            expiry_date=today + timedelta(days=91))
        run('Local item, 0 days remaining (expires today — qualifies)',
            True, rule, '1001',
            expiry_date=today + timedelta(days=0))
        run('Local item, expired yesterday (does NOT qualify)',
            False, rule, '1001',
            expiry_date=today - timedelta(days=1))

        # ── 2. Imported item with 180-day threshold ──────────────────────────
        self.stdout.write('\n2. Imported item (180-day threshold)')
        rule_imp = make_rule(item_code='2001', expiry_within_days=180)
        run('Imported item, 179 days remaining (qualifies)',
            True, rule_imp, '2001',
            expiry_date=today + timedelta(days=179))
        run('Imported item, 181 days remaining (does NOT qualify)',
            False, rule_imp, '2001',
            expiry_date=today + timedelta(days=181))

        # ── 3. No expiry date on transaction line ────────────────────────────
        self.stdout.write('\n3. Missing expiry date')
        run('Rule with expiry_within_days, no expiry date on transaction (skip)',
            False, rule, '1001',
            expiry_date=None)  # No expiry data

        rule_no_expiry = make_rule(item_code='1001', expiry_within_days=None)
        run('Rule WITHOUT expiry filter, no expiry date (should match — normal sale)',
            True, rule_no_expiry, '1001',
            expiry_date=None)

        # ── 4. Batch A qualifies, Batch B does not ───────────────────────────
        self.stdout.write('\n4. Two batches same item, different expiry')
        rule = make_rule(item_code='3001', expiry_within_days=90)
        run('Batch A: 30 days (qualifies)',
            True, rule, '3001',
            expiry_date=today + timedelta(days=30))
        run('Batch B: 120 days (does NOT qualify)',
            False, rule, '3001',
            expiry_date=today + timedelta(days=120))

        # ── 5. Origin filter: local only ─────────────────────────────────────
        self.stdout.write('\n5. Origin filter: local/imported')
        rule_local = make_rule(item_code='4001', expiry_within_days=90, is_imported_filter='local')
        local_attrs = {'4001': {'is_imported': False, 'origin_code': 'EGY', 'pack_price': Decimal('50'), 'cost_price': Decimal('35')}}
        imp_attrs   = {'4001': {'is_imported': True,  'origin_code': 'GER', 'pack_price': Decimal('200'), 'cost_price': Decimal('140')}}

        run('local rule + local item (qualifies)',
            True, rule_local, '4001',
            expiry_date=today + timedelta(days=30), item_attrs=local_attrs)
        run('local rule + imported item (does NOT qualify)',
            False, rule_local, '4001',
            expiry_date=today + timedelta(days=30), item_attrs=imp_attrs)

        rule_imp2 = make_rule(item_code='4001', expiry_within_days=180, is_imported_filter='imported')
        run('imported rule + imported item (qualifies)',
            True, rule_imp2, '4001',
            expiry_date=today + timedelta(days=60), item_attrs=imp_attrs)
        run('imported rule + local item (does NOT qualify)',
            False, rule_imp2, '4001',
            expiry_date=today + timedelta(days=60), item_attrs=local_attrs)

        # ── 6. Origin codes whitelist ─────────────────────────────────────────
        self.stdout.write('\n6. Origin codes whitelist')
        rule_egypt = make_rule(item_code='5001', expiry_within_days=90, origin_codes=['EGY', 'SAU'])
        egy_attrs  = {'5001': {'is_imported': False, 'origin_code': 'EGY', 'pack_price': Decimal('30'), 'cost_price': Decimal('20')}}
        ger_attrs  = {'5001': {'is_imported': True,  'origin_code': 'GER', 'pack_price': Decimal('200'), 'cost_price': Decimal('140')}}

        run('Origin=EGY, whitelist=[EGY,SAU] (qualifies)',
            True, rule_egypt, '5001',
            expiry_date=today + timedelta(days=45), item_attrs=egy_attrs)
        run('Origin=GER, whitelist=[EGY,SAU] (does NOT qualify)',
            False, rule_egypt, '5001',
            expiry_date=today + timedelta(days=45), item_attrs=ger_attrs)

        # ── 7. Margin filter ──────────────────────────────────────────────────
        self.stdout.write('\n7. Margin filter')
        # margin = (50-35)/50 * 100 = 30%
        rule_margin = make_rule(item_code='6001', expiry_within_days=90,
                                margin_min=Decimal('20'), margin_max=Decimal('40'))
        attrs_30pct = {'6001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('50'), 'cost_price': Decimal('35')}}
        attrs_10pct = {'6001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('50'), 'cost_price': Decimal('45')}}
        attrs_50pct = {'6001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('50'), 'cost_price': Decimal('25')}}

        run('Margin 30% within [20%-40%] (qualifies)',
            True, rule_margin, '6001',
            expiry_date=today + timedelta(days=45), item_attrs=attrs_30pct)
        run('Margin 10% below minimum [20%-40%] (does NOT qualify)',
            False, rule_margin, '6001',
            expiry_date=today + timedelta(days=45), item_attrs=attrs_10pct)
        run('Margin 50% above maximum [20%-40%] (does NOT qualify)',
            False, rule_margin, '6001',
            expiry_date=today + timedelta(days=45), item_attrs=attrs_50pct)

        # ── 8. Pack price filter ──────────────────────────────────────────────
        self.stdout.write('\n8. Pack price filter')
        rule_price = make_rule(item_code='7001', expiry_within_days=90,
                               pack_price_min=Decimal('100'), pack_price_max=Decimal('500'))
        cheap = {'7001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('50'), 'cost_price': Decimal('30')}}
        mid   = {'7001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('250'), 'cost_price': Decimal('150')}}
        pricey= {'7001': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('600'), 'cost_price': Decimal('400')}}

        run('Price 250 within [100-500] (qualifies)',
            True, rule_price, '7001',
            expiry_date=today + timedelta(days=30), item_attrs=mid)
        run('Price 50 below minimum (does NOT qualify)',
            False, rule_price, '7001',
            expiry_date=today + timedelta(days=30), item_attrs=cheap)
        run('Price 600 above maximum (does NOT qualify)',
            False, rule_price, '7001',
            expiry_date=today + timedelta(days=30), item_attrs=pricey)

        # ── 9. Cross-branch sale ──────────────────────────────────────────────
        self.stdout.write('\n9. Cross-branch (branch_filter empty = all branches)')
        rule_any_branch = make_rule(item_code='8001', expiry_within_days=90, branch_filter='')
        run('Any branch — branch_filter empty (qualifies)',
            True, rule_any_branch, '8001',
            expiry_date=today + timedelta(days=45), branch_code='160')

        rule_specific = make_rule(item_code='8001', expiry_within_days=90, branch_filter='100')
        run('branch_filter=100, sale at branch 100 (qualifies)',
            True, rule_specific, '8001',
            expiry_date=today + timedelta(days=45), branch_code='100')
        run('branch_filter=100, sale at branch 160 (does NOT qualify)',
            False, rule_specific, '8001',
            expiry_date=today + timedelta(days=45), branch_code='160')

        # ── 10. Combined filters ──────────────────────────────────────────────
        self.stdout.write('\n10. Combined filters (expiry + origin + margin)')
        rule_combined = make_rule(
            item_code='9001',
            expiry_within_days=90,
            is_imported_filter='local',
            margin_min=Decimal('15'),
        )
        attrs_ok  = {'9001': {'is_imported': False, 'origin_code': 'EGY', 'pack_price': Decimal('100'), 'cost_price': Decimal('80')}}
        # margin = (100-80)/100 * 100 = 20% >= 15% OK

        run('All filters pass (qualifies)',
            True, rule_combined, '9001',
            expiry_date=today + timedelta(days=60), item_attrs=attrs_ok)

        # Change expiry to fail
        run('Expiry 100 days (fails expiry filter even if other filters pass)',
            False, rule_combined, '9001',
            expiry_date=today + timedelta(days=100), item_attrs=attrs_ok)

        # Change to imported (fails origin filter)
        attrs_imp_ok = {'9001': {'is_imported': True, 'origin_code': 'GER', 'pack_price': Decimal('100'), 'cost_price': Decimal('80')}}
        run('Imported item (fails origin filter)',
            False, rule_combined, '9001',
            expiry_date=today + timedelta(days=60), item_attrs=attrs_imp_ok)

        # ── 11. Category wiring (Feature 7) ───────────────────────────────────
        self.stdout.write('\n11. Category-code rule wiring')
        # Rule targets a CATEGORY (no item_code, no rule_items) + near-expiry
        rule_cat = make_rule(item_code='', category_code='CAT_PAIN', expiry_within_days=90)
        cat_match = {'A100': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('10'),
                              'cost_price': Decimal('5'), 'category_softech_id': 'CAT_PAIN'}}
        cat_other = {'A200': {'is_imported': False, 'origin_code': '', 'pack_price': Decimal('10'),
                              'cost_price': Decimal('5'), 'category_softech_id': 'CAT_VITAMINS'}}
        run('Item in category CAT_PAIN (qualifies)',
            True, rule_cat, 'A100',
            expiry_date=today + timedelta(days=30), item_attrs=cat_match)
        run('Item in different category (does NOT qualify)',
            False, rule_cat, 'A200',
            expiry_date=today + timedelta(days=30), item_attrs=cat_other)
        run('Item not in catalog/attrs (category rule fails-closed)',
            False, rule_cat, 'A999',
            expiry_date=today + timedelta(days=30), item_attrs={})

        # ── 12. Expiry bucket helper (single source of truth) ─────────────────
        self.stdout.write('\n12. Expiry bucket boundaries')
        from apps.incentives.engine import _expiry_bucket
        bucket_cases = [
            (0, '0-30'), (30, '0-30'), (31, '31-60'), (60, '31-60'),
            (61, '61-90'), (90, '61-90'), (91, '91-180'), (180, '91-180'),
            (181, '181+'), (None, 'unknown'),
        ]
        for days, expected in bucket_cases:
            got = _expiry_bucket(days)
            ok = got == expected
            if ok:
                passed += 1
                self.stdout.write(self.style.SUCCESS(f'  [PASS] bucket({days}) = {got}'))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(
                    f'  [FAIL] bucket({days}) = {got}, expected {expected}'))

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('\n' + '=' * 60)
        total = passed + failed
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f'ALL TESTS PASSED: {passed}/{total}'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'FAILURES: {failed}/{total} failed  ({passed} passed)'
            ))
        self.stdout.write('=' * 60)
