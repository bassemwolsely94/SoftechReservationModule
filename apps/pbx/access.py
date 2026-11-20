"""Who may manage the PBX credentials (role review fix round 1, C1 / I1).

One rule for: storing a SIP secret (ExtensionWebRTCView), remapping an extension that carries a
browser-phone credential, the supervisor listen/whisper endpoint, and the /auth/me flag
`can_set_webrtc` that hides the editor. Admin and supervisor, as before.
"""

PBX_MANAGER_ROLES = ('admin', 'supervisor')


def is_pbx_manager(profile) -> bool:
    return bool(profile and profile.is_active and profile.role in PBX_MANAGER_ROLES)
