// Admin «إعادة ضبط المصادقة الثنائية» on /users (UAT 2026-11-21). The server decides
// (POST /api/users/<id>/reset-2fa/ is admin-only and refuses the admin's own account); this only
// says when the button is worth showing: an admin, looking at someone else, who has 2FA on.
export function canResetMfa(currentUser, row) {
  if (!currentUser || !row) return false
  if (currentUser.role !== 'admin') return false
  if (!row.mfa_enabled) return false
  return row.id !== currentUser.id
}
