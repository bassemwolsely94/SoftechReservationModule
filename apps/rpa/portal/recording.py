"""Recording what the robot saw: availability checks and placed orders.

STUBS from Task 7 (the agent queue calls these). Task 8 replaces both with the real recording
(PortalLine answers, flags, the portal AvailabilityBatch, commit_order keyed
`portal-basket-<pk>`, remainders). Until then they only mark the basket status.
"""
from __future__ import annotations


def record_check(basket, lines_payload):
    """filled by Task 8. A dry run ended clean: the basket is dry_run_ok."""
    basket.status = 'dry_run_ok'
    basket.save(update_fields=['status'])
    return None


def record_order(basket, *, order_ref: str, history_lines: list, staff):
    """filled by Task 8. An order number was read: the basket is submitted (Task 8 records it
    through commit_order and moves it on to recorded)."""
    basket.status = 'submitted'
    basket.save(update_fields=['status'])
    return basket
