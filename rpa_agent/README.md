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

## Manual dry-run checklist

1. SOFTECH is open on the correct screen, window title unchanged, no dialogs open.
2. Checklist items are all ticked; hands are off the keyboard and mouse.
3. Start a run with the wrong window focused: expect outcome wrong_window, nothing typed.
4. Start a correct run; confirm keys are typed and a screenshot appears in /rpa.
5. Press Esc mid-run: typing stops, outcome stopped_by_operator.
6. Trigger an unexpected popup: expect unknown_popup with a screenshot, no further typing.
7. The dry run ends with outcome dry_run_ok and nothing is saved in SOFTECH.
