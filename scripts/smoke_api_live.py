"""
Comprehensive live API test - runs against http://localhost:8001
"""
import requests, sys, json
from datetime import date

BASE = 'http://localhost:8001/api'
ADMIN_USER = 'bassemwolsely94'
ADMIN_PASS = 'TestAdmin123'

results = {'pass': 0, 'fail': 0, 'warn': 0}
_token = None

def _get_token():
    global _token
    if _token:
        return _token
    r = requests.post(f'{BASE}/auth/login/', json={'username': ADMIN_USER, 'password': ADMIN_PASS})
    if r.status_code == 200:
        _token = r.json()['access']
        return _token
    raise RuntimeError(f'Login failed: {r.status_code}')

def H(method, path, **kwargs):
    tok = _get_token()
    url = f'{BASE}{path}' if path.startswith('/') else f'{BASE}/{path}'
    return requests.request(method, url, headers={'Authorization': f'Bearer {tok}'}, **kwargs)

def check(label, fn_or_resp, expect=(200, 201), allow=None):
    try:
        r = fn_or_resp() if callable(fn_or_resp) else fn_or_resp
        code = r.status_code
        ok_codes = set(expect) | set(allow or [])
        if code in ok_codes:
            print(f'  PASS  [{code}]  {label}')
            results['pass'] += 1
            return r
        else:
            print(f'  FAIL  [{code}]  {label}  (expected {sorted(ok_codes)})')
            try:
                body = r.json()
                if isinstance(body, dict):
                    for k, v in list(body.items())[:2]:
                        print(f'        {k}: {str(v)[:100]}')
            except Exception:
                print(f'        body: {r.text[:150]}')
            results['fail'] += 1
            return r
    except Exception as e:
        print(f'  ERR   [---]  {label}  {e}')
        results['fail'] += 1
        return None

def section(title):
    print(f'\n=== {title} ===')


# =============================================================================
# AUTH
# =============================================================================
section('AUTH')
r_login = requests.post(f'{BASE}/auth/login/', json={'username': ADMIN_USER, 'password': ADMIN_PASS})
if r_login.status_code == 200:
    _token = r_login.json()['access']
    _refresh = r_login.json()['refresh']
    print(f'  PASS  [200]  login')
    results['pass'] += 1
else:
    print(f'  FAIL  [{r_login.status_code}]  login - CANNOT CONTINUE')
    sys.exit(1)

check('GET /auth/me/', H('GET', '/auth/me/'))
check('POST /auth/refresh/', requests.post(f'{BASE}/auth/refresh/', json={'refresh': _refresh}))
check('GET /auth/me/ no token => 401', requests.get(f'{BASE}/auth/me/'), expect=(401,))


# =============================================================================
# RESERVATIONS
# =============================================================================
section('RESERVATIONS')
r_res_list = check('GET /reservations/', H('GET', '/reservations/'))
_res_id = None
if r_res_list and r_res_list.status_code == 200:
    d = r_res_list.json()
    items = d.get('results', d) if isinstance(d, dict) else d
    if items:
        _res_id = items[0]['id']

check('GET /reservations/dashboard/', H('GET', '/reservations/dashboard/'))

r_branches = H('GET', '/branches/')
_branch_id = None
if r_branches.status_code == 200:
    brs = r_branches.json()
    brs_list = brs.get('results', brs) if isinstance(brs, dict) else brs
    if brs_list:
        _branch_id = brs_list[0]['id']

r_items = H('GET', '/items/')
_item_id = None
if r_items.status_code == 200:
    its = r_items.json()
    its_list = its.get('results', its) if isinstance(its, dict) else its
    if its_list:
        _item_id = its_list[0]['id']

if _branch_id and _item_id:
    r_create = check('POST /reservations/ (create)', H('POST', '/reservations/', json={
        'item': _item_id, 'branch': _branch_id,
        'quantity_requested': 1, 'contact_name': 'API Test',
        'contact_phone': '01099990099', 'priority': 'normal', 'channel': 'pickup',
    }), expect=(201,))
    if r_create and r_create.status_code == 201:
        _res_id = r_create.json()['id']
        print(f'        created reservation id={_res_id}')

