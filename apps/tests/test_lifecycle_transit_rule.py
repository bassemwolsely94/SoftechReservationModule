"""
Data lifecycle Stage 3: the transit row rules. Automatic alert notes and alert_sent/synced events of a transfer
closed for the rule's period are removed; an open transfer keeps its latest one per level. Mismatch alerts,
manual notes and every other audit action stay. No test here reaches SOFTECH.
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.data_lifecycle.register import RULES
from apps.transits.models import InTransitAuditEvent, InTransitNote, InTransitTransfer

AUTO = '🔔 تنبيه تلقائي'


def _removed(key):
    ids = set()
    for qs in RULES[key].candidates():
        ids |= set(qs.values_list('pk', flat=True))
    return ids


class TransitRuleBase(TestCase):
    def _transfer(self, doc, status, updated_days_ago):
        t = InTransitTransfer.objects.create(
            erp_doc_number=doc, issue_date=datetime.date(2026, 1, 1), transit_status=status)
        InTransitTransfer.objects.filter(pk=t.pk).update(
            updated_at=timezone.now() - datetime.timedelta(days=updated_days_ago))
        return t

    def _note(self, t, body, note_type='alert', age=0):
        n = InTransitNote.objects.create(transfer=t, note_type=note_type, body=body)
        InTransitNote.objects.filter(pk=n.pk).update(created_at=timezone.now() - datetime.timedelta(days=age))
        return n

    def _event(self, t, action, detail='', age=0):
        e = InTransitAuditEvent.objects.create(transfer=t, action=action, detail=detail)
        InTransitAuditEvent.objects.filter(pk=e.pk).update(created_at=timezone.now() - datetime.timedelta(days=age))
        return e


class NoteRuleTests(TransitRuleBase):
    def test_closed_over_90_days_alerts_removed(self):
        for i, status in enumerate(('received', 'cancelled', 'force_closed')):
            t = self._transfer(f'c{i}', status, 100)
            n = self._note(t, f'{AUTO} (critical): x')
            self.assertEqual(_removed('transit_alert_notes'), {n.pk}, status)
            n.delete()

    def test_closed_under_90_days_kept(self):
        t = self._transfer('c', 'received', 30)
        self._note(t, f'{AUTO} (critical): x', age=200)     # an old note of a recently edited transfer waits
        self.assertEqual(_removed('transit_alert_notes'), set())

    def test_open_keeps_latest_per_level(self):
        t = self._transfer('o', 'in_transit', 0)
        old_crit = self._note(t, f'{AUTO} (critical): a', age=5)
        new_crit = self._note(t, f'{AUTO} (critical): b', age=1)
        old_local = self._note(t, f'{AUTO}: a', age=4)
        new_local = self._note(t, f'{AUTO}: b', age=2)
        only_warn = self._note(t, f'{AUTO} (warn): a', age=3)
        self.assertEqual(_removed('transit_alert_notes'), {old_crit.pk, old_local.pk})
        self.assertNotIn(new_crit.pk, _removed('transit_alert_notes'))
        self.assertNotIn(new_local.pk, _removed('transit_alert_notes'))
        self.assertNotIn(only_warn.pk, _removed('transit_alert_notes'))
        for status in ('erp_mismatch', 'expired_pending'):
            t.transit_status = status
            t.save()
            self.assertEqual(_removed('transit_alert_notes'), {old_crit.pk, old_local.pk}, status)

    def test_preview_equals_real_removal(self):
        t = self._transfer('o', 'in_transit', 0)
        self._note(t, f'{AUTO} (critical): a', age=5)
        self._note(t, f'{AUTO} (critical): b', age=1)
        c = self._transfer('c', 'received', 100)
        self._note(c, f'{AUTO}: z')
        expected = len(_removed('transit_alert_notes'))
        self.assertEqual(expected, 2)
        self.assertEqual(sum(qs.count() for qs in RULES['transit_alert_notes'].candidates()), expected)

    def test_mismatch_never_selected(self):
        t = self._transfer('c', 'received', 200)
        self._note(t, '🔔 تباين مع ERP: x')
        o = self._transfer('o', 'in_transit', 0)
        self._note(o, '🔔 تباين مع ERP: a', age=3)
        self._note(o, '🔔 تباين مع ERP: b', age=1)
        self.assertEqual(_removed('transit_alert_notes'), set())

    def test_manual_note_never_selected(self):
        t = self._transfer('c', 'received', 200)
        self._note(t, 'ملاحظة', note_type='note')
        self._note(t, 'نظام', note_type='system')
        self._note(t, f'{AUTO} (critical): typed by a person', note_type='note')
        self.assertEqual(_removed('transit_alert_notes'), set())


class EventRuleTests(TransitRuleBase):
    def test_closed_over_90_days_alerts_removed(self):
        t = self._transfer('c', 'received', 100)
        a = self._event(t, 'alert_sent', 'level=d14, days=14')
        s = self._event(t, 'synced', 'ERP sync')
        self.assertEqual(_removed('transit_audit_events'), {a.pk, s.pk})

    def test_closed_under_90_days_kept(self):
        t = self._transfer('c', 'cancelled', 10)
        self._event(t, 'alert_sent', 'level=d14, days=14', age=300)
        self._event(t, 'synced', 'x', age=300)
        self.assertEqual(_removed('transit_audit_events'), set())

    def test_open_keeps_latest_per_level(self):
        t = self._transfer('o', 'in_transit', 0)
        old_d14 = self._event(t, 'alert_sent', 'level=d14, days=14', age=5)
        self._event(t, 'alert_sent', 'level=d14, days=15', age=1)
        self._event(t, 'alert_sent', 'level=local, days_since_local_receipt=3', age=4)
        old_sync = self._event(t, 'synced', 'a', age=6)
        self._event(t, 'synced', 'b', age=2)
        self.assertEqual(_removed('transit_audit_events'), {old_d14.pk, old_sync.pk})

    def test_mismatch_never_selected(self):
        t = self._transfer('c', 'received', 200)
        self._event(t, 'alert_sent', 'erp_mismatch: missing=1, qty_diff=0')
        o = self._transfer('o', 'erp_mismatch', 0)
        self._event(o, 'alert_sent', 'erp_mismatch: missing=1', age=3)
        self._event(o, 'alert_sent', 'erp_mismatch: missing=2', age=1)
        self.assertEqual(_removed('transit_audit_events'), set())

    def test_other_audit_actions_never_selected(self):
        t = self._transfer('c', 'received', 200)
        for action in ('viewed', 'exported', 'linked', 'unlinked', 'received', 'force_closed'):
            self._event(t, action, 'level=d14')
        self.assertEqual(_removed('transit_audit_events'), set())
