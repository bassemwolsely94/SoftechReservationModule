"""
apps/pbx/recordings.py

Call-recording resolution + tokenized playback URLs (doc 15 Phase 2).

Browsers' <audio> tags cannot send the JWT Authorization header, so playback
URLs carry a short-lived signed token instead (django.core.signing) — the
recording view validates it without authentication.
"""
import os

from django.conf import settings
from django.core import signing

_SALT = 'pbx-recording'
TOKEN_MAX_AGE = 3600  # seconds


def session_has_recording(session) -> bool:
    return bool(session and (session.recording_url or session.recording_path))


def signed_recording_url(session_pk: int) -> str:
    """Relative playback URL with a 1-hour signed token."""
    token = signing.dumps(session_pk, salt=_SALT)
    return f'/api/pbx/recordings/{session_pk}/?t={token}'


def validate_recording_token(session_pk: int, token: str) -> bool:
    try:
        return signing.loads(token, salt=_SALT, max_age=TOKEN_MAX_AGE) == session_pk
    except signing.BadSignature:
        return False


def resolve_local_path(session) -> str:
    """
    Absolute local path of the recording when PBX_RECORDINGS_DIR is a mount
    of the Asterisk monitor directory. '' when unavailable.
    Only the basename is used — no path traversal from stored values.
    """
    base = getattr(settings, 'PBX_RECORDINGS_DIR', '')
    if not base or not session.recording_path:
        return ''
    path = os.path.join(base, os.path.basename(session.recording_path))
    return path if os.path.isfile(path) else ''


def resolve_remote_url(session) -> str:
    """HTTP URL of the recording (explicit URL, or Issabel-served base)."""
    if session.recording_url:
        return session.recording_url
    base = getattr(settings, 'PBX_RECORDINGS_URL_BASE', '')
    if base and session.recording_path:
        return f"{base.rstrip('/')}/{os.path.basename(session.recording_path)}"
    return ''
