"""
apps/hr/attendance/agent_auth.py — how the office agent signs in.

Agents have no staff login and don't use the JWT flow. Each sends its own secret in a header. Only
the secret's SHA-256 is stored, it is compared in constant time, and revoking an agent ends access.
A valid secret opens only the views that use these classes, never a staff endpoint.
"""
import hashlib
import hmac
import secrets

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.hr.models import AttendanceAgent

HEADER = 'X-ElR-Attendance-Agent'
_META_KEY = 'HTTP_X_ELR_ATTENDANCE_AGENT'


def _as_bytes(value) -> bytes:
    # bytes, so a non-ASCII header can never make the hash or compare_digest raise
    return str(value).encode('utf-8', 'surrogateescape')


def hash_secret(secret) -> str:
    return hashlib.sha256(_as_bytes(secret)).hexdigest()


def agent_for_secret(secret):
    """The active agent holding this secret, or None."""
    if not secret:
        return None
    # The lookup is on the hash, never the secret, so its timing tells nothing about the secret.
    digest = hash_secret(secret)
    agent = AttendanceAgent.objects.filter(token_hash=digest, revoked_at__isnull=True).first()
    if agent is None or not hmac.compare_digest(_as_bytes(agent.token_hash), _as_bytes(digest)):
        return None
    return agent


def issue_agent(name, created_by=None):
    """Create an agent. Returns (agent, secret); the secret can't be read back later."""
    secret = secrets.token_urlsafe(32)
    agent = AttendanceAgent.objects.create(name=name, token_hash=hash_secret(secret), created_by=created_by)
    return agent, secret


class AgentSecretAuthentication(BaseAuthentication):
    """Sets request.auth to the AttendanceAgent. request.user stays anonymous: an agent is not staff."""

    def authenticate(self, request):
        sent = request.META.get(_META_KEY)
        if not sent:
            return None
        agent = agent_for_secret(sent)
        if agent is None:
            raise AuthenticationFailed('غير مصرح')
        return AnonymousUser(), agent

    def authenticate_header(self, request):
        return HEADER   # makes a missing secret a 401, not a 403


class HasAgentSecret(BasePermission):

    def has_permission(self, request, view):
        return isinstance(request.auth, AttendanceAgent)
