"""
apps/pbx/recordings.py

Call-recording resolution + tokenized playback URLs (doc 15 Phase 2).

Issabel keeps recordings in date folders under the monitor root:
  /var/spool/asterisk/monitor/2026/10/12/exten-160-153-20261012-100632-<uniqueid>.wav
and the CDR `recordingfile` column holds either that full path or just the
file name (the date folder is then rebuilt from calldate). We store the path
RELATIVE to the root ('2026/10/12/exten-….wav') and refuse anything that
escapes it.

Audio sources, in order: local mount (PBX_RECORDINGS_DIR) → SFTP (read-only
single-file download) → HTTP (PBX_RECORDINGS_URL_BASE).

Browsers' <audio> tags cannot send the JWT Authorization header, so playback
URLs carry a short-lived signed token instead (django.core.signing).
"""
import io
import logging
import mimetypes
import os
import posixpath

from django.conf import settings
from django.core import signing

logger = logging.getLogger('elrezeiky.pbx')

_SALT = 'pbx-recording'
TOKEN_MAX_AGE = 3600  # seconds
MAX_AUDIO_BYTES = 60 * 1024 * 1024


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


# ── Paths ─────────────────────────────────────────────────────────────────────

def _root() -> str:
    return getattr(settings, 'PBX_RECORDINGS_ROOT', '/var/spool/asterisk/monitor').rstrip('/')


def relative_path(stored: str, calldate=None) -> str:
    """
    Normalise a stored/CDR recording value to 'YYYY/MM/DD/file.wav' under the
    monitor root. '' if empty or unsafe.
    """
    p = (stored or '').strip().replace('\\', '/')
    if not p:
        return ''
    root = _root() + '/'
    bare_name = '/' not in p
    if p.startswith(root):
        p = p[len(root):]
    elif p.startswith('/'):
        p = posixpath.basename(p)            # absolute path outside the root: keep the name only
    if bare_name and calldate is not None:
        p = f'{calldate:%Y/%m/%d}/{p}'       # CDR gave only the file name
    norm = posixpath.normpath(p)
    if norm.startswith('..') or norm.startswith('/') or '/../' in f'/{norm}/':
        return ''
    return norm


def _session_relative(session) -> str:
    return relative_path(session.recording_path, getattr(session, 'started_at', None))


def resolve_local_path(session) -> str:
    """Absolute local path when PBX_RECORDINGS_DIR mounts the monitor root, '' otherwise."""
    base = getattr(settings, 'PBX_RECORDINGS_DIR', '')
    rel = _session_relative(session) if session.recording_path else ''
    if not base or not rel:
        return ''
    for candidate in (os.path.join(base, *rel.split('/')), os.path.join(base, posixpath.basename(rel))):
        if os.path.isfile(candidate):
            return candidate
    return ''


def resolve_remote_url(session) -> str:
    """HTTP URL of the recording (explicit URL, or Issabel-served base)."""
    if session.recording_url:
        return session.recording_url
    base = getattr(settings, 'PBX_RECORDINGS_URL_BASE', '')
    rel = _session_relative(session) if session.recording_path else ''
    if base and rel:
        return f"{base.rstrip('/')}/{rel}"
    return ''


# ── CDR lookup (Issabel MySQL, read-only) ─────────────────────────────────────

def lookup_cdr_recording(unique_id: str) -> str:
    """Relative recording path for an Asterisk uniqueid from the CDR, '' if none."""
    from config.issabel import cdr_configured, get_cdr_connection
    if not unique_id or not cdr_configured():
        return ''
    from decouple import config
    table = config('ISSABEL_CDR_TABLE', default='cdr')
    conn = get_cdr_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT calldate, recordingfile FROM {table} "
                        f"WHERE uniqueid = %s AND recordingfile <> '' "
                        f"ORDER BY billsec DESC LIMIT 1", (unique_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return relative_path(row['recordingfile'], row['calldate']) if row else ''


def ensure_recording(session) -> bool:
    """Fill session.recording_path from the CDR when the bridge didn't capture it."""
    if session is None or session.recording_path or session.recording_url:
        return session_has_recording(session)
    try:
        rel = lookup_cdr_recording(session.unique_id)
    except Exception as exc:
        logger.warning('recordings: CDR lookup failed for %s: %s', session.unique_id, exc)
        return False
    if rel:
        type(session).objects.filter(pk=session.pk).update(recording_path=rel)
        session.recording_path = rel
        return True
    return False


# ── SFTP (read-only, single file) ─────────────────────────────────────────────

def sftp_configured() -> bool:
    return bool(getattr(settings, 'PBX_RECORDINGS_SFTP_HOST', '') and
                getattr(settings, 'PBX_RECORDINGS_SFTP_USER', '') and
                (getattr(settings, 'PBX_RECORDINGS_SFTP_PASSWORD', '') or
                 getattr(settings, 'PBX_RECORDINGS_SFTP_KEY_FILE', '')))


def _sftp_connect():
    import paramiko
    client = paramiko.SSHClient()
    # Trust on first use, then pin: a changed host key raises BadHostKeyException
    known = os.path.join(str(settings.BASE_DIR), '.pbx_known_hosts')
    if os.path.exists(known):
        client.load_host_keys(known)
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        settings.PBX_RECORDINGS_SFTP_HOST, port=settings.PBX_RECORDINGS_SFTP_PORT,
        username=settings.PBX_RECORDINGS_SFTP_USER,
        password=settings.PBX_RECORDINGS_SFTP_PASSWORD or None,
        key_filename=settings.PBX_RECORDINGS_SFTP_KEY_FILE or None,
        timeout=10, banner_timeout=10, auth_timeout=10,
        look_for_keys=False, allow_agent=False)
    try:
        client.save_host_keys(known)
    except OSError:
        pass
    return client


def fetch_sftp(rel: str) -> bytes | None:
    """Download one recording by relative path. None when missing."""
    if not rel or not sftp_configured():
        return None
    client = _sftp_connect()
    try:
        sftp = client.open_sftp()
        remote = f'{_root()}/{rel}'
        size = sftp.stat(remote).st_size
        if size > MAX_AUDIO_BYTES:
            raise ValueError(f'recording too large ({size} bytes)')
        buf = io.BytesIO()
        sftp.getfo(remote, buf)
        return buf.getvalue()
    except FileNotFoundError:
        return None
    finally:
        client.close()


def load_session_audio(session) -> tuple[bytes | None, str]:
    """Audio bytes + mime for a session from the best available source."""
    ensure_recording(session)
    local = resolve_local_path(session)
    if local:
        with open(local, 'rb') as f:
            return f.read(), mimetypes.guess_type(local)[0] or 'audio/wav'

    rel = _session_relative(session) if session.recording_path else ''
    if rel and sftp_configured():
        try:
            data = fetch_sftp(rel)
            if data:
                return data, mimetypes.guess_type(rel)[0] or 'audio/wav'
        except Exception as exc:
            logger.warning('recordings: SFTP fetch failed for %s: %s', rel, exc)

    remote = resolve_remote_url(session)
    if remote:
        try:
            import requests
            resp = requests.get(remote, timeout=30)
            resp.raise_for_status()
            mime = resp.headers.get('Content-Type', '') or mimetypes.guess_type(remote)[0] or 'audio/wav'
            return resp.content, mime.split(';')[0]
        except Exception as exc:
            logger.warning('recordings: HTTP fetch failed for %s: %s', remote, exc)
    return None, ''
