"""
python manage.py import_softech_reservations
One-time import of existing reservations from SOFTECH
(doccode '80' = حجز, '180' = تسليم حجز) into the platform Reservation model.
"""
from django.core.management.base import BaseCommand
from config.sybase import get_sybase_connection
from apps.sync.sybase_queries import QUERY_SOFTECH_RESERVATIONS, QUERY_EXISTING_RESERVATIONS
from apps.reservations.models import Reservation
from apps.customers.models import Customer
from apps.catalog.models import Item
from apps.branches.models import Branch
import logging

logger = logging.getLogger('elrezeiky.sync')


class Command(BaseCommand):
    help = 'One-time import of existing SOFTECH reservations (doccode 80/180)'

    def handle(self, *args, **options):
        self.stdout.write("Connecting to SOFTECH...")
        try:
            conn = get_sybase_connection()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Connection failed: {e}"))
            return

        # Try stktransm + stktrans join first (doccode 80 / 180)
        imported = 0
        skipped = 0
        errors = 0

        self.stdout.write("Importing from stktransm + stktrans (doccode 80/180)...")
        try:
            cursor = conn.cursor()
            cursor.execute(QUERY_SOFTECH_RESERVATIONS)
            rows = cursor.fetchall()
            self.stdout.write(f"Found {len(rows)} reservation lines in SOFTECH.")

            for row in rows:
                try:
                    branchcode = str(row[0])
                    doccode = str(row[1])
                    docnumber = str(row[2])
                    docdate = row[3]
                    cust_code = str(row[4]).strip() if row[4] else ''
                    itemcode = str(row[8]).strip() if row[8] else ''
                    transqty = row[9] or 1

                    if not cust_code or not itemcode:
                        skipped += 1
                        continue

                    customer = Customer.objects.filter(softech_id=cust_code).first()
                    item = Item.objects.filter(softech_id=itemcode).first()
                    branch = Branch.objects.filter(softech_branch_id=branchcode).first()

                    if not customer or not item or not branch:
                        skipped += 1
                        continue

                    reserve_key = f"SFTECH-{branchcode}-{doccode}-{docnumber}"

                    # doccode='180' = fulfilled, '80' = still pending
                    res_status = 'fulfilled' if doccode == '180' else 'pending'

                    _, created = Reservation.objects.get_or_create(
                        softech_reserve_id=reserve_key,
                        defaults={
                            'customer': customer,
                            'item': item,
                            'branch': branch,
                            'quantity_requested': transqty,
                            'status': res_status,
                            'contact_phone': customer.phone,
                            'contact_name': customer.name,
                            'notes': f'مستورد من SOFTECH — doccode={doccode}',
                        }
                    )
                    if created:
                        imported += 1
                    else:
                        skipped += 1

                except Exception as e:
                    errors += 1
                    logger.warning(f"Reservation import error: {e}")

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"stktransm query failed ({e}), trying salesreserve table..."
            ))
            # Fallback: try salesreserve table directly
            try:
                cursor = conn.cursor()
                cursor.execute(QUERY_EXISTING_RESERVATIONS)
                rows = cursor.fetchall()
                self.stdout.write(f"Found {len(rows)} rows in salesreserve.")

                for row in rows:
                    try:
                        salesresid = str(row[0])
                        itemcode = str(row[1]).strip() if row[1] else ''
                        personcode = str(row[2]).strip() if row[2] else ''
                        brid = str(row[3]).strip() if row[3] else ''

                        customer = Customer.objects.filter(softech_id=personcode).first()
                        item = Item.objects.filter(softech_id=itemcode).first()
                        branch = Branch.objects.filter(softech_branch_id=brid).first()

                        if not customer or not item or not branch:
                            skipped += 1
                            continue

                        _, created = Reservation.objects.get_or_create(
                            softech_reserve_id=f"SR-{salesresid}",
                            defaults={
                                'customer': customer,
                                'item': item,
                                'branch': branch,
                                'quantity_requested': row[4] or 1,
                                'status': 'pending',
                                'contact_phone': customer.phone,
                                'contact_name': customer.name,
                                'notes': row[6] or '',
                            }
                        )
                        if created:
                            imported += 1
                        else:
                            skipped += 1
                    except Exception as e2:
                        errors += 1
            except Exception as e2:
                self.stdout.write(self.style.ERROR(f"salesreserve also failed: {e2}"))

        conn.close()
        self.stdout.write(self.style.SUCCESS(
            f"✅ Import complete — imported: {imported}, skipped: {skipped}, errors: {errors}"
        ))
