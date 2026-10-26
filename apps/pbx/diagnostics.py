"""
apps/pbx/diagnostics.py

Step-by-step PBX connectivity check for the «إعدادات السنترال» tab. Each step
says what failed, the likely cause, and what to do — in Arabic. Steps after a
blocking failure are reported as 'skip' so the first broken link is obvious.
Read-only: Login, Ping, CoreSettings, ModuleCheck only.
"""
import errno
import os
import socket
import time

from django.conf import settings

OK, WARN, FAIL, SKIP = 'ok', 'warn', 'fail', 'skip'


def _step(key, label, status, detail='', hint='', ms=None):
    return {'key': key, 'label': label, 'status': status,
            'detail': detail, 'hint': hint, 'ms': ms}


class _Wire:
    def __init__(self, sock):
        self.sock, self.buf = sock, b''

    def send(self, fields):
        self.sock.sendall((''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode())

    def read(self):
        while b'\r\n\r\n' not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('EOF')
            self.buf += chunk
        raw, self.buf = self.buf.split(b'\r\n\r\n', 1)
        out = {}
        for line in raw.decode('utf-8', errors='replace').split('\r\n'):
            k, sep, v = line.partition(':')
            if sep:
                out[k.strip()] = v.strip()
        return out

    def action(self, fields):
        """Send and return the matching Response block (skip interleaved events)."""
        self.send(fields)
        for _ in range(50):
            block = self.read()
            if 'Response' in block:
                return block
        raise ConnectionError('no response')


def _tcp_failure_hint(exc, host, port):
    if isinstance(exc, socket.timeout):
        return ('انتهت المهلة دون رد',
                f'السيرفر {host} لا يرد على المنفذ {port}: الجهاز مطفأ، أو الشبكة/VPN بين الفرع والسنترال مقطوعة، '
                'أو جدار حماية يحجب المنفذ، أو AMI غير مفعّل على هذا المنفذ. '
                'جرّب ping للسيرفر من جهاز الـ Django: لو ping يعمل فالمشكلة في المنفذ/الجدار الناري.')
    code = getattr(exc, 'errno', None)
    if code in (errno.ECONNREFUSED, 10061):
        return ('رفض الاتصال',
                f'السيرفر يعمل لكن لا شيء يستمع على المنفذ {port}: AMI غير مفعّل في Issabel '
                '(manager.conf → enabled = yes) أو المنفذ مختلف، أو Asterisk متوقف.')
    if code in (errno.EHOSTUNREACH, errno.ENETUNREACH, 10065, 10051):
        return ('لا يوجد مسار للسيرفر', 'عنوان IP خاطئ أو الشبكة غير موصلة بالسيرفر.')
    return (str(exc), 'خطأ شبكة غير متوقع — راجع الاتصال بالسيرفر.')


def run_diagnostics(timeout: float = 5.0) -> dict:
    host = getattr(settings, 'AMI_HOST', '')
    port = int(getattr(settings, 'AMI_PORT', 5038) or 5038)
    user = getattr(settings, 'AMI_USER', '')
    secret = getattr(settings, 'AMI_SECRET', '')
    tech = getattr(settings, 'AMI_CHANNEL_TECH', 'SIP')
    steps = []
    blocked = False

    def add(*a, **kw):
        steps.append(_step(*a, **kw))

    def skip(key, label):
        add(key, label, SKIP, 'تخطّي — فشلت خطوة سابقة')

    # 1. Configuration
    missing = [n for n, v in (('AMI_HOST', host), ('AMI_USER', user), ('AMI_SECRET', secret)) if not v]
    if missing:
        add('config', 'إعدادات الاتصال', FAIL, 'ناقص: ' + '، '.join(missing),
            'أضف القيم الناقصة في ملف .env ثم أعد تشغيل السيرفر وعملية run_ami_bridge.')
        blocked = True
    else:
        add('config', 'إعدادات الاتصال', OK, f'{host}:{port} — مستخدم {user} — تقنية {tech}')

    # 2. DNS
    ip = None
    if blocked:
        skip('dns', 'تحليل عنوان السيرفر')
    else:
        try:
            t = time.monotonic()
            ip = socket.gethostbyname(host)
            add('dns', 'تحليل عنوان السيرفر', OK, ip, ms=int((time.monotonic() - t) * 1000))
        except OSError as exc:
            add('dns', 'تحليل عنوان السيرفر', FAIL, str(exc),
                f'الاسم «{host}» لا يُترجم لعنوان IP — استخدم عنوان IP مباشرة أو صحّح الـ DNS.')
            blocked = True

    # 3–7. TCP → banner → login → ping → version/driver
    sock = None
    wire = None
    for key, label in (('tcp', 'الوصول للمنفذ (شبكة)'), ('banner', 'استجابة Asterisk'),
                       ('login', 'تسجيل الدخول إلى AMI'), ('ping', 'زمن الاستجابة'),
                       ('version', 'إصدار Asterisk'), ('driver', f'تعريف القنوات {tech}')):
        if blocked:
            skip(key, label)
            continue
        try:
            t = time.monotonic()
            if key == 'tcp':
                try:
                    sock = socket.create_connection((ip, port), timeout=timeout)
                    sock.settimeout(timeout)
                    wire = _Wire(sock)
                    add(key, label, OK, f'{ip}:{port} مفتوح', ms=int((time.monotonic() - t) * 1000))
                except OSError as exc:
                    detail, hint = _tcp_failure_hint(exc, host, port)
                    add(key, label, FAIL, detail, hint)
                    blocked = True
            elif key == 'banner':
                banner = b''
                while not banner.endswith(b'\n'):
                    ch = sock.recv(1)
                    if not ch:
                        raise ConnectionError('EOF')
                    banner += ch
                text = banner.decode(errors='replace').strip()
                if 'Asterisk Call Manager' in text:
                    add(key, label, OK, text)
                else:
                    add(key, label, FAIL, text or 'لا شيء',
                        f'المنفذ {port} يرد لكن ليس AMI — غالباً رقم منفذ خاطئ.')
                    blocked = True
            elif key == 'login':
                resp = wire.action({'Action': 'Login', 'Username': user, 'Secret': secret})
                if resp.get('Response') == 'Success':
                    add(key, label, OK, f'تم الدخول كـ {user}')
                else:
                    add(key, label, FAIL, resp.get('Message', 'رُفض'),
                        'اسم المستخدم أو كلمة السر خطأ، أو عنوان IP لسيرفر الـ Django غير مسموح '
                        'في manager.conf (permit=). راجع إعدادات مستخدم AMI في Issabel.')
                    blocked = True
            elif key == 'ping':
                resp = wire.action({'Action': 'Ping'})
                ms = int((time.monotonic() - t) * 1000)
                add(key, label, OK if ms < 500 else WARN, f'{ms} ms',
                    '' if ms < 500 else 'الاستجابة بطيئة — الشبكة مزدحمة أو السيرفر محمّل.', ms=ms)
            elif key == 'version':
                resp = wire.action({'Action': 'CoreSettings'})
                add(key, label, OK, resp.get('AsteriskVersion', '—'))
            elif key == 'driver':
                module = 'chan_pjsip.so' if tech.upper() == 'PJSIP' else 'chan_sip.so'
                resp = wire.action({'Action': 'ModuleCheck', 'Module': module})
                if resp.get('Response') == 'Success':
                    add(key, label, OK, f'{module} محمّل')
                else:
                    add(key, label, WARN, f'{module} غير محمّل',
                        'AMI_CHANNEL_TECH لا يطابق نوع التحويلات في Issabel — '
                        'غيّره إلى SIP أو PJSIP حسب السنترال وإلا سيفشل الاتصال من الشاشة.')
        except (OSError, ConnectionError) as exc:
            add(key, label, FAIL, str(exc) or type(exc).__name__,
                'انقطع الاتصال أثناء الفحص — غالباً عنوان IP غير مسموح في manager.conf أو ضغط على السيرفر.')
            blocked = True

    if sock is not None:
        try:
            wire.send({'Action': 'Logoff'})
            sock.close()
        except OSError:
            pass

    # 8. Bridge process (events → screen-pop / call logs)
    steps.append(_bridge_step())

    # 9. Dial context + recordings
    ctx = getattr(settings, 'AMI_DIAL_CONTEXT', '') or getattr(settings, 'AMI_SPY_CONTEXT', '')
    steps.append(_step('dial', 'سياق الاتصال الصادر', OK if ctx else WARN,
                       ctx or 'from-internal (افتراضي)',
                       '' if ctx else 'لم يُضبط AMI_DIAL_CONTEXT — يُستخدم from-internal؛ تأكد أنه يسمح بالخطوط الخارجية.'))
    steps.append(_recordings_step())

    worst = FAIL if any(s['status'] == FAIL for s in steps) else (
        WARN if any(s['status'] == WARN for s in steps) else OK)
    return {'overall': worst, 'steps': steps}


def _bridge_step():
    from django.utils import timezone
    from apps.pbx.models import PBXBridgeStatus

    label = 'عملية استقبال الأحداث (run_ami_bridge)'
    st = PBXBridgeStatus.current()
    if st is None:
        return _step('bridge', label, FAIL, 'لم تعمل أبداً',
                     'شغّل الأمر: python manage.py run_ami_bridge كخدمة دائمة — بدونه لا تظهر المكالمات الواردة ولا تُسجَّل.')
    if st.state == 'auth_failed':
        return _step('bridge', label, FAIL, st.last_error, 'العملية تعمل لكن كلمة سر AMI مرفوضة — صحّح AMI_SECRET وأعد تشغيلها.')
    if st.state == 'not_configured':
        return _step('bridge', label, FAIL, st.last_error, 'أكمل إعدادات AMI في .env وأعد تشغيل العملية.')
    if not st.is_alive:
        age = int((timezone.now() - st.last_heartbeat_at).total_seconds() / 60) if st.last_heartbeat_at else None
        return _step('bridge', label, FAIL,
                     f'آخر نبضة منذ {age} دقيقة' if age is not None else 'لا توجد نبضات',
                     'العملية متوقفة أو معلّقة — أعد تشغيل run_ami_bridge وراجع سجلها. '
                     + (f'آخر خطأ: {st.last_error}' if st.last_error else ''))
    return _step('bridge', label, OK,
                 f'متصل منذ {timezone.localtime(st.connected_since):%Y-%m-%d %H:%M}'
                 + (f' — أعاد الاتصال {st.reconnect_count} مرة' if st.reconnect_count else ''))


def _recordings_step():
    """CDR (which file) + SFTP (can we read it) when configured; else mount / URL."""
    from apps.pbx import recordings
    from config.issabel import cdr_configured, get_cdr_connection

    label = 'الوصول لتسجيلات المكالمات'
    if recordings.sftp_configured():
        rel = ''
        if cdr_configured():
            try:
                conn = get_cdr_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT calldate, recordingfile FROM cdr WHERE recordingfile <> '' "
                                "AND disposition = 'ANSWERED' ORDER BY calldate DESC LIMIT 1")
                    row = cur.fetchone()
                conn.close()
                rel = recordings.relative_path(row['recordingfile'], row['calldate']) if row else ''
            except Exception as exc:
                return _step('recordings', label, WARN, f'CDR: {exc}',
                             'تعذر قراءة قاعدة CDR — راجع ISSABEL_CDR_USER / PASSWORD وأن المنفذ 3306 مسموح.')
        try:
            client = recordings._sftp_connect()
            try:
                sftp = client.open_sftp()
                root = recordings._root()
                sftp.listdir(root)
                if rel:
                    size = sftp.stat(f'{root}/{rel}').st_size
                    return _step('recordings', label, OK, f'SFTP: آخر تسجيل مقروء ({size // 1024} KB) — {rel}')
                return _step('recordings', label, OK, f'SFTP: المجلد {root} مقروء')
            finally:
                client.close()
        except FileNotFoundError:
            return _step('recordings', label, WARN, f'الملف غير موجود: {rel}',
                         'المسار في CDR لا يطابق المجلد — راجع PBX_RECORDINGS_ROOT.')
        except PermissionError:
            return _step('recordings', label, FAIL, 'لا صلاحية قراءة',
                         'مستخدم SFTP لا يملك صلاحية القراءة على مجلد monitor — أضفه لمجموعة asterisk.')
        except Exception as exc:
            return _step('recordings', label, FAIL, f'SFTP: {type(exc).__name__}: {exc}',
                         'تعذر الدخول عبر SFTP — راجع PBX_RECORDINGS_SFTP_USER / PASSWORD وأن المنفذ 22 مفتوح.')

    local = getattr(settings, 'PBX_RECORDINGS_DIR', '')
    remote = getattr(settings, 'PBX_RECORDINGS_URL_BASE', '')
    if local:
        if os.path.isdir(local) and os.access(local, os.R_OK):
            return _step('recordings', label, OK, f'مجلد: {local}')
        return _step('recordings', label, WARN, f'المجلد غير متاح: {local}',
                     'تأكد من ربط مجلد monitor الخاص بـ Asterisk على هذا السيرفر.')
    if remote:
        try:
            import requests
            r = requests.head(remote, timeout=5)
            ok = r.status_code < 500
            return _step('recordings', label, OK if ok else WARN, f'{remote} → HTTP {r.status_code}')
        except Exception as exc:
            return _step('recordings', label, WARN, str(exc),
                         'رابط التسجيلات لا يرد — لن يعمل التفريغ والاستماع للتسجيلات.')
    return _step('recordings', label, WARN, 'غير مضبوط',
                 'اضبط PBX_RECORDINGS_SFTP_HOST / USER / PASSWORD (موصى به) لتفعيل الاستماع والتفريغ.')
