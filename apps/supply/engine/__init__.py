"""apps/supply/engine — the read-only decision core (doc 24 Phase 3).

Every function here reuses an authoritative engine and computes only wiring/combination:
  net_demand         — reconcile ledger vs ItemDemandMetrics.gap  (never recompute gap)
  allocate_internal  — transfer_engine surplus rule, scoped to one item
  supplier_options   — effective-cost ranking + historical deal (procurement data)
  recommend          — orchestrates the above into the explicit quantity ledger (§20)
"""
from .demand import net_demand                       # noqa: F401
from .allocation import allocate_internal, transferable_surplus, network_internal_cover  # noqa: F401
from .sourcing import supplier_options, effective_unit_cost, historical_best_deal  # noqa: F401
from .recommend import recommend                     # noqa: F401
