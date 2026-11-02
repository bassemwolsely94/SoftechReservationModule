"""
core/safe_fetch.py — fetch a URL that someone other than us chose (security Batch 6, W-6).

A call's recording URL is editable by the call centre, a PBX webhook names its own, and image
candidates come from web search. Fetching such a URL from the server must not reach what only
the server can reach: 127.0.0.1, the LAN, the cloud metadata address, or local files.

  • http / https only;
  • every address the host resolves to must be public — except hosts the caller names in
    `allow_hosts` (the PBX configured by admins in PBX_RECORDINGS_URL_BASE may sit on the LAN);
  • redirects are followed by hand, at most MAX_REDIRECTS, and every hop is checked again;
  • the body is streamed and the fetch fails once it passes `max_bytes`.

Residual risk: the host is resolved again when requests connects, so a DNS answer that changes
between the check and the connection (rebinding) is not covered.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 3


class UnsafeURL(ValueError):
    """The URL is refused (scheme, address, redirect or size)."""


def _public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split('%')[0])
    if getattr(addr, 'ipv4_mapped', None):
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def check_url(url: str, allow_hosts=()) -> None:
    """Raise UnsafeURL unless `url` is http(s) to a public host (or an allowed host)."""
    parts = urlsplit(url or '')
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise UnsafeURL(f'scheme not allowed: {parts.scheme or "-"}')
    host = parts.hostname.lower()
    if host in {h.lower() for h in allow_hosts if h}:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80),
                                   proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnsafeURL(f'cannot resolve {host}') from exc
    if not infos or not all(_public(info[4][0]) for info in infos):
        raise UnsafeURL(f'not a public address: {host}')


def fetch(url: str, *, max_bytes: int, timeout: float = 20, headers=None,
          allow_hosts=()) -> tuple[bytes, str]:
    """(body, content-type without parameters) — raises UnsafeURL or the requests error."""
    import requests

    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, allow_hosts)
        resp = requests.get(url, headers=headers or {}, timeout=timeout, stream=True, allow_redirects=False)
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get('Location')
                if not location:
                    raise UnsafeURL('redirect without a location')
                url = urljoin(url, location)
                continue
            resp.raise_for_status()
            declared = resp.headers.get('Content-Length')
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise UnsafeURL(f'too large: {declared} bytes')
            body, size = [], 0
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > max_bytes:
                    raise UnsafeURL(f'too large: over {max_bytes} bytes')
                body.append(chunk)
            ctype = (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            return b''.join(body), ctype
        finally:
            resp.close()
    raise UnsafeURL('too many redirects')


def configured_host(setting_value: str) -> tuple[str, ...]:
    """The host of an admin-configured base URL, for `allow_hosts` ('' → none)."""
    host = urlsplit(setting_value or '').hostname
    return (host,) if host else ()
