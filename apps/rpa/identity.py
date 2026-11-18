"""Which SOFTECH usercode a staff profile types as."""


def expected_softech_usercode(profile):
    """Approved salesperson identity first, else the profile's own SOFTECH user id/name, else None."""
    ident = (profile.softech_identities
             .filter(kind='salesperson', status='approved').order_by('-reviewed_at', '-id').first())
    if ident is not None and (ident.person_code or '').strip():
        return ident.person_code.strip()
    return (profile.softech_user_id or '').strip() or (profile.softech_username or '').strip() or None
