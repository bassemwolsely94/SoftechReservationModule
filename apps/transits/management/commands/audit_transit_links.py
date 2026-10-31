"""
python manage.py audit_transit_links [--commit]

P-33 (c): list in-transit transfers linked to a transfer request whose branches (or ERP-matched date)
disagree with the 125 — links made by the old docnumber-only rule. PostgreSQL only, no SOFTECH.
Without --commit nothing changes. With --commit each wrong link is removed, with an audit event and a
system note on the transit and on the transfer request. Nothing is re-linked automatically.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.transits import linking


class Command(BaseCommand):
    help = 'Report (and with --commit remove) transit → transfer links that do not match the 125.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true', help='Unlink the wrong links (default: report only).')

    def handle(self, *args, **opts):
        from apps.transfers.models import TransferRequestMessage
        from apps.transits.models import InTransitAuditEvent, InTransitNote, InTransitTransfer
        qs = (InTransitTransfer.objects.filter(linked_request__isnull=False)
              .select_related('linked_request__supplying_branch', 'linked_request__requesting_branch'))
        wrong = [(t, why) for t in qs for why in [linking.wrong_link(t)] if why]
        for t, why in wrong:
            self.stdout.write(f'125 #{t.erp_doc_number} ({t.erp_supplying_branch_code} → '
                              f'{t.erp_receiving_branch_code or "?"}, {t.issue_date}) ↔ '
                              f'{t.linked_request.request_number}: {why}')
        if not opts['commit']:
            self.stdout.write(f'{len(wrong)} wrong link(s). Report only — run with --commit to unlink.')
            return
        for t, why in wrong:
            tr = t.linked_request
            with transaction.atomic():
                t.linked_request = None
                t.save(update_fields=['linked_request'])
                InTransitAuditEvent.log(t, 'unlinked', detail=f'{tr.request_number}: {why}')
                InTransitNote.log_system(t, f'أُلغي ربط خاطئ بالطلب {tr.request_number} — الفرع أو التاريخ '
                                            f'لا يطابق مستند 125 رقم {t.erp_doc_number}.')
                TransferRequestMessage.log_system(tr, f'أُلغي ربط خاطئ بمستند التحويل 125 رقم {t.erp_doc_number} '
                                                      f'من فرع {t.erp_supplying_branch_code} — الفرع أو التاريخ لا يطابق.')
        self.stdout.write(f'{len(wrong)} wrong link(s) removed.')
