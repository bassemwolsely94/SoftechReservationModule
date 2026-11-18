"""Manual adapter: staff key orders in by hand; nothing is ever sent to a platform."""
from decimal import Decimal

from apps.marketplace.adapters.base import IncomingLine, IncomingOrder, PlatformAdapter


class ManualAdapter(PlatformAdapter):
    code = 'manual'

    def verify_webhook(self, request) -> bool:
        return False

    def parse_order(self, payload: dict) -> IncomingOrder:
        lines = [IncomingLine(external_sku=str(l.get('external_sku', '')), name=l.get('name', ''),
                              qty=Decimal(str(l.get('qty', 1))), unit_price=Decimal(str(l.get('unit_price', 0))),
                              item_id=l.get('item_id'))
                 for l in payload.get('lines', [])]
        return IncomingOrder(
            external_id=str(payload.get('external_id', '')),
            external_store_id=str(payload.get('external_store_id', '')),
            customer_name=payload.get('customer_name', ''),
            customer_phone=payload.get('customer_phone', ''),
            address=payload.get('address', ''),
            payment_mode=payload.get('payment_mode', ''),
            total=Decimal(str(payload.get('total', 0))),
            lines=lines, raw=payload)

    def push_stock(self, store, rows):
        return {'skipped': 'manual'}

    def push_prices(self, store, rows):
        return {'skipped': 'manual'}

    def send_status(self, order, status):
        return {'skipped': 'manual'}