if _res_id:
    check(f'GET /reservations/{_res_id}/', H('GET', f'/reservations/{_res_id}/'))
    check(f'POST change-status available',
          H('POST', f'/reservations/{_res_id}/change-status/', json={'status': 'available'}))
    check(f'POST change-status available again => 400',
          H('POST', f'/reservations/{_res_id}/change-status/', json={'status': 'available'}),
          expect=(400,))
    check(f'POST log note',
          H('POST', f'/reservations/{_res_id}/log/', json={'activity_type': 'note', 'message': 'api test note'}),
          expect=(201,))
    check(f'GET activities', H('GET', f'/reservations/{_res_id}/activities/'))
    check(f'POST downpayment',
          H('POST', f'/reservations/{_res_id}/downpayments/', json={'amount': '100.00', 'payment_method': 'cash'}),
          expect=(201,))
    check(f'GET downpayments', H('GET', f'/reservations/{_res_id}/downpayments/'))
    check(f'GET images', H('GET', f'/reservations/{_res_id}/images/'))
    check(f'GET print', H('GET', f'/reservations/{_res_id}/print/'), allow=(404,))
    check(f'POST share-whatsapp', H('POST', f'/reservations/{_res_id}/share-whatsapp/'), allow=(404,))


# =============================================================================
# CUSTOMERS
# =============================================================================
section('CUSTOMERS')
r_custs = check('GET /customers/', H('GET', '/customers/'))
_cust_id = None
if r_custs and r_custs.status_code == 200:
    d = r_custs.json()
    items = d.get('results', d) if isinstance(d, dict) else d
    if items:
        _cust_id = items[0]['id']
        check(f'GET /customers/{_cust_id}/', H('GET', f'/customers/{_cust_id}/'))
        check(f'GET purchases', H('GET', f'/customers/{_cust_id}/purchases/'))
        check(f'GET reservations', H('GET', f'/customers/{_cust_id}/reservations/'))
        check(f'GET top_items', H('GET', f'/customers/{_cust_id}/top_items/'))


# =============================================================================
# ITEMS & BRANCHES
# =============================================================================
section('ITEMS & BRANCHES')
check('GET /items/', H('GET', '/items/'))
check('GET softech-search', H('GET', '/items/softech-search/', params={'q': 'par'}), allow=(400, 404))
check('GET /branches/', H('GET', '/branches/'))
if _branch_id:
    check(f'GET /branches/{_branch_id}/settings/', H('GET', f'/branches/{_branch_id}/settings/'), allow=(404,))


# =============================================================================
# TRANSFERS
# =============================================================================
section('TRANSFERS')
r_tr = check('GET /transfers/', H('GET', '/transfers/'))
_tr_id = None
if r_tr and r_tr.status_code == 200:
    d = r_tr.json()
    items = d.get('results', d) if isinstance(d, dict) else d
    if items:
        _tr_id = items[0]['id']
        check(f'GET /transfers/{_tr_id}/', H('GET', f'/transfers/{_tr_id}/'))
        check(f'GET messages', H('GET', f'/transfers/{_tr_id}/messages/'))
        check(f'GET print', H('GET', f'/transfers/{_tr_id}/print/'), allow=(404,))


# =============================================================================
# VOUCHERS
# =============================================================================
section('VOUCHERS')
r_vouch = check('GET /vouchers/vouchers/', H('GET', '/vouchers/vouchers/'))
_vch_code = None
if r_vouch and r_vouch.status_code == 200:
    d = r_vouch.json()
    items = d.get('results', d) if isinstance(d, dict) else d
    if items:
        _vch_id = items[0]['id']
        _vch_code = items[0].get('code', '')
        check(f'GET /vouchers/vouchers/{_vch_id}/', H('GET', f'/vouchers/vouchers/{_vch_id}/'))

r_vcreate = check('POST create voucher', H('POST', '/vouchers/vouchers/', json={
    'title': 'API Test Voucher', 'voucher_type': 'discount_pct',
    'discount_pct': 10, 'branch': _branch_id, 'status': 'active',
    'valid_from': date.today().isoformat(),
}), expect=(201,), allow=(400,))
if r_vcreate and r_vcreate.status_code == 201:
    vdata = r_vcreate.json()
    if 'id' in vdata and 'code' in vdata and vdata['code']:
        print(f'        PASS: id={vdata["id"]} code={vdata["code"]} present in 201 response (Gap-7 fix)')
    else:
        print(f'        FAIL: created voucher missing id/code in response - Gap-7 not fixed')

