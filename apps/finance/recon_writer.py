"""
apps/finance/recon_writer.py

Phase-G — GATED SOFTECH write-back for reconstructed A/P allocations.

⚠️ Guarded by settings.AP_RECONCILE_WRITER_ENABLED (default False). With the flag
OFF (current state), every entry point only returns a DRY-RUN plan and writes
nothing to SOFTECH.

KEY DESIGN (from the captured native سداد, 2026-09-20):
  The historical problem is 49k+ payments (existing `cheques` vouchers) that were
  never allocated to an invoice. Reconstruction therefore **never creates a
  `cheques` row** — the money was already recorded when the voucher was made
  (balances already moved). We only write the MISSING allocation:

    1. INSERT INTO chequestrans (...)     ← the allocation link (plain DML, no
                                             trigger → reversible; also our
                                             idempotency key)
    2. UPDATE stktransm SET docvaluepay += amount, fatcurrentstatus=('90' full |
                                             '15' partial), docvaluepaybc         ← the invoice header sync

  This sidesteps EVERY hard problem of a full سداد: no `cheques` insert (which is
  IRREVERSIBLE — the encrypted trigger auto-commits and computes balances), no
  `temp_r_mon` replication checksum (proprietary hash we cannot compute), and no
  balance math (already done by the original voucher).

NO ROLLBACK SAFETY NET: SOFTECH statements auto-commit here (verified — a cheques
insert could not be rolled back). So the writer is correct-by-construction:
  • chequestrans is inserted FIRST and is the idempotency guard — a retry that
    sees an existing chequestrans row skips entirely (never re-updates stktransm,
    so docvaluepay can never double-count);
  • every write is verify-read-back; any mismatch STOPS the batch;
  • re-validate against live SOFTECH immediately before writing.

Mirrors the proven apps/invoices/writer.py + apps/pos_orders/writer.py playbook
(inline-literal DML — parameterised INSERTs silently don't land on this ASE).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import Allocation

DB = 'SOFTECHDB9.dbo'


class ReconWriteError(Exception):
    """A validation failure — the caller surfaces it; nothing is written."""


class ReconWriteIntegrityError(ReconWriteError):
    """SOFTECH state is not what we wrote (half-landed write / header out of sync).
    A bulk run must STOP on this — never keep writing over an inconsistent state."""


# ── settings gates ────────────────────────────────────────────────────────────

def writer_enabled() -> bool:
    return bool(getattr(settings, 'AP_RECONCILE_WRITER_ENABLED', False))


def _update_patientdata() -> bool:
    # The native client also does `UPDATE patientdata SET custtotalpay += amount
    # WHERE branchcode AND labno=docnumber`. For a SUPPLIER invoice this keys into a
    # customer/patient table by docnumber and is of unclear correctness, so it is
    # OFF by default and gated separately until investigated.
    return bool(getattr(settings, 'AP_RECONCILE_UPDATE_PATIENTDATA', False))


def _default_usercode() -> str:
    return str(getattr(settings, 'AP_RECONCILE_DEFAULT_USERCODE', '') or '1')


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(d) -> str:
    """SOFTECH datetime literal: 'M-D-YYYY 0:0:0.000' (matches the captured DML)."""
    if isinstance(d, (datetime.datetime,)):
        d = d.date()
    if not isinstance(d, datetime.date):
        d = datetime.date.fromisoformat(str(d)[:10])
    return f'{d.month}-{d.day}-{d.year} 0:0:0.000'


def _num(docnumber) -> str:
    s = str(docnumber).strip()
    return s.split('.')[0] if s else '0'


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def payment_usercode(allocation: Allocation) -> str:
    return allocation.payment.usercode or _default_usercode()


def _chequestrans_insert_sql(cheqsno, ib, dc, dn, dd, usercode, amount, due_before, cheqbranch) -> str:
    """docvaluepaynow = THIS voucher's amount; docvaluepaid = what the invoice still
    OWED BEFORE this voucher (the «مبلغ مستحق» column of SOFTECH's سداد فواتير grid).
    SOFTECH ticks «مغلق» on the link where paynow == docvaluepaid — the payment that
    clears the invoice. Proven 2026-09-28 on 735 native multi-payment invoices in entry
    order: 674 fit due-before vs 45 cumulative (the 45 = old vouchers linked years
    later); owner's native invoice 140/10746 shows it on screen. (It was wrongly
    written as cumulative-paid-after until 2026-09-28 — both agree for a single full
    settlement, which is why the pilot looked right.)"""
    return (
        f"INSERT INTO {DB}.chequestrans "
        f"(cheqsno, branchcode, doccode, docnumber, docdate, usercode, "
        f"docvaluepaid, docvaluepaynow, cheqbranchcode) VALUES "
        f"({cheqsno}, '{ib}', '{dc}', {dn}, '{dd}', '{usercode}', "
        f"{due_before}, {amount}, '{cheqbranch}')"
    )


# ── plan (pure — safe to call any time) ───────────────────────────────────────

def build_plan(allocation: Allocation) -> dict:
    """
    Build the ordered SOFTECH statements to record ONE approved allocation of an
    existing voucher to an invoice. Pure: computes from the mirror, writes nothing.
    The live path re-reads SOFTECH for the authoritative docvaluepay before writing.
    """
    payment = allocation.payment
    invoice = allocation.invoice
    amount = _dec(allocation.amount)
    if amount <= 0:
        raise ReconWriteError('amount must be > 0')
    if payment.party_id != invoice.party_id:
        raise ReconWriteError('payment/invoice party mismatch')

    usercode = payment_usercode(allocation)
    ib, dc, dn = invoice.branchcode, invoice.doccode, _num(invoice.docnumber)
    dd = _fmt_date(invoice.docdate)
    cheqsno = int(payment.cheqsno)
    cheqbranch = payment.branchcode

    # projected header total (mirror view; recomputed from SOFTECH at write time)
    new_paid = _dec(invoice.doc_value_pay) + amount
    fat = '90' if new_paid >= _dec(invoice.doc_value) else '15'

    chequestrans_sql = _chequestrans_insert_sql(
        cheqsno, ib, dc, dn, dd, usercode, amount,
        _dec(invoice.doc_value) - _dec(invoice.doc_value_pay), cheqbranch)
    stktransm_sql = (
        f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
        f"docvaluepay={new_paid}, docvaluepaybc={new_paid} "
        f"WHERE branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} "
        f"AND docdate='{dd}'"
    )
    exists_sql = (
        f"SELECT COUNT(*) FROM {DB}.chequestrans WHERE cheqsno={cheqsno} "
        f"AND cheqbranchcode='{cheqbranch}' AND branchcode='{ib}' AND doccode='{dc}' "
        f"AND docnumber={dn} AND docdate='{dd}'"
    )
    readback_sql = (
        f"SELECT docvaluepaynow FROM {DB}.chequestrans WHERE cheqsno={cheqsno} "
        f"AND cheqbranchcode='{cheqbranch}' AND branchcode='{ib}' AND doccode='{dc}' "
        f"AND docnumber={dn} AND docdate='{dd}'"
    )
    invoice_read_sql = (
        f"SELECT docvalue, docvaluepay, bcurrency, bcrate FROM {DB}.stktransm "
        f"WHERE branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} AND docdate='{dd}'"
    )
    plan = {
        'allocation_id': allocation.id,
        'amount': str(amount),
        'cheque': {'branchcode': cheqbranch, 'cheqsno': cheqsno},
        'invoice': {'branchcode': ib, 'doccode': dc, 'docnumber': dn, 'docdate': dd},
        'projected_docvaluepay': str(new_paid),
        'projected_fatcurrentstatus': fat,
        # order matters — chequestrans first = idempotency guard (never double-count)
        'statements': [
            {'label': 'guard_exists', 'kind': 'select', 'sql': exists_sql},
            {'label': 'invoice_read', 'kind': 'select', 'sql': invoice_read_sql},
            {'label': 'chequestrans_insert', 'kind': 'write', 'sql': chequestrans_sql},
            {'label': 'stktransm_update',   'kind': 'write', 'sql': stktransm_sql},
            {'label': 'readback', 'kind': 'select', 'sql': readback_sql},
        ],
        'patientdata_update_enabled': _update_patientdata(),
    }
    if _update_patientdata():
        plan['statements'].insert(4, {
            'label': 'patientdata_update', 'kind': 'write',
            'sql': (f"UPDATE {DB}.patientdata SET custtotalpay=custtotalpay+{amount} "
                    f"WHERE branchcode='{ib}' AND labno={dn}")})
    return plan


# ── push (GATED) ──────────────────────────────────────────────────────────────

def push_allocation(allocation: Allocation, *, dry_run: bool = True,
                    user=None, force: bool = False, conn=None) -> dict:
    """
    Record ONE approved allocation into SOFTECH. With AP_RECONCILE_WRITER_ENABLED
    off (default) or dry_run=True, returns the plan and writes NOTHING.

    Live path (flag on + dry_run False): idempotency guard → re-validate live →
    INSERT chequestrans → UPDATE stktransm → verify-readback → mark 'written'.
    """
    if allocation.origin not in (Allocation.ORIGIN_APPROVED,):
        raise ReconWriteError(
            f"only approved allocations are writable (got '{allocation.origin}')")
    # cheques.cheqtype '10' = مقبوضات (money RECEIVED from the supplier: refunds,
    # returns, «دخول خطأ» reversals). SOFTECH settles those against RETURNS only —
    # never let one pay a purchase invoice. (Write path only: reversal must still work.)
    if ((allocation.payment.cheqtype or '').strip() == '10'
            and not allocation.invoice.is_return):
        raise ReconWriteError('receipt voucher (مقبوضات, cheqtype 10) cannot settle a purchase invoice')
    if allocation.payment.chain_role in ('reversed', 'reversal'):
        raise ReconWriteError('payment was cancelled by a مقبوضات receipt — it cannot settle an invoice')

    plan = build_plan(allocation)

    if not writer_enabled() or dry_run:
        return {'dry_run': True, 'written': False, 'enabled': writer_enabled(), 'plan': plan}

    # ---- LIVE PATH (only reached with the flag ON and dry_run=False) ----------
    from config.sybase import get_sybase_connection
    own_conn = conn is None             # a bulk caller passes one shared connection
    if own_conn:
        conn = get_sybase_connection()
    result = {'dry_run': False, 'written': False, 'plan': plan, 'steps': []}
    try:
        _live_write(conn, allocation, plan, result, force)
        _audit_write(allocation, user, result)
        return result
    except Exception as exc:
        # every SOFTECH interaction is audited — including the blocked/failed ones
        result['error'] = str(exc)
        _audit_write(allocation, user, result)
        raise
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass


def _audit_write(allocation: Allocation, user, result: dict) -> None:
    from .models import ReconAuditEvent
    if result.get('error'):
        action = 'allocation_write_failed'
    elif result.get('already_present'):
        action = 'allocation_write_skipped'
    else:
        action = 'allocation_written'
    inv, pay = allocation.invoice, allocation.payment
    ReconAuditEvent.objects.create(
        action=action, allocation=allocation, party=inv.party, performed_by=user,
        before_state={'invoice_doc_value_pay': str(inv.doc_value_pay),
                      'allocation_origin_before': 'approved'},
        after_state={k: result.get(k) for k in
                     ('written', 'already_present', 'projected_docvaluepay',
                      'fatcurrentstatus', 'steps', 'error')},
        detail=(f'SOFTECH سداد: سند {pay.branchcode}/{pay.cheqsno} → فاتورة '
                f'{inv.branchcode}/{inv.doccode}/{inv.docnumber} مبلغ {allocation.amount}'
                + (f' — خطأ: {result["error"]}' if result.get('error') else ''))[:1000],
    )


def _mark_written(allocation: Allocation, header_paid: Decimal | None = None) -> None:
    from .models import MatchCandidate, APInvoice
    allocation.origin = Allocation.ORIGIN_WRITTEN
    allocation.synced_at = timezone.now()
    allocation.save(update_fields=['origin', 'synced_at'])
    if header_paid is not None:     # keep the mirror's SOFTECH header in step
        APInvoice.objects.filter(pk=allocation.invoice_id).update(doc_value_pay=header_paid)
    if allocation.candidate_id:
        MatchCandidate.objects.filter(pk=allocation.candidate_id).update(
            status=MatchCandidate.STATUS_WRITTEN)


def _scalar_fn(cur):
    def _scalar(sql):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None
    return _scalar


def _atomic(conn, cur, result: dict, *, work, restored) -> None:
    """Run `work` (several DML statements) as ONE transaction when the connection
    supports it. On any failure: roll back, then PROVE the rollback restored SOFTECH
    (`restored()` re-reads it) — if not, raise an integrity error instead of trusting
    it. Connections without transaction control (test fakes) run `work` directly."""
    tx = all(hasattr(conn, m) for m in ('begin', 'commit', 'rollback'))
    if not tx:
        work()
        return
    conn.begin()
    try:
        work()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        result['steps'].append('rolled_back')
        import time
        ok, verified = False, False
        for _ in range(4):
            try:
                ok, verified = restored(_scalar_fn(cur)), True
                break
            except Exception:
                time.sleep(5)
        # the connection itself died (HQ drop): the server aborts an uncommitted
        # transaction on disconnect — PROVE it on a fresh connection, don't assume
        for _ in range(6 if not verified else 0):
            try:
                from config.sybase import get_sybase_connection
                fresh = get_sybase_connection()
                try:
                    ok = restored(_scalar_fn(fresh.cursor()))
                    result['steps'].append('rollback_verified_fresh_connection')
                    break
                finally:
                    try:
                        fresh.close()
                    except Exception:
                        pass
            except Exception:
                time.sleep(20)
        if not ok:
            raise ReconWriteIntegrityError(
                f'transaction failed ({exc}) and the rollback could NOT be verified — STOP') from exc
        raise ReconWriteError(f'rolled back cleanly: {exc}') from exc


def _reverse_steps(cur, _scalar, row_key, inv_key, fat, new_paid, result) -> None:
    cur.execute(f"DELETE FROM {DB}.chequestrans WHERE {row_key}")
    result['steps'].append('chequestrans_delete')
    if _scalar(f"SELECT COUNT(*) FROM {DB}.chequestrans WHERE {row_key}"):
        raise ReconWriteIntegrityError('chequestrans row still present after DELETE — STOP')
    cur.execute(f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
                f"docvaluepay={new_paid}, docvaluepaybc={new_paid} WHERE {inv_key}")
    result['steps'].append('stktransm_update')
    hdr = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
    if abs(hdr - new_paid) > Decimal('0.01'):
        raise ReconWriteIntegrityError(
            f'stktransm header did not revert (docvaluepay {hdr} ≠ {new_paid}) — STOP')


LOCK_WAIT_SECONDS = 30


def _bounded_lock_wait(cur) -> None:
    # A statement blocked by someone else's lock (e.g. a stalled SOFTECH replication
    # agent) is cancelled by the SERVER after this many seconds instead of waiting
    # forever. Without it, a client-side timeout leaves the statement queued on HQ,
    # where it could still execute later with nobody to finish the second step
    # (2026-09-27 incident: reversal DELETEs queued behind SSB-SBRep150).
    try:
        cur.execute(f'set lock wait {LOCK_WAIT_SECONDS}')
    except Exception:
        pass


def _top_up(conn, cur, _scalar, allocation, inv_key, cheqsno, cheqbranch, row_now, result) -> None:
    """Raise OUR existing chequestrans row for this voucher + invoice from `row_now` to
    allocation.amount, and the invoice header by the same difference — one transaction,
    both verified, a failed rollback proven (2026-09-29: 29 partial links written while
    fifo links held part of the invoice). docvaluepaid («owed before») is left as is;
    the date-order re-chain after the round sets it. Native rows are never modified."""
    from .models import ReconAuditEvent
    if not ReconAuditEvent.objects.filter(action='allocation_written', allocation=allocation).exists():
        raise ReconWriteError('the existing link was entered in SOFTECH itself — not modified (review)')
    target = _dec(allocation.amount)
    delta = target - row_now
    row_key = f"{inv_key} AND cheqsno={cheqsno} AND cheqbranchcode='{cheqbranch}'"
    cur.execute(f"SELECT docvalue, docvaluepay, bcurrency, bcrate FROM {DB}.stktransm WHERE {inv_key}")
    inv = cur.fetchone()
    if not inv:
        raise ReconWriteError('invoice not found in SOFTECH at write time')
    live_docvalue, live_paid = _dec(inv[0]), _dec(inv[1])
    bcrate = _dec(inv[3]) if inv[3] is not None else Decimal('1')
    if bcrate not in (Decimal('0'), Decimal('1')):
        raise ReconWriteError(f'foreign-currency invoice (bcrate {bcrate}) — not auto-written')
    if live_paid + delta > live_docvalue + Decimal('0.01'):
        raise ReconWriteError(f'top-up {delta} would over-pay invoice (live paid {live_paid} + {delta} > {live_docvalue})')
    cheq_value = _scalar(f"SELECT cheqvalue FROM {DB}.cheques WHERE cheqsno={cheqsno} AND branchcode='{cheqbranch}'")
    if cheq_value is None:
        raise ReconWriteError('voucher not found in SOFTECH at write time')
    ret_sign, pur_sign = ('1', '-1') if allocation.payment.is_receipt else ('-1', '1')
    cheq_used = _dec(_scalar(
        f"SELECT SUM(CASE WHEN doccode='120' THEN {ret_sign} ELSE {pur_sign} END * docvaluepaynow) "
        f"FROM {DB}.chequestrans WHERE cheqsno={cheqsno} AND cheqbranchcode='{cheqbranch}'"))
    effect = allocation.payment.allocation_effect(delta, allocation.invoice.is_return)
    if cheq_used + effect > _dec(cheq_value) + Decimal('0.01'):
        raise ReconWriteError(f'top-up {delta} would over-allocate voucher {cheqbranch}/{cheqsno} '
                              f'(already {cheq_used} of {cheq_value})')
    new_paid = live_paid + delta
    fat = '90' if new_paid >= live_docvalue else '15'

    def _work():
        cur.execute(f"UPDATE {DB}.chequestrans SET docvaluepaynow={target} WHERE {row_key}")
        result['steps'].append('chequestrans_topup')
        if abs(_dec(_scalar(f"SELECT docvaluepaynow FROM {DB}.chequestrans WHERE {row_key}")) - target) > Decimal('0.01'):
            raise ReconWriteIntegrityError('chequestrans top-up did not land — STOP')
        cur.execute(f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
                    f"docvaluepay={new_paid}, docvaluepaybc={new_paid} WHERE {inv_key}")
        result['steps'].append('stktransm_update')
        if abs(_dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}")) - new_paid) > Decimal('0.01'):
            raise ReconWriteIntegrityError('stktransm header did not update — STOP')

    _atomic(conn, cur, result, work=_work,
            restored=lambda q: (abs(_dec(q(f"SELECT docvaluepaynow FROM {DB}.chequestrans WHERE {row_key} AT ISOLATION 0")) - row_now) <= Decimal('0.01')
                                and abs(_dec(q(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key} AT ISOLATION 0")) - live_paid) <= Decimal('0.01')))
    hdr_after = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
    _mark_written(allocation, header_paid=hdr_after)
    result.update({'written': True, 'topped_up': str(delta), 'from': str(row_now),
                   'projected_docvaluepay': str(new_paid), 'fatcurrentstatus': fat})


def _live_write(conn, allocation: Allocation, plan: dict, result: dict, force: bool) -> None:
    """Guarded live write of one allocation; fills `result`, raises on any failure."""
    cur = conn.cursor()
    _bounded_lock_wait(cur)

    def _scalar(sql):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None

    ib, dc, dn, dd = (plan['invoice']['branchcode'], plan['invoice']['doccode'],
                      plan['invoice']['docnumber'], plan['invoice']['docdate'])
    cheqsno, cheqbranch = plan['cheque']['cheqsno'], plan['cheque']['branchcode']
    inv_key = (f"branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} "
               f"AND docdate='{dd}'")

    # 1. idempotency — a matching chequestrans already exists ⇒ no writes. But
    #    first prove the invoice HEADER reflects its allocations; a header that
    #    lags Σ docvaluepaynow means an earlier write half-landed → never mark
    #    'written' over it silently (surface for manual repair instead).
    exists = _scalar(plan['statements'][0]['sql'])
    if exists and not force:
        alloc_sum = _dec(_scalar(
            f"SELECT SUM(docvaluepaynow) FROM {DB}.chequestrans WHERE {inv_key}"))
        hdr_paid = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
        if hdr_paid + Decimal('0.01') < alloc_sum:
            raise ReconWriteIntegrityError(
                f'invoice header out of sync: docvaluepay {hdr_paid} < Σ allocations '
                f'{alloc_sum} — manual repair needed (half-landed earlier write)')
        row_now = _dec(_scalar(plan['statements'][-1]['sql']))       # this pair's docvaluepaynow
        if row_now + Decimal('0.01') < _dec(allocation.amount):
            # the pair is already linked for LESS than the allocation now holds (a partial
            # written while other links took part of the invoice) → raise OUR row, never add
            # a second one for the same voucher + invoice
            _top_up(conn, cur, _scalar, allocation, inv_key, cheqsno, cheqbranch, row_now, result)
            return
        _mark_written(allocation, header_paid=hdr_paid)
        result.update({'written': True, 'already_present': True})
        return

    # 2. re-validate against live SOFTECH — invoice side
    cur.execute(plan['statements'][1]['sql'])
    inv = cur.fetchone()
    if not inv:
        raise ReconWriteError('invoice not found in SOFTECH at write time')
    live_docvalue, live_paid = _dec(inv[0]), _dec(inv[1])
    bcrate = _dec(inv[3]) if inv[3] is not None else Decimal('1')
    if bcrate not in (Decimal('0'), Decimal('1')):
        raise ReconWriteError(f'foreign-currency invoice (bcrate {bcrate}) — not auto-written')
    amount = _dec(allocation.amount)
    if live_paid + amount > live_docvalue + Decimal('0.01'):
        raise ReconWriteError(
            f'allocation {amount} would over-pay invoice '
            f'(live paid {live_paid} + {amount} > docvalue {live_docvalue})')
    new_paid = live_paid + amount
    fat = '90' if new_paid >= live_docvalue else '15'

    # 2b. re-validate — voucher side: never allocate more than the voucher holds
    cheq_value = _scalar(
        f"SELECT cheqvalue FROM {DB}.cheques WHERE cheqsno={cheqsno} "
        f"AND branchcode='{cheqbranch}'")
    if cheq_value is None:
        raise ReconWriteError('voucher not found in SOFTECH at write time')
    # signed like SOFTECH netting: in a مدفوعات a return row is a credit; in a
    # مقبوضات the return row is what the refund pays
    ret_sign, pur_sign = ('1', '-1') if allocation.payment.is_receipt else ('-1', '1')
    cheq_used = _dec(_scalar(
        f"SELECT SUM(CASE WHEN doccode='120' THEN {ret_sign} ELSE {pur_sign} END * docvaluepaynow) "
        f"FROM {DB}.chequestrans WHERE cheqsno={cheqsno} AND cheqbranchcode='{cheqbranch}'"))
    effect = allocation.payment.allocation_effect(amount, allocation.invoice.is_return)
    if cheq_used + effect > _dec(cheq_value) + Decimal('0.01'):
        raise ReconWriteError(
            f'allocation {amount} would over-allocate voucher {cheqbranch}/{cheqsno} '
            f'(already {cheq_used} of {cheq_value})')

    def _write_steps():
        # 3. INSERT chequestrans FIRST (idempotency key; reversible — no trigger).
        #    Rebuilt against LIVE paid: docvaluepaid = what is still owed before this voucher.
        cur.execute(_chequestrans_insert_sql(
            cheqsno, ib, dc, dn, dd, payment_usercode(allocation), amount,
            live_docvalue - live_paid, cheqbranch))
        result['steps'].append('chequestrans_insert')
        # 4. verify-readback the allocation BEFORE touching the header
        if _scalar(plan['statements'][-1]['sql']) is None:
            raise ReconWriteIntegrityError('chequestrans did not land (readback empty) — STOP')
        # 5. UPDATE stktransm header (recomputed against live paid)
        cur.execute(
            f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
            f"docvaluepay={new_paid}, docvaluepaybc={new_paid} WHERE {inv_key}")
        result['steps'].append('stktransm_update')
        # 6. verify-readback the header
        hdr = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
        if abs(hdr - new_paid) > Decimal('0.01'):
            raise ReconWriteIntegrityError(
                f'stktransm header did not update (docvaluepay {hdr} ≠ {new_paid}) — STOP')

    # INSERT + header UPDATE as ONE transaction; a failed rollback is proven, not assumed
    _atomic(conn, cur, result, work=_write_steps,
            restored=lambda q: (not q(plan['statements'][0]['sql'] + ' AT ISOLATION 0')
                                and abs(_dec(q(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key} AT ISOLATION 0"))
                                        - live_paid) <= Decimal('0.01')))
    hdr_after = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))

    _mark_written(allocation, header_paid=hdr_after)
    result.update({'written': True, 'projected_docvaluepay': str(new_paid),
                   'fatcurrentstatus': fat})


# ── reversal (GATED) — undo an allocation WE wrote ────────────────────────────

def reverse_allocation(allocation: Allocation, *, user=None, note: str = '', conn=None) -> dict:
    """
    Undo one allocation this writer recorded in SOFTECH: DELETE our chequestrans row
    and lower stktransm.docvaluepay by the same amount (fatcurrentstatus back to '15'
    when no longer fully paid), verify both, then drop the mirror allocation and mark
    its candidate REJECTED so the engine never re-proposes the wrong pair.

    Only for origin='written' rows that carry our 'allocation_written' audit event —
    SOFTECH's own native allocations are never touched. Gated by the same flag.
    """
    from .models import ReconAuditEvent, MatchCandidate
    if allocation.origin != Allocation.ORIGIN_WRITTEN:
        raise ReconWriteError(f"only written allocations are reversible (got '{allocation.origin}')")
    if not ReconAuditEvent.objects.filter(action='allocation_written', allocation=allocation).exists():
        raise ReconWriteError('no record that this writer wrote it — refusing to reverse a native allocation')
    if not writer_enabled():
        raise ReconWriteError('SOFTECH writer is disabled (AP_RECONCILE_WRITER_ENABLED)')

    plan = build_plan(allocation)
    ib, dc, dn, dd = (plan['invoice']['branchcode'], plan['invoice']['doccode'],
                      plan['invoice']['docnumber'], plan['invoice']['docdate'])
    cheqsno, cheqbranch = plan['cheque']['cheqsno'], plan['cheque']['branchcode']
    amount = _dec(allocation.amount)
    inv_key = f"branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} AND docdate='{dd}'"
    row_key = f"{inv_key} AND cheqsno={cheqsno} AND cheqbranchcode='{cheqbranch}'"

    from config.sybase import get_sybase_connection
    own_conn = conn is None
    if own_conn:
        conn = get_sybase_connection()
    result = {'reversed': False, 'steps': []}
    try:
        cur = conn.cursor()
        _bounded_lock_wait(cur)

        def _scalar(sql):
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None

        now = _scalar(f"SELECT docvaluepaynow FROM {DB}.chequestrans WHERE {row_key}")
        if now is None:
            raise ReconWriteError('our chequestrans row is not in SOFTECH — nothing to reverse')
        if abs(_dec(now) - amount) > Decimal('0.01'):
            raise ReconWriteError(f'chequestrans amount {now} ≠ allocation {amount} — refusing')
        cur.execute(f"SELECT docvalue, docvaluepay FROM {DB}.stktransm WHERE {inv_key}")
        inv = cur.fetchone()
        if not inv:
            raise ReconWriteError('invoice not found in SOFTECH')
        docvalue, paid = _dec(inv[0]), _dec(inv[1])
        new_paid = paid - amount
        if new_paid < Decimal('-0.01'):
            raise ReconWriteError(f'reversal would make docvaluepay negative ({paid} − {amount})')
        new_paid = max(new_paid, Decimal('0'))
        fat = '90' if new_paid >= docvalue else '15'

        # DELETE + header UPDATE as ONE transaction: both land or neither does
        # (2026-09-27: a header UPDATE hit the lock-wait limit after the DELETE had
        # auto-committed → one half-landed reversal).
        _atomic(conn, cur, result,
                work=lambda: _reverse_steps(cur, _scalar, row_key, inv_key, fat, new_paid, result),
                restored=lambda q: (bool(q(f"SELECT COUNT(*) FROM {DB}.chequestrans WHERE {row_key} AT ISOLATION 0"))
                                    and abs(_dec(q(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key} AT ISOLATION 0"))
                                            - paid) <= Decimal('0.01')))
        hdr = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
        result.update({'reversed': True, 'docvaluepay': str(new_paid), 'fatcurrentstatus': fat})
        from .models import APInvoice
        APInvoice.objects.filter(pk=allocation.invoice_id).update(doc_value_pay=hdr)
    except Exception as exc:
        ReconAuditEvent.objects.create(
            action='allocation_reverse_failed', allocation=allocation,
            party=allocation.invoice.party, performed_by=user,
            after_state={'error': str(exc), 'steps': result['steps']},
            detail=f'فشل عكس التخصيص: {exc}'[:1000])
        raise
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass

    inv_obj, pay = allocation.invoice, allocation.payment
    cand = allocation.candidate
    ReconAuditEvent.objects.create(
        action='allocation_reversed', candidate=cand, party=inv_obj.party, performed_by=user,
        before_state={'allocation_id': allocation.id, 'amount': str(amount), 'origin': 'written'},
        after_state=result,
        detail=(f'عكس من SOFTECH: سند {pay.branchcode}/{pay.cheqsno} ↛ فاتورة '
                f'{inv_obj.branchcode}/{inv_obj.docnumber} مبلغ {amount}'
                + (f' — {note}' if note else ''))[:1000])
    allocation.delete()
    if cand is not None:
        cand.status = MatchCandidate.STATUS_REJECTED
        cand.decided_by = user
        cand.decided_at = timezone.now()
        cand.decision_note = ('عُكس من SOFTECH' + (f': {note}' if note else ''))[:1000]
        cand.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
    _refresh_payment_flag(pay)
    return result


def _refresh_payment_flag(payment) -> None:
    unalloc = not payment.allocations.exists()
    if payment.is_unallocated != unalloc:
        payment.is_unallocated = unalloc
        payment.save(update_fields=['is_unallocated'])


def complete_half_reversal(allocation: Allocation, *, user=None, note: str = '', conn=None) -> dict:
    """
    Finish a reversal whose chequestrans DELETE landed but whose header UPDATE did
    not (the 2026-09-27 lock-wait case). Acts ONLY when SOFTECH proves it: our row is
    gone, we wrote it (audit), and header − Σ remaining links == this allocation's
    amount. Then lowers the header by exactly that amount (verified) and closes the
    mirror side like a normal reversal. Gated by the writer flag.
    """
    from .models import ReconAuditEvent, MatchCandidate, APInvoice
    if allocation.origin != Allocation.ORIGIN_WRITTEN:
        raise ReconWriteError('only written allocations can be completed')
    if not ReconAuditEvent.objects.filter(action='allocation_written', allocation=allocation).exists():
        raise ReconWriteError('no record that this writer wrote it')
    if not writer_enabled():
        raise ReconWriteError('SOFTECH writer is disabled (AP_RECONCILE_WRITER_ENABLED)')
    plan = build_plan(allocation)
    ib, dc, dn, dd = (plan['invoice']['branchcode'], plan['invoice']['doccode'],
                      plan['invoice']['docnumber'], plan['invoice']['docdate'])
    cheqsno, cheqbranch = plan['cheque']['cheqsno'], plan['cheque']['branchcode']
    amount = _dec(allocation.amount)
    inv_key = f"branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} AND docdate='{dd}'"
    row_key = f"{inv_key} AND cheqsno={cheqsno} AND cheqbranchcode='{cheqbranch}'"
    from config.sybase import get_sybase_connection
    own = conn is None
    if own:
        conn = get_sybase_connection()
    result = {'reversed': False, 'steps': [], 'repair': True}
    try:
        cur = conn.cursor()
        _bounded_lock_wait(cur)

        def _scalar(sql):
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None

        # proof reads on chequestrans are dirty reads (AT ISOLATION 0): replication agents
        # hold table locks on it for minutes; only the stktransm UPDATE needs a lock
        if _scalar(f"SELECT COUNT(*) FROM {DB}.chequestrans WHERE {row_key} AT ISOLATION 0"):
            raise ReconWriteError('our chequestrans row is still present — use reverse_allocation')
        links = _dec(_scalar(f"SELECT SUM(docvaluepaynow) FROM {DB}.chequestrans WHERE {inv_key} AT ISOLATION 0"))
        cur.execute(f"SELECT docvalue, docvaluepay FROM {DB}.stktransm WHERE {inv_key}")
        inv = cur.fetchone()
        if not inv:
            raise ReconWriteError('invoice not found in SOFTECH')
        docvalue, paid = _dec(inv[0]), _dec(inv[1])
        if abs((paid - links) - amount) > Decimal('0.01'):
            raise ReconWriteError(
                f'not provably half-landed: header {paid} − links {links} ≠ amount {amount} — refusing')
        new_paid = max(paid - amount, Decimal('0'))
        fat = '90' if new_paid >= docvalue else '15'
        cur.execute(f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
                    f"docvaluepay={new_paid}, docvaluepaybc={new_paid} WHERE {inv_key}")
        result['steps'].append('stktransm_update')
        hdr = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
        if abs(hdr - new_paid) > Decimal('0.01'):
            raise ReconWriteIntegrityError(f'header did not update ({hdr} ≠ {new_paid}) — STOP')
        result.update({'reversed': True, 'docvaluepay': str(new_paid), 'fatcurrentstatus': fat})
        APInvoice.objects.filter(pk=allocation.invoice_id).update(doc_value_pay=hdr)
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
    inv_obj, pay, cand = allocation.invoice, allocation.payment, allocation.candidate
    ReconAuditEvent.objects.create(
        action='allocation_reversed', candidate=cand, party=inv_obj.party, performed_by=user,
        before_state={'allocation_id': allocation.id, 'amount': str(amount), 'origin': 'written',
                      'half_landed': True},
        after_state=result,
        detail=(f'إكمال عكس نصف منفَّذ: سند {pay.branchcode}/{pay.cheqsno} ↛ فاتورة '
                f'{inv_obj.branchcode}/{inv_obj.docnumber} مبلغ {amount}'
                + (f' — {note}' if note else ''))[:1000])
    allocation.delete()
    if cand is not None:
        cand.status = MatchCandidate.STATUS_REJECTED
        cand.decided_by = user
        cand.decided_at = timezone.now()
        cand.decision_note = ('عُكس من SOFTECH (إكمال)' + (f': {note}' if note else ''))[:1000]
        cand.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
    _refresh_payment_flag(pay)
    return result


def due_chain(docvalue: Decimal, header_paid: Decimal, ours: list) -> list:
    """«مبلغ مستحق» (chequestrans.docvaluepaid) for OUR links on one invoice, chained
    CHRONOLOGICALLY after the native links: `ours` = [(sort_key, paynow), …]. Native
    payments are what the header holds beyond ours. Returns the due-before value per
    link in the given order; the last link of a fully paid invoice gets due == paynow
    (SOFTECH ticks «مغلق» on it). Raises ReconWriteError when the numbers don't
    reconcile (never guess)."""
    ordered = sorted(ours, key=lambda x: x[0])
    ours_sum = sum((n for _, n in ordered), Decimal('0'))
    native = header_paid - ours_sum
    if native < Decimal('-0.01'):
        raise ReconWriteError(f'header paid {header_paid} < our links {ours_sum} — not consistent')
    due, out = docvalue - max(native, Decimal('0')), []
    for _, now in ordered:
        if now > due + Decimal('0.01'):
            raise ReconWriteError(f'link {now} exceeds what is due ({due}) — over-paid invoice')
        out.append(due.quantize(Decimal('0.01')))
        due -= now
    return out


def fix_due_before(invoice, allocations: list, *, conn, commit: bool = False, user=None) -> dict:
    """Correct docvaluepaid on OUR written links of one invoice (2026-09-28: they held
    cumulative-paid-after, SOFTECH means owed-before). Reads SOFTECH live (header +
    every link), recomputes with due_chain(), and — only when `commit` — updates just
    the rows that differ, in ONE transaction, verified. Native links are never touched."""
    from .models import ReconAuditEvent
    ib, dc = invoice.branchcode, invoice.doccode
    dn, dd = _num(invoice.docnumber), _fmt_date(invoice.docdate)
    inv_key = f"branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} AND docdate='{dd}'"
    cur = conn.cursor()
    _bounded_lock_wait(cur)
    # COMMITTED reads (not AT ISOLATION 0): an orphaned session from a dropped
    # connection can hold this invoice's UPDATE uncommitted; a dirty read would take
    # its new values as «already right» and skip an invoice that later rolls back
    # (2026-09-28, invoice 81122). A held lock now waits/fails → retried or reported.
    cur.execute(f"SELECT docvalue, docvaluepay FROM {DB}.stktransm WHERE {inv_key}")
    hdr = cur.fetchone()
    if not hdr:
        raise ReconWriteError('invoice not found in SOFTECH')
    docvalue, header_paid = _dec(hdr[0]), _dec(hdr[1])
    cur.execute(f"SELECT cheqsno, cheqbranchcode, docvaluepaid, docvaluepaynow FROM {DB}.chequestrans "
                f"WHERE {inv_key}")
    live = {(int(r[0]), str(r[1]).strip()): (_dec(r[2]), _dec(r[3])) for r in cur.fetchall()}
    links_sum = sum((n for _, n in live.values()), Decimal('0'))
    if abs(links_sum - header_paid) > Decimal('0.01'):
        raise ReconWriteError(f'header {header_paid} ≠ Σ links {links_sum} — skipped')
    ours = []
    for a in allocations:
        k = (int(a.payment.cheqsno), a.payment.branchcode)
        if k not in live:
            raise ReconWriteError(f'our link {k} not in SOFTECH')
        ours.append(((a.payment.voucher_date, a.payment.cheqsno, a.id), live[k][1], k))
    targets = due_chain(docvalue, header_paid, [(s, n) for s, n, _ in ours])
    changes = []
    for (s, now, k), target in zip(sorted(ours, key=lambda x: x[0]), targets):
        before = live[k][0]
        if abs(before - target) > Decimal('0.01'):
            changes.append({'cheqsno': k[0], 'cheqbranch': k[1], 'paynow': str(now),
                            'before': str(before), 'after': str(target),
                            'closes': abs(target - now) <= Decimal('0.01')})
    if not commit or not changes:
        return {'changes': changes, 'committed': False}

    def _work():
        for ch in changes:
            cur.execute(f"UPDATE {DB}.chequestrans SET docvaluepaid={ch['after']} WHERE {inv_key} "
                        f"AND cheqsno={ch['cheqsno']} AND cheqbranchcode='{ch['cheqbranch']}'")
            cur.execute(f"SELECT docvaluepaid FROM {DB}.chequestrans WHERE {inv_key} "
                        f"AND cheqsno={ch['cheqsno']} AND cheqbranchcode='{ch['cheqbranch']}'")
            got = cur.fetchone()
            if not got or abs(_dec(got[0]) - Decimal(ch['after'])) > Decimal('0.01'):
                raise ReconWriteIntegrityError(f"docvaluepaid did not update for {ch['cheqsno']} — STOP")

    def _restored(q):
        return all(abs(_dec(q(f"SELECT docvaluepaid FROM {DB}.chequestrans WHERE {inv_key} AND cheqsno={ch['cheqsno']} "
                              f"AND cheqbranchcode='{ch['cheqbranch']}' AT ISOLATION 0")) - Decimal(ch['before']))
                   <= Decimal('0.01') for ch in changes)

    _atomic(conn, cur, {'steps': []}, work=_work, restored=_restored)
    ReconAuditEvent.objects.create(
        action='allocation_due_fixed', party=invoice.party, performed_by=user,
        before_state={'invoice_id': invoice.id, 'rows': [{k: c[k] for k in ('cheqsno', 'cheqbranch', 'before')} for c in changes]},
        after_state={'rows': changes},
        detail=(f'تصحيح «مبلغ مستحق» (docvaluepaid) لروابطنا على الفاتورة {ib}/{invoice.docnumber}: '
                f'{len(changes)} سطر، ترتيب زمني')[:1000])
    return {'changes': changes, 'committed': True}


def rechain_after_write(invoice_ids, *, conn, user=None) -> dict:
    """Run after EVERY write round (owner 2026-09-29): re-chain «مبلغ مستحق» on the
    invoices just written so our links read oldest-voucher-first and the latest one
    closes the invoice — a write stores owed-before in ENTRY order, so an older voucher
    written after a newer one leaves the chain out of date order. Only OUR links (those
    with an allocation_written audit) are touched; failures are reported, never fatal to
    the writes already made (the next round or fix_ap_due_before retries them)."""
    from .models import ReconAuditEvent
    ids = {i for i in invoice_ids if i}
    stats = {'invoices': 0, 'rows_changed': 0, 'now_closed': 0, 'skipped': 0, 'errors': {}}
    if not ids or not writer_enabled():
        return stats
    ours = set(ReconAuditEvent.objects.filter(action='allocation_written', allocation__invoice_id__in=ids)
               .values_list('allocation_id', flat=True))
    groups = {}
    for a in (Allocation.objects.filter(id__in=ours, origin__in=[Allocation.ORIGIN_WRITTEN, Allocation.ORIGIN_SOFTECH])
              .select_related('invoice', 'invoice__party', 'payment')):
        groups.setdefault(a.invoice_id, []).append(a)
    for allocs in groups.values():
        try:
            res = fix_due_before(allocs[0].invoice, allocs, conn=conn, commit=True, user=user)
        except ReconWriteIntegrityError as e:
            stats['errors']['integrity: ' + str(e)[:60]] = 1
            break
        except Exception as e:                     # lock / validation — retried next round
            stats['skipped'] += 1
            k = str(e).split('(')[0][:60]
            stats['errors'][k] = stats['errors'].get(k, 0) + 1
            continue
        if res['changes']:
            stats['invoices'] += 1
            stats['rows_changed'] += len(res['changes'])
            stats['now_closed'] += sum(1 for c in res['changes'] if c['closes'])
    return stats


def complete_half_write(allocation: Allocation, *, user=None, note: str = '', conn=None) -> dict:
    """
    Finish a WRITE whose chequestrans INSERT landed but whose header UPDATE did not
    (pre-atomic 2026-09-26 read-timeouts: the server ran the INSERT, the client never
    saw it). Acts ONLY when SOFTECH proves it: the allocation is still 'approved', we
    audited a failed write attempt for it, our row is present with exactly this amount,
    and Σ links − header == this amount. Then raises the header by exactly that amount
    (verified) and marks the allocation written — audited as 'allocation_written' so
    it stays reversible. Gated by the writer flag.
    """
    from .models import ReconAuditEvent

    def _eligible(a):
        # 'softech' too: the nightly ingest re-labels our landed-but-unconfirmed row as a
        # native allocation — still ours when we only ever recorded FAILED attempts on it
        return (a.origin in (Allocation.ORIGIN_APPROVED, Allocation.ORIGIN_SOFTECH)
                and ReconAuditEvent.objects.filter(action='allocation_write_failed', allocation=a).exists()
                and not ReconAuditEvent.objects.filter(action='allocation_written', allocation=a).exists())

    if not _eligible(allocation):
        raise ReconWriteError('not an unconfirmed write of ours (needs a failed attempt on record, '
                              'no successful write) — refusing')
    if not writer_enabled():
        raise ReconWriteError('SOFTECH writer is disabled (AP_RECONCILE_WRITER_ENABLED)')
    plan = build_plan(allocation)
    ib, dc, dn, dd = (plan['invoice']['branchcode'], plan['invoice']['doccode'],
                      plan['invoice']['docnumber'], plan['invoice']['docdate'])
    inv_key = f"branchcode='{ib}' AND doccode='{dc}' AND docnumber={dn} AND docdate='{dd}'"
    from config.sybase import get_sybase_connection
    own = conn is None
    if own:
        conn = get_sybase_connection()
    result = {'written': False, 'steps': [], 'repair': True, 'half_landed': True}
    try:
        cur = conn.cursor()
        _bounded_lock_wait(cur)

        def _scalar(sql):
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None

        def _landed(a):
            k = f"{inv_key} AND cheqsno={int(a.payment.cheqsno)} AND cheqbranchcode='{a.payment.branchcode}'"
            now = _scalar(f"SELECT docvaluepaynow FROM {DB}.chequestrans WHERE {k} AT ISOLATION 0")
            return now is not None and abs(_dec(now) - _dec(a.amount)) <= Decimal('0.01')

        if not _landed(allocation):
            raise ReconWriteError('our chequestrans row (with this amount) is not in SOFTECH — nothing half-landed')
        # several half-landed writes on ONE invoice leave one combined gap: complete them together
        group = [allocation] + [
            s for s in Allocation.objects.filter(invoice_id=allocation.invoice_id)
                                         .exclude(pk=allocation.pk).select_related('payment')
            if _eligible(s) and _landed(s)]
        amount = sum((_dec(a.amount) for a in group), Decimal('0'))
        links = _dec(_scalar(f"SELECT SUM(docvaluepaynow) FROM {DB}.chequestrans WHERE {inv_key} AT ISOLATION 0"))
        cur.execute(f"SELECT docvalue, docvaluepay FROM {DB}.stktransm WHERE {inv_key}")
        inv = cur.fetchone()
        if not inv:
            raise ReconWriteError('invoice not found in SOFTECH')
        docvalue, paid = _dec(inv[0]), _dec(inv[1])
        if abs((links - paid) - amount) > Decimal('0.01'):
            raise ReconWriteError(
                f'not provably half-landed: links {links} − header {paid} ≠ amount {amount} — refusing')
        result['completed_ids'] = [a.id for a in group]
        new_paid = paid + amount
        if new_paid > docvalue + Decimal('0.01'):
            raise ReconWriteError(f'completing would over-pay invoice ({new_paid} > {docvalue}) — refusing')
        fat = '90' if new_paid >= docvalue else '15'
        cur.execute(f"UPDATE {DB}.stktransm SET fatcurrentstatus='{fat}', "
                    f"docvaluepay={new_paid}, docvaluepaybc={new_paid} WHERE {inv_key}")
        result['steps'].append('stktransm_update')
        hdr = _dec(_scalar(f"SELECT docvaluepay FROM {DB}.stktransm WHERE {inv_key}"))
        if abs(hdr - new_paid) > Decimal('0.01'):
            raise ReconWriteIntegrityError(f'header did not update ({hdr} ≠ {new_paid}) — STOP')
        result.update({'written': True, 'already_present': True,
                       'projected_docvaluepay': str(new_paid), 'fatcurrentstatus': fat})
        # audited as a normal 'allocation_written' (keeps it reversible), steps show the repair
        result['steps'].append('half_write_completed')
        for a in group:
            _mark_written(a, header_paid=hdr)
            _audit_write(a, user, dict(result, already_present=False))
    except Exception as exc:
        result['error'] = str(exc)
        _audit_write(allocation, user, result)
        raise
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
    return result
