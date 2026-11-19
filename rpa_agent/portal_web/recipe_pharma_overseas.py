"""Pharma Overseas (SOFTECH supplier 565) website recipe: data only, no logic.

Everything the driver needs to find on the site lives here as role / label / text names, so a
change on the site is a change of this file. Values marked CONFIRM were not yet checked on the
real site; calibrate them with the operator (logged in by hand) before the first dry run.
"""

BASE_URL = 'https://shop.pharmaemarket.com/pharma/en/EGP/'

PATHS = {
    'quick_order': 'my-account/quick-order',
    'place_order': 'my-account/place-order',
    'order_history': 'my-account/orders',          # CONFIRM (SAP Commerce default)
}

# banner text (regex, case-insensitive) -> meaning; checked in this order
MESSAGES = {
    r'No Enough material Stock': 'short',
    r'No material Stock': 'out',
    r'Out Of Stock': 'out',
    r'already in your cart': 'merged',
    r'Quick order list has been added to the cart': 'added',
    r'order number\s*#\s*(\d+)': 'order_ref',
}

# controls the robot never presses, whatever the plan says (case-insensitive, by name or text)
DENY = ('Submit Order', 'Submit Return', 'Recurring order', 'Sign Out')

# the only controls the robot presses at all (exact names; order numbers in Order History match
# ORDER_LINK). Anything else is refused like a DENY control.
ALLOW = ('Add to cart', 'Update', 'Remove', 'Search', 'Proceed To Next Step')
ORDER_LINK = r'^\d{6,}$'

# ── where things are (CONFIRM each on the real site) ──
ACCOUNT_LABEL = 'Account name'                     # element holding the logged-in account name
CREDIT_LABELS = {'consumption': 'Consumption', 'credit': 'Credit', 'limit': 'Credit Limit'}
SKU_FIELD = 'SKU'                                  # quick order: product code field (label)
QTY_FIELD = 'Qty'                                  # quick order: quantity field (label)
ADD_BUTTON = 'Add to cart'
CART_TABLE = 'Cart'                                # table name (aria-label / caption)
UPDATE_BUTTON = 'Update'                           # a cart row's qty update button
REMOVE_BUTTON = 'Remove'
ROW_QTY_FIELD = 'Quantity'                         # the qty field inside a cart row (label)
PROCEED = 'Proceed To Next Step'
SEARCH_FIELD = 'Search'
SEARCH_BUTTON = 'Search'
SEARCH_RESULTS = 'Search results'                  # list name
SEARCH_TOP = 5
TOTAL_LABELS = {'without_tax': 'Total Without Tax', 'tax': 'Tax', 'total': 'Order Total'}
HISTORY_TABLE = 'Order History'
DETAILS_TABLE = 'Order details'

# cart / details table header text -> row key
CART_COLUMNS = {
    'ID': 'sku', 'Product': 'name', 'Qty': 'qty', 'PH. Price': 'price', 'Discount %': 'discount_pct',
    'Available Bonus': 'bonus_text', 'Expiry Date': 'expiry',
}
HISTORY_COLUMNS = {'Order Number': 'order_ref', 'Date Placed': 'date'}
# a pager next to the Order History or details table (link / button names, regex): the robot never
# presses it, it only learns that the table it read is not the whole list (CONFIRM on the real site)
PAGER = r'^(Next|Next Page|>|»|›|Show More|Load More|Page \d+ of \d+)$'
# the element holding how many lines an order has, when the details page shows it (CONFIRM)
DETAILS_COUNT_LABEL = 'Number of items'
# R21 (fail closed): PAGER and DETAILS_COUNT_LABEL above are guesses until checked on the real site.
# While this is False the robot never reports "history_none" (no order, the basket may be retried):
# an empty read is "history_unclear" and a person decides. Set it True only after the on-site check:
# logged in by hand on an account with more Order History rows than one page holds, confirm that
# (1) PAGER matches the list's next-page control, (2) the list is newest first, (3) PAGER also
# matches a long order's details pager, and (4) DETAILS_COUNT_LABEL names the item count shown on
# an order's details page - with a screenshot of each in the calibration notes.
HISTORY_PAGING_CONFIRMED = False
DETAILS_COLUMNS = {'ID': 'sku', 'Qty': 'qty'}
DATE_FORMATS = ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%b %d, %Y', '%d %b %Y')

LOGIN_PATH_HINT = '/login'                          # a URL with this is the login page