check('GET lookup invalid code => 404', H('GET', '/vouchers/vouchers/lookup/', params={'code': 'INVALID-XXXX'}), expect=(404,))
check('GET lookup no code => 400', H('GET', '/vouchers/vouchers/lookup/'), expect=(400,))
if _vch_code:
    check(f'GET lookup valid code', H('GET', '/vouchers/vouchers/lookup/', params={'code': _vch_code}))


# =============================================================================
# NOTIFICATIONS
# =============================================================================
section('NOTIFICATIONS')
check('GET /notifications/', H('GET', '/notifications/'))
check('GET unread-count', H('GET', '/notifications/unread-count/'))
check('POST mark-all-read', H('POST', '/notifications/mark-all-read/'))
check('DELETE clear-all', H('DELETE', '/notifications/clear-all/'))
check('GET preferences', H('GET', '/notifications/preferences/'))
check('DELETE delete-old', H('DELETE', '/notifications/delete-old/'), allow=(404,))


# =============================================================================
# USERS & PERMISSIONS
# =============================================================================
section('USERS & PERMISSIONS')
check('GET /users/staff/', H('GET', '/users/staff/'))
check('GET /users/permissions/', H('GET', '/users/permissions/'))


# =============================================================================
# DASHBOARD & SYNC
# =============================================================================
section('DASHBOARD & SYNC')
check('GET /dashboard/summary/', H('GET', '/dashboard/summary/'))
check('GET /dashboard/followups/', H('GET', '/dashboard/followups/'))
check('GET /dashboard/purchasing/', H('GET', '/dashboard/purchasing/'))
check('GET /sync/status/', H('GET', '/sync/status/'))
check('GET /sync/logs/', H('GET', '/sync/logs/'))


# =============================================================================
# CALL CENTER (newly added to client.js)
# =============================================================================
section('CALL CENTER')
check('GET /callcenter/calls/', H('GET', '/callcenter/calls/'))
check('GET lookup', H('GET', '/callcenter/calls/lookup/', params={'phone': '01099990099'}), allow=(404,))
check('GET dashboard', H('GET', '/callcenter/calls/dashboard/'), allow=(404,))
check('GET address-updates', H('GET', '/callcenter/address-updates/'))


# =============================================================================
# AUDIT (newly registered in urls.py)
# =============================================================================
section('AUDIT')
check('GET /audit/logs/', H('GET', '/audit/logs/'))
check('GET /audit/flags/', H('GET', '/audit/flags/'))
check('GET /audit/flags/summary/', H('GET', '/audit/flags/summary/'))
check('POST /audit/flags/run-detection/', H('POST', '/audit/flags/run-detection/', json={'window_hours': 1}))


# =============================================================================
# FOLLOW-UPS (newly added to client.js)
# =============================================================================
section('FOLLOW-UPS')
check('GET /followups/tasks/', H('GET', '/followups/tasks/'))
check('GET /followups/tasks/dashboard/', H('GET', '/followups/tasks/dashboard/'))
check('GET /followups/chronic/', H('GET', '/followups/chronic/'))


# =============================================================================
# DEMAND
# =============================================================================
section('DEMAND')
check('GET /demand/', H('GET', '/demand/'))
check('GET /demand/dashboard/', H('GET', '/demand/dashboard/'))


# =============================================================================
# CHRONIC CLASSIFIER
# =============================================================================
section('CHRONIC CLASSIFIER')
check('GET /chronic/tags/', H('GET', '/chronic/tags/'))
check('GET /chronic/ingredients/', H('GET', '/chronic/ingredients/'))
check('GET /chronic/items/', H('GET', '/chronic/items/'))
check('GET /chronic/items/summary/', H('GET', '/chronic/items/summary/'))


# =============================================================================
# PURCHASING ENGINE
# =============================================================================
section('PURCHASING ENGINE')
check('GET /purchasing/runs/latest/', H('GET', '/purchasing/runs/latest/'), allow=(404,))
check('GET /purchasing/summary/', H('GET', '/purchasing/summary/'))
check('GET /purchasing/metrics/', H('GET', '/purchasing/metrics/'))
check('GET /purchasing/config/', H('GET', '/purchasing/config/'))
check('GET /purchasing/transfer-recs/summary/', H('GET', '/purchasing/transfer-recs/summary/'), allow=(404,))


# =============================================================================
# SHORTAGE & STOCK COUNT
# =============================================================================
section('SHORTAGE & STOCK COUNT')
check('GET /shortage/lists/', H('GET', '/shortage/lists/'))
check('GET /stockcount/sessions/', H('GET', '/stockcount/sessions/'))


