"""
generate_insights  (doc 18)
===========================
Build a bilingual narrative report for a period and (optionally) send it to the
configured WhatsApp recipients.

  python manage.py generate_insights --period day            # yesterday
  python manage.py generate_insights --period week --date 2026-05-31
  python manage.py generate_insights --period day --send     # + WhatsApp
  python manage.py generate_insights --period day --lang en --print

Schedule (Cairo): day → 07:00, week → Sun 08:00, month → 1st 08:00.
Delivery: WhatsApp Cloud API sends to individual numbers (InsightRecipient) — it
cannot post to groups; recipients forward to their branch group if desired.
"""
from datetime import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate a narrative insight report (and optionally send via WhatsApp)'

    def add_arguments(self, parser):
        parser.add_argument('--period', choices=['day', 'week', 'mtd', 'month'], default='day')
        parser.add_argument('--domain', choices=['sales', 'purchasing', 'all'], default='all',
                            help="Report domain(s): sales, purchasing, or all (both)")
        parser.add_argument('--date', help='Reference date YYYY-MM-DD (default: yesterday)')
        parser.add_argument('--send', action='store_true', help='Send to WhatsApp recipients')
        parser.add_argument('--print', action='store_true', help='Print the narrative')
        parser.add_argument('--lang', choices=['ar', 'en'], default='ar')

    def handle(self, *args, **opts):
        from apps.insights.engine import InsightEngine
        ref = None
        if opts.get('date'):
            ref = datetime.strptime(opts['date'], '%Y-%m-%d').date()

        domains = ['sales', 'purchasing'] if opts['domain'] == 'all' else [opts['domain']]
        for domain in domains:
            run = InsightEngine.run(period_type=opts['period'], ref_date=ref, domain=domain)
            self.stdout.write(self.style.SUCCESS(
                f'Report #{run.pk} [{run.domain}]: {run.period_type} {run.period_start}→{run.period_end}, '
                f'{run.findings_count} findings.'))
            if opts.get('print'):
                self.stdout.write('')
                self.stdout.write(run.narrative_ar if opts['lang'] == 'ar' else run.narrative_en)
            if opts.get('send'):
                sent = self._send(run)
                self.stdout.write(self.style.SUCCESS(f'  [{run.domain}] sent to {sent} recipient(s).'))

    def _send(self, run):
        from django.utils import timezone
        from apps.insights.models import InsightRecipient
        from apps.insights.engine import InsightEngine
        try:
            from apps.whatsapp.sender import WhatsAppSender
            sender = WhatsAppSender()
        except Exception as e:
            self.stderr.write(f'WhatsApp sender unavailable: {e}')
            return 0

        recipients = InsightRecipient.objects.filter(active=True)
        sent = 0
        for rc in recipients:
            if run.period_type not in (rc.period_types or '').split(','):
                continue
            # Scope precedence: salesperson → branch → chain.
            body = run.narrative_ar
            if rc.salesperson_usercode:
                body = InsightEngine.render_for_salesperson(run, rc.salesperson_usercode, 'ar')
                if body is None:
                    continue
            elif rc.branch_id:
                body = InsightEngine.render_for_branch(run, rc.branch_id, 'ar')
                if body is None:
                    continue
            try:
                sender.send_text(wa_id=rc.wa_number, body=body[:4000])
                sent += 1
            except Exception as e:
                self.stderr.write(f'send to {rc.wa_number} failed: {e}')
        if sent:
            run.sent_at = timezone.now(); run.sent_to = sent
            run.save(update_fields=['sent_at', 'sent_to'])
        return sent
