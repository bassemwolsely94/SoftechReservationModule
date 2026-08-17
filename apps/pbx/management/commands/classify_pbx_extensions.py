"""
python manage.py classify_pbx_extensions

Auto-classifies extensions based on confirmed user rules:
  - Ext 10–18   → agent   (call-centre agents)
  - Ext 45–100  → hq      (HQ administrative employees)
  - Ext 106–200 → branch  (pharmacy branch desk phones)
  - goip*, grandstream*, trunk* → gateway (already done by sync)
  - Everything else → other (needs manual review)

Run after sync_pbx_extensions.
"""
from django.core.management.base import BaseCommand
from apps.pbx.models import AgentExtension


# Call-centre agents: extensions 10–18 (confirmed by user)
AGENT_EXTS = {'10', '11', '12', '13', '14', '15', '16', '17', '18'}

# HQ administrative employees: extensions 45–100 (confirmed by user)
HQ_ADMIN_EXTS = {
    '45', '50', '51', '52', '55', '56', '57', '58',
    '60', '61', '62',
    '70', '71', '72', '73',
    '80', '85', '86',
    '90', '91', '92', '93',
    '100',
}

# Branch desk phones confirmed by user
BRANCH_EXTS = {
    '106', '107', '108',
    '130', '140', '150', '153',
    '160', '162', '163', '170',
    '200',
}


class Command(BaseCommand):
    help = 'Auto-classify PBX extensions by confirmed user rules'

    def handle(self, *args, **options):
        # Process ALL non-gateway extensions so we can fix previously wrong types too
        exts = AgentExtension.objects.exclude(extension_type=AgentExtension.TYPE_GATEWAY)
        classified = 0

        for ext in exts:
            new_type = None

            if ext.extension in AGENT_EXTS:
                new_type = AgentExtension.TYPE_AGENT
            elif ext.extension in HQ_ADMIN_EXTS:
                new_type = AgentExtension.TYPE_HQ
            elif ext.extension in BRANCH_EXTS:
                new_type = AgentExtension.TYPE_BRANCH

            if new_type and new_type != ext.extension_type:
                old = ext.extension_type
                ext.extension_type = new_type
                ext.save(update_fields=['extension_type', 'updated_at'])
                classified += 1
                self.stdout.write(
                    f'  ext={ext.extension:<12} {old} -> {new_type}'
                )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Classified {classified} extensions.'))

        # Show what still needs manual review
        remaining = AgentExtension.objects.filter(
            extension_type='other', is_active=True
        )
        if remaining.exists():
            self.stdout.write(self.style.WARNING(
                f'\n{remaining.count()} extensions still typed as "other" — review in Admin:'
            ))
            for ext in remaining.order_by('extension'):
                ip = ext.last_ip or '-'
                self.stdout.write(f'  ext={ext.extension:<12} ip={ip}')

        # Summary by type
        self.stdout.write('')
        self.stdout.write('Summary:')
        for t, label in AgentExtension.EXTENSION_TYPE_CHOICES:
            count = AgentExtension.objects.filter(extension_type=t).count()
            self.stdout.write(f'  {label:<25} {count}')
