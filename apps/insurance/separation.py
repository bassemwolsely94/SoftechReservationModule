"""
apps/insurance/separation.py

Name-separation matching for insurance claims.

A maintained list of employee/patient names (InsuranceSeparationList/Name) that
must be pulled OUT of the motalbas they appear in and billed on a different
claim (e.g. staff moved to شركة الخدمات الطبية).  This module fuzzy-matches a
claim's prescriptions against an active separation list so the user can review
and exclude them.

Matching is Arabic-aware (reuses the catalog normalizer: folds أ/إ/آ→ا, ى→ي,
ة→ه, drops tashkeel/tatweel, collapses spaces) and token-based so it catches
spelling/spacing variants and shortened names — never an ORM injection risk.
"""
from apps.catalog.search_index import normalize_search_text


def normalize_name(value) -> str:
    """Arabic-folded, whitespace-collapsed form used for name matching."""
    return normalize_search_text(value)


def _tokens(normalized: str) -> list:
    return [t for t in normalized.split(' ') if t]


def _is_ordered_subseq(short: list, long: list) -> bool:
    """True if every token of `short` appears in `long` in the same order."""
    it = iter(long)
    return all(tok in it for tok in short)


def _prefix_len(a: list, b: list) -> int:
    """Number of leading tokens that match in order."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def match_name(rx_tokens: list, list_tokens: list):
    """
    Compare a prescription name's tokens against a listed name's tokens using
    ORDERED matching — Egyptian names are distinguished by the specific ordered
    sequence (given · father · grandfather …), so set-based matching wildly
    over-matches on common tokens (احمد/محمد).  Returns (matched, type, score).

      • full    — exact, OR the whole listed name (≥3 tokens) appears in the
                  prescription name in order (rx may carry an extra middle name).
      • partial — the prescription name is an ordered sub-sequence of the listed
                  name, OR they share the same first ≥3 tokens (shortened/variant).
      • 2-token listed names (e.g. راضى ماهر) require an EXACT match.
    """
    if not rx_tokens or not list_tokens:
        return False, None, 0.0
    shared = len(set(rx_tokens) & set(list_tokens))
    score  = shared / max(len(rx_tokens), len(list_tokens))

    if rx_tokens == list_tokens:
        return True, 'full', 1.0
    # Short listed names are too generic for anything but an exact match
    if len(list_tokens) < 3:
        return False, None, score
    # Full: the complete listed name is present in the prescription name, in order
    if _is_ordered_subseq(list_tokens, rx_tokens):
        return True, 'full', score
    # Partial: rx is an ordered subset of the listed name (a shortened form)…
    if len(rx_tokens) >= 3 and _is_ordered_subseq(rx_tokens, list_tokens):
        return True, 'partial', score
    # …or they share a specific 3-token leading sequence
    if _prefix_len(rx_tokens, list_tokens) >= 3:
        return True, 'partial', score
    return False, None, score


def find_separation_matches(claim, sep_list_id=None) -> dict:
    """
    READ-ONLY: for every non-excluded prescription in `claim`, find matches
    against ACTIVE separation-list names (optionally restricted to one list).

    Returns {
      'lists': [{id, label, name_count}...],       # active lists (for the picker)
      'matches': [ {prescription_id, patient_name, net_after, is_excluded,
                    matched_name, list_label, list_id, match_type, score} ],
      'match_count', 'checked_names',
    }
    """
    from .models import (
        InsuranceSeparationList, InsuranceSeparationName, InsuranceClaimExclusion,
    )

    lists = list(InsuranceSeparationList.objects.filter(is_active=True))
    names_qs = InsuranceSeparationName.objects.filter(is_active=True, sep_list__is_active=True)
    if sep_list_id:
        names_qs = names_qs.filter(sep_list_id=sep_list_id)
    names = list(names_qs.select_related('sep_list'))

    # Pre-tokenize the list names once
    prepared = [(n, _tokens(n.normalized or normalize_name(n.name))) for n in names]

    excluded_ids = set(
        InsuranceClaimExclusion.objects
        .filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    matches = []
    for rx in claim.prescriptions.all():
        rx_tokens = _tokens(normalize_name(rx.patient_name))
        if not rx_tokens:
            continue
        best = None   # (match_type_rank, score, name_obj, match_type)
        for name_obj, list_tokens in prepared:
            ok, mtype, score = match_name(rx_tokens, list_tokens)
            if not ok:
                continue
            rank = 2 if mtype == 'full' else 1
            if best is None or (rank, score) > (best[0], best[1]):
                best = (rank, score, name_obj, mtype)
        if best:
            _, score, name_obj, mtype = best
            # Patient ID from companiesitems enrichment (whichever is populated)
            national_id = (getattr(rx, 'financial_no', '') or getattr(rx, 'membership_no', '')
                           or getattr(rx, 'file_no', '') or getattr(rx, 'patient_no', '') or '')
            matches.append({
                'prescription_id': rx.id,
                'patient_name':    rx.patient_name,
                'gross_before':    float(rx.gross_before or 0),
                'net_after':       float(rx.net_after or 0),
                'is_excluded':     rx.id in excluded_ids,
                'matched_name':    name_obj.name,
                'list_label':      name_obj.sep_list.label,
                'list_id':         name_obj.sep_list_id,
                'match_type':      mtype,
                'score':           round(score, 2),
                'reviewed':        bool(getattr(rx, 'separation_reviewed', False)),
                # ── Cross-check details ────────────────────────────────────────
                'docnumber':       rx.softech_docnumber,          # رقم الفاتورة
                'docdate':         rx.softech_docdate.isoformat() if rx.softech_docdate else None,
                'branch':          rx.softech_branchcode,          # الفرع
                'personcode':      rx.softech_personcode,          # كود العميل
                'national_id':     national_id,                    # الرقم القومي / المالي (إن وُجد)
                'dept_name':       getattr(rx, 'dept_name', '') or '',
            })

    # full matches first, then by score desc
    matches.sort(key=lambda m: (m['match_type'] != 'full', -m['score']))
    return {
        'lists':         [{'id': l.id, 'label': l.label, 'name_count': l.names.filter(is_active=True).count()}
                          for l in lists],
        'matches':       matches,
        'match_count':   len(matches),
        'reviewed_count': sum(1 for m in matches if m['reviewed']),
        'checked_names': len(prepared),
    }
