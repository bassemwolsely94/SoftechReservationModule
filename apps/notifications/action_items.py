"""
apps/notifications/action_items.py — which notifications ask the reader to DO something (C26 / D-19).

The bell opens on «يحتاج إجراء» (action items) by default; «الكل» is one click away and the user's
choice is remembered on StaffProfile.bell_view. This file is the ONE place that decides what an
action item is: a fixed set of notification types, nothing fuzzy, no per-row guessing. To move a
type in or out, edit ACTION_TYPES (and the owner list in the PR / help text) — nothing else.

Rule of thumb used for the first cut (owner may adjust, see the C26 PR "Owner questions"):
  in  = the notification names a task that someone must do now (call, approve, dispatch, settle, reply)
  out = status changes, monitoring ticks (transit_*, SLA, connectivity — the 📡 flood), periodic
        reports without a to-do list, celebrations and broadcasts.

The action view pulls these types from EVERY notifier category the user may see (the role's
notifier visibility + personal mutes still apply — views._visible_categories), so an @-mention or a
new-branch-to-classify reaches the bell's action list even though it rides a quiet feed.
"""

# type → why it is an action (kept next to the type so the reason travels with it)
ACTION_REASONS = {
    # reservations — a customer is waiting
    'reservation_created':       'جهّز الحجز / أكّد للعميل',
    'reservation_assigned':      'حجز مُسند إليك',
    'stock_available':           'اتصل بالعميل: الصنف متاح',
    # delivery
    'delivery_new':              'وزّع طلب التوصيل',
    'delivery_cash_variance':    'سوِّ عجز النقدية مع الطيار',
    # transfers
    'transfer_request':          'وافق / صرّف طلب التحويل',
    'unfulfilled_transfer_flag': 'تحويل لم يُصرف — تابعه',
    # customers / demand
    'churn_alert':               'اتصل بالعميل قبل أن ينقطع',
    'demand_assigned':           'طلب مُسند إليك',
    'demand_back_in_stock':      'اتصل بالعميل: الصنف المطلوب عاد',
    'demand_sla_breach':         'طلب تجاوز المهلة',
    'case_sla_breach':           'حالة عميل تجاوزت المهلة',
    # personal
    'mention':                   'ذُكرت — ردّ',
    'chatter_mention':           'ذُكرت في تعليق — ردّ',
    'personal_reminder':         'تذكير وضعته لنفسك',
    # system (admin) — rare, deduplicated
    'branch_pending':            'صنّف الفرع الجديد',
    'sync_failure':              'مزامنة تفشل مرارًا — افحصها',
    # weekly lists that say who acts
    'hq_exception_digest':       'استثناءات الأسبوع بالجنيه — من يتصرف',
    'return_window_digest':      'أصناف يجب إرجاعها قبل الموعد',
    'ap_review_digest':          'قائمة مراجعة تسوية الموردين',
    'receipt_check_digest':      'استلام بدون طلب — راجعه',
}

ACTION_TYPES = frozenset(ACTION_REASONS)

VIEW_ACTION = 'action'
VIEW_ALL = 'all'
BELL_VIEWS = (VIEW_ACTION, VIEW_ALL)
DEFAULT_BELL_VIEW = VIEW_ACTION


def is_action(notification_type: str) -> bool:
    return notification_type in ACTION_TYPES


def clean_view(raw, default=VIEW_ALL):
    """A ?view= value → 'action' | 'all'. Unknown values fall back to `default` (the REST default
    stays 'all' so the inbox page, mobile and other callers keep today's behaviour)."""
    return raw if raw in BELL_VIEWS else default
