#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# Windows consoles default to cp1256 here, which can't encode the emoji/em-dash
# used throughout our log + command output (raises UnicodeEncodeError mid-write).
# Force UTF-8 with replacement on the raw streams before Django/logging grab them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Flag test runs so middleware/signals can behave differently
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        from django.conf import settings
        try:
            settings.TESTING = True
        except Exception:
            pass
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
