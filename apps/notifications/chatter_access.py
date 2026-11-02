"""
Who may use a record's live chatter thread (Batch 6, W-3).

The WebSocket follows the REST rules in apps.notifications.views: only chattable models, and a
branch user only for records of their own branches (core.branch_scope — the all-branch roles and
access_all_branches see every branch). `_get_record_branch_id` answers one branch id, or — once
Batch 5 part 2 lands — the set of a transfer's two sides; a record whose branch isn't known stays
open, as on REST.
"""
from core import branch_scope

MAX_MESSAGE_CHARS = 2000            # same cap as chatter_post


def can_use_thread(user, model_name, record_id) -> bool:
    from apps.notifications.views import _ALLOWED_CHATTER_MODELS, _get_record_branch_id
    if model_name not in _ALLOWED_CHATTER_MODELS:
        return False
    if getattr(user, 'staff_profile', None) is None:
        return False
    if branch_scope.branch_ids(user) is None:          # all-branch user
        return True
    try:
        rid = int(record_id)
    except (TypeError, ValueError):
        return False
    owner = _get_record_branch_id(model_name, rid)
    sides = owner if isinstance(owner, set) else ({owner} if owner is not None else set())
    return not sides or any(branch_scope.allows(user, b) for b in sides)
