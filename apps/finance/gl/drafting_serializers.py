"""JSON shapes for the drafting API (Plan 2 / Task 8). Decimals leave as strings, dates as ISO."""
from .drafting import proposal_version
from .views import _j


def party_json(p):
    rp = p.recon_party
    return {'id': p.pk, 'party_type': p.party_type, 'code': p.code, 'name': p.name,
            'status': p.status, 'proposal_basis': p.proposal_basis,
            'softech_personcode': p.softech_personcode,
            'softech_name': rp.name if rp else '', 'is_active': p.is_active,
            'confirmed_at': p.confirmed_at.isoformat() if p.confirmed_at else None}


def map_json(m):
    return {'id': m.pk, 'kind': m.kind, 'source_value': m.source_value,
            'account_code': m.account.code, 'account_name': m.account.name,
            'branch_id': m.branch_id, 'note': m.note,
            'updated_at': m.updated_at.isoformat() if m.updated_at else None}


def rule_json(r):
    return _j({'id': r.pk, 'code': r.code, 'version': r.version, 'source_type': r.source_type,
               'description': r.description, 'conditions': r.conditions, 'action': r.action,
               'granularity': r.granularity, 'lines': r.lines, 'book': r.book,
               'priority': r.priority, 'effective_from': r.effective_from,
               'effective_to': r.effective_to, 'is_active': r.is_active,
               'created_at': r.created_at})


def doc_json(d):
    return _j({'id': d.pk, 'source_type': d.source_type, 'source_key': d.source_key,
               'doc_date': d.doc_date, 'branch_code': d.branch_code, 'kind': d.kind,
               'personcode': d.personcode, 'amounts': d.amounts, 'attrs': d.attrs,
               'version': d.version, 'status': d.status})


def exception_json(e):
    return _j({'id': e.pk, 'kind': e.kind, 'status': e.status, 'source_date': e.source_date,
               'message': e.message, 'detail': e.detail, 'original_entry': e.original_entry_id,
               'proposed_lines': e.proposed_lines, 'proposal_version': proposal_version(e.proposed_lines),
               'created_at': e.created_at,
               'resolution_note': e.resolution_note, 'resolved_at': e.resolved_at,
               'doc': doc_json(e.source_doc)})


def source_doc_json(d):
    row = doc_json(d)
    row.update(rule_code=d.rule.code if d.rule else None,
               rule_version=d.rule.version if d.rule else None,
               content_hash=(d.content_hash or '')[:12],
               first_seen=d.first_seen.isoformat() if d.first_seen else None,
               last_seen=d.last_seen.isoformat() if d.last_seen else None)
    return row
