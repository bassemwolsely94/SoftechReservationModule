"""PIC Analytics tunables (doc 33). Seeded by seed_config; DEFAULTS apply when a row is missing."""
from apps.config.models import SystemSetting

DEFAULTS = {
    'pic_loyal_months': 10,       # months with a purchase in the last 12 to count as "loyal"
    'pic_overdue_factor': 1.5,    # overdue when days since last visit > factor x personal cycle
    'pic_call_return_hours': 24,  # missed call counts as returned within N hours
    'pic_call_purchase_days': 7,  # call counts as converted if a purchase follows within N days
}


def setting(key):
    return SystemSetting.get(key, DEFAULTS[key])
