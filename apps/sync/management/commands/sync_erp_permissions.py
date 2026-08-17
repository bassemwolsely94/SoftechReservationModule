"""
python manage.py sync_erp_permissions

One-shot mirror of the SOFTECH permission model (usergroups / mitems / mglevels)
into Django. Runs the same logic the scheduled full-sync uses (hourly).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Mirror SOFTECH usergroups / screens / group-permissions into Django'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        from apps.sync.models import SyncRun
        from apps.sync.tasks import sync_erp_permissions

        run = SyncRun.objects.create(status='running')
        conn = get_sybase_connection()
        try:
            n = sync_erp_permissions(conn, run)
            run.status = 'success'
            run.records_synced = n
            run.save()
            self.stdout.write(self.style.SUCCESS(f'Synced {n} permission records.'))
        finally:
            conn.close()

        from apps.users.models import ErpUserGroup, ErpScreen, ErpGroupPermission
        self.stdout.write(
            f'  groups={ErpUserGroup.objects.count()} '
            f'screens={ErpScreen.objects.count()} '
            f'group_permissions={ErpGroupPermission.objects.count()}'
        )
