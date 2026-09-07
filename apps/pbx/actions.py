"""
apps/pbx/actions.py

Synchronous AMI action client — for one-off manager actions issued from
Django views (the async event bridge in ami_bridge.py stays read-only).

Phase 2 (doc 15): supervisor live listen / whisper via Asterisk ChanSpy.

Flow: Originate a call TO the supervisor's own extension; when they answer,
Asterisk runs ChanSpy() on the target agent's channel prefix:
  - listen  → options 'bq'   (spy on bridged channel, quiet)
  - whisper → options 'bqw'  (as above + whisper to the spied channel)

Configuration (.env — same credentials as the event bridge):
  AMI_HOST / AMI_PORT / AMI_USER / AMI_SECRET
  AMI_SPY_CONTEXT   — dialplan context of supervisor extensions
                      (Issabel/FreePBX default: from-internal)
  AMI_CHANNEL_TECH  — SIP or PJSIP (default SIP)
"""
import logging
import socket

from django.conf import settings

logger = logging.getLogger('elrezeiky.pbx')

SPY_MODES = {
    'listen':  'bq',
    'whisper': 'bqw',
}


class AMIActionError(RuntimeError):
    pass


class AMIActionClient:
    """Minimal blocking AMI client: connect → login → action → close."""

    def __init__(self, timeout: float = 8.0):
        self.host    = getattr(settings, 'AMI_HOST', '127.0.0.1')
        self.port    = int(getattr(settings, 'AMI_PORT', 5038))
        self.user    = getattr(settings, 'AMI_USER', '')
        self.secret  = getattr(settings, 'AMI_SECRET', '')
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b''

    # ── Wire helpers ──────────────────────────────────────────────────────────

    def _send(self, fields: dict):
        data = ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n'
        self._sock.sendall(data.encode())

    def _read_block(self) -> dict:
        """Read one AMI block (terminated by CRLF CRLF)."""
        while b'\r\n\r\n' not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise AMIActionError('انقطع اتصال AMI')
            self._buf += chunk
        raw, self._buf = self._buf.split(b'\r\n\r\n', 1)
        block = {}
        for line in raw.decode('utf-8', errors='replace').split('\r\n'):
            if ':' in line:
                k, _, v = line.partition(':')
                block[k.strip()] = v.strip()
        return block

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __enter__(self):
        if not self.user or not self.secret:
            raise AMIActionError('AMI غير مهيأ — راجع AMI_USER / AMI_SECRET في env')
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        # Banner line (e.g. "Asterisk Call Manager/5.0")
        banner = b''
        while not banner.endswith(b'\r\n'):
            chunk = self._sock.recv(1)
            if not chunk:
                raise AMIActionError('لم يصل banner من AMI')
            banner += chunk

        self._send({'Action': 'Login', 'Username': self.user, 'Secret': self.secret})
        resp = self._read_block()
        if resp.get('Response') != 'Success':
            raise AMIActionError(f"فشل تسجيل الدخول إلى AMI: {resp.get('Message', '')}")
        return self

    def __exit__(self, *exc):
        try:
            if self._sock is not None:
                self._send({'Action': 'Logoff'})
                self._sock.close()
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    def action(self, fields: dict) -> dict:
        self._send(fields)
        return self._read_block()


def originate_chanspy(supervisor_ext: str, target_ext: str, mode: str = 'listen') -> dict:
    """
    Ring the supervisor's phone; on answer, run ChanSpy on the agent's channel.
    Returns the AMI response dict. Raises AMIActionError on failure.
    """
    options = SPY_MODES.get(mode)
    if options is None:
        raise AMIActionError(f'وضع مراقبة غير معروف: {mode}')

    tech    = getattr(settings, 'AMI_CHANNEL_TECH', 'SIP')
    context = getattr(settings, 'AMI_SPY_CONTEXT', 'from-internal')
    label   = 'همس' if mode == 'whisper' else 'استماع'

    with AMIActionClient() as client:
        resp = client.action({
            'Action':      'Originate',
            'Channel':     f'{tech}/{supervisor_ext}',
            'Application': 'ChanSpy',
            'Data':        f'{tech}/{target_ext},{options}',
            'CallerID':    f'{label} {target_ext} <{supervisor_ext}>',
            'Context':     context,
            'Async':       'true',
            'Timeout':     '20000',
        })
    if resp.get('Response') != 'Success':
        raise AMIActionError(resp.get('Message', 'فشل تنفيذ المراقبة'))
    logger.info('ChanSpy %s: supervisor ext %s → agent ext %s', mode, supervisor_ext, target_ext)
    return resp
