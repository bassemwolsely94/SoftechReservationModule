"""
Password rules (Batch 3, A-5; owner decision 2026-10-27: 10 characters plus Django's checks).
"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def password_problem(password, user=None) -> str:
    """Why `password` is refused, as one line (Arabic — LANGUAGE_CODE), or '' when it is fine.
    settings.AUTH_PASSWORD_VALIDATORS: 10+ characters, not a common password, not digits only,
    not close to the username / name / email."""
    try:
        validate_password(password, user)
    except ValidationError as e:
        return ' '.join(e.messages)
    return ''
