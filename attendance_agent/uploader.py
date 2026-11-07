"""HTTP calls from the agent to the ERP (`/api/hr-attendance/agent/`).

`send` returns only when the ERP has really accepted the data, because the caller
then deletes its spool file. Anything less raises UploadError, and the file stays.
"""
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

HEADER = 'X-ElR-Attendance-Agent'
TIMEOUT_SECONDS = 60
_PREFIX = '/api/hr-attendance/agent'
_KINDS = frozenset({'punches', 'roster', 'runs'})
_RETRY_LATER_CODES = frozenset({401, 408, 429})


class UploadError(Exception):
    """The ERP didn't accept this. Messages hold a status or class name only.

    `permanent` means the ERP answered and refused this file, so other files may still
    go. Otherwise the ERP or the network is the problem, and sending stops for now.
    """

    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects. urllib would turn a redirected POST into a GET that answers
    200, which looks like an ack, and would carry the secret to the new address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Uploader:
    def __init__(self, base_url, secret):
        scheme = urllib.parse.urlsplit(base_url).scheme
        if scheme not in ('http', 'https'):
            raise ValueError('the ERP address must start with http or https')
        self._base_url = base_url.rstrip('/')
        self._secret = secret
        # An empty ProxyHandler ignores any system proxy: the secret and the punches
        # go directly to the configured address.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
        )

    def get_config(self) -> dict:
        config = self._json_object(self._request('GET', 'config'))
        if not isinstance(config.get('devices'), list):
            raise UploadError('unexpected config answer')
        return config

    def send(self, kind, payload) -> None:
        if kind not in _KINDS:
            raise UploadError('unknown spool entry', permanent=True)
        answer = self._json_object(self._request('POST', kind, payload))
        if kind == 'punches':
            self._check_counts(answer, len(payload['punches']))

    @staticmethod
    def _check_counts(answer, sent):
        accepted, duplicate = answer.get('accepted'), answer.get('duplicate')
        if not isinstance(accepted, int) or not isinstance(duplicate, int):
            raise UploadError('unexpected punches answer', permanent=True)
        if accepted + duplicate != sent:
            raise UploadError(
                f'punch counts do not add up: {accepted} + {duplicate} of {sent}',
                permanent=True,
            )

    @staticmethod
    def _json_object(raw):
        """Only a JSON object counts as an answer. A front-end page or an empty 200
        must not look like an ack, because the file is deleted after one."""
        try:
            answer = json.loads(raw)
        except ValueError:
            raise UploadError('answer is not JSON', permanent=True) from None
        if not isinstance(answer, dict):
            raise UploadError('answer is not a JSON object', permanent=True)
        return answer

    def _request(self, method, endpoint, payload=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        headers = {HEADER: self._secret, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            f'{self._base_url}{_PREFIX}/{endpoint}/',
            data=data, headers=headers, method=method,
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            exc.close()
            permanent = 400 <= exc.code < 500 and exc.code not in _RETRY_LATER_CODES
            raise UploadError(f'HTTP {exc.code}', permanent=permanent) from None
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise UploadError(type(exc).__name__) from None
