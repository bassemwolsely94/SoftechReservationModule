"""
apps/tests/security/permission_matrix.py

Renders docs/security/PERMISSION_MATRIX.md — the reviewable role × module × action × branch
scope matrix — from the code that enforces it:

  • actions per role: seed_permissions.PERMISSIONS (owner decision 1: the code matrix is truth);
  • branch scope per module: BRANCH_SCOPE below, which states what the views do since Batch 5.

test_permission_matrix.py fails when the document and the code drift apart; regenerate with
    venv/Scripts/python.exe manage.py shell -c "from apps.tests.security.permission_matrix import write; write()"
"""
from pathlib import Path

from apps.users.management.commands.seed_permissions import ALL_ACTIONS, ALL_MODULES, PERMISSIONS
from apps.users.models import ROLE_CHOICES
from core.branch_scope import ALL_BRANCH_ROLES

DOC = Path(__file__).resolve().parents[3] / 'docs' / 'security' / 'PERMISSION_MATRIX.md'

LETTER = {'view': 'V', 'create': 'C', 'edit': 'E', 'delete': 'D', 'approve': 'A',
          'export': 'X', 'assign': 'S', 'finalize': 'F'}

# What the API does with a branch-scoped user (not in ALL_BRANCH_ROLES, no access_all_branches).
# own  = own branches only (home + allowed − restricted), enforced in list, detail, actions and
#        create (core.branch_scope) — covered by test_branch_isolation.py / _part2.py
# role = the module's own hard-coded role rule (older code, fail-closed), not yet on branch_scope
# all  = chain-wide by design (owner decision 3: stock and transfer screens) or no branch field
# open = NOT branch-scoped today; listed with the pending decision or later batch that owns it
BRANCH_SCOPE = {
    'pos':          'own — orders, actions, queue, exceptions, flush, referral stats',
    'reservations': 'own — list, detail, activity, merge target, dashboard, analytics',
    'delivery':     'own (+ rider: orders assigned to them)',
    'demand':       'own — list, detail, actions, create (branch_scope); analytics pages network-wide (open)',
    'transfers':    'own side — requesting OR supplying (decision 3) via branch_scope; workflow sides stay home-branch / HQ lists; create + edit own requesting side',
    'followups':    'own — tasks, dashboard (?branch narrows), generate, reminders (branch_scope)',
    'customers':    'find any by full phone (masked), browse / name-search / edit / churn list own (B-2)',
    'chronic':      'all — catalogue data',
    'campaigns':    'all — HQ module',
    'vouchers':     'all — chain-wide redemption',
    'catalog':      'all — stock is readable network-wide (decision 3); batches, expiry alerts, expiry reports, disposals and expiry count sessions own (part 2); rebalance suggestions all',
    'stockcount':   'own — sessions by SOFTECH branch code (scope_code); create / spawn own only',
    'shortage':     'own — lists, items, exports, aggregate; stock-check shows other branches (transfers)',
    'purchasing':   'all — HQ module; supply cases / decisions own + network (viewer role)',
    'invoices':     'open — HQ module; branch roles have no grant',
    'incentives':   'open — all-branch roles only hold it; sales targets (analytics view) own branch',
    'cheques':      'own — plans, instalments, treasury dashboard',
    'finance':      'own branch rows only; consolidated + supplier A/P = all-branch roles (B-1); payments own',
    'callcenter':   'own — calls, cases (+ assigned to me), dashboards, converts; omni inbox own + assigned (branch_scope)',
    'hr':           'role — own records; managers see all',
    'approvals':    'n/a — scoped by requester / approver',
    'analytics':    'own — sales, performance, customers, churn, inventory; cross-branch P&L / capital boards all-branch roles (B-1); customer search B-2',
    'dashboard':    'own — reservation + sales KPIs (?branch only narrows)',
    'audit':        'all — HQ module',
    'sync':         'all — HQ module',
    'settings':     'all — HQ module',
    'users':        'all — HQ module',
    'admin':        'all — HQ module',
    'commerce':     'all — no branch field (feature-flag gated)',
    'offers':       'all — offers are chain config; apply-to-order and evaluate own (part 2)',
    'insurance':    'open — softech branch code only; HQ claims module (later batch)',
    'replacement':  'own — scoped_cases + authz.require (accessible_branch_ids = branch_scope)',
    'stock_audit':  'own — named branch managers see their branches (branch_scope); management all',
    'gamification': 'n/a — own data; rankings are network-wide by design',
    'help':         'n/a — no branch data',
    'tasks':        'own + «جميع الفروع» + created / assigned to me; all-branch schedules read-only for branch roles',
}


def _cell(role, module):
    if role == 'admin':
        return 'all'
    acts = PERMISSIONS.get(role, {}).get(module, set())
    return ''.join(LETTER[a] for a in ALL_ACTIONS if a in acts) or '—'


def render() -> str:
    roles = [r for r, _ in ROLE_CHOICES]
    out = [
        '# Permission matrix — role × module × action × branch scope',
        '',
        'Generated by `apps/tests/security/permission_matrix.py` from `seed_permissions.PERMISSIONS`',
        '(the owner\'s source of truth) and the branch-scope table in that file. Do not edit by hand —',
        '`test_permission_matrix` fails when this file and the code differ.',
        '',
        'Actions: ' + ' · '.join(f'**{LETTER[a]}** {a}' for a in ALL_ACTIONS) + '. `all` = admin.',
        '',
        '## Branch scope',
        '',
        f'All-branch roles: {", ".join(ALL_BRANCH_ROLES)} — and anyone with `access_all_branches`. '
        'Everyone else sees their home branch plus `allowed_branches`. A `restricted_branches` entry '
        'always wins, even over all-branch roles. A branch role with no branch, an inactive account '
        'or a user without a staff profile sees nothing (`core/branch_scope.py`, owner decision 3).',
        '',
        '## Matrix',
        '',
        '| module | ' + ' | '.join(roles) + ' | branch scope for branch roles |',
        '|---|' + '---|' * len(roles) + '---|',
    ]
    for module in ALL_MODULES:
        cells = ' | '.join(_cell(r, module) for r in roles)
        out.append(f'| `{module}` | {cells} | {BRANCH_SCOPE.get(module, "open — not reviewed")} |')
    out += [
        '',
        '## Record-state and separation-of-duty rules enforced on the server',
        '',
        '- Approvals engine refuses a requester\'s own approval (Z-11; `test_approvals_self_approval`).',
        '- POS order: locked once pushed — no edit / delete; push and cancel need the push grant (Z-5b, Z-10).',
        '- Payments: editable only while pending / disputed; only pending can be deleted; status moves only by confirm / reconcile / dispute (Z-10a).',
        '- Cheque plan: edit only in draft; delete only draft / cancelled.',
        '- Supplier invoice: an edit to a confirmed invoice sends it back to review (Z-11).',
        '- Delivery: a rider acts only on orders assigned to them; value fields close once out for delivery (Z-10a).',
        '- Workflow-only fields (status, approvers, SOFTECH doc refs, amounts) are read-only or server-set (Z-10).',
        '- Every SOFTECH write: switch default off, dry-run default, idempotency / lock, AuditLog (Batch 2, `softech_write_manifest.py`).',
        '',
        '## Open decisions',
        '',
        'B-1 finance, B-2 customers, B-3 supervisor / quality_manager: decided 2026-10-30 (`PENDING.md`). New ones go there.',
        '',
    ]
    return '\n'.join(out)


def write():
    DOC.write_text(render(), encoding='utf-8')
