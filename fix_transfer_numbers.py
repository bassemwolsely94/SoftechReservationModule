import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

print("Step 1: Populate request_number for existing rows...")
with connection.cursor() as c:
    # Add the column without unique constraint first (if not exists)
    c.execute("""
        ALTER TABLE transfers_transferrequest
        ADD COLUMN IF NOT EXISTS request_number VARCHAR(20) NOT NULL DEFAULT ''
    """)
    print("  ✓ Column added (or already exists)")

    # Populate with TR-000001 format based on existing IDs
    c.execute("""
        UPDATE transfers_transferrequest
        SET request_number = 'TR-' || LPAD(id::text, 6, '0')
        WHERE request_number = '' OR request_number IS NULL
    """)
    updated = c.rowcount
    print(f"  ✓ Updated {updated} rows with request numbers")

    # Now add the unique constraint
    c.execute("""
        ALTER TABLE transfers_transferrequest
        DROP CONSTRAINT IF EXISTS transfers_transferrequest_request_number_key
    """)
    c.execute("""
        ALTER TABLE transfers_transferrequest
        ADD CONSTRAINT transfers_transferrequest_request_number_key
        UNIQUE (request_number)
    """)
    print("  ✓ Unique constraint added")

print("\nStep 2: Verify...")
with connection.cursor() as c:
    c.execute("SELECT id, request_number FROM transfers_transferrequest ORDER BY id")
    rows = c.fetchall()
    for row in rows:
        print(f"  ID={row[0]}  →  {row[1]}")

print("\n✅ Done — now run: python manage.py migrate --fake transfers 0002_redesign")
print("Then: python manage.py migrate")
