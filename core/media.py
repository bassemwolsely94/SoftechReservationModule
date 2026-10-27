"""
GET /media/<path> — serves uploads, enforcing the signature added by
core.storage.SignedMediaStorage (public prefixes excepted).

Production (Nginx): set MEDIA_ACCEL_REDIRECT=True and the file itself is sent by
Nginx through the internal /protected-media/ location (X-Accel-Redirect) — Django
only checks the signature. Without it (Windows / dev) Django streams the file.

Script-capable types (HTML/SVG/XML/JS) are always sent as a sandboxed download so
an uploaded file can never run script on our origin.
"""
import mimetypes
import posixpath
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_GET

from .storage import is_public_media, verify_media_signature

_SCRIPT_CAPABLE = ('.html', '.htm', '.xhtml', '.svg', '.svgz', '.xml', '.js', '.mjs')


def _clean(path: str) -> str | None:
    norm = posixpath.normpath('/' + path.replace('\\', '/')).lstrip('/')
    if not norm or norm.startswith('..') or '\x00' in norm:
        return None
    return norm


@require_GET
def serve_media(request, path):
    name = _clean(path)
    if name is None:
        raise Http404
    if not is_public_media(name) and not verify_media_signature(
            name, request.GET.get('exp'), request.GET.get('sig')):
        return HttpResponseForbidden('رابط الملف غير صالح أو منتهي الصلاحية')

    root = Path(settings.MEDIA_ROOT).resolve()
    full = (root / name).resolve()
    if root not in full.parents or not full.is_file():
        raise Http404

    if getattr(settings, 'MEDIA_ACCEL_REDIRECT', False):
        resp = HttpResponse()
        resp['X-Accel-Redirect'] = '/protected-media/' + name
        resp['Content-Type'] = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    else:
        resp = FileResponse(open(full, 'rb'))

    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Cache-Control'] = 'public, max-age=604800' if is_public_media(name) else 'private, max-age=3600'
    if name.lower().endswith(_SCRIPT_CAPABLE):
        resp['Content-Security-Policy'] = 'sandbox'
        resp['Content-Disposition'] = f'attachment; filename="{posixpath.basename(name)}"'
    return resp
