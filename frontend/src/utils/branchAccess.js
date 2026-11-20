// Who may pick ANY branch on a create form or branch filter (role review, owner decision 4).
// The server decides (core/branch_scope.check_branch_value); this only decides whether to show
// the picker. Admin, or can_pick_any_branch on /auth/me — computed by the server from the same
// core.branch_scope rule (all-branch role or the all-branches flag).
export function canPickAnyBranch(user) {
  return !!user && (user.role === 'admin' || !!user.can_pick_any_branch)
}
