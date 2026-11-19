"""Platform adapter interface (doc 38). One concrete adapter per platform; nothing here writes to SOFTECH."""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class IncomingLine:
    external_sku: str
    name: str
    qty: Decimal
    unit_price: Decimal
    item_id: int | None = None


@dataclass
class IncomingOrder:
    external_id: str
    external_store_id: str
    customer_name: str
    customer_phone: str
    address: str
    payment_mode: str
    total: Decimal
    lines: list[IncomingLine] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class PlatformAdapter:
    code = ''

    def __init__(self, channel=None):
        self.channel = channel

    def verify_webhook(self, request) -> bool:
        raise NotImplementedError

    def parse_order(self, payload: dict) -> IncomingOrder:
        raise NotImplementedError

    def push_stock(self, store, rows: list) -> dict:
        raise NotImplementedError

    def push_prices(self, store, rows: list) -> dict:
        raise NotImplementedError

    def send_status(self, order, status: str) -> dict:
        raise NotImplementedError
