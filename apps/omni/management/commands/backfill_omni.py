"""
python manage.py backfill_omni [--dry-run]

One-time Phase 0 backfill (idempotent — safe to re-run):

  1. Seed the legacy ChannelAccount rows:
     - 'whatsapp' account from env (WHATSAPP_PHONE_NUMBER_ID) if configured
     - 'voice' account for the Issabel PBX
  2. Link every WAConversation to the legacy account + an umbrella
     omni.Conversation, and envelope its WAMessages as TimelineEvents.
  3. Envelope historical callcenter.CallLogs as TimelineEvents.

Uses the same ingestion functions as the live signals, so backfilled and
live data are structurally identical.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.omni import services
from apps.omni.models import ChannelAccount, TimelineEvent


class Command(BaseCommand):
    help = 'Backfill omni umbrella conversations from whatsapp + callcenter history'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be done without writing')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        # ── 1. Seed legacy accounts ─────────────────────────────────────────
        wa_account = None
        phone_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
        if phone_id:
            if dry:
                exists = ChannelAccount.objects.filter(
                    channel='whatsapp', phone_or_handle=phone_id).exists()
                self.stdout.write(f'[dry] whatsapp account ({phone_id}): '
                                  f'{"exists" if exists else "would create"}')
            else:
                wa_account, created = ChannelAccount.objects.get_or_create(
                    channel='whatsapp', phone_or_handle=phone_id,
                    defaults={
                        'name': 'واتساب الرئيسي (Cloud API)',
                        'provider': 'meta_cloud',
                        'department': 'مركز الاتصالات',
                        'provider_ref': phone_id,
                        'is_default': True,
                    },
                )
                # Ensure legacy account routes webhooks + is the default sender
                changed = []
                if not wa_account.provider_ref:
                    wa_account.provider_ref = phone_id
                    changed.append('provider_ref')
                if not ChannelAccount.objects.filter(
                        channel='whatsapp', is_default=True).exclude(pk=wa_account.pk).exists() \
                        and not wa_account.is_default:
                    wa_account.is_default = True
                    changed.append('is_default')
                if changed:
                    wa_account.save(update_fields=changed + ['updated_at'])
                self.stdout.write(f'whatsapp account: {"created" if created else "exists"} #{wa_account.pk}')
        else:
            self.stdout.write(self.style.WARNING(
                'WHATSAPP_PHONE_NUMBER_ID not set — skipping WhatsApp account seed'))

        if not dry:
            voice, created = ChannelAccount.objects.get_or_create(
                channel='voice', phone_or_handle='issabel',
                defaults={
                    'name': 'سنترال Issabel',
                    'provider': 'ami',
                    'department': 'مركز الاتصالات',
                },
            )
            self.stdout.write(f'voice account: {"created" if created else "exists"} #{voice.pk}')

        # ── 2. WhatsApp threads + messages ──────────────────────────────────
        from apps.whatsapp.models import WAConversation, WAMessage

        wa_convs = WAConversation.objects.all()
        linked = 0
        if not dry and wa_account is not None:
            linked = wa_convs.filter(account__isnull=True).update(account=wa_account)
        self.stdout.write(f'WAConversations: {wa_convs.count()} total, {linked} linked to account')

        msg_count = 0
        messages = WAMessage.objects.select_related('conversation__customer', 'sent_by').order_by('created_at')
        self.stdout.write(f'WAMessages to scan: {messages.count()}')
        if not dry:
            for msg in messages.iterator(chunk_size=500):
                if services.ingest_wa_message(msg) is not None:
                    msg_count += 1
            self.stdout.write(f'WAMessage events created: {msg_count}')

        # ── 3. Call logs ────────────────────────────────────────────────────
        from apps.callcenter.models import CallLog

        calls = CallLog.objects.select_related('customer', 'handled_by', 'branch').order_by('called_at')
        self.stdout.write(f'CallLogs to scan: {calls.count()}')
        call_count = 0
        if not dry:
            for log in calls.iterator(chunk_size=500):
                if services.ingest_call_log(log) is not None:
                    call_count += 1
            self.stdout.write(f'CallLog events created: {call_count}')

        self.stdout.write(self.style.SUCCESS(
            f'Done. TimelineEvents total: {TimelineEvent.objects.count()}'))
