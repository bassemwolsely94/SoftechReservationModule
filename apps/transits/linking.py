"""
apps/transits/linking.py

P-33 (c): which TransferRequest a SOFTECH 125 (in-transit transfer) belongs to.

SOFTECH docnumbers repeat per (branch, doctype), so the staff-typed `erp_reference` alone linked a
125 from one branch to another branch's request. A link now needs:
  • the same docnumber AND the same supplying branch;
  • the same receiving branch (when the 125 names one);
  • when the request carries an ERP-matched document date, within ±3 days of the 125's issue date,
    and an ERP-matched doc code of '125' or blank.
More than one candidate → no link ('ambiguous'). Used by sync_in_transit and audit_transit_links.
"""
import datetime

DATE_TOLERANCE = datetime.timedelta(days=3)


def _code(branch):
    return str(getattr(branch, 'softech_branch_id', '') or '').strip()


def build_index(transfers):
    """{(erp_reference, supplying branch code): [TransferRequest, …]}"""
    index = {}
    for tr in transfers:
        index.setdefault((str(tr.erp_reference).strip(), _code(tr.supplying_branch)), []).append(tr)
    return index


def fits(tr, recv_code, issue_date):
    """True when the request agrees with the 125 beyond its docnumber and supplying branch."""
    if recv_code and _code(tr.requesting_branch) != str(recv_code).strip():
        return False
    if tr.erp_match_doc_code and str(tr.erp_match_doc_code).strip() not in ('125', ''):
        return False
    if tr.erp_match_doc_date and issue_date and abs(tr.erp_match_doc_date - issue_date) > DATE_TOLERANCE:
        return False
    return True


def match(index, doc_num, supply_code, recv_code, issue_date):
    """(TransferRequest | None, reason) — reason: 'linked' | 'none' | 'ambiguous'."""
    candidates = [tr for tr in index.get((str(doc_num).strip(), str(supply_code).strip()), [])
                  if fits(tr, recv_code, issue_date)]
    if len(candidates) == 1:
        return candidates[0], 'linked'
    return None, ('ambiguous' if candidates else 'none')


def wrong_link(transit):
    """Why an existing link disagrees with the 125, or '' when it is fine."""
    tr = transit.linked_request
    if tr is None:
        return ''
    if _code(tr.supplying_branch) != str(transit.erp_supplying_branch_code).strip():
        return f'supplying branch {_code(tr.supplying_branch)} ≠ 125 {transit.erp_supplying_branch_code}'
    if not fits(tr, transit.erp_receiving_branch_code, transit.issue_date):
        return (f'receiving branch {_code(tr.requesting_branch)} / match date {tr.erp_match_doc_date} '
                f'≠ 125 {transit.erp_receiving_branch_code} {transit.issue_date}')
    return ''
