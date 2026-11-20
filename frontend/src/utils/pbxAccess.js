// Who may store a SIP secret / remap a credentialed extension: the server's PBX-manager rule,
// exposed on /auth/me as can_set_webrtc (apps/pbx/access.py). Hides the editor; the server decides.
export function canSetWebrtc(user) {
  return !!user && !!user.can_set_webrtc
}