# =============================================================================
# DELIVERY & PAYMENTS
# =============================================================================
section('DELIVERY & PAYMENTS')
check('GET /delivery/', H('GET', '/delivery/'))
check('GET /delivery/summary/', H('GET', '/delivery/summary/'))
check('GET /payments/', H('GET', '/payments/'))
check('GET /payments/summary/', H('GET', '/payments/summary/'))


# =============================================================================
# ANALYTICS
# =============================================================================
section('ANALYTICS')
check('GET /analytics/filter-options/', H('GET', '/analytics/filter-options/'))
check('GET /analytics/sales/', H('GET', '/analytics/sales/'))
check('GET /analytics/performance/', H('GET', '/analytics/performance/'))


# =============================================================================
# FINANCE
# =============================================================================
section('FINANCE')
check('GET /finance/dashboard/', H('GET', '/finance/dashboard/'))
check('GET /finance/pnl/', H('GET', '/finance/pnl/'))
check('GET /finance/treasury/', H('GET', '/finance/treasury/'))
check('GET /finance/cash-flow/', H('GET', '/finance/cash-flow/'))
check('GET /finance/expenses/', H('GET', '/finance/expenses/'))
check('GET /finance/schema/', H('GET', '/finance/schema/'))


# =============================================================================
# INVOICES & INCENTIVES
# =============================================================================
section('INVOICES & INCENTIVES')
check('GET /invoices/invoices/', H('GET', '/invoices/invoices/'))
check('GET /invoices/vendors/', H('GET', '/invoices/vendors/'))
check('GET /incentives/programs/', H('GET', '/incentives/programs/'))
check('GET /incentives/rules/', H('GET', '/incentives/rules/'))
check('GET /incentives/transactions/', H('GET', '/incentives/transactions/'))


# =============================================================================
# TASKS
# =============================================================================
section('TASKS')
check('GET /tasks/', H('GET', '/tasks/'))
check('GET /tasks/my/', H('GET', '/tasks/my/'))
check('GET /tasks/dashboard/', H('GET', '/tasks/dashboard/'))
check('GET /tasks/schedules/', H('GET', '/tasks/schedules/'))


# =============================================================================
# CONFIG
# =============================================================================
section('CONFIG')
check('GET /config/settings/', H('GET', '/config/settings/'))
check('GET /config/dropdowns/', H('GET', '/config/dropdowns/'))


# =============================================================================
# SECURITY - ANON ACCESS
# =============================================================================
section('SECURITY - ANON MUST GET 401')
anon_endpoints = [
    '/reservations/', '/customers/', '/transfers/', '/vouchers/vouchers/',
    '/notifications/', '/users/staff/', '/audit/logs/', '/audit/flags/',
    '/followups/tasks/', '/callcenter/calls/', '/demand/', '/purchasing/metrics/',
    '/deliveries/' if False else '/delivery/',
]
for ep in anon_endpoints:
    r = requests.get(f'{BASE}{ep}')
    if r.status_code == 401:
        print(f'  PASS  [401]  anon GET {ep}')
        results['pass'] += 1
    else:
        print(f'  FAIL  [{r.status_code}]  anon GET {ep} should be 401')
        results['fail'] += 1


# =============================================================================
# SECURITY - PERMISSION MATRIX (non-admin must get 403)
# =============================================================================
section('SECURITY - PERMISSIONS MATRIX')
# We are admin, so we should get 200; we verify non-admin gets 403 via test suite


# =============================================================================
# RATE LIMIT GUARD
# =============================================================================
section('RATE LIMIT (login 10/min)')
rl = requests.Session()
hit_429 = False
for i in range(11):
    r = rl.post(f'{BASE}/auth/login/', json={'username': 'nobody_rl_test', 'password': f'bad{i}'})
    if r.status_code == 429:
        print(f'  PASS  [429]  rate-limit fires at attempt {i+1}')
        results['pass'] += 1
        hit_429 = True
        break
if not hit_429:
    print(f'  FAIL  [---]  rate-limit did NOT fire after 11 bad attempts')
    results['fail'] += 1


# =============================================================================
# SUMMARY
# =============================================================================
total = results['pass'] + results['fail']
print(f'\n{"="*70}')
print(f'RESULTS: {results["pass"]} passed  /  {results["fail"]} failed  /  {total} total')
print(f'{"="*70}')
if results['fail'] > 0:
    sys.exit(1)
