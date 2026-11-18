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
DETAILS_COLUMNS = {'ID': 'sku', 'Qty': 'qty'}
DATE_FORMATS = ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%b %d, %Y', '%d %b %Y')

LOGIN_PATH_HINT = '/login'                          # a URL with this is the login page
