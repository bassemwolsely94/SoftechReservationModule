"""
apps/omni/providers — messaging provider abstraction (doc 15 §2.2).

WhatsApp (and future channels) send through a provider resolved per
ChannelAccount, so numbers can migrate between providers (Meta Cloud API,
BSPs, …) without touching ERP logic.

    from apps.omni.providers import get_provider
    provider = get_provider(account)          # account may be None → env-configured default
    provider.send_message(payload)            # Meta Cloud message format
"""
from apps.omni.providers.base import BaseProvider, ProviderError
from apps.omni.providers.meta_cloud import MetaCloudProvider
from apps.omni.providers.meta_graph import MetaGraphProvider
from apps.omni.providers.stubs import (
    AndroidBridgeProvider, Dialog360Provider, TwilioProvider,
)
from apps.omni.providers.telegram_bot import TelegramBotProvider

_REGISTRY = {
    'meta_cloud':     MetaCloudProvider,
    'd360':           Dialog360Provider,
    'twilio':         TwilioProvider,
    'android_bridge': AndroidBridgeProvider,
    'meta_graph':     MetaGraphProvider,
    'telegram_bot':   TelegramBotProvider,
}


def get_provider(account=None) -> BaseProvider:
    """
    Resolve the provider for a ChannelAccount.
    account=None → MetaCloudProvider on env credentials (legacy default).
    """
    if account is None:
        return MetaCloudProvider(account=None)
    cls = _REGISTRY.get(account.provider)
    if cls is None:
        raise ProviderError(f'مزوّد غير مدعوم: {account.provider}')
    return cls(account=account)
