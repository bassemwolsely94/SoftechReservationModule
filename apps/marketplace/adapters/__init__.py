"""Adapter registry. Real platforms add one module each and one line here."""
from apps.marketplace.adapters.base import PlatformAdapter
from apps.marketplace.adapters.fake import FakeAdapter
from apps.marketplace.adapters.manual import ManualAdapter

REGISTRY = {ManualAdapter.code: ManualAdapter, FakeAdapter.code: FakeAdapter}


def get_adapter(code: str, channel=None) -> PlatformAdapter:
    return REGISTRY[code](channel)
