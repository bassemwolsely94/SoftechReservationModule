"""
apps/omni/providers/base.py
"""


class ProviderError(RuntimeError):
    """Raised when a provider is unconfigured, unsupported, or rejects a send."""


class BaseProvider:
    """
    Messaging provider contract.

    Providers speak the Meta Cloud API message format (the de-facto standard
    also used by BSPs like 360dialog). A provider with a different wire format
    translates internally.
    """

    def __init__(self, account=None):
        self.account = account  # omni.ChannelAccount or None (env default)

    @property
    def configured(self) -> bool:
        """Whether this provider has the credentials it needs to send."""
        return True

    def send_message(self, payload: dict) -> dict:
        """Send one message payload; returns the provider response dict."""
        raise NotImplementedError

    def health(self) -> dict:
        """
        Best-effort provider-side health probe.
        Returns {'ok': bool, 'detail': str, ...} — must never raise.
        """
        return {'ok': False, 'detail': 'not implemented'}
