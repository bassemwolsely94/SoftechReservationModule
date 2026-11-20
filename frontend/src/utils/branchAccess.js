// Who may pick ANY branch on a create form or branch filter (role review, owner decision 4).
// The server decides (core/branch_scope.check_branch_value); this only decides whether to show
// the picker. Admin, or a user flagged "all branches" (access_all_branches on /auth/me).
export function canPickAnyBranch(user) {
  return !!user && (user.role === 'admin' || !!user.access_all_branches)
}
