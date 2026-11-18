# ElRezeiky SOFTECH screen robot - Windows agent (Stage 1, dry-run)

## Install (operator PC)

    pip install -r rpa_agent/requirements.txt

## Pair

In the web app open /rpa, tab «أجهزتي», register the device and copy the token.
Create `%APPDATA%\ElRezeiky\rpa_agent.json`:

    {"base_url": "https://<server>", "token": "<paste token>"}

## Run

From the folder that contains `rpa_agent/`:

    python -m rpa_agent.main

The agent polls for a claimed document, shows the checklist (tick every item, then «ابدأ»),
then types the key plan into the SOFTECH window. «إيقاف» or Esc stops it at once; after a stop
nothing more is sent. Keep your hands off the keyboard while it runs.

## Tests (no extra libraries needed)

    python -m unittest discover -s rpa_agent/tests -t .

## Supplier website robot (Pharma Overseas)

The same agent can fill the Pharma Overseas cart (`portal_web/`). It never presses Submit Order,
Submit Return, Recurring order or Sign Out, never presses anything on the review page, and never
types into a password field: **a person logs in and a person presses Submit Order.**

Install the browser once (after `pip install -r rpa_agent/requirements.txt`):

    python -m playwright install chromium

Turn it on in `%APPDATA%\ElRezeiky\rpa_agent.json`:

    {"base_url": "https://<server>", "token": "<paste token>", "portal_enabled": true}

Optional keys: `"portal_browser_channel": "msedge"` drives the installed Microsoft Edge instead
of Playwright's Chromium (use it if Chromium will not start on this PC);
`"portal_profile_dir"` moves the browser profile. `"allow_live": true` is needed before a live
basket is filled (default off: dry runs only).

The browser profile lives in `%LOCALAPPDATA%\ElRezeiky\portal_browser`. The site login stays in
that profile; the agent never reads, copies or logs its cookies. Do not copy this folder.

Log in («فتح متصفح الموردين»): start the agent with

    python -m rpa_agent.main --open-portal-browser

A browser window opens on Quick Order. Log in by hand with the account the job uses, then leave
the window open. If the site asks for a login during a run, the strip shows
«سجّل الدخول ثم اضغط متابعة»; log in within 5 minutes or the basket goes to a person.

Tests (local fixture pages only, never the real site):

    cd rpa_agent && python -m pytest portal_web/tests -q

Set `RPA_PORTAL_TEST_BROWSER=msedge` (or a browser path) to drive another browser in the tests.

### Supplier robot dry-run checklist

1. Log in by hand on the account named in the job; the cart is empty.
2. A dry-run basket fills, reads back and removes only its own lines; the cart ends empty and the
   basket shows dry_run_ok in /rpa.
3. Put one item in the cart by hand, then run a basket: expect cart_not_empty, nothing touched.
4. Log in on the other account, then run: expect wrong_account, nothing touched.
5. Log out mid-run: the strip asks to log in; leaving it 5 minutes gives login_required_timeout.
6. Press Esc mid-run: stopped_by_operator; the basket goes to a person.
7. Live (only after the owner switches the portal live and `allow_live` is on): the robot stops on
   the review page with «راجع ثم اضغط Submit Order بنفسك». Check the page and press Submit Order
   yourself; the robot reads the order number and the Order History lines.

## Manual dry-run checklist

1. SOFTECH is open on the correct screen, window title unchanged, no dialogs open.
2. Checklist items are all ticked; hands are off the keyboard and mouse.
3. Start a run with the wrong window focused: expect outcome wrong_window, nothing typed.
4. Start a correct run; confirm keys are typed and a screenshot appears in /rpa.
5. Press Esc mid-run: typing stops, outcome stopped_by_operator.
6. Trigger an unexpected popup: expect unknown_popup with a screenshot, no further typing.
7. The dry run ends with outcome dry_run_ok and nothing is saved in SOFTECH.
