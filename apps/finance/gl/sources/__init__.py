"""Normalised SOFTECH source documents (Plan 2).

Readers (one per source type, registered in ``READERS`` by Tasks 4-5) turn SOFTECH rows into
``SourceDoc``s. A reader has the signature ``reader(date_from, date_to, fetch) -> Iterable[SourceDoc]``
where ``fetch(sql) -> list[dict]`` is injectable so tests never touch SOFTECH.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class SourceDoc:
    source_type: str
    source_key: str
    doc_date: date
    branch_code: str
    kind: str = ''
    personcode: str = ''
    amounts: dict = field(default_factory=dict)   # dict[str, Decimal]
    attrs: dict = field(default_factory=dict)


# source_type -> reader(date_from, date_to, fetch); filled by the reader modules.
READERS: dict = {}


def _canon(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def content_hash(doc: SourceDoc) -> str:
    """sha256 of the canonical JSON of everything except ``source_key``."""
    payload = {
        'source_type': doc.source_type, 'doc_date': doc.doc_date, 'branch_code': doc.branch_code,
        'kind': doc.kind, 'personcode': doc.personcode, 'amounts': doc.amounts, 'attrs': doc.attrs,
    }
    raw = json.dumps(_canon(payload), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
