"""
Unit tests for apps.purchasing.views.shortage_overlay_label — the نقص/بديل السوق
export column label that differentiates every dismissal CAUSE (not a flat 'مستبعد').

Pure function over an Item's shortage attributes → no DB needed (SimpleTestCase,
unsaved Item instances).
"""
from django.test import SimpleTestCase

from apps.catalog.models import Item
from apps.purchasing.views import shortage_overlay_label


def _item(**kw):
    # Unsaved instance — we only read shortage attributes + get_..._display().
    return Item(**kw)


class ShortageOverlayLabelTests(SimpleTestCase):
    def test_active_shortage(self):
        text, kind = shortage_overlay_label(_item(in_shortage=True))
        self.assertEqual(text, 'ندره بالسوق / ناقص جدا')
        self.assertEqual(kind, 'shortage')

    def test_shortage_wins_over_dismissed(self):
        # Defensive: if both flags are set, the live shortage takes precedence.
        text, kind = shortage_overlay_label(
            _item(in_shortage=True, shortage_dismissed=True,
                  shortage_dismiss_reason='obsolete'))
        self.assertEqual((text, kind), ('ندره بالسوق / ناقص جدا', 'shortage'))

    def test_false_positive_carries_no_state(self):
        # Wrongly auto-detected → blank cell, no fill, even though dismissed=True.
        text, kind = shortage_overlay_label(
            _item(shortage_dismissed=True, shortage_dismiss_reason='false_positive'))
        self.assertEqual((text, kind), ('', ''))

    def test_variant_shows_its_own_label(self):
        text, kind = shortage_overlay_label(
            _item(shortage_dismissed=True, shortage_dismiss_reason='variant'))
        self.assertEqual(kind, 'variant')
        self.assertEqual(text, 'مقاس/شكل بديل لمنتج متاح')      # not a flat 'مستبعد'

    def test_each_non_variant_cause_is_distinct(self):
        cases = {
            'on_request':   'مستبعد: يُطلب عند الحاجة',
            'obsolete':     'مستبعد: غير متوفر بالسوق المصري',
            'not_shortage': 'مستبعد: ليس ناقصًا (موقوف/موسمي)',
            'other':        'مستبعد: أخرى',
        }
        seen = set()
        for reason, expected in cases.items():
            text, kind = shortage_overlay_label(
                _item(shortage_dismissed=True, shortage_dismiss_reason=reason))
            self.assertEqual(kind, 'dismissed', reason)
            self.assertEqual(text, expected, reason)
            seen.add(text)
        self.assertEqual(len(seen), len(cases), 'causes must be distinguishable')

    def test_other_appends_free_text_note(self):
        text, kind = shortage_overlay_label(
            _item(shortage_dismissed=True, shortage_dismiss_reason='other',
                  shortage_dismiss_note='موسمي — يعود في الشتاء'))
        self.assertEqual(kind, 'dismissed')
        self.assertEqual(text, 'مستبعد: أخرى (موسمي — يعود في الشتاء)')

    def test_dismissed_without_reason_falls_back(self):
        text, kind = shortage_overlay_label(
            _item(shortage_dismissed=True, shortage_dismiss_reason=''))
        self.assertEqual((text, kind), ('مستبعد', 'dismissed'))

    def test_neither_flag_is_blank(self):
        text, kind = shortage_overlay_label(_item())
        self.assertEqual((text, kind), ('', ''))
