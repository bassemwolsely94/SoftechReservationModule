@echo off
cd /d "C:\Users\basse\OneDrive\ElRezeiky Depts\IT Software Development\Claude Development\Reservation Module"
call venv\Scripts\activate
set DJANGO_SETTINGS_MODULE=config.settings
python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application