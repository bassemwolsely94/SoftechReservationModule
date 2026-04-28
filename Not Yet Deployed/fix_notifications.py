import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        ALTER TABLE notifications_notification
        ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS notification_type VARCHAR(40) NOT NULL DEFAULT 'system',
        ADD COLUMN IF NOT EXISTS transfer_request_id_ref INTEGER NULL,
        ADD COLUMN IF NOT EXISTS reservation_id BIGINT NULL
    """)
    print("Done — columns added successfully")
