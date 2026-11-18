"""
apps/forecasting/call_center.py

The one place that finds the call center (crews piece 2b, Part B): the live crew of type
«كول سنتر». Every call-center reader (KPI board block, targets, forecasts, references, the target
workbook, rollup refresh, PIC calls, insights) calls call_center_crew() — its figures are the
crew's KpiActualRollup rows (crew set, branch NULL) written by build_crew_rollups, and its seller
codes are the crew members' dated SOFTECH user codes. The fake «CC» branch is no longer read here;
only the one-shot switch tools find it (apps/crews/cc_legacy.py).
"""
from datetime import date

CALL_CENTER_TYPE = 'call_center'


def call_center_crew():
    """The non-archived crew of type call_center (lowest id if several), or None."""
    from apps.crews.models import Crew
    return (Crew.objects.filter(type=CALL_CENTER_TYPE, is_archived=False)
            .order_by('id').first())


def call_center_crew_ids() -> list:
    """Ids of every live call-center crew (the chain-scope call_count sums each once)."""
    from apps.crews.models import Crew
    return list(Crew.objects.filter(type=CALL_CENTER_TYPE, is_archived=False)
                .order_by('id').values_list('id', flat=True))


def call_center_seller_codes(start: date, end: date) -> list:
    """The SOFTECH user codes the call-center crew's members carried on any day of
    [start, end] (sorted). No crew → []."""
    crew = call_center_crew()
    if crew is None:
        return []
    from apps.crews.membership import identities
    return sorted({str(i.value).strip() for i in identities(crew, start, end)
                   if i.kind == 'softech_user' and str(i.value).strip()})
