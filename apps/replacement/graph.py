"""
apps/replacement/graph.py — the case's transaction-lineage tree (doc 25 §7), built server-side
so the React LineageGraph component only renders.

Node: {id, kind, title, subtitle, amount, date, status, confidence, origin, doc, children}
"""
from __future__ import annotations

from .models import CaseDocument as CD, ReplacementItem


def _doc(ref):
    if ref is None:
        return None
    return {'id': ref.pk, 'kind': ref.doc_kind, 'kind_label': ref.get_doc_kind_display(),
            'branchcode': ref.branchcode, 'doccode': ref.doccode, 'docnumber': ref.docnumber,
            'docdate': ref.docdate.isoformat(), 'amount': str(ref.amount), 'phcode': ref.phcode,
            'party_code': ref.party_code, 'party_name': ref.party_name, 'usercode': ref.usercode,
            'channel': ref.channel, 'note': ref.note,
            'time': ref.doc_time.strftime('%H:%M') if ref.doc_time else ''}


def _node(cd: CD, title, children=None):
    ref = cd.document
    return {'id': f'cd{cd.pk}', 'casedoc_id': cd.pk, 'kind': cd.role, 'title': title,
            'subtitle': f'{ref.branchcode}/{ref.docnumber} · {ref.docdate:%Y-%m-%d}',
            'amount': str(cd.amount if cd.amount is not None else ref.amount),
            'date': ref.docdate.isoformat(), 'status': cd.status, 'confidence': float(cd.confidence),
            'origin': cd.origin, 'evidence': cd.evidence, 'doc': _doc(ref), 'children': children or []}


def build_tree(case) -> dict:
    docs = list(case.documents.select_related('document', 'parent').order_by('document__docdate', 'id'))
    by_role = {}
    for d in docs:
        by_role.setdefault(d.role, []).append(d)

    items = [{'id': f'it{i.pk}', 'kind': 'item', 'title': i.item_name or i.itemcode,
              'subtitle': f'{i.itemcode} · {i.get_disposition_display()}',
              'amount': str(i.eligible_public_value) if i.disposition != ReplacementItem.DISP_DISPENSED else '',
              'status': i.disposition, 'children': []} for i in case.items.all()]
    rx = {'id': 'rx', 'kind': 'prescription', 'title': 'الروشتة',
          'subtitle': f'{len(items)} صنف', 'children': items}

    contract = [_node(d, 'بيع تعاقد') for d in by_role.get(CD.ROLE_CONTRACT_SALE, [])]
    contract += [_node(d, 'مرتجع جزئي') for d in by_role.get(CD.ROLE_CONTRACT_RETURN, [])]
    contract += [_node(d, 'ملغى بمرتجع كامل') for d in by_role.get(CD.ROLE_CONTRACT_VOID, [])]

    vouchers = []
    for v in by_role.get(CD.ROLE_VOUCHER, []):
        kids = [_node(p, 'فاتورة منتجات') for p in docs
                if p.role == CD.ROLE_PRODUCT_SALE and p.parent_id == v.pk]
        vouchers.append(_node(v, 'سند صرف', kids))
    returns = [_node(d, 'مرتجع للمورد', [_node(s, 'سند تسوية المرتجع') for s in docs
                                          if s.role == CD.ROLE_RETURN_SETTLEMENT and s.parent_id == d.pk])
               for d in by_role.get(CD.ROLE_SUPPLIER_RETURN, [])]
    purchase = [_node(d, 'فاتورة شراء — إنشاء الرصيد', vouchers + returns)
                for d in by_role.get(CD.ROLE_PURCHASE, [])]

    balance = {'id': 'bal', 'kind': 'balance', 'title': 'الرصيد المتبقي',
               'amount': str(case.outstanding), 'children': [],
               'subtitle': f'منتجات {case.redeemed_products} · نقدي {case.redeemed_cash}'
                           + (f' · غير مصنّف {case.redeemed_unclassified}' if case.redeemed_unclassified else '')}
    return {'id': 'case', 'kind': 'case', 'title': case.number or f'#{case.pk}',
            'subtitle': case.patient_name or case.softech_pic or '—',
            'amount': str(case.entitlement), 'children': [rx] + contract + purchase + [balance]}
